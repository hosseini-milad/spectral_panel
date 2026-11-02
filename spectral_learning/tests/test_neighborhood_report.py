import unittest
import numpy as np
from spectral_learning.services.neighborhood_report import analyze_neighborhoods


class NeighborhoodReportTests(unittest.TestCase):
    def test_known_neighbors_and_isolate_denominators(self):
        z = np.array([[1., 0.], [1., .1], [-1., 0.], [0., 0.]])
        nodes = [dict(component_id=str(i), source_file='graph') for i in range(4)]
        summary, rows, metas, near = analyze_neighborhoods(z, [0, 0, 1, 2], ['A', 'B', 'C'], nodes, [dict(source=0, target=1)], 1)
        self.assertEqual(near[0].tolist(), [1]); self.assertEqual(near[1].tolist(), [0])
        self.assertEqual(near[3].tolist(), [-1])
        self.assertEqual(summary['macro_graph_neighbor_recall'], 1.)
        self.assertEqual(summary['graph_neighbor_recall_valid_components'], 2)
        self.assertEqual(summary['graph_isolates'], 2)
        self.assertIsNone(rows[2]['graph_neighbor_recall'])
        self.assertIsNone(rows[3]['knn_same_meta_fraction'])
        self.assertAlmostEqual(rows[0]['same_meta_excess'], .5)
        self.assertAlmostEqual(metas[0]['rms_radius'], .05)
        self.assertEqual(metas[1]['rms_radius'], 0.)

    def test_ties_are_deterministic_self_excluded_and_k_capped(self):
        nodes = [dict(component_id=str(i), source_file='g') for i in range(3)]
        _, _, _, near = analyze_neighborhoods(np.ones((3, 2)), [0, 0, 0], ['A'], nodes, [], 10)
        self.assertEqual(near.tolist(), [[1, 2], [0, 2], [0, 1]])

    def test_cross_meta_edges_rejected(self):
        nodes = [dict(component_id=str(i), source_file='g') for i in range(2)]
        with self.assertRaisesRegex(ValueError, 'crosses'):
            analyze_neighborhoods(np.eye(2), [0, 1], ['A', 'B'], nodes, [dict(source=0, target=1)])

    def test_single_component_has_no_invented_neighbors(self):
        summary, rows, _, near = analyze_neighborhoods([[1., 0.]], [0], ['A'], [dict(component_id='0', source_file='g')], [])
        self.assertEqual(near.shape, (1, 0)); self.assertIsNone(summary['macro_graph_neighbor_recall'])
        self.assertIsNone(rows[0]['same_meta_excess'])
