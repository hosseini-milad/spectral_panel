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

    def export(self):
        with patch('spectral_learning.services.behavior_signal_inputs.get_db', return_value=self.fixture.db), \
             patch('spectral_learning.services.behavior_signal_inputs.load_raw_chunks',
                   side_effect=lambda day: copy.deepcopy(self.fixture.graphs[day])), \
             patch('torch.optim.Adam', side_effect=AssertionError('Must not train')):
            return build_behavior_signal_inputs(self.experiment, alpha=.25)

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

    def test_tampered_checkpoint_stops_before_database_access(self):
        path = self.experiment/'seed-17/spectral/neighborhood/model.pt'; original = path.read_bytes()
        try:
            path.write_bytes(original + b'tamper')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                self.export()
        finally:
            path.write_bytes(original)

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
