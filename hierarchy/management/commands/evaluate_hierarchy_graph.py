from datetime import datetime
from django.core.management.base import BaseCommand, CommandError
from hierarchy.services.component_hierarchy_evaluation import evaluate_hierarchy
from hierarchy.services.hierarchy_metrics import format_metrics_table


class Command(BaseCommand):
    help = 'Evaluate a saved daily component hierarchy and draw chunk/component/Meta-component schematics; never rebuild the graph.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--day', required=True)
        parser.add_argument('--run-id', help='Complete hierarchy run; default active daily version. Each evaluation writes a new report version.')

    def handle(self, *args, **options):
        try:
            datetime.strptime(options['day'], '%Y-%m-%d')
            evaluation, paths = evaluate_hierarchy(options['day'], run_id=options['run_id'], progress=self.stdout.write)
        except Exception as exc:
            raise CommandError(f'Hierarchy evaluation failed: {exc}') from exc
        self.stdout.write(self.style.SUCCESS(f"[HIER-EVAL] COMPLETE: hierarchy_run={evaluation['hierarchy_run_id']}; report={evaluation['run_id']}"))
        self.stdout.write(format_metrics_table(evaluation['metrics_table']))
        for name, path in paths.items():
            self.stdout.write(f'[HIER-EVAL] {name}: {path}')
