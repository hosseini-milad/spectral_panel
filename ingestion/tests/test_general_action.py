import importlib
import io
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from bson import ObjectId
from django.core.management import call_command, CommandError
from django.test import override_settings
from mongoengine import connect, disconnect, get_db

from ingestion.management.commands.normalize_parquet_dataset import NUMERIC_FIELDS


class GeneralActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.settings = override_settings(BASE_DIR=Path(cls.directory.name))
        cls.settings.enable()
        disconnect()
        connect('test_general_action_' + uuid.uuid4().hex, host='localhost', port=27017,
                serverSelectionTimeoutMS=5000)
        cls.db = get_db()
        cls.db.client.admin.command('ping')
        # Legacy stage commands select siem_db explicitly; route them to this
        # disposable database while running the actual unmodified commands.
        cls.modules = [importlib.import_module('ingestion.management.commands.' + name)
                       for name in ('normalize_parquet_dataset', 'build_clustered_candidates',
                                    'build_day_representatives', 'visualize_representatives')]
        cls.patches = [patch.object(module, 'get_connection', return_value={'siem_db': cls.db})
                       for module in cls.modules]
        for item in cls.patches:
            item.start()

    @classmethod
    def tearDownClass(cls):
        for item in reversed(cls.patches):
            item.stop()
        cls.db.client.drop_database(cls.db.name)
        disconnect()
        connect('siem_db', host='localhost', port=27017)
        cls.settings.disable()
        cls.directory.cleanup()

    def setUp(self):
        for name in self.db.list_collection_names():
            self.db[name].delete_many({})
        self.source = 'clustered-day-2026-06-21-chunk-0'
        self.module = importlib.import_module('ingestion.management.commands.general-action')

    def seed(self):
        documents = []
        for i in range(100):
            values = {field: float((i * (j + 1)) % 89 + 1) for j, field in enumerate(NUMERIC_FIELDS)}
            documents.append({**values, '_id': ObjectId(), 'source_file': 'nfcapd.202606210000_normal.parquet',
                              'source_day': '2026-06-21', 'row_index': i, 'label': 0, 'protocol': 'tcp'})
        self.db.security_data.insert_many(documents)

    def execute(self, **options):
        output = io.StringIO()
        call_command('general-action', source_file=self.source, sample_per_day=100,
                     neighbors=2, degree_cap=3, ratio=.3, skip_eigen=False,
                     stdout=output, stderr=output, **options)
        return output.getvalue()

    def test_full_pipeline_and_resume_preserve_memberships_and_refresh_reports(self):
        self.seed()
        with patch.object(self.module, 'call_command', wraps=call_command) as dispatch:
            output = self.execute(threshold=.5)
        self.assertEqual(len(dispatch.call_args_list), 10)
        self.assertIn('ALL 10 STAGES COMPLETED', output)
        self.assertEqual(self.db.normalized_security_data.count_documents({}), 100)
        self.assertEqual(self.db.sampled_security_data.count_documents({}), 10)
        self.assertEqual(self.db.graph_representatives.count_documents({}), 3)
        self.assertGreater(len(self.db.graph_metadata.find_one()['edges']), 0)
        components = list(self.db.graph_components.find({}))
        self.assertEqual(sum(row['node_count'] for row in components), 10)
        self.assertTrue(all(row['node_feature_profile'] for row in components))
        self.assertTrue(all(row['categorical_profile']['protocol']['count'] == row['node_count'] for row in components))
        rep_ids = set(self.db.graph_representatives.distinct('_id'))
        with patch.object(self.module, 'call_command', wraps=call_command) as dispatch:
            resumed = self.execute()
        self.assertEqual(len(dispatch.call_args_list), 6)
        self.assertIn('SKIP Normalize', resumed)
        self.assertEqual(rep_ids, set(self.db.graph_representatives.distinct('_id')))
        self.assertEqual(self.db.graph_metadata.find_one()['graph_parameters']['similarity_threshold'], .5)
        root = Path(self.directory.name) / 'document'
        for category in ('component', 'report', 'nominal'):
            folder = root / category / 'layer1' / '2026-06-21' / 'chunk-0' / self.source
            self.assertTrue(any(folder.rglob('*.png')))
        self.assertTrue(any((root / 'component').rglob('*layer1_structure.json')))

    def test_full_pipeline_can_visualize_an_edgeless_graph(self):
        self.seed()
        output = self.execute()
        self.assertIn('ALL 10 STAGES COMPLETED', output)
        self.assertEqual(len(self.db.graph_metadata.find_one()['edges']), 0)
        self.assertTrue(any((Path(self.directory.name) / 'document' / 'nominal').rglob('*.png')))

    def test_invalid_date_and_missing_raw_stop_before_dispatch(self):
        with patch.object(self.module, 'call_command') as dispatch:
            with self.assertRaises(CommandError):
                call_command('general-action', source_file='clustered-day-2026-02-30-chunk-0')
            with self.assertRaises(CommandError):
                self.execute()
            dispatch.assert_not_called()

    def test_first_failed_stage_prevents_later_stages(self):
        self.seed()
        with patch.object(self.module, 'call_command', side_effect=CommandError('normalization unavailable')) as dispatch:
            with self.assertRaisesRegex(CommandError, '1/10 Normalize chunk failed'):
                self.execute()
            self.assertEqual(dispatch.call_count, 1)

    def test_partial_candidates_do_not_trigger_upstream_overwrite(self):
        self.seed()
        from ingestion.services.graph.candidate_graph import CANDIDATE_GENERATION
        self.db.sampled_security_data.insert_one({'source_day': '2026-06-21', 'chunk_index': 0,
                                                 'candidate_generation': CANDIDATE_GENERATION, 'isRandom': False})
        with patch.object(self.module, 'call_command') as dispatch:
            with self.assertRaisesRegex(CommandError, 'Partial/incompatible output'):
                self.execute()
            dispatch.assert_not_called()
