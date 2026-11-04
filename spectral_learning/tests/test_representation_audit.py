import copy
import csv
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import torch

from . import test_normal_behavior as fixtures
from spectral_learning.services.representation_quality import covering_masks, latent_geometry, audit_chunk, measured_neighborhood
from spectral_learning.services.representation_audit import run_representation_audit
from spectral_learning.services.normal_behavior_reports import load_reference_bundle
from spectral_learning.services.autoencoder_inputs import prepare_chunks


class RepresentationQualityTests(unittest.TestCase):
    def test_covering_masks_are_disjoint_complete_reproducible_and_allow_missing_rows(self):
        mask = np.asarray([[True, False, True], [False, False, False], [False, True, False]])
        parts = covering_masks(mask, 5, 19)
        np.testing.assert_array_equal(parts.sum(axis=0), mask.astype(int))
        np.testing.assert_array_equal(parts, covering_masks(mask, 5, 19))
        self.assertFalse(parts[:, 1].any())
        self.assertTrue(np.all(parts[:, ~mask] == 0))
        with self.assertRaises(ValueError):
            covering_masks(mask, 1)

    def test_effective_rank_has_defined_geometry_not_an_attack_cutoff(self):
        stats = latent_geometry([[1, 0], [-1, 0], [0, 1], [0, -1]])
        self.assertAlmostEqual(stats['effective_rank'], 2)
        self.assertAlmostEqual(stats['participation_ratio'], 2)
        self.assertEqual(latent_geometry(np.zeros((4, 3)))['effective_rank'], 0)
        self.assertFalse(latent_geometry(np.ones((1, 3)))['rank_estimable'])
        with self.assertRaises(ValueError):
            latent_geometry([[np.nan]])

    def test_measured_neighbors_respect_missing_values_and_isolates(self):
        arrays = dict(edge_index=np.array([[0, 1], [1, 2]]), edge_weight=np.array([.5, .8]))
        values = np.array([[2., 0.], [4., 8.], [6., 10.], [0., 0.]])
        observed = np.array([[True, False], [True, True], [True, True], [False, False]])
        result = measured_neighborhood(arrays, values, observed)
        np.testing.assert_array_equal(result['degree'], [1, 2, 1, 0])
        np.testing.assert_allclose(result['weighted_degree'], [.5, 1.3, .8, 0])
        np.testing.assert_allclose(result['neighbor_feature_mean'][1], [4., 10.])
        np.testing.assert_allclose(result['neighbor_feature_std'][1], [2., 0.])
        np.testing.assert_array_equal(result['neighbor_observation_count'][1], [2, 1])
        self.assertFalse(result['neighbor_feature_valid'][3].any())


class RepresentationAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse graph/raw-record fixtures, but execute no inherited test methods.
        cls.fixture = fixtures.NormalBehaviorTests()
        cls.fixture.setUp()
        cls.bundle = Path(cls.fixture.run_pipeline()['paths']['directory'])

    @classmethod
    def tearDownClass(cls):
        cls.fixture.doCleanups()

    def run_audit(self, **kwargs):
        with patch('spectral_learning.services.representation_audit.get_db', return_value=self.fixture.db), \
             patch('spectral_learning.services.representation_audit.load_raw_chunks',
                   side_effect=lambda day: copy.deepcopy(self.fixture.graphs[day])):
            return run_representation_audit(self.bundle, ['2026-06-21'], mask_passes=3, **kwargs)

    def test_frozen_audit_exports_quality_contract_arrays_and_schematics_without_training(self):
        with patch('torch.optim.Adam', side_effect=AssertionError('Audit must not train')), \
             patch('spectral_learning.services.autoencoder_inputs.fit_scaler', side_effect=AssertionError('Audit must reuse scaler')):
            result = self.run_audit()
        folder = Path(result['directory'])
        manifest = json.loads((folder / 'manifest.json').read_text())
        contract = manifest['contract']
        self.assertTrue(manifest['weights_unchanged_verified'])
        self.assertEqual(manifest['model_acceptance'], 'not_decided_by_this_audit')
        self.assertEqual(contract['named_feature_weights']['status'], 'not_estimated')
        self.assertIsNone(contract['named_feature_weights']['values'])
        self.assertEqual(contract['uncertainty']['status'], 'not_calibrated')
        self.assertNotIn('thresholds', manifest)
        with (folder / 'graph_representation_quality.csv').open(encoding='utf-8-sig') as stream:
            quality = list(csv.DictReader(stream))
        self.assertEqual(len(quality), 18)  # 4 reference + 2 additional graphs, 3 variants.
        self.assertTrue(all(row['predicted_entries'] == row['observed_active_entries'] for row in quality))
        with np.load(folder / '2026-06-20' / 'chunk-0' / 'inputs.npz', allow_pickle=False) as inputs, \
             np.load(folder / '2026-06-20' / 'chunk-0' / 'spectral_representation.npz', allow_pickle=False) as arrays:
            np.testing.assert_array_equal(arrays['feature_target_coverage'], inputs['observed_active_mask'].astype(int))
            np.testing.assert_array_equal(inputs['feature_masks'].sum(axis=0), inputs['observed_active_mask'].astype(int))
            self.assertEqual(arrays['latent'].shape, (12, 3))
            self.assertEqual(arrays['mask_reconstruction_mse'].shape, (3, 12))
            self.assertEqual(int(arrays['component_size'].sum()), 12)
        for name in ['representation_audit_schematic.png', 'representation_audit_schematic.svg',
                     'representation_quality.png', 'coverage.csv', 'feature_reconstruction.csv']:
            self.assertGreater((folder / name).stat().st_size, 0)

    def test_zero_target_rows_have_invalid_error_instead_of_normality_claim(self):
        models, scaler, parameters, *_ = load_reference_bundle(self.bundle)
        graph = copy.deepcopy(self.fixture.graphs['2026-06-20'][0])
        chunk = prepare_chunks([graph], {graph.key: 'train'}, scaler, required_splits=())[0]
        chunk.mask[0] = False
        before = {key: value.clone() for key, value in models['spectral']['model'].state_dict().items()}
        summary, arrays, _ = audit_chunk(models['spectral']['model'], chunk, passes=5)
        self.assertFalse(arrays['feature_error_valid'][0])
        self.assertEqual(arrays['observed_active_count'][0], 0)
        self.assertEqual(summary['nodes_without_feature_targets'], 1)
        self.assertLessEqual(summary['permutation_max_absolute_error'], 1e-4)
        for key, value in models['spectral']['model'].state_dict().items():
            torch.testing.assert_close(value, before[key], rtol=0, atol=0)
        chunk.mask[:] = False
        summary, arrays, _ = audit_chunk(models['spectral']['model'], chunk, passes=5)
        self.assertIsNone(summary['covering_reconstruction_mse'])
        self.assertIsNone(summary['mask_relative_latent_change_mean'])
        self.assertFalse(arrays['feature_error_valid'].any())

    def test_mutated_source_is_not_reported_complete(self):
        calls = 0
        def load(day):
            nonlocal calls
            calls += 1
            graphs = copy.deepcopy(self.fixture.graphs[day])
            if calls > 2:
                graphs[0].features[0, 0] += 1
            return graphs
        with patch('spectral_learning.services.representation_audit.get_db', return_value=self.fixture.db), \
             patch('spectral_learning.services.representation_audit.load_raw_chunks', side_effect=load):
            with self.assertRaisesRegex(ValueError, 'Source graph/features changed'):
                run_representation_audit(self.bundle, ['2026-06-21'], mask_passes=2)
        base = Path(self.fixture.directory.name) / 'document' / 'autoencoder' / 'layer1' / '2026-06-20' / 'whole-day' / 'representation_audit' / 'runs'
        statuses = [json.loads(path.read_text())['status'] for path in base.glob('*/run_status.json')]
        self.assertIn('failed', statuses)

    def test_weight_change_prevents_successful_audit(self):
        original = audit_chunk
        def change_weight(model, *args, **kwargs):
            result = original(model, *args, **kwargs)
            with torch.no_grad():
                next(model.parameters()).add_(.001)
            return result
        with patch('spectral_learning.services.representation_audit.audit_chunk', side_effect=change_weight):
            with self.assertRaisesRegex(ValueError, 'weights changed'):
                self.run_audit()
