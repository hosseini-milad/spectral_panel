import importlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from django.core.management import call_command, get_commands, CommandError
from hierarchy.services.component_hierarchy import build_hierarchy
from hierarchy.services.component_hierarchy_evaluation import evaluate_hierarchy


class DailyCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = importlib.import_module('hierarchy.tests.test_component_hierarchy').ComponentHierarchyTests
        cls.fixture.setUpClass(); cls.db = cls.fixture.db

    @classmethod
    def tearDownClass(cls):
        cls.fixture.tearDownClass()

    def setUp(self):
        self.fixture().setUp()

    def test_build_then_evaluate_are_separate_and_report_keeps_graph_unchanged(self):
        with patch('hierarchy.services.component_hierarchy_report.write_reports', side_effect=AssertionError('build must not render')):
            call_command('build_hierarchy_graph', day='2026-06-21', stdout=io.StringIO())
        run = self.db.component_hierarchy_runs.find_one({'status': 'complete'})
        self.assertEqual(run['paths'], {})
        self.assertIn('evaluation_snapshot', run)
        edges = list(self.db.component_hierarchy_edges.find({}))
        original = self.db.component_hierarchy_graphs.find_one()
        output = io.StringIO()
        call_command('evaluate_hierarchy_graph', day='2026-06-21', stdout=output)
        self.assertIn('[HIER-EVAL] COMPLETE', output.getvalue())
        self.assertEqual(self.db.component_hierarchy_graphs.find_one(), original)
        self.assertEqual(list(self.db.component_hierarchy_edges.find({})), edges)
        report = self.db.component_hierarchy_evaluations.find_one({'status': 'complete'})
        paths = report['paths']
        self.assertTrue(Path(paths['meta_schematic']).exists())
        self.assertFalse(list(Path(paths['directory']).glob('*.html')))
        evaluation = json.loads(Path(paths['evaluation']).read_text())
        self.assertEqual(evaluation['hierarchy_run_id'], run['_id'])
        self.assertEqual(evaluation['temporal_level'], 'day')
        second, second_paths = evaluate_hierarchy('2026-06-21', run_id=run['_id'])
        self.assertNotEqual(second_paths['directory'], paths['directory'])
        self.assertEqual(self.db.component_hierarchy_runs.count_documents({}), 1)

    def test_legacy_snapshot_without_diagnostics_can_be_evaluated_without_upstream(self):
        run, _ = build_hierarchy('2026-06-21', render_reports=False)
        self.db.component_hierarchy_runs.update_one({'_id': run['run_id']}, {'$unset': {'evaluation_snapshot': ''}})
        self.db.graph_metadata.delete_many({})
        evaluation, paths = evaluate_hierarchy('2026-06-21')
        self.assertEqual(evaluation['diagnostics_origin'], 'recomputed_from_saved_descriptors')
        self.assertTrue(Path(paths['overview']).exists())

    def test_bad_partition_and_failed_render_never_modify_source_graph(self):
        run, _ = build_hierarchy('2026-06-21', render_reports=False)
        pointer = self.db.component_hierarchy_graphs.find_one()
        with patch('hierarchy.services.component_hierarchy_evaluation.write_reports', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                evaluate_hierarchy('2026-06-21')
        self.assertEqual(self.db.component_hierarchy_graphs.find_one(), pointer)
        self.assertEqual(self.db.component_hierarchy_runs.find_one()['status'], 'complete')
        self.assertEqual(self.db.component_hierarchy_evaluations.find_one()['status'], 'failed')
        self.db.meta_components.update_one({}, {'$set': {'node_indices': [9999]}})
        with self.assertRaisesRegex(ValueError, 'partition'):
            evaluate_hierarchy('2026-06-21')

    def test_old_commands_are_gone_and_options_are_validated(self):
        commands = get_commands()
        remaining = {name for name, app in commands.items() if app == 'hierarchy'}
        self.assertEqual(remaining, {'build_hierarchy_graph', 'evaluate_hierarchy_graph'})
        for kwargs in ({'day': 'bad'}, {'day': '2026-06-21', 'run_id': 'missing'}):
            with self.assertRaises(CommandError):
                call_command('evaluate_hierarchy_graph', **kwargs)
