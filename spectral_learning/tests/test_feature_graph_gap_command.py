import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from spectral_learning.management.commands.evaluate_feature_graph_gap import Command


MODULE = 'spectral_learning.management.commands.evaluate_feature_graph_gap'


class FeatureGraphGapCommandTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        for name in ('manifest.json', 'run_status.json', 'feature_model.pt', 'graph_model.pt',
                     'spectral_model.pt', 'reference_arrays.npz'):
            (self.folder / name).write_text('fixture', encoding='utf-8')
        self.manifest = dict(normal_day='2026-06-20', alpha=.01, origin_id_field='provenance.raw_id')

    def execute(self, **kwargs):
        output = io.StringIO()
        call_command('evaluate_feature_graph_gap', **dict(day='2026-06-23',
                     reference_bundle=str(self.folder), stdout=output, **kwargs))
        return output.getvalue()

    def test_replay_is_required_and_policy_and_origin_are_fixed(self):
        with patch(MODULE + '.load_reference_bundle', return_value=(*[None]*5, self.manifest)), \
             patch(MODULE + '.call_command') as evaluate:
            self.execute()
        args, options = evaluate.call_args
        self.assertEqual(args, ('learn_normal_behavior',))
        self.assertEqual(options['reference_bundle'], str(self.folder.resolve()))
        self.assertEqual(options['score_policy'], 'feature_graph_gap')
        self.assertEqual(options['origin_id_field'], 'provenance.raw_id')
        self.assertEqual(options['evaluate_days'], ['2026-06-23'])
        self.assertNotIn('epochs', options)
        self.assertNotIn('alpha', options)

    def test_check_only_does_not_run_evaluation(self):
        with patch(MODULE + '.load_reference_bundle', return_value=(*[None]*5, self.manifest)), \
             patch(MODULE + '.call_command') as evaluate:
            output = self.execute(check_only=True)
        evaluate.assert_not_called()
        self.assertIn('readiness were NOT checked', output)

    def test_missing_files_stop_before_loading_or_evaluation(self):
        (self.folder / 'graph_model.pt').unlink()
        with patch(MODULE + '.load_reference_bundle') as load, patch(MODULE + '.call_command') as evaluate:
            with self.assertRaisesRegex(CommandError, 'missing: graph_model.pt'):
                self.execute()
        load.assert_not_called(); evaluate.assert_not_called()

    def test_bad_checksum_or_wrong_reference_day_stops_evaluation(self):
        with patch(MODULE + '.load_reference_bundle', side_effect=ValueError('checksum mismatch')), \
             patch(MODULE + '.call_command') as evaluate:
            with self.assertRaisesRegex(CommandError, 'checksum mismatch'):
                self.execute()
            evaluate.assert_not_called()
        with patch(MODULE + '.load_reference_bundle', return_value=(*[None]*5, dict(self.manifest, normal_day='2026-06-19'))), \
             patch(MODULE + '.call_command') as evaluate:
            with self.assertRaisesRegex(CommandError, 'normal_day differs'):
                self.execute()
            evaluate.assert_not_called()

    def test_invalid_or_same_day_stops_before_loading(self):
        with patch(MODULE + '.load_reference_bundle') as load:
            for day in ('2026-06-20', '2026-02-30', 'bad'):
                with self.subTest(day=day), self.assertRaises(CommandError):
                    call_command('evaluate_feature_graph_gap', day=day,
                                 reference_bundle=str(self.folder), stdout=io.StringIO())
            load.assert_not_called()

    def test_training_flags_are_not_exposed(self):
        parser = Command().create_parser('manage.py', 'evaluate_feature_graph_gap')
        with self.assertRaisesRegex(CommandError, 'unrecognized arguments: --epochs'):
            parser.parse_args(['--day', '2026-06-23', '--reference-bundle', str(self.folder), '--epochs', '1'])
