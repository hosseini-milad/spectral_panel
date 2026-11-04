"""Whole-day held-out normal references with an existing frozen encoder."""
from django.core.management.base import BaseCommand, CommandError
from spectral_learning.services.behavior_signal_inputs import build_behavior_signal_inputs
from spectral_learning.services.hierarchy_behavior import run_hierarchy_behavior, load_hierarchy
from mongoengine import get_db
import json
from pathlib import Path


class Command(BaseCommand):
    help = 'Replay unseen normal days with fixed whole-day group-fit/calibration/test roles, then build hierarchical references; no encoder training.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--experiment-bundle', required=True)
        parser.add_argument('--reference-bundle')
        parser.add_argument('--fit-days', nargs='+', required=True)
        parser.add_argument('--calibration-days', nargs='+', required=True)
        parser.add_argument('--test-days', nargs='+', required=True)
        parser.add_argument('--seed', type=int, default=17)
        parser.add_argument('--alpha', type=float, default=.01)
        parser.add_argument('--write', action='store_true')

    def handle(self, *args, **options):
        try:
            roles={}
            for field,role in [('fit_days','normal_group_train'),('calibration_days','normal_group_calibration'),('test_days','normal_group_test')]:
                for day in options[field]:
                    if day in roles:
                        raise ValueError('Each normal day must have exactly one role')
                    roles[day]=role
            # Preflight hierarchy availability before expensive spectral replay.
            from datetime import date
            for day in roles:
                if date.fromisoformat(day).isoformat()!=day:
                    raise ValueError('Use YYYY-MM-DD dates')
            experiment=json.loads((Path(options['experiment_bundle'])/'manifest.json').read_text())
            db=get_db()
            for day in sorted(set(roles) | {experiment['normal_day']} | set(experiment['days'])):
                load_hierarchy(db,day)
            self.stdout.write(f'[NORMAL GROUP REFERENCE] Fixed day roles: {roles}; encoder remains frozen')
            node=build_behavior_signal_inputs(options['experiment_bundle'],seed=options['seed'],alpha=options['alpha'],
                reference_bundle=options['reference_bundle'],write=options['write'],progress=self.stdout.write,normal_day_roles=roles)
            self.stdout.write(f"[NORMAL GROUP REFERENCE] Completed node inputs: {node['directory']}")
            group=run_hierarchy_behavior(node['directory'],alpha=options['alpha'],write=options['write'],progress=self.stdout.write)
        except Exception as exc:
            raise CommandError(f'Normal group reference preparation failed: {exc}') from exc
        self.stdout.write(self.style.SUCCESS('[NORMAL GROUP REFERENCE] COMPLETE — fixed model, no ablation or final alerts'))
        for prefix,result in [('node',node),('group',group)]:
            for name,value in result.items():
                self.stdout.write(f'{prefix}_{name}: {value}')
