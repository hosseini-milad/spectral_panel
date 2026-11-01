from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from spectral_learning.services.spectral_pipeline import run_spectral


class Command(BaseCommand):
    help = 'Phase 1: version-pinned sparse eigenvector analysis, invariant message-passing inputs and statistical/schematic reports.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--day', required=True)
        parser.add_argument('--scope', choices=['all', 'chunks', 'components'], default='all')
        parser.add_argument('--chunk-index', type=int)
        parser.add_argument('--hierarchy-run-id')
        parser.add_argument('--eigenvectors', type=int, default=8)
        parser.add_argument('--max-basis', type=int, default=32)
        parser.add_argument('--dense-limit', type=int, default=256)
        parser.add_argument('--higher-levels', type=int, default=2, help='Planning scenarios above Meta-components, not computed graph layers.')
        parser.add_argument('--planning-ratio', type=float, default=.5)
        parser.add_argument('--force', action='store_true', help='Create a new version; retain earlier spectra and reports.')

    def handle(self, *args, **options):
        try:
            datetime.strptime(options['day'], '%Y-%m-%d')
        except ValueError as exc:
            raise CommandError('--day must be a valid YYYY-MM-DD date.') from exc
        if not 1 <= options['eigenvectors'] <= options['max_basis'] <= 128:
            raise CommandError('Require 1 <= eigenvectors <= max-basis <= 128.')
        if not 2 <= options['dense_limit'] <= 2048:
            raise CommandError('Require dense-limit in [2, 2048].')
        if not 0 <= options['higher_levels'] <= 8 or not 0 < options['planning_ratio'] < 1:
            raise CommandError('Require higher-levels in [0, 8] and planning-ratio in (0, 1).')
        if options['chunk_index'] is not None and (options['scope'] != 'chunks' or options['chunk_index'] < 0):
            raise CommandError('--chunk-index requires --scope chunks and a nonnegative index.')
        try:
            result = run_spectral(options['day'], scope=options['scope'], chunk_index=options['chunk_index'],
                                  hierarchy_run_id=options['hierarchy_run_id'], requested=options['eigenvectors'],
                                  budget=options['max_basis'], dense_limit=options['dense_limit'],
                                  higher_levels=options['higher_levels'], planning_ratio=options['planning_ratio'],
                                  force=options['force'], progress=self.stdout.write)
        except Exception as exc:
            raise CommandError(f'Spectral phase 1 failed: {exc}') from exc
        self.stdout.write(self.style.SUCCESS(f"[SPECTRAL] PHASE 1 COMPLETE: run={result['run_id']}; graphs={len(result['graphs'])}"))
        for graph in result['graphs']:
            self.stdout.write(f"{graph['graph_key']}: nodes={graph['node_count']}; blocks={graph['component_count']}; "
                              f"encoded={graph['encoded_node_percent']:.2f}%; residual={graph['max_residual']:.3g}")
            self.stdout.write(f"Reports: {graph['artifacts']['directory']}")
        for key, path in result['phase'].items():
            self.stdout.write(f'[SPECTRAL] {key}: {path}')
        self.stdout.write('[SPECTRAL] No learned embeddings, Autoencoder, Ridge or anomaly scores were produced. Higher levels are explicitly marked planning-only.')
