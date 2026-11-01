from datetime import datetime
from django.core.management.base import BaseCommand, CommandError
from spectral_learning.services.message_passing_pipeline import run_message_passing


class Command(BaseCommand):
    help = 'Phase 2: train eigenvector-aware masked-feature probes, evaluate ablations/interventions, export embeddings and schematics.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--day', required=True)
        parser.add_argument('--spectral-run-id', help='Complete pinned phase-1 run; default: active full-day run.')
        parser.add_argument('--epochs', type=int, default=30)
        parser.add_argument('--hidden-dim', type=int, default=32)
        parser.add_argument('--layers', type=int, default=2)
        parser.add_argument('--perturbation-repeats', type=int, default=3)
        parser.add_argument('--seed', type=int, default=17)
        parser.add_argument('--force', action='store_true')

    def handle(self, *args, **options):
        try:
            datetime.strptime(options['day'], '%Y-%m-%d')
            result = run_message_passing(options['day'], phase1_run_id=options['spectral_run_id'],
                epochs=options['epochs'], hidden=options['hidden_dim'], layers=options['layers'],
                repeats=options['perturbation_repeats'], seed=options['seed'], force=options['force'], progress=self.stdout.write)
        except Exception as exc:
            raise CommandError(f'Message-passing phase failed: {exc}') from exc
        self.stdout.write(self.style.SUCCESS(f"[MESSAGE PASSING] PHASE 2 COMPLETE: run={result['run_id']}; graphs={len(result['graphs'])}"))
        for name, path in result['phase'].items():
            self.stdout.write(f'[MESSAGE PASSING] {name}: {path}')
        self.stdout.write('Embeddings learned via transductive feature probes. No temporal detection, full graph Autoencoder or anomaly scores. Review input_audit.csv.')
