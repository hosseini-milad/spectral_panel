import importlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from django.core.management import call_command, CommandError, get_commands

from hierarchy.services.component_hierarchy import build_hierarchy
from spectral_learning.services.spectral_pipeline import run_spectral


class SpectralPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = importlib.import_module('hierarchy.tests.test_component_hierarchy').ComponentHierarchyTests
        cls.fixture.setUpClass()
        cls.db = cls.fixture.db

    @classmethod
    def tearDownClass(cls):
        cls.fixture.tearDownClass()

    def setUp(self):
        self.fixture().setUp()
        # Upstream hierarchy numerics are real; rendering is independently tested
        # by hierarchy.tests. All spectral operators and outputs below are real.
        with patch('hierarchy.services.component_hierarchy_report.write_reports', return_value={'directory': 'upstream-fixture'}):
            self.hierarchy, _ = build_hierarchy('2026-06-21')

    def test_full_phase_persists_versioned_encodings_and_planning_only_upper_layers(self):
        result = run_spectral('2026-06-21', requested=3, budget=8)
        self.assertEqual(len(result['graphs']), 3)
        self.assertEqual(self.db.spectral_analysis_runs.find_one()['status'], 'complete')
        self.assertEqual(self.db.spectral_node_encodings.count_documents({}), 16)
        for graph in result['graphs']:
            self.assertTrue(graph['numerical_checks_pass'])
            self.assertFalse(graph['learned_embeddings_generated'])
            arrays = np.load(graph['artifacts']['features'], allow_pickle=False)
            self.assertEqual(arrays['eigenvectors'].shape, (graph['node_count'], 8))
            self.assertEqual(arrays['node_ids'].shape[0], graph['node_count'])
            self.assertTrue(Path(graph['artifacts']['schematic']).exists())
        manifest = json.loads(Path(result['phase']['manifest']).read_text())
        readiness = manifest['hierarchy_readiness']
        self.assertEqual([row['nodes'] for row in readiness if row['level'] >= 4], [2, 1])
        self.assertTrue(all(row['spectral_status'] == 'not_computed' for row in readiness if row['level'] >= 3))
        self.assertEqual(manifest['autoencoder'], 'not_run')
        self.assertEqual(self.db.component_hierarchy_runs.find_one()['status'], 'complete')
        self.assertNotIn('generate_hourly_spectral_reports', get_commands())

    def test_failure_and_changed_sources_do_not_replace_previous_active_run(self):
        first = run_spectral('2026-06-21', scope='components', requested=2, budget=8)
        with self.assertRaisesRegex(ValueError, 'exists'):
            run_spectral('2026-06-21', scope='components')
        with patch('spectral_learning.services.spectral_pipeline.write_graph', side_effect=OSError('disk unavailable')):
            with self.assertRaisesRegex(OSError, 'disk unavailable'):
                run_spectral('2026-06-21', scope='components', force=True)
        self.assertEqual(self.db.spectral_analysis_active.find_one()['run_id'], first['run_id'])
        self.assertEqual(self.db.spectral_analysis_runs.count_documents({'status': 'failed'}), 1)
        second = run_spectral('2026-06-21', scope='components', requested=2, budget=8, force=True)
        self.assertNotEqual(first['run_id'], second['run_id'])
        self.assertEqual(self.db.spectral_analysis_runs.count_documents({'status': 'complete'}), 2)
        self.assertEqual(self.db.spectral_node_encodings.count_documents({'run_id': first['run_id']}), 6)

    def test_source_mutation_during_analysis_is_not_published(self):
        from spectral_learning.services.spectral_reports import write_graph
        def mutate(graph, result, run_id):
            paths = write_graph(graph, result, run_id)
            self.db.component_hierarchy_edges.update_one({}, {'$set': {'weight': .91}})
            return paths
        with patch('spectral_learning.services.spectral_pipeline.write_graph', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'changed during spectral analysis'):
                run_spectral('2026-06-21', scope='components')
        self.assertEqual(self.db.spectral_analysis_active.count_documents({}), 0)
        self.assertEqual(self.db.spectral_analysis_runs.find_one()['status'], 'failed')

    def test_inconsistent_chunk_version_is_rejected_before_new_run(self):
        self.db.graph_metadata.update_one({}, {'$set': {'component_revision': 'changed'}})
        with self.assertRaisesRegex(ValueError, 'differs from the selected hierarchy run'):
            run_spectral('2026-06-21')
        self.assertEqual(self.db.spectral_analysis_runs.count_documents({}), 0)

    def test_command_scoped_chunk_executes_and_rejects_invalid_options(self):
        output = io.StringIO()
        call_command('spectral_analysis', day='2026-06-21', scope='chunks', chunk_index=0,
                     eigenvectors=2, max_basis=8, stdout=output)
        self.assertIn('PHASE 1 COMPLETE', output.getvalue())
        self.assertEqual(self.db.spectral_graphs.count_documents({}), 1)
        for extra in ({'day': '2026-02-30'}, {'day': '2026-06-21', 'max_basis': 2},
                      {'day': '2026-06-21', 'chunk_index': 0}):
            with self.assertRaises(CommandError):
                call_command('spectral_analysis', **extra)
