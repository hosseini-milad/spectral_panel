from pathlib import Path
import uuid

from django.core.management.base import BaseCommand, CommandError
from ingestion.utils.document_paths import document_directory
from spectral_learning.services.behavior_scoring import load_score_dataset, source_sha256, POLICIES
from spectral_learning.services.behavior_score_reports import write_score_analysis
from spectral_learning.services.spectral_reports import dump_json


class Command(BaseCommand):
    help = 'Analyze saved node_scores.csv or ZIP, compare calibrated score policies and export alert/missed cases without retraining or MongoDB queries.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--scores', required=True)
        parser.add_argument('--normal-day', default='2026-06-20')
        parser.add_argument('--alphas', type=float, nargs='+', default=[.01, .05, .1])
        parser.add_argument('--score-policy', choices=POLICIES, default='joint_spectral_gap')
        parser.add_argument('--output-dir')

    def handle(self, *args, **options):
        folder = None
        created = False
        try:
            self.stdout.write('[SCORE AUDIT] Reading and aligning feature/graph/spectral candidate rows...')
            source_digest = source_sha256(options['scores'])
            dataset = load_score_dataset(options['scores'])
            folder = (Path(options['output_dir']) if options['output_dir'] else
                      document_directory('autoencoder', layer=1, day=options['normal_day']) / 'score_analysis' / 'runs' / uuid.uuid4().hex)
            folder.mkdir(parents=True, exist_ok=False)
            created = True
            dump_json(folder / 'run_status.json', dict(status='building'))
            self.stdout.write(f'[SCORE AUDIT] candidates={len(dataset.metadata):,}; output={folder}')
            paths, state = write_score_analysis(folder, dataset, options['normal_day'],
                alphas=tuple(options['alphas']), selected_policy=options['score_policy'],
                source=dict(path=str(options['scores']), sha256=source_digest))
            if source_sha256(options['scores']) != source_digest:
                raise ValueError('Input score file changed during analysis')
            dump_json(folder / 'run_status.json', dict(status='complete'))
        except Exception as exc:
            if created:
                dump_json(folder / 'run_status.json', dict(status='failed', error=str(exc)))
            raise CommandError(f'Behavior score analysis failed: {exc}') from exc
        self.stdout.write(self.style.SUCCESS('[SCORE AUDIT] COMPLETE'))
        for name, path in paths.items():
            self.stdout.write(f'{name}: {path}')
        for row in state.get('metrics', []):
            if row['split'] == 'external_test' and row['score_policy'] == options['score_policy'] and row['alpha'] == options['alphas'][0]:
                self.stdout.write(f"[SCORE AUDIT] {row['day']}: label1_recall={row['recall_label1']}; label0_false_alerts={row['false_alert_fraction_label0']}; label1_precision={row['precision_label1']}")
