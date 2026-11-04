import importlib
import io
import unittest
from unittest.mock import patch

from django.core.management import call_command, CommandError


class HyperGeneralActionTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module('ingestion.management.commands.hyper-general-action')
        self.database = patch.object(self.module, 'get_db')
        self.db = self.database.start().return_value
        self.addCleanup(self.database.stop)
        self.db.security_data.count_documents.return_value = 45001
        self.dispatch = patch.object(self.module, 'call_command')
        self.run_chunk = self.dispatch.start()
        self.addCleanup(self.dispatch.stop)

    def execute(self, **kwargs):
        output = io.StringIO()
        call_command('hyper-general-action', source_file='clustered-day-2026-06-21',
                     stdout=output, stderr=output, **kwargs)
        return output.getvalue()

    def test_automatic_indices_and_default_options(self):
        output = self.execute()
        calls = self.run_chunk.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertEqual([call.kwargs['source_file'] for call in calls],
                         [f'clustered-day-2026-06-21-chunk-{index}' for index in range(3)])
        for call in calls:
            self.assertEqual(call.args, ('general-action',))
            self.assertEqual(call.kwargs['sample_per_day'], 20000)
            self.assertEqual(call.kwargs['ratio'], .10)
        self.assertIn('raw_chunk=5,001', output)

    def test_optional_range_and_parameters_are_forwarded(self):
        self.execute(start_chunk=1, max_chunks=1, threshold=.95, ratio=.2, neighbors=8,
                     degree_cap=15, batch_size=500, skip_eigen=True)
        self.run_chunk.assert_called_once()
        kwargs = self.run_chunk.call_args.kwargs
        self.assertEqual(kwargs['source_file'], 'clustered-day-2026-06-21-chunk-1')
        for key, value in {'threshold': .95, 'ratio': .2, 'neighbors': 8, 'degree_cap': 15,
                           'batch_size': 500, 'skip_eigen': True}.items():
            self.assertEqual(kwargs[key], value)

    def test_cli_limit_only_dispatches_first_ten_chunks_and_supports_resume(self):
        self.db.security_data.count_documents.return_value = 1000000
        output = io.StringIO()
        call_command('hyper-general-action', '--source-file', 'clustered-day-2026-06-21',
                     '--limit', '10', stdout=output)
        self.assertEqual([c.kwargs['source_file'] for c in self.run_chunk.call_args_list],
                         [f'clustered-day-2026-06-21-chunk-{i}' for i in range(10)])
        self.run_chunk.reset_mock()
        self.execute(start_chunk=5, limit=2)
        self.assertEqual([c.kwargs['source_file'] for c in self.run_chunk.call_args_list],
                         ['clustered-day-2026-06-21-chunk-5', 'clustered-day-2026-06-21-chunk-6'])

    def test_failure_stops_later_chunks_and_keeps_cause(self):
        self.run_chunk.side_effect = [None, CommandError('component audit failed')]
        with self.assertRaisesRegex(CommandError, r'stopped at chunk 1.*component audit failed'):
            self.execute()
        self.assertEqual(self.run_chunk.call_count, 2)

    def test_exact_multiple_does_not_add_empty_chunk(self):
        self.db.security_data.count_documents.return_value = 40000
        self.execute()
        self.assertEqual(self.run_chunk.call_count, 2)

    def test_invalid_or_empty_requests_never_dispatch(self):
        for options in ({'start_chunk': -1}, {'limit': 0}, {'limit': -1}, {'limit': 2, 'max_chunks': 3}, {'max_chunks': 0}, {'sample_per_day': 0},
                        {'ratio': 1}, {'threshold': 2}, {'start_chunk': 10}):
            with self.subTest(options=options), self.assertRaises(CommandError):
                self.execute(**options)
        for source in ('clustered-day-2026-02-30', 'clustered-day-2026-06-21-chunk-0'):
            with self.assertRaises(CommandError):
                call_command('hyper-general-action', source_file=source)
        self.db.security_data.count_documents.return_value = 0
        with self.assertRaises(CommandError):
            self.execute()
        self.run_chunk.assert_not_called()
