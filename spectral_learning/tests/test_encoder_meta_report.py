import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from spectral_learning.services.encoder_meta_report import build_meta_view


class EncoderMetaReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'chunk'; self.folder.mkdir()
        np.savez(self.folder / 'inputs.npz', node_ids=['a', 'b', 'c'], component_index=[0, 0, 1], component_ids=['C0', 'C1'])
        np.savez(self.folder / 'spectral_outputs.npz', latent=np.array([[0., 2.], [2., 4.], [10., 6.]]))
        self.manifest = self.root / 'manifest.json'
        self.manifest.write_text(json.dumps(dict(source_day='2026-06-22', run_id='test', status='complete', chunks=[dict(graph_key='graph', chunk_index=0, nodes=3, paths=dict(directory=str(self.folder)))])))
        self.lineage = self.root / 'lineage.json'
        self.data = dict(nodes=[dict(source_day='2026-06-22', source_file='graph', component_id='C0', member_node_ids=['a', 'b'], node_count=2, chunk_index=0), dict(source_day='2026-06-22', source_file='graph', component_id='C1', member_node_ids=['c'], node_count=1, chunk_index=0)], meta_components=[dict(meta_component_id='M0', node_indices=[0, 1])])
        self.output = self.root / 'out'

    def run_report(self):
        self.lineage.write_text(json.dumps(self.data))
        return build_meta_view(self.manifest, self.lineage, self.output)

    def test_node_weighted_pooling_retains_within_component_variance(self):
        result = self.run_report()
        with np.load(self.output / 'meta_encoder_features.npz') as arrays:
            raw = np.array([[0., 2.], [2., 4.], [10., 6.]])
            np.testing.assert_allclose(arrays['latent_mean'][0], raw.mean(0))
            np.testing.assert_allclose(arrays['latent_std'][0], raw.std(0))
            self.assertEqual(arrays['chunk_component_counts'].tolist(), [[2]])
        self.assertEqual(result['candidate_nodes'], 3)
        self.assertTrue((self.output / 'meta_encoder_schematic.png').is_file())

    def test_stale_candidate_membership_is_rejected(self):
        self.data['nodes'][0]['member_node_ids'] = ['a', 'different']
        with self.assertRaisesRegex(ValueError, 'membership differs'):
            self.run_report()
        self.assertFalse(self.output.exists())

    def test_duplicate_and_missing_component_assignment_are_rejected(self):
        self.data['meta_components'][0]['node_indices'] = [0, 0]
        with self.assertRaisesRegex(ValueError, 'duplicate hierarchy membership'):
            self.run_report()
        self.data['meta_components'][0]['node_indices'] = [0]
        with self.assertRaisesRegex(ValueError, 'unassigned'):
            self.run_report()
