from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from spectral_learning.services.encoder_meta_report import build_meta_view


class Command(BaseCommand):
    help = 'Visualize existing spectral L1 embeddings beside exact daily Meta-component membership; no retraining.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--day', required=True)
        parser.add_argument('--manifest', help='Explicit completed L1 Autoencoder manifest; otherwise newest local run.')
        parser.add_argument('--lineage', help='Explicit hierarchy lineage.json; otherwise newest local evaluation run.')
        parser.add_argument('--top', type=int, default=12)
        parser.add_argument('--neighbors', type=int, default=10, help='Cosine kNN count for post-hoc neighborhood diagnostics.')

    def handle(self, *args, **options):
        try:
            datetime.strptime(options['day'], '%Y-%m-%d')
            root = Path(settings.BASE_DIR) / 'document'
            def choose(explicit, category, layer, pattern):
                if explicit:
                    return Path(explicit)
                choices = list((root / category / layer / options['day'] / 'whole-day').glob(pattern))
                if not choices:
                    raise ValueError(f'Missing {category} exports for {options["day"]}.')
                return max(choices, key=lambda p: (p.stat().st_mtime_ns, str(p)))
            manifest = choose(options['manifest'], 'autoencoder', 'layer1', 'runs/*/manifest.json')
            lineage = choose(options['lineage'], 'hierarchy', 'layer2', '*/runs/*/lineage.json')
            import json
            source = json.loads(manifest.read_text(encoding='utf-8-sig'))
            if source['source_day'] != options['day']:
                raise ValueError('Manifest day does not match --day.')
            output = root / 'autoencoder' / 'layer1' / options['day'] / 'whole-day' / 'runs' / source['run_id'] / 'meta_view' / lineage.parent.name
            result = build_meta_view(manifest, lineage, output, options['top'], options['neighbors'])
        except Exception as exc:
            raise CommandError(f'Meta encoder visualization failed: {exc}') from exc
        self.stdout.write(self.style.SUCCESS(f'Membership verified: {result["components"]} components, {result["meta_components"]} metas, {result["candidate_nodes"]} candidate nodes.'))
        self.stdout.write(f'Manifest: {manifest}\nLineage: {lineage}\nOutput: {output}')
        if 'neighborhood' in result:
            report = result['neighborhood']
            self.stdout.write(f'Neighborhood recall: {report["macro_graph_neighbor_recall"]}; isolates: {report["graph_isolates"]}; valid queries: {report["graph_neighbor_recall_valid_components"]}')
        else:
            self.stdout.write(self.style.WARNING('Lineage has no edges field; neighborhood diagnostics were not generated.'))
