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
from spectral_learning.services.upper_graph import initial_moments, aggregate_moments, global_moments, build_upper_graph, descriptor_edges


class UpperGraphTests(unittest.TestCase):
    def test_recursive_moments_conserve_mass_variance_and_missing_observations(self):
        graph = graph_input(6, [(0, 1, 1), (2, 3, 1)])
        graph.features = np.arange(18).reshape(6, 3).astype(float)
        graph.feature_mask[1, 0] = False; graph.feature_mask[4, 2] = False
        state = initial_moments(graph)
        grouped = aggregate_moments(state, [{'node_indices': [0, 1]}, {'node_indices': [2, 3, 4]}, {'node_indices': [5]}])
        again = aggregate_moments(grouped, [{'node_indices': [0, 2]}, {'node_indices': [1]}])
        a, b = global_moments(state), global_moments(again)
        np.testing.assert_allclose(a.mean, b.mean); np.testing.assert_allclose(a.variance, b.variance)
        np.testing.assert_array_equal(a.count, b.count); self.assertEqual(float(again.mass.sum()), 6)

    def test_new_graph_is_not_an_empty_quotient_and_partition_is_exact(self):
        graph = graph_input(12, [(i, i + 1, 1) for i in range(0, 12, 2)])
        graph.features = np.tile(np.array([.1, .2, .3]), (12, 1))
        graph.lineage = [{'chunk_index': i % 2} for i in range(12)]
        result = analyze_graph(graph)
        parent, state, audit = build_upper_graph(graph, result, initial_moments(graph), run_id='test', neighbors=3)
        self.assertEqual(parent.layer, 3); self.assertEqual(len(parent.node_ids), 6)
        self.assertEqual(audit['quotient_cross_edges'], 0)
        self.assertGreater(len(parent.edges), 0)
        self.assertEqual(parent.source['edge_origin'], 'new_similarity_graph_not_quotient')
        self.assertEqual(float(state.mass.sum()), 12)
        self.assertTrue(all(row['source_chunks'] == [0, 1] for row in parent.lineage))
        self.assertLessEqual(parent.source['graph_parameters']['max_degree'], 3)
        self.assertEqual(graph.layer, 2)

    def test_similarity_matches_direct_distance_is_deterministic_and_bounded(self):
        rng = np.random.default_rng(9); x = rng.normal(size=(15, 6)); mask = np.ones_like(x, dtype=bool)
        edges, policy = descriptor_edges(x, mask, neighbors=4, threshold=.01)
        standardized = (x - x.mean(axis=0)) / x.std(axis=0)
        for edge in edges:
            expected = np.exp(-np.mean((standardized[edge['source']] - standardized[edge['target']]) ** 2) / 2)
            self.assertAlmostEqual(edge['weight'], expected, places=12)
        again, _ = descriptor_edges(x, mask, neighbors=4, threshold=.01, batch_size=3)
        self.assertEqual(edges, again); self.assertLessEqual(policy['max_degree'], 4)
        sparse_mask = np.zeros_like(mask); sparse_mask[:, :2] = True
        empty, _ = descriptor_edges(x, sparse_mask)
        self.assertEqual(empty, [])


class UpperPipelineTests(unittest.TestCase):
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
        from spectral_learning.services.message_passing_pipeline import run_message_passing
        self.fixture().setUp()
        with patch('hierarchy.services.component_hierarchy_report.write_reports', return_value={'directory': 'fixture'}):
            build_hierarchy('2026-06-21')
        self.phase1 = run_spectral('2026-06-21', requested=2, budget=8)
        self.phase2 = run_message_passing('2026-06-21', epochs=1, hidden=8, layers=1, repeats=1)

    def test_small_real_upper_run_has_spectra_lineage_and_explicit_training_skip(self):
        from spectral_learning.services.upper_pipeline import run_upper
        stream = io.StringIO()
        call_command('analyze_upper_hierarchy', day='2026-06-21', levels=2, epochs=1, hidden_dim=8, layers=1,
                     perturbation_repeats=1, stdout=stream)
        self.assertIn('[UPPER] COMPLETE', stream.getvalue())
        run = self.db.upper_spectral_runs.find_one({'status': 'complete'})
        self.assertEqual(self.db.upper_spectral_graphs.count_documents({'run_id': run['_id']}), 2)
        manifest = json.loads(Path(run['phase_artifacts']['manifest']).read_text())
        self.assertEqual(manifest['source_message_passing_run'], self.phase2['run_id'])
        self.assertEqual([row['layer'] for row in manifest['levels']], [3, 4])
        for record in manifest['levels']:
            self.assertTrue(record['spectral']['numerical_checks_pass'])
            self.assertEqual(record['message_passing_status'], 'not_run_insufficient_validation_test_entries')
            self.assertTrue(Path(record['construction']['schematic']).exists())
            arrays = np.load(record['construction']['graph'], allow_pickle=False)
            self.assertEqual(int(arrays['original_component_mass'].sum()), 6)
            self.assertTrue(record['aggregation_audit']['partition_exactly_once'])
            self.assertFalse(list(Path(record['construction']['directory']).glob('*.html')))
        previous = run['_id']
        with patch('spectral_learning.services.upper_pipeline.write_upper_graph', side_effect=OSError('disk failed')):
            with self.assertRaisesRegex(OSError, 'disk failed'):
                run_upper('2026-06-21', epochs=1, hidden=8, layers=1, repeats=1, force=True)
        self.assertEqual(self.db.upper_spectral_active.find_one()['run_id'], previous)
        self.assertEqual(self.db.spectral_message_passing_active.find_one()['run_id'], self.phase2['run_id'])

    def test_upper_graph_with_enough_nodes_executes_real_message_passing(self):
        from spectral_learning.services.upper_pipeline import run_upper
        graph = graph_input(20, [(i, i + 1, 1) for i in range(0, 20, 2)])
        graph.features = np.column_stack([np.linspace(0, 1, 20), np.arange(20) % 3, np.linspace(.2, .8, 20)])
        graph.lineage = [{'chunk_index': i % 2} for i in range(20)]
        source_run = dict(_id=self.phase2['run_id'], input_audit=[dict(graph_key='test', check='source', status='synthetic', detail='Fixture only')])
        phase1 = self.db.spectral_analysis_runs.find_one({'_id': self.phase1['run_id']})
        source = (graph, np.ones((20, 8)), source_run, phase1, 'fixture-source-digest')
        with patch('spectral_learning.services.upper_pipeline.load_source', return_value=source):
            result = run_upper('2026-06-21', levels=1, epochs=2, hidden=8, layers=1, repeats=1)
        record = result['levels'][0]
        self.assertEqual(record['spectral']['node_count'], 10)
        self.assertEqual(record['message_passing_status'], 'trained_and_evaluated')
        self.assertTrue(record['message_passing']['learned_embeddings_generated'])
        self.assertEqual(record['message_passing']['source_spectral_collection'], 'upper_spectral_runs')
        self.assertEqual(record['message_passing']['spectral_run_id'], result['run_id'])
        self.assertEqual(self.db.upper_spectral_nodes.count_documents({'run_id': result['run_id']}), 10)
        per_feature = record['message_passing']['spectral_probe']['per_feature']
        self.assertEqual(sum(row['test_entries'] for row in per_feature), record['message_passing']['spectral_probe']['test_entries'])

    def test_source_mutation_and_bad_options_are_rejected(self):
        from spectral_learning.services.upper_pipeline import run_upper
        self.db.component_hierarchy_edges.update_one({}, {'$set': {'weight': .01}})
        with self.assertRaisesRegex(ValueError, 'changed since'):
            run_upper('2026-06-21')
        self.assertEqual(self.db.upper_spectral_runs.count_documents({}), 0)
        for extra in ({'levels': 0}, {'neighbors': 0}, {'bandwidth': float('nan')}, {'epochs': 0}, {'day': 'invalid'}):
            with self.assertRaises(CommandError):
                call_command('analyze_upper_hierarchy', **dict({'day': '2026-06-21'}, **extra))
