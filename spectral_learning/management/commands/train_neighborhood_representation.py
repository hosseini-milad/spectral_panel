from django.core.management.base import BaseCommand, CommandError

from spectral_learning.services.neighborhood_experiment import run_neighborhood_experiment


class Command(BaseCommand):
    help = 'Compare preserved graph/spectral encoders with auxiliary degree and neighbor-moment reconstruction; no alerts or automatic promotion.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--reference-bundle', required=True)
        parser.add_argument('--days', nargs='+', default=[])
        parser.add_argument('--seeds', nargs='+', type=int, default=[17, 29, 43])
        parser.add_argument('--epochs', type=int, default=None, help='Same budget for both arms; defaults to reference epochs')
        parser.add_argument('--neighborhood-weight', type=float, default=.1)

    def handle(self, *args, **options):
        try:
            paths = run_neighborhood_experiment(options['reference_bundle'], options['days'],
                seeds=options['seeds'], epochs=options['epochs'], auxiliary_weight=options['neighborhood_weight'],
                progress=self.stdout.write)
        except Exception as exc:
            raise CommandError(f'Neighborhood representation experiment failed: {exc}') from exc
        self.stdout.write(self.style.SUCCESS('[NEIGHBORHOOD] COMPLETE — experimental models; no alerts or automatic promotion'))
        for name, path in paths.items():
            self.stdout.write(f'{name}: {path}')
