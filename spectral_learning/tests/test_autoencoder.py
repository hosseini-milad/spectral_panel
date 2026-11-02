import io
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch
from bson import ObjectId
from django.test import override_settings
from django.core.management import call_command, CommandError
from mongoengine import connect, disconnect, get_db

from ingestion.services.graph.components import persist_components
from spectral_learning.services.autoencoder_inputs import load_raw_chunks, chunk_splits, fit_scaler, prepare_chunks, FEATURES
from spectral_learning.services.autoencoder_training import train_shared
from spectral_learning.services.autoencoder_pipeline import run_autoencoder


class AutoencoderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(); cls.settings = override_settings(BASE_DIR=Path(cls.directory.name)); cls.settings.enable()
        disconnect(); connect('test_ae_' + uuid.uuid4().hex, host='localhost', port=27017, serverSelectionTimeoutMS=5000)
        cls.db = get_db(); cls.db.client.admin.command('ping')

    @classmethod
    def tearDownClass(cls):
        cls.db.client.drop_database(cls.db.name); disconnect(); connect('siem_db', host='localhost', port=27017)
        cls.settings.disable(); cls.directory.cleanup()

    def setUp(self):
        for name in self.db.list_collection_names(): self.db[name].delete_many({})
        for chunk in range(3):
            source = f'clustered-day-2026-06-21-chunk-{chunk}'; ids = []
            for i in range(12):
                original, sampled = ObjectId(), ObjectId(); ids.append(str(sampled))
                values = dict(bytes=10 + i * 3 + chunk, packets=i+1, duration_s=.1+i/10,
                              flag_syn=i % 2, protocol='tcp' if i % 2 else 'udp', iat_mean=0 if chunk < 2 else 42)
                self.db.security_data.insert_one(dict(values, _id=original, source_day='2026-06-21', label=chunk % 2))
                self.db.sampled_security_data.insert_one(dict(values, _id=sampled, original_id=str(original), source_file=source, source_day='2026-06-21'))
            metadata = dict(source_file=source, source_day='2026-06-21', node_ids=ids,
                            edges=[dict(source=i, target=i+1, weight=.95) for i in range(8)],
                            graph_parameters={'layer': 1, 'chunk_index': chunk, 'feature_fields': ['bytes', 'packets', 'duration_s']})
            self.db.graph_metadata.insert_one(dict(metadata)); persist_components(metadata, write_reports=False)

    def prepared(self):
        graphs = load_raw_chunks('2026-06-21'); splits = chunk_splits(graphs); scaler, audit = fit_scaler(graphs, splits)
        return graphs, splits, scaler, audit, prepare_chunks(graphs, splits, scaler, max_pairs=16)

    def test_raw_training_scaler_and_feature_masks_ignore_test_values_and_labels(self):
        graphs, splits, scaler, audit, prepared = self.prepared()
        self.assertNotIn('label', FEATURES); self.assertNotIn('threat_intel_score', FEATURES)
        original = scaler['mean'].copy()
        graphs[-1].features[:, 0] *= 1000
        updated, _ = fit_scaler(graphs, splits)
        np.testing.assert_array_equal(original, updated['mean'])
        self.assertFalse(scaler['active'][FEATURES.index('iat_mean')])
        self.assertEqual({c.split for c in prepared}, {'train', 'validation', 'test'})
        for chunk in prepared:
            self.assertFalse((chunk.fixed_hidden & ~chunk.mask).any())
            self.assertTrue(np.all(chunk.fixed_hidden.any(axis=1)[chunk.mask.any(axis=1)]))

    def test_hidden_edge_targets_are_absent_from_input_and_negatives_are_within_blocks(self):
        *_, prepared = self.prepared()
        for chunk in prepared:
            original = {tuple(sorted(pair)) for pair in chunk.original.arrays['edge_index'].T.tolist()}
            observed = {tuple(sorted(pair)) for pair in chunk.spectral.arrays['edge_index'].T.tolist()}
            positives = {tuple(sorted(pair)) for pair in chunk.pairs[:, :len(chunk.positive_weights)].T.tolist()}
            self.assertFalse(observed & positives); self.assertEqual(observed | positives, original)
            for a, b in chunk.pairs[:, len(chunk.positive_weights):].T:
                self.assertNotIn(tuple(sorted((int(a), int(b)))), original)
                self.assertEqual(chunk.original.arrays['block_index'][a], chunk.original.arrays['block_index'][b])
            self.assertTrue(chunk.spectral.summary['numerical_checks_pass'])

    def test_shared_training_is_deterministic_and_test_values_do_not_select_weights(self):
        _, _, scaler, _, prepared = self.prepared()
        first = train_shared(prepared, scaler, epochs=2, hidden=16, latent=4, layers=1)
        test = next(c for c in prepared if c.split == 'test'); test.values[:, 0] += 10
        second = train_shared(prepared, scaler, epochs=2, hidden=16, latent=4, layers=1)
        for variant in first:
            self.assertEqual(first[variant]['history'], second[variant]['history'])
            for key in first[variant]['state']:
                torch.testing.assert_close(first[variant]['state'][key], second[variant]['state'][key], rtol=0, atol=0)
            result = first[variant]['results'][prepared[0].graph.key]
            self.assertEqual(result['latent'].shape, (12, 4))
            self.assertTrue(np.isfinite(result['latent']).all())
            self.assertEqual(int(result['pooled_size'].sum()), 12)
            isolates = next(row for row in result['coverage'] if row['group'] == 'isolated')
            self.assertEqual(isolates['node_count'], 3)

    def test_command_writes_real_models_npz_statistics_schematics_and_versions(self):
        output = io.StringIO()
        call_command('train_layer1_autoencoder', day='2026-06-21', epochs=2, hidden_dim=16, latent_dim=4,
                     layers=1, max_pairs=16, stdout=output)
        self.assertIn('[AUTOENCODER] COMPLETE', output.getvalue())
        run = self.db.autoencoder_runs.find_one({'status': 'complete'}); folder = Path(run['paths']['directory'])
        manifest = json.loads(Path(run['paths']['manifest']).read_text())
        self.assertEqual(len(manifest['chunks']), 3); self.assertEqual(len(manifest['metrics']), 9)
        self.assertTrue(manifest['source_versions_verified'])
        self.assertTrue(Path(run['paths']['overview']).exists()); self.assertTrue(Path(run['paths']['schematic']).exists())
        checkpoint = torch.load(folder / 'spectral_model.pt', weights_only=True)
        self.assertEqual(checkpoint['parameters']['latent_dim'], 4)
        for chunk in manifest['chunks']:
            inputs = np.load(Path(chunk['paths']['directory']) / 'inputs.npz', allow_pickle=False)
            self.assertEqual(inputs['targets'].shape, (12, 21))
            for variant in ('feature', 'graph', 'spectral'):
                arrays = np.load(Path(chunk['paths']['directory']) / f'{variant}_outputs.npz', allow_pickle=False)
                self.assertEqual(arrays['latent'].shape, (12, 4))
            from spectral_learning.models.layer1_autoencoder import Layer1Autoencoder
            from spectral_learning.services.message_passing_evaluation import tensors
            replay_arrays = dict(edge_index=inputs['original_edge_index'], edge_weight=inputs['original_edge_weight'],
                node_spectral=inputs['inference_node_spectral'], node_spectral_mask=inputs['inference_node_spectral_mask'],
                edge_spectral=inputs['inference_edge_spectral'], edge_spectral_mask=inputs['inference_edge_spectral_mask'])
            replay = Layer1Autoencoder(21, hidden_dim=16, latent_dim=4, layers=1, variant='spectral')
            replay.load_state_dict(checkpoint['state_dict']); replay.eval()
            with torch.no_grad():
                _, latent = replay(tensors(replay_arrays, inputs['targets'], inputs['model_observed_mask']))
            exported = np.load(Path(chunk['paths']['directory']) / 'spectral_outputs.npz', allow_pickle=False)
            np.testing.assert_allclose(latent.numpy(), exported['latent'], rtol=1e-5, atol=1e-6)
            self.assertTrue(Path(chunk['paths']['schematic']).exists())
            self.assertFalse(list(Path(chunk['paths']['directory']).glob('*.html')))
        self.assertTrue((folder / 'constant_feature_shift_audit.csv').exists())
        before = self.db.autoencoder_active.find_one()['run_id']
        with patch('spectral_learning.services.autoencoder_pipeline.write_run', side_effect=OSError('disk unavailable')):
            with self.assertRaisesRegex(OSError, 'disk unavailable'):
                run_autoencoder('2026-06-21', epochs=1, hidden=16, latent=4, layers=1, max_pairs=16, force=True)
        self.assertEqual(self.db.autoencoder_active.find_one()['run_id'], before)
        self.assertEqual(self.db.autoencoder_runs.count_documents({'status':'failed'}), 1)
        with self.assertRaisesRegex(ValueError, 'exists'):
            run_autoencoder('2026-06-21')

    def test_mutated_source_is_not_published_and_invalid_options_fail(self):
        from spectral_learning.services.autoencoder_reports import write_run
        def mutate(*args, **kwargs):
            paths = write_run(*args, **kwargs)
            self.db.security_data.update_one({}, {'$inc': {'bytes': 1}})
            return paths
        with patch('spectral_learning.services.autoencoder_pipeline.write_run', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'changed during reporting'):
                run_autoencoder('2026-06-21', epochs=1, hidden=16, latent=4, layers=1, max_pairs=16)
        self.assertEqual(self.db.autoencoder_active.count_documents({}), 0)
        self.assertEqual(self.db.autoencoder_runs.find_one()['status'], 'failed')
        for values in ({'epochs': 0}, {'latent_dim': 21}, {'structure_weight': float('nan')}, {'day': 'bad'}):
            with self.assertRaises(CommandError):
                call_command('train_layer1_autoencoder', **dict({'day':'2026-06-21'}, **values))
