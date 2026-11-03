"""A replay-only entry point with a fixed feature/graph disagreement policy."""
from datetime import date
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from spectral_learning.services.normal_behavior_reports import load_reference_bundle


class Command(BaseCommand):
    help = 'Evaluate one independent day with a saved normal-reference model and fixed feature_graph_gap policy; never train a new model.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--day', required=True, help='Independent evaluation day, YYYY-MM-DD')
        parser.add_argument('--normal-day', default='2026-06-20')
        parser.add_argument('--reference-bundle', required=True, help='Complete saved normal_behavior run directory')
        parser.add_argument('--check-only', action='store_true', help='Verify bundle files/checksums only; do not query source data or run evaluation')

    def handle(self, *args, **options):
        try:
            for value in (options['day'], options['normal_day']):
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError('Use YYYY-MM-DD dates')
            if options['day'] == options['normal_day']:
                raise ValueError('Evaluation day must differ from the normal reference day')
            if not options['reference_bundle'].strip():
                raise ValueError('Provide a nonempty reference-bundle directory')
            folder = Path(options['reference_bundle']).expanduser().resolve()
            required = ('manifest.json', 'run_status.json', 'feature_model.pt',
                        'graph_model.pt', 'spectral_model.pt', 'reference_arrays.npz')
            missing = [name for name in required if not (folder / name).is_file()]
            if missing:
                raise ValueError(f'Incomplete bundle at {folder}; missing: {", ".join(missing)}')
            _, _, _, _, _, manifest = load_reference_bundle(folder)
            if manifest['normal_day'] != options['normal_day']:
                raise ValueError('Bundle normal_day differs from --normal-day')
            origin_field = manifest['origin_id_field']
        except Exception as exc:
            raise CommandError(f'Feature/graph reference check failed: {exc}') from exc
        self.stdout.write(f"[FEATURE GRAPH GAP] Reference files verified: {folder}; normal_day={manifest['normal_day']}; alpha={manifest['alpha']}")
        self.stdout.write('[FEATURE GRAPH GAP] Policy fixed to feature_graph_gap; original model weights are reused; no model training.')
        if options['check_only']:
            self.stdout.write('[FEATURE GRAPH GAP] Bundle check complete. MongoDB source availability, source signatures and evaluation-day readiness were NOT checked.')
            return
        # The required, verified nonempty bundle prevents the training branch.
        # Reuse the original lineage field; never infer it from external labels.
        call_command('learn_normal_behavior', normal_day=options['normal_day'],
                     evaluate_days=[options['day']], reference_bundle=str(folder),
                     origin_id_field=origin_field, score_policy='feature_graph_gap',
                     stdout=self.stdout, stderr=self.stderr)
