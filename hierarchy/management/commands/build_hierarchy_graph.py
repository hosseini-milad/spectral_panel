from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from hierarchy.services.component_hierarchy import build_hierarchy


class Command(BaseCommand):
    help = 'Build a component-based layer-2 graph, persist daily Meta-components. Use evaluate_hierarchy_graph for evaluation and schematics.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--day', required=True)
        parser.add_argument('--threshold', type=float, default=.85)
        parser.add_argument('--neighbors', type=int, default=8)
        parser.add_argument('--degree-cap', type=int, default=12)
        parser.add_argument('--require-complete-day', action='store_true', help='Reject missing day chunks; default builds available chunks and reports partial coverage.')
        parser.add_argument('--force', action='store_true', help='Create a new component-hierarchy version; retain all previous runs.')

    def handle(self, *args, **options):
        try:
            datetime.strptime(options['day'], '%Y-%m-%d')
        except ValueError as exc:
            raise CommandError('--day must be a valid YYYY-MM-DD date.') from exc
        if not 0 <= options['threshold'] <= 1 or options['neighbors'] < 1 or options['degree_cap'] < 2:
            raise CommandError('Require threshold in [0, 1], neighbors >= 1, and degree-cap >= 2.')
        try:
            evaluation, paths = build_hierarchy(options['day'], force=options['force'],
                                               threshold=options['threshold'], neighbors=options['neighbors'],
                                               degree_cap=options['degree_cap'], progress=self.stdout.write, render_reports=False, require_complete_day=options['require_complete_day'])
        except Exception as exc:
            raise CommandError(f'Component hierarchy failed: {exc}') from exc
        self.stdout.write(self.style.SUCCESS(
            f"[META] COMPLETE: chunks={evaluation['chunk_count']}; components={evaluation['component_count']}; "
            f"candidate_nodes={evaluation['candidate_node_count']}; edges={evaluation['edge_count']}; "
            f"meta_components={evaluation['meta_component_count']}"))
        for name, value in paths.items():
            self.stdout.write(f'[META] {name}: {value}')
        for warning in evaluation['warnings']:
            self.stdout.write(f'[META] WARNING: {warning}')
        self.stdout.write(f"[META] run_id: {evaluation['run_id']}")
        self.stdout.write(f"[META] Next: python -u manage.py evaluate_hierarchy_graph --day {options['day']} --run-id {evaluation['run_id']}")
        self.stdout.write('[META] Legacy representative-based hierarchy data was preserved.')
