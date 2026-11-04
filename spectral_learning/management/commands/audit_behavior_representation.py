from django.core.management.base import BaseCommand, CommandError

from spectral_learning.services.representation_audit import run_representation_audit


class Command(BaseCommand):
    help = 'Audit frozen behavior representations, feature-mask sensitivity, geometry and component pooling; no scoring or retraining.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--reference-bundle', required=True)
        parser.add_argument('--days', nargs='+', default=[], help='Additional days; the normal-reference day is always included')
        parser.add_argument('--mask-passes', type=int, default=5, help='2..20 disjoint covering feature-mask views; default 5 is approximately 20 percent masking per view')

    def handle(self, *args, **options):
        try:
            paths = run_representation_audit(options['reference_bundle'], options['days'],
                mask_passes=options['mask_passes'], progress=self.stdout.write)
        except Exception as exc:
            raise CommandError(f'Behavior representation audit failed: {exc}') from exc
        self.stdout.write(self.style.SUCCESS('[REPRESENTATION] COMPLETE — no model training or anomaly decisions'))
        for name, path in paths.items():
            self.stdout.write(f'{name}: {path}')
