import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from spectral_learning.services.behavior_signal_inputs import (
    fit_calibration, channel_value, build_behavior_signal_inputs, persist_inputs,
)
from spectral_learning.tests import test_normal_behavior as fixtures
from spectral_learning.services.neighborhood_experiment import run_neighborhood_experiment


def evidence(values):
    return dict(isolated=np.zeros(len(values), dtype=bool), feature_hidden=np.ones((len(values), 1), dtype=bool),
                **{k: v for channel in ['feature', 'degree', 'neighbor_mean', 'neighbor_std']
                   for k, v in [(channel+'_valid', np.ones(len(values), dtype=bool)),
                                (channel+'_mse', np.asarray(values, dtype=float)),
                                (channel+'_target_count', np.ones(len(values), dtype=int))]})


class SignalCalibrationTests(unittest.TestCase):
    def test_only_calibration_split_fits_and_ties_are_conservative(self):
        x = evidence([1., 1., 1.])
        state = fit_calibration([('calibration', x), ('test', evidence([999.])),
                                 ('additional_day', evidence([9999.]))], .25)
        self.assertEqual(state['degree:connected']['threshold'], 1.)
        row = channel_value('degree', x, 0, state, 'cal')
        self.assertEqual(row['tail_probability'], 1.)
        self.assertFalse(row['exceeds_tail'])
        row = channel_value('degree', evidence([2.]), 0, state, 'cal')
        self.assertEqual(row['tail_probability'], .25)
        self.assertTrue(row['exceeds_tail'])

    def test_no_targets_or_insufficient_calibration_never_become_normal_zero(self):
        x = evidence([0.]); state = fit_calibration([('calibration', x)], .01)
        row = channel_value('degree', x, 0, state, 'cal')
        self.assertEqual(row['status'], 'uncalibrated')
        self.assertIsNone(row['tail_probability'])
        x['neighbor_mean_valid'][0] = False; x['neighbor_mean_target_count'][0] = 0
        row = channel_value('neighbor_mean', x, 0, state, 'cal')
        self.assertEqual(row['status'], 'unavailable'); self.assertIsNone(row['residual'])


class SignalInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = fixtures.NormalBehaviorTests(); cls.fixture.setUp()
        cls.reference = Path(cls.fixture.run_pipeline()['paths']['directory'])
        with patch('spectral_learning.services.neighborhood_experiment.get_db', return_value=cls.fixture.db), \
             patch('spectral_learning.services.neighborhood_experiment.load_raw_chunks',
                   side_effect=lambda day: copy.deepcopy(cls.fixture.graphs[day])):
            result = run_neighborhood_experiment(cls.reference, ['2026-06-21'], seeds=[17], epochs=1)
        cls.experiment = Path(result['directory'])

    @classmethod
    def tearDownClass(cls):
        cls.fixture.doCleanups()

    def export(self, **options):
        with patch('spectral_learning.services.behavior_signal_inputs.get_db', return_value=self.fixture.db), \
             patch('spectral_learning.services.behavior_signal_inputs.load_raw_chunks',
                   side_effect=lambda day: copy.deepcopy(self.fixture.graphs[day])), \
             patch('torch.optim.Adam', side_effect=AssertionError('Must not train')):
            return build_behavior_signal_inputs(self.experiment, alpha=.25, **options)

    def test_frozen_export_contract_references_and_nulls_are_consistent(self):
        result = self.export(); folder = Path(result['directory'])
        rows = [json.loads(s) for s in (folder/'observations.jsonl').read_text().splitlines()]
        self.assertEqual(len(rows), 72)
        self.assertEqual(len({r['_id'] for r in rows}), 72)
        self.assertTrue(all(r['fusion']['alert'] is None for r in rows))
        self.assertTrue(all('raw_label' not in r for r in rows))
        for row in rows:
            self.assertTrue(row['quality']['contract_valid'])
            self.assertEqual(row['signals']['temporal_context']['status'], 'not_computed')
            if row['isolated']:
                self.assertIsNone(row['signals']['neighbor_mean']['residual'])
            else:
                self.assertEqual(row['signals']['degree']['status'], 'valid')
        self.assertFalse(self.fixture.db.behavior_observations.count_documents({}))
        self.assertEqual(json.loads((folder/'run_status.json').read_text())['status'], 'complete')

    def test_repeated_exports_have_identical_ids_and_payloads(self):
        first = self.export(); second = self.export()
        self.assertEqual(first['run_id'], second['run_id'])
        self.assertEqual((Path(first['directory'])/'observations.jsonl').read_bytes(),
                         (Path(second['directory'])/'observations.jsonl').read_bytes())

    def test_single_chunk_preserves_original_global_index_masks_and_edge_targets(self):
        from spectral_learning.services.autoencoder_inputs import (prepare_chunk, masked_topology,
            feature_corruption, transform, analyze_graph)
        from spectral_learning.services.normal_behavior_reports import load_reference_bundle
        _, scaler, *_ = load_reference_bundle(self.reference)
        graph = copy.deepcopy(self.fixture.graphs['2026-06-21'][0])
        chunk = prepare_chunk(graph, 'additional_day', scaler, seed=17, index=5, max_pairs=8)
        masked, pairs, labels, weights = masked_topology(graph, analyze_graph(graph), 17+5, 8)
        values, mask = transform(graph, scaler)
        expected_hidden = feature_corruption(mask, np.random.default_rng(17+1000+5))
        np.testing.assert_array_equal(chunk.fixed_hidden, expected_hidden)
        np.testing.assert_array_equal(chunk.pairs, pairs)
        np.testing.assert_array_equal(chunk.pair_labels, labels)
        np.testing.assert_array_equal(chunk.positive_weights, weights)
        np.testing.assert_array_equal(chunk.values, values)
        np.testing.assert_array_equal(chunk.spectral.arrays['edge_index'], analyze_graph(masked).arrays['edge_index'])

    def test_only_one_prepared_spectral_chunk_is_alive(self):
        import weakref
        from spectral_learning.services.autoencoder_inputs import prepare_chunk
        live = []
        def tracked(*args, **kwargs):
            self.assertFalse(any(ref() is not None for ref in live))
            chunk = prepare_chunk(*args, **kwargs)
            live.append(weakref.ref(chunk))
            return chunk
        with patch('spectral_learning.services.behavior_signal_inputs.prepare_chunk', side_effect=tracked):
            self.export()
        self.assertGreater(len(live), 6)  # includes calibration replay

    def test_completed_export_resumes_after_database_failure_without_inference(self):
        from pymongo.errors import ConnectionFailure
        messages = []
        with patch('spectral_learning.services.behavior_signal_inputs._verify_raw_sources',
                   side_effect=ConnectionFailure('MongoDB stopped')):
            with self.assertRaisesRegex(ConnectionFailure, 'MongoDB stopped'):
                self.export(progress=messages.append)
        folder = Path(messages[-1].split('export: ', 1)[1])
        status = json.loads((folder/'run_status.json').read_text())
        payload = (folder/'observations.jsonl').read_bytes()
        self.assertEqual(status['status'], 'failed')
        self.assertFalse((folder/'manifest.json').exists())
        with patch('spectral_learning.services.behavior_signal_inputs.prepare_chunk',
                   side_effect=AssertionError('Must not repeat spectral preparation')), \
             patch('spectral_learning.services.behavior_signal_inputs._evaluate',
                   side_effect=AssertionError('Must not repeat inference')):
            result = self.export(resume_bundle=folder)
        self.assertEqual(result['run_id'], status['run_id'])
        self.assertEqual((folder/'observations.jsonl').read_bytes(), payload)
        self.assertEqual(json.loads((folder/'run_status.json').read_text())['status'], 'complete')
        self.assertTrue(json.loads((folder/'manifest.json').read_text())['inference_reused'])

    def test_resume_rejects_truncated_tampered_and_wrong_calibration_exports(self):
        for kind in ('truncated', 'tampered', 'calibration'):
            with self.subTest(kind=kind):
                result = self.export(); folder = Path(result['directory'])
                original_status = (folder/'run_status.json').read_bytes()
                path = folder/'observations.jsonl'
                if kind == 'truncated':
                    path.write_text(''.join(path.read_text().splitlines(keepends=True)[:-1]))
                elif kind == 'tampered':
                    path.write_text(path.read_text().replace('candidate_flow', 'changed', 1))
                else:
                    (folder/'calibration.json').write_text('{}')
                with self.assertRaises(ValueError):
                    self.export(resume_bundle=folder)
                self.assertEqual((folder/'run_status.json').read_bytes(), original_status)
                self.assertTrue((folder/'resume_attempt_error.json').exists())

    def test_resume_rejects_temporary_only_export(self):
        result = self.export(); folder = Path(result['directory'])
        (folder/'observations.jsonl').rename(folder/'observations.jsonl.tmp')
        with self.assertRaisesRegex(ValueError, 'completed observations.jsonl'):
            self.export(resume_bundle=folder)

    def test_tampered_checkpoint_stops_before_database_access(self):
        path = self.experiment/'seed-17/spectral/neighborhood/model.pt'; original = path.read_bytes()
        try:
            path.write_bytes(original + b'tamper')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                self.export()
        finally:
            path.write_bytes(original)

    def add_normal_day(self, day):
        graphs=copy.deepcopy(self.fixture.graphs['2026-06-22'])
        for graph in graphs:
            old_ids=graph.node_ids[:]
            graph.day=day;graph.key=graph.key.replace('2026-06-22',day)
            graph.node_ids=[value.replace('2026-06-22',day) for value in old_ids]
            graph.lineage=[dict(original_id=value) for value in graph.node_ids]
            graph.block_lookup={part:value.replace('2026-06-22',day) for part,value in graph.block_lookup.items()}
            for old,new in zip(old_ids,graph.node_ids):
                doc=self.fixture.db.security_data.find_one({'_id':old})
                doc.update(_id=new,source_day=day,label=0,timestamp=doc['timestamp'].replace('2026-06-22',day))
                self.fixture.db.security_data.insert_one(doc)
        self.fixture.graphs[day]=graphs
        self.addCleanup(lambda:self.fixture.graphs.pop(day,None))
        self.addCleanup(lambda:self.fixture.db.security_data.delete_many({'source_day':day}))

    def extended_export(self, roles, **options):
        with patch('spectral_learning.services.behavior_signal_inputs.get_db',return_value=self.fixture.db), \
             patch('spectral_learning.services.behavior_signal_inputs.load_raw_chunks',side_effect=lambda day:copy.deepcopy(self.fixture.graphs[day])), \
             patch('torch.optim.Adam',side_effect=AssertionError('No new training')):
            return build_behavior_signal_inputs(self.experiment,alpha=.25,normal_day_roles=roles,**options)

    def test_whole_normal_days_extend_group_roles_without_refitting_node_calibration(self):
        from spectral_learning.services.hierarchy_behavior import read_signal_bundle
        roles={'2026-06-15':'normal_group_train','2026-06-16':'normal_group_calibration','2026-06-17':'normal_group_test'}
        for day in roles:self.add_normal_day(day)
        result=self.extended_export(roles);folder=Path(result['directory'])
        manifest,days,normal=read_signal_bundle(folder)
        self.assertEqual(normal,'2026-06-20');self.assertEqual(manifest['identity']['normal_group_day_roles'],roles)
        for day,role in roles.items():
            self.assertEqual({r['split'] for r in days[day].values()},{role})
        calibration=json.loads((folder/'calibration.json').read_text())
        self.assertEqual(calibration['degree:connected']['n'],9)
        self.assertIn('2026-06-22',manifest['identity']['protected_historical_signatures'])

    def test_resume_whole_day_roles_keeps_protected_history_and_payload(self):
        roles={'2026-06-15':'normal_group_calibration'}
        self.add_normal_day('2026-06-15')
        first=self.extended_export(roles);folder=Path(first['directory'])
        payload=(folder/'observations.jsonl').read_bytes()
        with patch('spectral_learning.services.behavior_signal_inputs._evaluate',
                   side_effect=AssertionError('Resume must not infer')):
            second=self.extended_export(roles,resume_bundle=folder)
        self.assertEqual(first['run_id'],second['run_id'])
        self.assertEqual(payload,(folder/'observations.jsonl').read_bytes())
        # Changing the day role cannot reuse even an otherwise intact payload.
        with self.assertRaisesRegex(ValueError,'identity differs'):
            self.extended_export({'2026-06-15':'normal_group_train'},resume_bundle=folder)

    def test_new_normal_days_reject_historical_aliases_and_non_normal_labels(self):
        self.add_normal_day('2026-06-15');roles={'2026-06-15':'normal_group_calibration'}
        first=self.fixture.graphs['2026-06-15'][0].node_ids[0]
        historical=self.fixture.graphs['2026-06-22'][0].node_ids[0]
        self.fixture.db.security_data.update_one({'_id':first},{'$set':{'original_id':historical}})
        with self.assertRaisesRegex(ValueError,'repeated raw IDs/content'):
            self.extended_export(roles)
        self.fixture.db.security_data.update_one({'_id':first},{'$unset':{'original_id':''},'$set':{'label':1}})
        with self.assertRaisesRegex(ValueError,'raw label=0'):
            self.extended_export(roles)

    def test_prepare_command_assigns_day_roles_and_runs_frozen_then_group_steps(self):
        from django.core.management import call_command
        import io
        module='spectral_learning.management.commands.prepare_normal_group_reference.'
        with patch(module+'get_db',return_value=self.fixture.db),patch(module+'load_hierarchy') as preflight, \
             patch(module+'build_behavior_signal_inputs',return_value={'directory':'node-out'}) as node, \
             patch(module+'run_hierarchy_behavior',return_value={'directory':'group-out'}) as group:
            call_command('prepare_normal_group_reference',experiment_bundle=str(self.experiment),
                fit_days=['2026-06-15','2026-06-16'],calibration_days=['2026-06-17','2026-06-18'],
                test_days=['2026-06-19'],write=True,stdout=io.StringIO())
        self.assertEqual(node.call_args.kwargs['normal_day_roles']['2026-06-19'],'normal_group_test')
        self.assertEqual(preflight.call_count,7)
        self.assertEqual(group.call_args.args[0],'node-out')
        self.assertTrue(group.call_args.kwargs['write'])

    def test_modified_export_payload_is_rejected_before_persistence(self):
        result = self.export(); folder = Path(result['directory'])
        run = json.loads((folder/'manifest.json').read_text())
        path = folder/'observations.jsonl'; path.write_text(path.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'payload checksum'):
            persist_inputs(self.fixture.db, run, path)

    def test_changed_raw_records_stop_export(self):
        doc = self.fixture.db.security_data.find_one()
        try:
            self.fixture.db.security_data.update_one({'_id': doc['_id']}, {'$set': {'bytes': 987654}})
            with self.assertRaisesRegex(ValueError, 'source/provenance changed'):
                self.export()
        finally:
            self.fixture.db.security_data.replace_one({'_id': doc['_id']}, doc)

    def test_persistence_is_idempotent_and_retry_repairs_partial_batch(self):
        result = self.export(); folder = Path(result['directory']); run = json.loads((folder/'manifest.json').read_text())
        # mongomock does not support current PyMongo UpdateOne bulk options;
        # execute the same update specifications through its update_one API.
        collection = self.fixture.db.behavior_observations
        def bulk(operations, ordered=False):
            for operation in operations:
                collection.update_one(operation._filter, operation._doc, upsert=operation._upsert)
        self.fixture.db.behavior_analysis_runs.delete_many({}); collection.delete_many({})
        try:
            with patch.object(collection, 'bulk_write', side_effect=RuntimeError('interrupted')):
                with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                    persist_inputs(self.fixture.db, run, folder/'observations.jsonl')
            self.assertEqual(self.fixture.db.behavior_analysis_runs.find_one() ['status'], 'failed')
            with patch.object(collection, 'bulk_write', side_effect=bulk):
                persist_inputs(self.fixture.db, run, folder/'observations.jsonl')
                persist_inputs(self.fixture.db, run, folder/'observations.jsonl')
            self.assertEqual(collection.count_documents({}), 72)
            self.assertEqual(self.fixture.db.behavior_analysis_runs.find_one()['status'], 'complete')
            row = collection.find_one()
            collection.update_one({'_id': row['_id']}, {'$set': {'fusion.score': 123}})
            with patch.object(collection, 'bulk_write', side_effect=bulk):
                with self.assertRaisesRegex(ValueError, 'content conflict'):
                    persist_inputs(self.fixture.db, run, folder/'observations.jsonl')
            self.assertEqual(self.fixture.db.behavior_analysis_runs.find_one()['status'], 'failed')
        finally:
            self.fixture.db.behavior_analysis_runs.delete_many({}); collection.delete_many({})
