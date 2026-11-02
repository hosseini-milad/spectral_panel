import importlib
import io
import json
import unittest
from pathlib import Path
from django.core.management import call_command, get_commands
from ingestion.management.commands.cleanup_legacy_collections import RETIRED


class CollectionCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = importlib.import_module('ingestion.tests.test_components').ComponentIntegrationTests
        cls.fixture.setUpClass(); cls.db = cls.fixture.db

    @classmethod
    def tearDownClass(cls):
        cls.fixture.tearDownClass()

    def setUp(self):
        self.fixture().setUp()
        for name in RETIRED:
            if name not in self.db.list_collection_names():
                self.db.create_collection(name)
        self.db.graph_representatives.insert_one({'required': 'active general-action'})
        self.db.spectral_pooled_features.insert_one({'required': 'meta embeddings'})

    def test_preview_never_drops_and_apply_only_removes_empty_allowlist(self):
        self.db.hyper_representatives.insert_one({'historical': True})
        call_command('cleanup_legacy_collections', stdout=io.StringIO())
        self.assertTrue(set(RETIRED) <= set(self.db.list_collection_names()))
        output = io.StringIO(); call_command('cleanup_legacy_collections', apply=True, stdout=output)
        self.assertNotIn('hyper_graph_edges', self.db.list_collection_names())
        self.assertNotIn('hyper_graph_metadata', self.db.list_collection_names())
        self.assertEqual(self.db.hyper_representatives.count_documents({}), 1)
        self.assertEqual(self.db.graph_representatives.count_documents({}), 1)
        self.assertEqual(self.db.spectral_pooled_features.count_documents({}), 1)
        self.assertIn('keep_nonempty', output.getvalue())
        report = Path(output.getvalue().split('Report: ')[1].splitlines()[0])
        manifest = json.loads(report.read_text())
        self.assertEqual(manifest['status'], 'complete')
        self.assertEqual(manifest['database'], self.db.name)
        self.assertIn('graph_representatives', manifest['retained_other_collections'])

    def test_empty_cleanup_is_repeatable_and_legacy_action_is_gone(self):
        call_command('cleanup_legacy_collections', apply=True, stdout=io.StringIO())
        self.assertFalse(set(RETIRED) & set(self.db.list_collection_names()))
        call_command('cleanup_legacy_collections', apply=True, stdout=io.StringIO())
        self.assertFalse(set(RETIRED) & set(self.db.list_collection_names()))
        self.assertNotIn('evaluate_component_allocation', get_commands())
