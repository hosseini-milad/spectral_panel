import unittest
from unittest.mock import patch

import numpy as np
from scipy import sparse

from spectral_learning.services.spectral_inputs import GraphInput, feature_array, FEATURES
from spectral_learning.services.spectral_core import analyze_graph, invariant_features, adjacency, normalized_laplacian


def graph_input(n, pairs):
    return GraphInput('test-graph', '2026-06-21', 2, None, 'component', [str(i) for i in range(n)],
                      [{'source': a, 'target': b, 'weight': w} for a, b, w in pairs],
                      np.ones((n, 3)), np.ones((n, 3), dtype=bool), ('a', 'b', 'c'), {'version': 'test'})


class SpectralCoreTests(unittest.TestCase):
    def test_disconnected_paths_and_isolate_have_expected_spectra_and_masks(self):
        graph = graph_input(6, [(0, 1, 1), (1, 2, 1), (3, 4, 1)])
        result = analyze_graph(graph)
        self.assertEqual(result.summary['expected_zero_modes'], 3)
        self.assertEqual(result.summary['expected_positive_rank'], 3)
        self.assertEqual(result.summary['global_lambda2'], 0)
        self.assertEqual(result.summary['encoded_node_count'], 5)
        self.assertFalse(result.arrays['node_spectral_mask'][5])
        self.assertFalse(result.arrays['basis_mask'][5].any())
        np.testing.assert_allclose(result.blocks[0]['full_eigenvalues'], [0, 1, 2], atol=1e-12)
        self.assertEqual(result.summary['spectrum_kind'], 'full')
        self.assertLess(result.summary['max_residual'], 1e-12)
        arrays = result.arrays; valid = arrays['basis_mask']
        rows = np.broadcast_to(np.arange(6)[:, None], valid.shape)[valid]
        global_basis = sparse.csr_matrix((arrays['eigenvectors'][valid], (rows, arrays['basis_global_columns'][valid])),
                                         shape=(6, len(arrays['global_basis_eigenvalues'])))
        matrix, _, _ = adjacency(6, graph.edges); lap, _ = normalized_laplacian(matrix)
        residual = lap @ global_basis - global_basis @ sparse.diags(arrays['global_basis_eigenvalues'])
        self.assertLess(np.linalg.norm(residual.data), 1e-12)
        np.testing.assert_allclose((global_basis.T @ global_basis).toarray(), np.eye(3), atol=1e-12)

    def test_sparse_cycle_avoids_dense_matrix_and_preserves_complete_repeated_groups(self):
        n = 80
        graph = graph_input(n, [(i, (i + 1) % n, 1) for i in range(n)])
        with patch.object(sparse.csr_matrix, 'toarray', side_effect=AssertionError('Unexpected dense allocation')):
            result = analyze_graph(graph, requested=3, budget=16, dense_limit=16)
        block = result.blocks[0]
        self.assertEqual(block['solver'], 'sparse_deflated_connected_block')
        self.assertEqual(block['basis_dim'], 4)
        self.assertAlmostEqual(block['fiedler_value'], 1 - np.cos(2 * np.pi / n), places=8)
        self.assertEqual(result.summary['spectrum_kind'], 'mixed_full_and_partial')
        self.assertIsNone(result.summary['full_spectrum_entropy'])
        self.assertIsNone(result.summary['full_spectrum_histogram'])

    def test_projector_signatures_ignore_signs_and_rotations_within_repeated_groups(self):
        n = 12
        result = analyze_graph(graph_input(n, [(i, (i + 1) % n, 1) for i in range(n)]), requested=3, budget=8)
        block = result.blocks[0]; dim = block['basis_dim']
        vectors = result.arrays['eigenvectors'][:, :dim]
        values = np.array(block['selected_values']); groups = block['eigenvalue_groups']
        rotated = vectors.copy(); rng = np.random.default_rng(33)
        for group in groups:
            q, _ = np.linalg.qr(rng.normal(size=(len(group), len(group))))
            rotated[:, group] = rotated[:, group] @ q
        before = invariant_features(vectors, values, groups, result.arrays['edge_index'].T)
        after = invariant_features(-rotated, values, groups, result.arrays['edge_index'].T)
        for left, right in zip(before, after):
            np.testing.assert_allclose(left, right, atol=1e-12)

    def test_basis_budget_never_splits_a_large_degenerate_eigenspace(self):
        graph = graph_input(10, [(i, j, 1) for i in range(10) for j in range(i + 1, 10)])
        limited = analyze_graph(graph, requested=2, budget=4)
        self.assertEqual(limited.summary['basis_limited_blocks'], 1)
        self.assertEqual(limited.summary['encoded_node_count'], 0)
        complete = analyze_graph(graph, requested=2, budget=12)
        self.assertEqual(complete.blocks[0]['basis_dim'], 9)
        self.assertEqual(complete.summary['encoded_node_count'], 10)

    def test_weak_connected_mode_is_not_removed_by_a_zero_threshold(self):
        result = analyze_graph(graph_input(4, [(0, 1, 1), (1, 2, 1e-9), (2, 3, 1)]))
        self.assertEqual(result.summary['expected_zero_modes'], 1)
        self.assertEqual(result.blocks[0]['basis_dim'], 3)
        self.assertGreater(result.blocks[0]['fiedler_value'], 0)
        self.assertLess(result.blocks[0]['fiedler_value'], 1e-8)

    def test_all_isolates_have_no_fake_spectral_encoding(self):
        result = analyze_graph(graph_input(4, []))
        self.assertEqual(result.summary['expected_positive_rank'], 0)
        self.assertIsNone(result.summary['encoded_nonisolate_percent'])
        self.assertFalse(result.arrays['basis_mask'].any())
        self.assertFalse(result.arrays['node_spectral_mask'].any())
        self.assertAlmostEqual(result.summary['full_spectrum_entropy'], 0)

    def test_invalid_edges_are_rejected(self):
        cases = [[(0, 2, 1)], [(0, 0, 1)], [(0, 1, -1)], [(0, 1, float('nan'))],
                 [(0, 1, 1), (1, 0, 1)], [(0.5, 1, 1)]]
        for edges in cases:
            with self.subTest(edges=edges), self.assertRaises(ValueError):
                analyze_graph(graph_input(2, edges))

    def test_bad_raw_eigenvalues_are_not_hidden_by_clipping(self):
        original = np.linalg.eigh
        def corrupt(matrix):
            values, vectors = original(matrix)
            values[-1] += 3
            return values, vectors
        with patch('numpy.linalg.eigh', side_effect=corrupt), self.assertRaisesRegex(ValueError, 'validation failed'):
            analyze_graph(graph_input(3, [(0, 1, 1), (1, 2, 1)]))

    def test_features_exclude_labels_scores_identifiers_and_duplicate_log_columns(self):
        values, mask = feature_array([{'bytes': .2, 'label': 1, 'threat_intel_score': 1,
                                       'chunk_index': 3, 'log_bytes': .2}])
        self.assertNotIn('label', FEATURES); self.assertNotIn('log_bytes', FEATURES)
        self.assertEqual(mask.sum(), 1)
        self.assertEqual(values[0, FEATURES.index('bytes')], .2)

    def test_message_passing_consumes_invariants_without_training(self):
        import torch
        from spectral_learning.models.eigenvector_gnn import EigenvectorAwareMessagePassing
        torch.manual_seed(1)
        result = analyze_graph(graph_input(6, [(i, (i + 1) % 6, 1) for i in range(6)]), requested=3)
        arrays = result.arrays
        model = EigenvectorAwareMessagePassing(3, hidden_dim=8, layers=1)
        def tensor(name):
            value = arrays[name]
            return torch.tensor(value, dtype=torch.bool if value.dtype == bool else (torch.long if name == 'edge_index' else torch.float32))
        output = model(tensor('node_features'), tensor('node_feature_mask'), tensor('node_spectral'),
                       tensor('node_spectral_mask'), tensor('edge_index'), tensor('edge_weight'),
                       tensor('edge_spectral'), tensor('edge_spectral_mask'), level=2)
        self.assertEqual(tuple(output.shape), (6, 8))
        self.assertTrue(torch.isfinite(output).all())
        output.square().mean().backward()
        self.assertTrue(any(parameter.grad is not None for parameter in model.parameters()))
        self.assertFalse(result.summary['message_passing_executed'])
