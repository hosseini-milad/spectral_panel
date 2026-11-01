from datetime import datetime
from django.core.management.base import BaseCommand, CommandError
from spectral_learning.services.upper_pipeline import run_upper


class Command(BaseCommand):
    help = 'Build actual L3+ Meta-component similarity graphs, analyze spectra, run eigenvector-aware MP and export statistical/schematic reports.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--day', required=True)
        parser.add_argument('--source-run-id', help='Complete L2 message-passing run; default active full-day run.')
        parser.add_argument('--levels', type=int, default=1, help='Actual layers starting at L3 (1..3).')
        parser.add_argument('--neighbors', type=int, default=8)
        parser.add_argument('--threshold', type=float, default=.85, help='RBF similarity, not original cosine threshold.')
        parser.add_argument('--bandwidth', type=float, default=1.)
        parser.add_argument('--epochs', type=int, default=60)
        parser.add_argument('--hidden-dim', type=int, default=32)
        parser.add_argument('--layers', type=int, default=2)
        parser.add_argument('--perturbation-repeats', type=int, default=3)
        parser.add_argument('--seed', type=int, default=17)
        parser.add_argument('--force', action='store_true')

    def handle(self, *args, **options):
        try:
            datetime.strptime(options['day'], '%Y-%m-%d')
            result = run_upper(options['day'], source_run_id=options['source_run_id'], levels=options['levels'],
                neighbors=options['neighbors'], threshold=options['threshold'], bandwidth=options['bandwidth'],
                epochs=options['epochs'], hidden=options['hidden_dim'], layers=options['layers'],
                repeats=options['perturbation_repeats'], seed=options['seed'], force=options['force'], progress=self.stdout.write)
        except Exception as exc:
            raise CommandError(f'Upper graph analysis failed: {exc}') from exc
        self.stdout.write(self.style.SUCCESS(f"[UPPER] COMPLETE: run={result['run_id']}; levels={len(result['levels'])}"))
        for name, path in result['phase'].items():
            self.stdout.write(f'[UPPER] {name}: {path}')
        self.stdout.write('New descriptor similarity edges; no automatic source spectral preservation or temporal detection claim.')
