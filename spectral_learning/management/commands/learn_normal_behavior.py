from django.core.management.base import BaseCommand, CommandError

from spectral_learning.services.normal_behavior import run_normal_behavior_cpu


class Command(BaseCommand):
    help = 'Learn normal-reference behavior, calibrate on separate chunks, and evaluate a frozen model across days. Export document reports and schematics.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--normal-day', default='2026-06-20')
        parser.add_argument('--evaluate-days', nargs='+', required=True)
        parser.add_argument('--epochs', type=int, default=60)
        parser.add_argument('--hidden-dim', type=int, default=64)
        parser.add_argument('--latent-dim', type=int, default=16)
        parser.add_argument('--layers', type=int, default=2)
        parser.add_argument('--max-pairs', type=int, default=2048)
        parser.add_argument('--alpha', type=float, default=.01, help='Nominal upper-tail alert fraction on normal calibration nodes (not a guaranteed operational FPR)')
        parser.add_argument('--seed', type=int, default=17)
        parser.add_argument('--origin-id-field', default='artificial_day.original_id', help='Dotted field holding original raw ID in copied records')
        parser.add_argument('--reference-bundle', help='Completed normal-behavior report directory: reuse saved weights, scaler and thresholds; do not train again')

    def handle(self, *args, **options):
        try:
            result = run_normal_behavior_cpu(options['normal_day'], options['evaluate_days'],
                epochs=options['epochs'], hidden=options['hidden_dim'], latent=options['latent_dim'],
                layers=options['layers'], max_pairs=options['max_pairs'], alpha=options['alpha'],
                seed=options['seed'], origin_field=options['origin_id_field'],
                reference_bundle=options['reference_bundle'], progress=self.stdout.write)
        except Exception as exc:
            raise CommandError(f'Normal-behavior workflow failed: {exc}') from exc
        self.stdout.write(self.style.SUCCESS(f'[NORMAL BEHAVIOR] COMPLETE: {result["run_id"]}'))
        for name, path in result['paths'].items():
            self.stdout.write(f'[NORMAL BEHAVIOR] {name}: {path}')
        self.stdout.write('Review lineage_audit.csv, held-out normal false alerts, reference labels and coverage before using alerts. Deviations are not attack probabilities.')
