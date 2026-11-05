from django.core.management.base import BaseCommand, CommandError

from spectral_learning.services.behavior_signal_inputs import build_behavior_signal_inputs


class Command(BaseCommand):
    help = 'Replay frozen neighborhood spectral model and export calibrated, source-verified signal inputs; no training, fusion or alerts.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--experiment-bundle', required=True)
        parser.add_argument('--resume-signal-bundle', help='Reuse a completed observations.jsonl after verifying pinned sources/model/calibration; no inference')
        parser.add_argument('--reference-bundle', help='Override reference path when moving bundles across machines')
        parser.add_argument('--seed', type=int, default=17, help='Preselected seed, never automatically selected from external outcomes')
        parser.add_argument('--alpha', type=float, default=.01)
        parser.add_argument('--write', action='store_true', help='Persist completed inputs to behavior_analysis_runs and behavior_observations')

    def handle(self, *args, **options):
        try:
            result = build_behavior_signal_inputs(options['experiment_bundle'], seed=options['seed'],
                alpha=options['alpha'], reference_bundle=options['reference_bundle'],resume_bundle=options['resume_signal_bundle'], write=options['write'],
                progress=self.stdout.write)
        except Exception as exc:
            raise CommandError(f'Behavior signal input export failed: {exc}') from exc
        self.stdout.write(self.style.SUCCESS('[SIGNAL INPUTS] COMPLETE — no training, fusion, alert decisions or ablation'))
        for name, value in result.items():
            self.stdout.write(f'{name}: {value}')
