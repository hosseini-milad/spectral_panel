"""Run: python -m unittest initial.test_artificial_day (requires mongomock)."""
from datetime import timedelta
from contextlib import contextmanager
import io
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import mongomock
from pymongo.errors import ExecutionTimeout, NetworkTimeout

from initial import artificialDay as module


class ArtificialDayTests(unittest.TestCase):
    def setUp(self):
        self.raw = mongomock.MongoClient().siem_db.security_data
        self.raw.create_index(module.SOURCE_INDEX)
        self.collection = Mock(wraps=self.raw)
        self.collection.bulk_write.side_effect = self.bulk_write
        self.db = SimpleNamespace(security_data=self.collection)
        self.size = patch.object(module, 'BLOCK_SIZE', 2)
        self.size.start()
        self.addCleanup(self.size.stop)
        for index in range(10):
            day = (module.START + timedelta(days=index)).isoformat()
            self.raw.insert_many([
                {'_id': index * 100 + rank, 'source_day': day,
                 'label': rank % 2, 'timestamp': '2026-06-21T12:34:56Z',
                 'nested': {'feature': rank}}
                for rank in reversed(range((index + 1) * 2))
            ])

    def bulk_write(self, operations, ordered):
        # mongomock 4.3's bulk adapter lacks current PyMongo's sort keyword.
        # Exercise its query/upsert engine through the equivalent update_one API.
        inserted = 0
        for operation in operations:
            inserted += self.raw.update_one(operation._filter, operation._doc,
                                            upsert=operation._upsert).upserted_id is not None
        return SimpleNamespace(upserted_count=inserted)

    def run_build(self, write=False):
        return module.build_artificial_day(self.db, dry_run=not write)

    def test_dry_run_and_default_production_plan(self):
        self.assertEqual(self.size.temp_original, 20_000)
        self.assertEqual(module.DAY_COUNT, 10)
        self.assertEqual(module.TARGET, '2026-06-20')
        before = list(self.raw.find())
        result = self.run_build()
        self.assertEqual(result['expected_total'], 20)
        self.assertEqual(result['inserted'], 0)
        self.assertEqual(list(self.raw.find()), before)
        self.collection.bulk_write.assert_not_called()
        self.assertEqual([row['skip'] for row in result['plan']], list(range(0, 20, 2)))
        self.assertEqual(result['plan'][-1]['source_day'], '2026-06-30')
        self.assertFalse(result['normal_baseline'])
        with patch.object(module, 'BLOCK_SIZE', 20_000):
            with self.assertRaisesRegex(ValueError, 'Insufficient raw'):
                self.run_build()
        self.collection.count_documents.assert_not_called()

    def test_write_preserves_raw_labels_timestamps_and_existing_destination(self):
        self.raw.insert_one({'_id': 'existing', 'source_day': module.TARGET, 'label': 9})
        originals = list(self.raw.find())
        result = self.run_build(write=True)
        self.assertEqual(result['inserted'], 20)
        copies = list(self.raw.find({'is_artificial_day': True}))
        self.assertEqual(len(copies), 20)
        self.assertEqual({record['label'] for record in copies}, {0, 1})
        for record in copies:
            metadata = record['artificial_day']
            original = self.raw.find_one({'_id': metadata['original_id']})
            self.assertEqual(record['timestamp'], original['timestamp'])
            self.assertEqual(record['nested'], original['nested'])
            self.assertEqual(record['label'], original['label'])
            index = (module.START.fromisoformat(metadata['original_source_day']) - module.START).days
            self.assertIn(metadata['source_rank'], (index * 2, index * 2 + 1))
            self.assertEqual(metadata['original_id'], index * 100 + metadata['source_rank'])
        for original in originals:
            self.assertEqual(self.raw.find_one({'_id': original['_id']}), original)
        before = list(self.raw.find())
        repeat = self.run_build(write=True)
        self.assertEqual(repeat['inserted'], 0)
        self.assertEqual(repeat['existing_selected'], 20)
        self.assertEqual(list(self.raw.find()), before)

    def test_shortage_in_last_day_never_writes(self):
        self.raw.delete_one({'_id': 919})
        with self.assertRaisesRegex(ValueError, 'Insufficient raw'):
            self.run_build(write=True)
        self.collection.bulk_write.assert_not_called()

    def test_excludes_synthetic_records_and_unselected_july(self):
        for rank, flags in enumerate(({'is_artificial_day': True},
                                      {'is_synthetic_normal': True}, {'artificial_day': {}})):
            self.raw.insert_one({'_id': -rank - 1, 'source_day': '2026-06-21', **flags})
        self.raw.insert_one({'_id': -9, 'source_day': '2026-07-01'})
        self.run_build(write=True)
        ids = {r['artificial_day']['original_id'] for r in
               self.raw.find({'source_day': module.TARGET})}
        self.assertTrue(all(value >= 0 for value in ids))

    def test_source_disappears_during_selection_never_writes(self):
        original_find = self.raw.find

        def changed(query):
            if query.get('source_day') == '2026-06-30':
                self.raw.delete_one({'_id': 919})
            return original_find(query)

        self.collection.find.side_effect = changed
        with self.assertRaisesRegex(ValueError, 'Insufficient raw data.*2026-06-30'):
            self.run_build(write=True)
        self.collection.bulk_write.assert_not_called()

    def test_conflicting_copy_is_not_overwritten(self):
        self.run_build(write=True)
        copy = self.raw.find_one({'source_day': module.TARGET})
        self.raw.update_one({'_id': copy['_id']}, {'$set': {'label': 999}})
        before = list(self.raw.find())
        self.collection.bulk_write.reset_mock()
        with self.assertRaisesRegex(ValueError, 'Conflicting existing copy'):
            self.run_build(write=True)
        self.collection.bulk_write.assert_not_called()
        self.assertEqual(list(self.raw.find()), before)

    def test_partial_failure_retains_copies_and_rerun_resumes(self):
        def interrupted(operations, ordered):
            self.bulk_write(operations[:3], ordered)
            raise RuntimeError('interrupted')

        self.collection.bulk_write.side_effect = interrupted
        with self.assertRaisesRegex(RuntimeError, 'interrupted'):
            self.run_build(write=True)
        self.assertEqual(self.raw.count_documents({'source_day': module.TARGET}), 3)
        self.collection.bulk_write.side_effect = self.bulk_write
        result = self.run_build(write=True)
        self.assertEqual(result['inserted'], 17)
        self.assertEqual(self.raw.count_documents({'source_day': module.TARGET}), 20)

    def test_integer_and_string_source_ids_remain_distinct(self):
        self.raw.update_one({'_id': 0}, {'$set': {'source_day': 'unused'}})
        self.raw.insert_one({'_id': '1', 'source_day': '2026-06-21', 'label': 1})
        result = self.run_build(write=True)
        self.assertEqual(result['inserted'], 20)
        origins = [r['artificial_day']['original_id'] for r in
                   self.raw.find({'source_day': module.TARGET})]
        self.assertIn(1, origins)
        self.assertIn('1', origins)

    def test_empty_day_fails_without_writes(self):
        self.raw.delete_many({'source_day': '2026-06-21'})
        with self.assertRaisesRegex(ValueError, 'Insufficient raw data.*2026-06-21'):
            self.run_build(write=True)
        self.collection.bulk_write.assert_not_called()

    def test_no_count_queries_are_needed(self):
        self.collection.count_documents.side_effect = ExecutionTimeout('count is forbidden')
        self.assertEqual(self.run_build(write=True)['inserted'], 20)
        self.collection.count_documents.assert_not_called()

    def test_cursor_network_timeout_identifies_day(self):
        self.collection.find.side_effect = NetworkTimeout('socket wait')
        with self.assertRaisesRegex(RuntimeError, 'Select 2026-06-21.*time limit exceeded'):
            self.run_build(write=True)
        self.collection.bulk_write.assert_not_called()

    def test_progress_reports_selection_and_completed_validation(self):
        progress = Mock()
        module.build_artificial_day(self.db, operation_timeout=7, progress=progress)
        self.collection.count_documents.assert_not_called()
        messages = [c.args[0] for c in progress.call_args_list]
        self.assertTrue(any('Validated 2026-06-21' in text for text in messages))
        self.assertTrue(any('Select 2026-06-30' in text for text in messages))

    def test_cli_failure_and_interrupt_return_nonzero_without_traceback(self):
        for error, code, text in ((ExecutionTimeout('slow'), 1, 'Ping MongoDB'),
                                  (KeyboardInterrupt(), 130, 'Interrupted'),
                                  (RuntimeError('unexpected'), 1, 'unexpected')):
            with self.subTest(error=type(error).__name__):
                output = io.StringIO()
                with patch.object(module, 'MongoClient') as client, patch('sys.stderr', output):
                    client.return_value.__enter__.return_value.admin.command.side_effect = error
                    self.assertEqual(module.main([]), code)
                self.assertIn(text, output.getvalue())
                self.assertNotIn('Traceback', output.getvalue())

    def test_cli_no_data_reports_failure_and_does_not_write(self):
        output = io.StringIO()
        with patch.object(module, 'MongoClient') as client, patch('sys.stderr', output):
            client.return_value.__enter__.return_value.__getitem__.return_value = self.db
            self.raw.delete_many({})
            self.assertEqual(module.main(['--write', '--timeout-seconds', '3']), 1)
            self.assertFalse(client.call_args.kwargs['retryReads'])
            self.assertEqual(client.call_args.kwargs['socketTimeoutMS'], 600000)
        self.assertIn('Insufficient raw data', output.getvalue())
        self.collection.bulk_write.assert_not_called()

    def test_write_creates_missing_source_index(self):
        self.raw.drop_indexes()
        self.assertEqual(self.run_build(write=True)['inserted'], 20)
        self.collection.create_index.assert_called_once()
        self.assertIn(module.SOURCE_INDEX, [list(i['key'].items()) for i in self.raw.list_indexes()])

    def test_dry_run_missing_index_fails_without_mutating_database(self):
        self.raw.drop_indexes()
        before = list(self.raw.find())
        with self.assertRaisesRegex(ValueError, 'Missing compound index.*prepare-index'):
            self.run_build()
        self.collection.create_index.assert_not_called()
        self.collection.bulk_write.assert_not_called()
        self.assertEqual(list(self.raw.find()), before)

    def test_existing_index_reused_without_counting(self):
        self.run_build()
        self.collection.create_index.assert_not_called()
        self.collection.count_documents.assert_not_called()

    def test_prepare_index_only_never_copies_records(self):
        self.raw.drop_indexes()
        with patch.object(module, 'MongoClient') as client, patch('sys.stderr', io.StringIO()), \
                patch('sys.stdout', io.StringIO()):
            client.return_value.__enter__.return_value.__getitem__.return_value = self.db
            self.assertEqual(module.main(['--prepare-index']), 0)
        self.collection.create_index.assert_called_once()
        self.collection.bulk_write.assert_not_called()

    def test_paged_selection_keeps_skip_order_and_opens_a_new_deadline_per_page(self):
        active = 0
        deadlines = []

        @contextmanager
        def request_timeout(seconds):
            nonlocal active
            active += 1
            deadlines.append(seconds)
            try:
                yield
            finally:
                active -= 1

        day = '2026-06-30'
        expected = list(self.raw.find(module.source_query(day)).sort('_id', 1).skip(3).limit(7))
        with patch.object(module, 'READ_BATCH_SIZE', 3), patch.object(module, 'timeout', request_timeout):
            selected = []
            for record in module._read(self.collection, module.source_query(day), 1, None,
                                       'test page', skip=3, limit=7, ordered=True):
                # File processing outside MongoDB must not consume a database deadline.
                self.assertEqual(active, 0)
                selected.append(record)
        self.assertEqual(selected, expected)
        self.assertEqual(deadlines, [1, 1, 1])
        calls = self.collection.find.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertNotIn('_id', calls[0].args[0])
        self.assertEqual(calls[1].args[0]['_id'], {'$gt': expected[2]['_id']})
        self.assertEqual(calls[2].args[0]['_id'], {'$gt': expected[5]['_id']})

    def test_timeout_on_a_later_page_still_prevents_any_writes(self):
        find = self.raw.find
        def fail_next_page(query):
            if query.get('source_day') == '2026-06-30' and '_id' in query:
                raise NetworkTimeout('later page stalled')
            return find(query)
        self.collection.find.side_effect = fail_next_page
        with patch.object(module, 'READ_BATCH_SIZE', 1):
            with self.assertRaisesRegex(RuntimeError, 'Select 2026-06-30.*time limit exceeded'):
                self.run_build(write=True)
        self.collection.bulk_write.assert_not_called()
        self.assertEqual(self.raw.count_documents({'source_day': module.TARGET}), 0)


if __name__ == '__main__':
    unittest.main()
