from django.core.management.base import BaseCommand, CommandError
from spectral_learning.services.hierarchy_behavior import run_hierarchy_behavior, find_signal_bundle


class Command(BaseCommand):
    help = 'Compare exact-membership components/Meta-components with normal train/calibration groups; export versioned evidence and diagrams.'
    requires_system_checks = []

    def add_arguments(self, parser):
        source=parser.add_mutually_exclusive_group(required=True)
        source.add_argument('--signal-bundle', help='Completed signal_inputs/runs/<export-id> directory')
        source.add_argument('--signal-run-id', help='Find an exact completed run ID in the standard document directory')
        parser.add_argument('--normal-day', default='2026-06-20', help='Used only for local --signal-run-id lookup')
        parser.add_argument('--alpha', type=float, default=.01)
        parser.add_argument('--min-train-groups', type=int, default=5)
        parser.add_argument('--write', action='store_true', help='Write derived hierarchy evidence; existing graph collections are never modified')

    def handle(self, *args, **options):
        try:
            bundle=options['signal_bundle'] or find_signal_bundle(options['signal_run_id'],options['normal_day'])
            self.stdout.write(f'[HIERARCHY BEHAVIOR] Signal bundle: {bundle}')
            result=run_hierarchy_behavior(bundle,alpha=options['alpha'],
                min_train=options['min_train_groups'],write=options['write'],progress=self.stdout.write)
        except Exception as exc:
            raise CommandError(f'Hierarchical behavior analysis failed: {exc}') from exc
        self.stdout.write(self.style.SUCCESS('[HIERARCHY BEHAVIOR] COMPLETE — no training, final alerts or new ablation'))
        for name,value in result.items():
            self.stdout.write(f'{name}: {value}')
