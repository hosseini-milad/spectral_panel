from datetime import datetime
from django.core.management.base import BaseCommand, CommandError
from spectral_learning.services.autoencoder_pipeline import run_autoencoder


class Command(BaseCommand):
    help = 'Train shared layer-1 masked feature/graph/spectral Autoencoders and export checkpoints, arrays, statistics and schematics.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--day', required=True)
        parser.add_argument('--epochs', type=int, default=60)
        parser.add_argument('--hidden-dim', type=int, default=64)
        parser.add_argument('--latent-dim', type=int, default=16)
        parser.add_argument('--layers', type=int, default=2)
        parser.add_argument('--max-pairs', type=int, default=2048)
        parser.add_argument('--structure-weight', type=float, default=.1)
        parser.add_argument('--weight-loss-weight', type=float, default=.05)
        parser.add_argument('--seed', type=int, default=17)
        parser.add_argument('--force', action='store_true')

    def handle(self, *args, **options):
        try:
            datetime.strptime(options['day'], '%Y-%m-%d')
            result = run_autoencoder(options['day'], epochs=options['epochs'], hidden=options['hidden_dim'],
                latent=options['latent_dim'], layers=options['layers'], max_pairs=options['max_pairs'],
                structure_weight=options['structure_weight'], weight_weight=options['weight_loss_weight'],
                seed=options['seed'], force=options['force'], progress=self.stdout.write)
        except Exception as exc:
            raise CommandError(f'Layer-1 Autoencoder failed: {exc}') from exc
        self.stdout.write(self.style.SUCCESS(f'[AUTOENCODER] COMPLETE: run={result["run_id"]}'))
        for row in result['metrics']:
            if row['split'] == 'test':
                self.stdout.write(f'[AUTOENCODER] TEST {row["model"]}: feature_mse={row["feature_mse"]:.6g}; mean_baseline={row["mean_baseline_mse"]:.6g}; relation_auc={row["relation_roc_auc"]}')
        for name, path in result['paths'].items():
            self.stdout.write(f'[AUTOENCODER] {name}: {path}')
        self.stdout.write('Held-out processing-chunk reconstruction experiment; residuals are not calibrated attack scores. Review input_audit.csv and constant-feature audit.')
