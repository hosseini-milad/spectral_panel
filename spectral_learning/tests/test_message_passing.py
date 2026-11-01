import importlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from django.core.management import call_command, CommandError

from spectral_learning.tests.test_spectral_core import graph_input
from spectral_learning.services.spectral_core import analyze_graph
from spectral_learning.services.message_passing_evaluation import (
    evaluate_message_passing, split_features, perturb_graph, pool_blocks, fit_probe, tensors,
)
from spectral_learning.services.message_passing_reports import input_audit


class MessagePassingTests(unittest.TestCase):
    def make_graph(self):
        graph = graph_input(12, [(i, i + 1, .9) for i in range(10)])
        graph.features = np.column_stack([np.linspace(0, 1, 12), np.arange(12) % 3, np.linspace(1, 2, 12)])
        return graph

    def test_heldout_entries_are_disjoint_and_scaling_uses_training_only(self):
        graph = self.make_graph()
        target, train, val, test, mean, scale = split_features(graph.features, graph.feature_mask)
        self.assertFalse((train & val).any()); self.assertFalse((test & train).any()); self.assertFalse((val & test).any())
        np.testing.assert_array_equal(train | val | test, graph.feature_mask)
        for col in range(3):
            self.assertAlmostEqual(mean[col], graph.features[train[:, col], col].mean())
        modified = graph.features.copy(); modified[val | test] += 1000
        _, _, _, _, changed_mean, changed_scale = split_features(modified, graph.feature_mask)
        np.testing.assert_array_equal(mean, changed_mean); np.testing.assert_array_equal(scale, changed_scale)
        result = analyze_graph(graph)
        args = tensors(result.arrays, target, train)
        # Encoder's first operation masks these values; all held-out entries remain absent.
        self.assertFalse(args[1].numpy()[val | test].any())

    def test_interventions_recompute_topology_and_training_is_reproducible(self):
        graph = self.make_graph(); result = analyze_graph(graph)
        evaluated = evaluate_message_passing(graph, result, epochs=3, hidden=8, layers=1, repeats=1)
        self.assertEqual(evaluated['spectral']['embedding'].shape, (12, 8))
        self.assertLess(evaluated['permutation_error'], 1e-5)
        self.assertLess(evaluated['eigenspace_invariance_error'], 1e-12)
        self.assertTrue(np.isfinite(evaluated['spectral']['embedding']).all())
        dropped = next(row for row in evaluated['interventions'] if row['intervention'] == 'edge_drop')
        self.assertEqual(dropped['component_count_delta'], 1)
        again = evaluate_message_passing(graph, result, epochs=3, hidden=8, layers=1, repeats=1)
        np.testing.assert_array_equal(evaluated['spectral']['embedding'], again['spectral']['embedding'])
        self.assertEqual(int(evaluated['pooled_sizes'].sum()), 12)
        self.assertEqual(evaluated['pooled_sizes'][-1], 1)
        np.testing.assert_allclose(evaluated['pooled_std'][-1], 0, atol=.001)

    def test_perturbations_do_not_mutate_sources_and_empty_edges_are_explicit(self):
        graph = self.make_graph(); before = graph.signature
        altered, count = perturb_graph(graph, 'edge_weight', .05, 17)
        self.assertEqual(graph.signature, before); self.assertGreater(count, 0)
        self.assertNotEqual(altered.edges, graph.edges)
        empty = graph_input(6, []); result = analyze_graph(empty)
        ev = evaluate_message_passing(empty, result, epochs=1, hidden=8, layers=1, repeats=1)
        self.assertTrue(all(row['status'] == 'not_applicable_no_items' for row in ev['interventions'][:2]))
        self.assertTrue(np.isfinite(ev['spectral']['embedding']).all())

    def test_audit_detects_mixed_thresholds_and_indirect_score_input(self):
        first = self.make_graph(); first.layer = 1
        first.source = {'graph_parameters': {'similarity_threshold': .95, 'feature_fields': ['bytes', 'threat_intel_score']}}
        second = self.make_graph(); second.layer = 1; second.key = 'second'
        second.source = {'graph_parameters': {'similarity_threshold': .995, 'feature_fields': ['bytes']}}
        audit = input_audit([first, second])
        self.assertTrue(any(row['status'] == 'mixed' for row in audit))
        self.assertTrue(any(row['status'] == 'review_required' for row in audit))
        second.source = {'graph_parameters': dict(first.source['graph_parameters'], chunk_index=1)}
        first.source['graph_parameters']['chunk_index'] = 0
        self.assertTrue(any(row['status'] == 'consistent' for row in input_audit([first, second])))


class MessagePassingPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = importlib.import_module('hierarchy.tests.test_component_hierarchy').ComponentHierarchyTests
        cls.fixture.setUpClass(); cls.db = cls.fixture.db

    @classmethod
    def tearDownClass(cls):
        cls.fixture.tearDownClass()

    def setUp(self):
        from hierarchy.services.component_hierarchy import build_hierarchy
        from spectral_learning.services.spectral_pipeline import run_spectral
        self.fixture().setUp()
        with patch('hierarchy.services.component_hierarchy_report.write_reports', return_value={'directory': 'fixture'}):
            build_hierarchy('2026-06-21')
        self.phase1 = run_spectral('2026-06-21', requested=2, budget=8)

    def test_command_persists_all_nodes_pool_membership_reports_and_retained_versions(self):
        from spectral_learning.services.message_passing_pipeline import run_message_passing
        stream = io.StringIO()
        call_command('spectral_message_passing', day='2026-06-21', epochs=2, hidden_dim=8, layers=1, perturbation_repeats=1, stdout=stream)
        self.assertIn('PHASE 2 COMPLETE', stream.getvalue())
        self.assertEqual(self.db.spectral_message_passing_nodes.count_documents({}), 16)
        pointer = self.db.spectral_message_passing_active.find_one()
        run = self.db.spectral_message_passing_runs.find_one({'_id': pointer['run_id']})
        manifest = json.loads(Path(run['phase_artifacts']['manifest']).read_text())
        self.assertEqual(manifest['phase1_run_id'], self.phase1['run_id'])
        self.assertEqual(manifest['parent_graph'], 'not_created')
        for graph in manifest['graphs']:
            features = np.load(graph['artifacts']['features'], allow_pickle=False)
            self.assertEqual(len(features['node_embeddings']), graph['node_count'])
            self.assertEqual(int(features['pooled_sizes'].sum()), graph['node_count'])
            self.assertTrue(Path(graph['artifacts']['pooling_schematic']).exists())
            self.assertFalse(list(Path(graph['artifacts']['directory']).glob('*.html')))
        with patch('spectral_learning.services.message_passing_pipeline.graph_report', side_effect=OSError('disk failed')):
            with self.assertRaisesRegex(OSError, 'disk failed'):
                run_message_passing('2026-06-21', epochs=1, hidden=8, layers=1, repeats=1, force=True)
        self.assertEqual(self.db.spectral_message_passing_active.find_one()['run_id'], run['_id'])
        self.assertEqual(self.db.spectral_message_passing_runs.count_documents({'status': 'failed'}), 1)
        self.assertEqual(self.db.spectral_analysis_active.find_one()['run_id'], self.phase1['run_id'])

    def test_stale_sources_and_invalid_options_are_rejected(self):
        from spectral_learning.services.message_passing_pipeline import run_message_passing
        self.db.component_hierarchy_edges.update_one({}, {'$set': {'weight': .1}})
        with self.assertRaisesRegex(ValueError, 'differ from phase 1'):
            run_message_passing('2026-06-21', epochs=1)
        self.assertEqual(self.db.spectral_message_passing_runs.count_documents({}), 0)
        for options in ({'epochs': 0}, {'hidden_dim': 2}, {'day': 'invalid'}):
            with self.assertRaises(CommandError):
                call_command('spectral_message_passing', **dict({'day': '2026-06-21'}, **options))
