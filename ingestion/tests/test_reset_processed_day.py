import tempfile
import unittest
from pathlib import Path
import mongomock
from ingestion.management.commands.reset_processed_day import reset_processed_day


class ProcessedDayResetTests(unittest.TestCase):
    def setUp(self):
        self.db=mongomock.MongoClient().siem_db
        for day in ['2026-06-16','2026-06-17']:
            self.db.security_data.insert_one(dict(_id='raw-'+day,source_day=day))
            for name in ['normalized_security_data','sampled_security_data','graph_metadata','graph_components']:
                self.db[name].insert_one(dict(source_day=day,source_file=f'clustered-day-{day}-chunk-0'))
            self.db.graph_representatives.insert_one(dict(source_file=f'clustered-day-{day}-chunk-0'))
            self.db.component_hierarchy_runs.insert_one(dict(_id='h-'+day,source_day=day))
            self.db.meta_components.insert_one(dict(run_id='h-'+day))
        self.db.behavior_analysis_runs.insert_one(dict(_id='cross',status='complete',identity=dict(source_signatures={'2026-06-17':{},'2026-06-16':{}})))
        for day in ['2026-06-16','2026-06-17']:
            self.db.behavior_observations.insert_one(dict(run_id='cross',entity=dict(source_day=day)))

    def test_force_deletes_target_derived_records_and_files_without_backup(self):
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/'document/autoencoder/layer1/2026-06-17';target.mkdir(parents=True);(target/'model.pt').write_bytes(b'old')
            other=target.parent/'2026-06-16';other.mkdir();(other/'keep.txt').write_text('keep')
            result=reset_processed_day(self.db,'2026-06-17',root,apply=True)
            self.assertFalse(target.exists());self.assertTrue(other.exists())
            self.assertFalse(result['backup_created'])
            self.assertFalse(list(Path(root).glob('document/report/database-maintenance/**/*.jsonl')))
        self.assertEqual(self.db.security_data.count_documents({}),2)
        self.assertEqual(self.db.sampled_security_data.count_documents({}),1)
        self.assertEqual(self.db.graph_representatives.count_documents({}),1)
        self.assertEqual(self.db.meta_components.count_documents({}),1)
        self.assertEqual(self.db.behavior_observations.count_documents({}),1)
        self.assertEqual(self.db.behavior_analysis_runs.find_one()['status'],'invalidated')

    def test_preview_does_not_change_database(self):
        with tempfile.TemporaryDirectory() as root:
            result=reset_processed_day(self.db,'2026-06-17',root)
        self.assertTrue(all(row['deleted']==0 for row in result['collections']))
        self.assertEqual(self.db.graph_metadata.count_documents({}),2)
        self.assertEqual(self.db.behavior_analysis_runs.find_one()['status'],'complete')

    def test_repeated_reset_is_safe_and_raw_is_required(self):
        with tempfile.TemporaryDirectory() as root:
            reset_processed_day(self.db,'2026-06-17',root,apply=True)
            result=reset_processed_day(self.db,'2026-06-17',root,apply=True)
            self.assertTrue(all(row['deleted']==0 for row in result['collections']))
            with self.assertRaisesRegex(ValueError,'No raw'):
                reset_processed_day(self.db,'2026-06-19',root,apply=True)
