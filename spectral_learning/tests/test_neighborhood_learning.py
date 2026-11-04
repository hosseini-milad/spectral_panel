import copy
import csv
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch

from spectral_learning.services.neighborhood_learning import (
    NeighborhoodAutoencoder, neighborhood_targets, fit_target_scaler, neighborhood_loss,
)
from spectral_learning.services.neighborhood_experiment import run_neighborhood_experiment
from spectral_learning.services.normal_behavior_reports import load_reference_bundle
from spectral_learning.services.autoencoder_inputs import prepare_chunks
from spectral_learning.tests import test_normal_behavior as fixtures


class NeighborhoodMathTests(unittest.TestCase):
    def test_detached_probe_cannot_update_encoder_but_auxiliary_can(self):
        model = NeighborhoodAutoencoder(3, 6, 2, 1)
        z = model.bottleneck(torch.ones(4, 6, requires_grad=True))
        model.decode_neighborhood(z, detach=True).sum().backward()
        self.assertTrue(all(p.grad is None for p in model.bottleneck.parameters()))
        model.zero_grad(); model.decode_neighborhood(z).sum().backward()
        self.assertTrue(any(p.grad is not None and p.grad.abs().sum() > 0 for p in model.bottleneck.parameters()))

    def test_missing_targets_are_not_zero_targets(self):
        prediction = torch.zeros(2, 5, requires_grad=True)
        values = np.ones((2, 5), dtype='float32'); mask = np.zeros((2, 5), dtype=bool)
        mask[:, 0] = True
        loss = neighborhood_loss(prediction, values, mask); loss.backward()
        self.assertGreater(float(loss.detach()), 0)
        self.assertTrue(torch.all(prediction.grad[:, 1:] == 0))


class NeighborhoodExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = fixtures.NormalBehaviorTests(); cls.fixture.setUp()
        cls.bundle = Path(cls.fixture.run_pipeline()['paths']['directory'])

    @classmethod
    def tearDownClass(cls):
        cls.fixture.doCleanups()

    def run_experiment(self, **options):
        with patch('spectral_learning.services.neighborhood_experiment.get_db', return_value=self.fixture.db), \
             patch('spectral_learning.services.neighborhood_experiment.load_raw_chunks',
                   side_effect=lambda day: copy.deepcopy(self.fixture.graphs[day])):
            return run_neighborhood_experiment(self.bundle, ['2026-06-21'], seeds=[17], epochs=2, **options)

    def test_targets_use_full_graph_and_train_scaler_ignores_test(self):
        _, scaler, *_ = load_reference_bundle(self.bundle)
        graph = copy.deepcopy(self.fixture.graphs['2026-06-20'][0])
        chunk = prepare_chunks([graph], {graph.key: 'train'}, scaler, max_pairs=4, required_splits=())[0]
        values, mask = neighborhood_targets(chunk); width = chunk.values.shape[1]
        self.assertAlmostEqual(float(values[1, 0]), np.log1p(2), places=6)
        self.assertTrue(mask[9:, 0].all()); self.assertFalse(mask[9:, 1:].any())
        self.assertFalse(mask[0, 1+width:].any())  # one neighbor cannot estimate spread
        self.assertTrue(mask[1, 1+width:].all())
        targets = {chunk.graph.key: (values, mask)}
        normalizer = fit_target_scaler([chunk], targets)
        test = copy.deepcopy(chunk); test.graph.key = 'test'; test.split = 'test'
        targets['test'] = (values * 1000, mask)
        again = fit_target_scaler([chunk, test], targets)
        np.testing.assert_array_equal(normalizer['mean'], again['mean'])

    def test_paired_training_exports_evidence_without_changing_reference_or_db(self):
        before = {p.name: p.read_bytes() for p in self.bundle.glob('*model.pt')}
        records = self.fixture.db.security_data.count_documents({})
        result = self.run_experiment(); folder = Path(result['directory'])
        manifest = json.loads((folder / 'manifest.json').read_text())
        self.assertEqual(manifest['status'], 'complete')
        self.assertTrue(manifest['paired_initialization_verified'])
        self.assertTrue(manifest['weights_unchanged_during_evaluation'])
        self.assertEqual(len(manifest['artifacts']), 4)
        self.assertEqual(self.fixture.db.security_data.count_documents({}), records)
        for p in self.bundle.glob('*model.pt'):
            self.assertEqual(p.read_bytes(), before[p.name])
        with (folder / 'aggregate_metrics.csv').open(encoding='utf-8-sig') as stream:
            rows = list(csv.DictReader(stream))
        empty = [r for r in rows if r['family'] in ('neighbor_mean', 'neighbor_std') and r['group'] == 'isolated']
        self.assertTrue(empty); self.assertTrue(all(r['targets'] == '0' and r['mse'] == '' for r in empty))
        p = folder / 'seed-17/spectral/neighborhood/2026-06-21/chunk-0.npz'
        with np.load(p, allow_pickle=False) as arrays:
            self.assertEqual(arrays['latent'].shape, (12, 3))
            self.assertFalse(arrays['neighbor_mean_valid'][9:].any())
            self.assertTrue(arrays['degree_valid'].all())
            self.assertEqual(len(arrays['raw_record_ids']), 12)
        for name in ['neighborhood_comparison.png', 'neighborhood_comparison.svg', 'neighborhood_schematic.svg']:
            self.assertGreater((folder / name).stat().st_size, 0)

    def test_baseline_probe_preserves_original_core_training_exactly(self):
        from spectral_learning.services.neighborhood_learning import train_pair
        from spectral_learning.services.autoencoder_training import train_shared
        _, scaler, parameters, *_ = load_reference_bundle(self.bundle)
        graphs = copy.deepcopy(self.fixture.graphs['2026-06-20'])
        splits = dict(zip([g.key for g in graphs], ['train', 'validation', 'calibration', 'test']))
        chunks = prepare_chunks(graphs, splits, scaler, max_pairs=8, required_splits=())
        original = train_shared(chunks, scaler, epochs=2, hidden=12, latent=3, layers=1, seed=17)
        pair, _ = train_pair(chunks, scaler, parameters, variant='spectral', seed=17, epochs=2,
                             auxiliary_weight=.1)
        for key, value in original['spectral']['state'].items():
            torch.testing.assert_close(value, pair['baseline']['state'][key], rtol=0, atol=0)

    def test_source_mutation_fails_and_marks_incomplete_run(self):
        original = self.fixture.db.security_data.find_one()
        def mutation(*args, **kwargs):
            from spectral_learning.services.neighborhood_learning import train_pair
            result = train_pair(*args, **kwargs)
            self.fixture.db.security_data.update_one({'_id': original['_id']}, {'$set': {'bytes': -999}})
            return result
        try:
            with patch('spectral_learning.services.neighborhood_experiment.train_pair', side_effect=mutation):
                with self.assertRaisesRegex(ValueError, 'changed'):
                    self.run_experiment()
        finally:
            self.fixture.db.security_data.replace_one({'_id': original['_id']}, original)
        statuses = list(Path(self.fixture.directory.name).glob('document/**/neighborhood_learning/runs/*/run_status.json'))
        self.assertTrue(any(json.loads(p.read_text())['status'] == 'failed' for p in statuses))

    def test_invalid_inputs_fail_before_database_access(self):
        with patch('spectral_learning.services.neighborhood_experiment.get_db', side_effect=AssertionError('DB')):
            for weight in [0, -1, float('nan')]:
                with self.assertRaises(ValueError):
                    self.run_experiment(auxiliary_weight=weight)
