import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np
from django.core.management import call_command, CommandError

from spectral_learning.services.behavior_scoring import (
    ScoreDataset, VARIANTS, load_score_dataset, fit_score_channels, evaluate_score_channels,
)


class BehaviorScoringTests(unittest.TestCase):
    def dataset(self):
        metadata, residuals = [], []
        for day, split, n in [('2026-06-20', 'train', 200), ('2026-06-20', 'calibration', 200),
                               ('2026-06-20', 'test', 100), ('2026-06-21', 'external_test', 100)]:
            for i in range(n):
                label = int(day != '2026-06-20' and i >= 50)
                identity = f'{day}-{split}-{i}'
                metadata.append(dict(day=day, split=split, graph_key=f'{day}-{split}',
                                     node_id=identity, raw_record_id='raw-' + identity, raw_label=str(label)))
                residuals.append([1., .01, .01] if label else [.1, .1, .1])
        return ScoreDataset(metadata, np.asarray(residuals), np.ones(len(metadata), dtype=bool))

    def test_disagreement_detects_a_pattern_missed_by_reconstruction(self):
        _, rows, _ = evaluate_score_channels(self.dataset(), '2026-06-20', (.01,))
        baseline = next(r for r in rows if r['split'] == 'external_test' and r['score_policy'] == 'spectral_reconstruction')
        gap = next(r for r in rows if r['split'] == 'external_test' and r['score_policy'] == 'feature_spectral_gap')
        self.assertEqual(baseline['recall_label1'], 0)
        self.assertEqual(gap['recall_label1'], 1)
        self.assertEqual(gap['false_alert_fraction_label0'], 0)
        self.assertEqual(gap['precision_label1'], 1)
        self.assertEqual(gap['node_score_roc_auc'], 1)
        joint = next(r for r in rows if r['split'] == 'external_test' and r['score_policy'] == 'joint_spectral_gap')
        self.assertEqual(joint['recall_label1'], 1)
        self.assertEqual(joint['false_alert_fraction_label0'], 0)

    def test_external_scores_and_labels_do_not_fit_floors_or_thresholds(self):
        dataset = self.dataset()
        _, _, state = evaluate_score_channels(dataset, '2026-06-20', (.01,))
        for i, row in enumerate(dataset.metadata):
            if row['day'] != '2026-06-20':
                dataset.residuals[i] *= 100000
                row['raw_label'] = '0'
        _, _, changed = evaluate_score_channels(dataset, '2026-06-20', (.01,))
        self.assertEqual(state, changed)

    def test_calibration_changes_thresholds_without_changing_training_scales(self):
        dataset = self.dataset()
        _, _, state = evaluate_score_channels(dataset, '2026-06-20', (.01,))
        for i, row in enumerate(dataset.metadata):
            if row['split'] == 'calibration':
                dataset.residuals[i, 0] = 100
        _, _, changed = evaluate_score_channels(dataset, '2026-06-20', (.01,))
        self.assertEqual(state['floors'], changed['floors'])
        self.assertNotEqual(state['thresholds']['feature_spectral_gap'], changed['thresholds']['feature_spectral_gap'])

    def write_csv(self, path, dataset):
        with path.open('w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.DictWriter(stream, fieldnames=[*dataset.metadata[0], 'model', 'score', 'valid'])
            writer.writeheader()
            for i, row in enumerate(dataset.metadata):
                for column in reversed(range(3)):
                    writer.writerow(dict(row, model=VARIANTS[column], score=dataset.residuals[i, column], valid='True'))

    def test_zip_input_aligns_by_identity_not_row_order_and_exports_real_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); dataset = self.dataset(); csv_path = root / 'node_scores.csv'
            self.write_csv(csv_path, dataset)
            archive = root / 'scores.zip'
            with zipfile.ZipFile(archive, 'w') as zipped:
                zipped.write(csv_path, arcname='nested/node_scores.csv')
            loaded = load_score_dataset(archive)
            np.testing.assert_array_equal(dataset.residuals, loaded.residuals)
            out = root / 'analysis'
            call_command('analyze_behavior_scores', scores=str(archive), normal_day='2026-06-20',
                         alphas=[.01], score_policy='feature_spectral_gap', output_dir=str(out), stdout=io.StringIO())
            for filename in ['score_analysis.json', 'score_policy_metrics.csv', 'selected_node_scores.csv',
                             'alert_case_samples.csv', 'score_channels.npz', '2026-06-21_score_audit.png',
                             'selected_policy_overview.svg']:
                self.assertGreater((out / filename).stat().st_size, 0)
            self.assertEqual(json.loads((out / 'run_status.json').read_text())['status'], 'complete')
            metrics = list(csv.DictReader((out / 'score_policy_metrics.csv').open(encoding='utf-8-sig')))
            gap = next(r for r in metrics if r['split'] == 'external_test' and r['score_policy'] == 'feature_spectral_gap')
            self.assertEqual(float(gap['recall_label1']), 1)
            # Existing analysis output must never be overwritten, even on error.
            before = (out / 'run_status.json').read_bytes()
            with self.assertRaises(CommandError):
                call_command('analyze_behavior_scores', scores=str(archive), output_dir=str(out), stdout=io.StringIO())
            self.assertEqual((out / 'run_status.json').read_bytes(), before)

    def test_missing_model_inconsistent_metadata_and_nonfinite_scores_fail(self):
        dataset = self.dataset()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'scores.csv'; self.write_csv(path, dataset)
            original = path.read_text(encoding='utf-8-sig').splitlines()
            for lines in [original[:-1], [*original, original[-1]],
                          [original[0], original[1].replace(',0.1,', ',nan,'), *original[2:]]]:
                path.write_text('\n'.join(lines) + '\n', encoding='utf-8-sig')
                with self.assertRaises(ValueError):
                    load_score_dataset(path)

    def test_reference_overlap_is_rejected(self):
        dataset = self.dataset()
        dataset.metadata[-1]['raw_record_id'] = dataset.metadata[0]['raw_record_id']
        with self.assertRaisesRegex(ValueError, 'overlap'):
            fit_score_channels(dataset, '2026-06-20')

    def test_undefined_label_metrics_are_not_reported_as_zero(self):
        dataset = self.dataset()
        for row in dataset.metadata:
            if row['day'] != '2026-06-20':
                row['raw_label'] = ''
        _, rows, _ = evaluate_score_channels(dataset, '2026-06-20', (.01,))
        self.assertTrue(all(r['recall_label1'] is None and r['false_alert_fraction_label0'] is None
                            for r in rows if r['split'] == 'external_test'))
