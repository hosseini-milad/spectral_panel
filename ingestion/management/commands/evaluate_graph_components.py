from django.core.management.base import BaseCommand, CommandError
from mongoengine import get_db

from ingestion.services.graph.components import persist_components


class Command(BaseCommand):
    help = 'Persist/backfill connected components and export complete JSON/TXT and PNG/SVG schematics.'
    requires_system_checks = []

    def add_arguments(self, parser):
        target = parser.add_mutually_exclusive_group(required=True)
        target.add_argument('--source-file')
        target.add_argument('--all', action='store_true')
        parser.add_argument('--layer', type=int, choices=[1, 2], default=1)

    def handle(self, *args, **options):
        db = get_db()
        collection = 'graph_metadata' if options['layer'] == 1 else 'hyper_graph_metadata'
        query = {'source_file': options['source_file']} if options['source_file'] else {}
        count = 0
        for metadata in db[collection].find(query).sort('source_file', 1):
            if metadata.get('status') in {'building', 'failed'}:
                raise CommandError(f"Graph is not complete: {metadata['source_file']}")
            try:
                result = persist_components(metadata, graph_collection=collection)
            except Exception as exc:
                raise CommandError(f"Component evaluation failed for {metadata['source_file']}: {exc}") from exc
            count += 1
            self.stdout.write(self.style.SUCCESS(
                f"{result['source_file']}: nodes={result['node_count']}; components={result['component_count']}; "
                f"missing_sources={result['missing_node_count']}"))
            for kind, path in result['paths'].items():
                self.stdout.write(f'{kind.upper()}: {path}')
        if not count:
            raise CommandError('No matching graphs found; no evaluation performed.')
