import copy
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mongomock
import numpy as np
import torch
from django.test import override_settings
from django.core.management import call_command, CommandError

from spectral_learning.services.spectral_inputs import GraphInput, FEATURES
from spectral_learning.services.normal_behavior import (
    reference_splits, calibration_threshold, record_identity, tail_probabilities,
    run_normal_behavior_cpu, audit_graph_identities,
)
from spectral_learning.services.normal_behavior_reports import load_reference_bundle, permutation_dispersion, cosine_tie_audit


class NormalBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = override_settings(BASE_DIR=Path(self.directory.name))
        self.settings.enable(); self.addCleanup(self.settings.disable)
        self.db = mongomock.MongoClient().siem_db
        self.graphs = {}
        for day, count in [('2026-06-20', 4), ('2026-06-21', 2), ('2026-06-22', 2)]:
            graphs = []
            for chunk in range(count):
                n = 12
                values = np.zeros((n, len(FEATURES))); mask = np.ones_like(values, dtype=bool)
                for col, name in enumerate(FEATURES):
                    values[:, col] = (np.arange(n) + chunk + 1) * (col + 1) if col < 10 else np.arange(n) % 2
                ids = [f'{day}-{chunk}-{i}' for i in range(n)]
                for i, value in enumerate(ids):
                    self.db.security_data.insert_one(dict(_id=value, source_day=day, label=0 if day.endswith('20') else i % 2,
                        timestamp=f'{day}T00:{chunk:02d}:{i:02d}', bytes=float(values[i, 0])))
                graph = GraphInput(f'clustered-day-{day}-chunk-{chunk}', day, 1, chunk, 'candidate_flow',
                    ids, [dict(source=i, target=i+1, weight=.9) for i in range(8)],
                    values, mask, FEATURES, {'test_source': 1},
                    {frozenset(range(9)): f'{day}-{chunk}-connected',
                     **{frozenset([i]): f'{day}-{chunk}-isolate-{i}' for i in range(9, n)}},
                    [dict(original_id=value) for value in ids])
                graphs.append(graph)
            self.graphs[day] = graphs

    def run_pipeline(self, **options):
        with patch('spectral_learning.services.normal_behavior.get_db', return_value=self.db), \
             patch('spectral_learning.services.normal_behavior.load_raw_chunks', side_effect=lambda day: copy.deepcopy(self.graphs[day])):
            return run_normal_behavior_cpu('2026-06-20', ['2026-06-21', '2026-06-22'],
                epochs=1, hidden=12, latent=3, layers=1, max_pairs=8, alpha=.25, **options)

    def test_threshold_rank_ties_and_missing_calibration(self):
        self.assertEqual(calibration_threshold([1, 2, 3, 4], .4), 3)
        np.testing.assert_allclose(tail_probabilities([1, 2, 2, 3], [2, 4]), [4/5, 1/5])
        with self.assertRaises(ValueError):
            calibration_threshold([1, 2], .01)
        with self.assertRaises(ValueError):
            calibration_threshold([np.nan], .5)
        splits = reference_splits(self.graphs['2026-06-20'])
        self.assertEqual(set(splits.values()), {'train', 'validation', 'calibration', 'test'})

    def test_identity_detects_original_ids_and_exact_copies_without_metadata(self):
        original = dict(_id='a', source_day='2026-06-21', timestamp='actual-time', bytes=123, label=1)
        copied = dict(original, _id='b', source_day='2026-06-20', label=0)
        self.assertTrue(record_identity(original) & record_identity(copied))
        changed = dict(copied, timestamp='different', bytes=999, provenance={'id': 'a'})
        self.assertTrue(record_identity(original) & record_identity(changed, 'provenance.id'))

    def test_full_training_frozen_external_reports_and_replay(self):
        normal_id = self.graphs['2026-06-20'][0].lineage[0]['original_id']
        copied_id = self.graphs['2026-06-21'][0].lineage[0]['original_id']
        self.db.security_data.update_one({'_id': copied_id}, {'$set': {'original_id': normal_id}})
        result = self.run_pipeline(score_policy='feature_graph_gap')
        folder = Path(result['paths']['directory'])
        manifest = json.loads((folder / 'manifest.json').read_text())
        self.assertEqual(manifest['status'], 'complete')
        self.assertTrue(manifest['fixed_model_verified'])
        self.assertEqual(manifest['reference_basis'], 'user_declared_label_normal_mixed_day_artificial_reference')
        self.assertEqual(len(manifest['metrics']), 18)
        self.assertEqual(manifest['behavior_scoring']['selected_policy'], 'feature_graph_gap')
        self.assertTrue((folder / 'score_analysis' / 'feature_explanations.csv').exists())
        self.assertTrue((folder / 'score_analysis' / 'selected_policy_overview.png').exists())
        with (folder / 'score_analysis' / 'feature_explanations.csv').open(encoding='utf-8-sig') as stream:
            explanation = next(csv.DictReader(stream))
        self.assertEqual(explanation['comparison_model'], 'graph')
        self.assertAlmostEqual(float(explanation['graph_squared_error']),
                               (float(explanation['graph_prediction']) - float(explanation['target'])) ** 2, places=5)
        with patch('spectral_learning.services.normal_behavior.get_db', side_effect=AssertionError('Check-only must not query MongoDB')):
            call_command('evaluate_feature_graph_gap', day='2026-06-23', reference_bundle=str(folder),
                         check_only=True, stdout=io.StringIO())
        self.assertEqual(next(row for row in manifest['coverage'] if row['day'] == '2026-06-21')['removed_nodes'], 1)
        normal_test = [r for r in manifest['metrics'] if r['split'] == 'test']
        self.assertEqual(len(normal_test), 3)
        self.assertTrue(all(r['heldout_normal_false_alert_fraction'] is not None for r in normal_test))
        self.assertTrue(all(r['heldout_normal_false_alert_fraction'] is None for r in manifest['metrics'] if r['split'] == 'external_test'))
        for filename in ['node_scores.csv', 'lineage_audit.csv', 'component_scores.csv', 'dispersion_permutation.csv',
                         'normal_behavior_schematic.png', 'normal_behavior_schematic.svg', 'evaluation_overview.png']:
            self.assertGreater((folder / filename).stat().st_size, 0)
        for day in self.graphs:
            self.assertTrue((folder / day / 'behavior_schematic.svg').exists())
        with np.load(folder / '2026-06-22' / 'chunk-0_spectral.npz', allow_pickle=False) as arrays:
            self.assertEqual(arrays['latent'].shape, (12, 3))
            self.assertTrue(np.isfinite(arrays['score']).all())
        first, _, _, calibration, thresholds, _ = load_reference_bundle(folder)
        with patch('spectral_learning.services.normal_behavior.train_shared', side_effect=AssertionError('Replay must not retrain')):
            replay = self.run_pipeline(reference_bundle=folder)
        second, _, _, recalibration, rethresholds, _ = load_reference_bundle(replay['paths']['directory'])
        self.assertEqual(thresholds, rethresholds)
        for variant in first:
            np.testing.assert_array_equal(calibration[variant], recalibration[variant])
            for key, value in first[variant]['model'].state_dict().items():
                torch.testing.assert_close(value, second[variant]['model'].state_dict()[key], rtol=0, atol=0)

    def test_overlap_removes_only_copied_nodes_and_incident_edges(self):
        normal = self.db.security_data.find_one({'source_day': '2026-06-20'})
        copied = self.graphs['2026-06-21'][0].lineage[0]['original_id']
        self.db.security_data.update_one({'_id': copied}, {'$set': {'artificial_day': {'original_id': normal['_id']}}})
        seen = set()
        audit_graph_identities(self.db, self.graphs['2026-06-20'], seen, 'reference', reject=True, origin_field='artificial_day.original_id')
        kept, audit, _ = audit_graph_identities(self.db, self.graphs['2026-06-21'], seen, 'external', reject=False, origin_field='artificial_day.original_id')
        self.assertEqual([g.chunk for g in kept], [0, 1])
        self.assertEqual(len(kept[0].node_ids), 11)
        self.assertNotIn(copied, kept[0].node_ids)
        self.assertEqual(kept[0].edges[0]['source'], 0)
        self.assertEqual(kept[0].edges[0]['target'], 1)
        self.assertEqual(sum(len(part) for part in kept[0].block_lookup), 11)
        self.assertEqual(len(self.graphs['2026-06-21'][0].node_ids), 12)
        self.assertEqual(audit[0]['overlap_nodes'], 1)
        self.assertFalse(audit[0]['excluded'])
        self.assertEqual(audit[0]['removed_nodes'], 1)

    def test_reference_duplicates_fail_before_training(self):
        a = self.graphs['2026-06-20'][0].lineage[0]['original_id']
        b = self.graphs['2026-06-20'][1].lineage[0]['original_id']
        self.db.security_data.update_one({'_id': b}, {'$set': {'original_id': a}})
        with patch('spectral_learning.services.normal_behavior.train_shared') as train:
            with self.assertRaisesRegex(ValueError, 'repeated raw'):
                self.run_pipeline()
            train.assert_not_called()

    def test_reference_attack_tag_and_fully_overlapping_evaluation_fail_before_training(self):
        value = self.graphs['2026-06-20'][0].lineage[0]['original_id']
        self.db.security_data.update_one({'_id': value}, {'$set': {'label': 1}})
        with self.assertRaisesRegex(ValueError, 'include label=1'):
            self.run_pipeline()
        self.db.security_data.update_one({'_id': value}, {'$set': {'label': 0}})
        for doc in self.db.security_data.find({'source_day': '2026-06-21'}):
            self.db.security_data.update_one({'_id': doc['_id']}, {'$set': {'original_id': value}})
        with patch('spectral_learning.services.normal_behavior.train_shared') as train:
            with self.assertRaisesRegex(ValueError, 'no independent nodes'):
                self.run_pipeline()
            train.assert_not_called()

    def test_source_mutation_does_not_complete_run(self):
        calls = 0
        def load(day):
            nonlocal calls
            calls += 1
            graph = copy.deepcopy(self.graphs[day])
            if calls > 3:
                graph[0].features[0, 0] += 10
            return graph
        with patch('spectral_learning.services.normal_behavior.load_raw_chunks', side_effect=load), \
             patch('spectral_learning.services.normal_behavior.get_db', return_value=self.db):
            with self.assertRaisesRegex(ValueError, 'Source changed'):
                run_normal_behavior_cpu('2026-06-20', ['2026-06-21', '2026-06-22'],
                    epochs=1, hidden=12, latent=3, layers=1, max_pairs=8, alpha=.25)
        statuses = list(Path(self.directory.name).rglob('run_status.json'))
        self.assertEqual(len(statuses), 1)
        self.assertEqual(json.loads(statuses[0].read_text())['status'], 'failed')

    def test_permutation_baseline_is_reproducible_and_preserves_singletons(self):
        z = np.array([[0., 0.], [0., 1.], [10., 0.], [10., 1.], [99., 99.]])
        assignment = np.array([0, 0, 1, 1, 2])
        first = permutation_dispersion(z, assignment)
        second = permutation_dispersion(z, assignment)
        for a, b in zip(first, second):
            np.testing.assert_array_equal(a, b)
        self.assertEqual(first[0][-1], 0)
        self.assertEqual(first[1][-1], 0)
        ties = cosine_tie_audit(np.ones((20, 3)), k=3)
        self.assertEqual(ties['boundary_tie_fraction'], 1)
        self.assertEqual(ties['mean_candidates_at_knn_boundary'], 19)
        self.assertEqual(cosine_tie_audit(np.zeros((2, 3)))['zero_norm_components'], 2)

    def test_command_errors_are_readable(self):
        with self.assertRaises(CommandError):
            call_command('learn_normal_behavior', normal_day='2026-06-20', evaluate_days=['2026-06-20'], stdout=io.StringIO())
