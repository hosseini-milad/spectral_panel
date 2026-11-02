"""Remove only empty, explicitly retired representative-hierarchy collections."""
import json
from datetime import datetime, timezone
from pathlib import Path
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from mongoengine import get_db

RETIRED = ('hyper_graph_edges', 'hyper_graph_metadata', 'hyper_representatives')


class Command(BaseCommand):
    help = 'Inspect retired hyper_* collections; --apply drops only empty allowlisted collections. All other collections are retained.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Drop only the three retired collections if empty; default only writes a preview.')

    def handle(self, *args, **options):
        db = get_db()
        report_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
        folder = Path(settings.BASE_DIR) / 'document' / 'report' / 'database-maintenance' / report_id
        manifest = dict(report_id=report_id, database=db.name, apply=options['apply'], status='planning',
                        allowlist=list(RETIRED), collections=[], created_at=datetime.now(timezone.utc).isoformat())
        def save():
            (folder / 'cleanup.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        try:
            existing = set(db.list_collection_names())
            manifest['retained_other_collections'] = sorted(existing - set(RETIRED))
            for name in RETIRED:
                count = db[name].count_documents({}) if name in existing else None
                manifest['collections'].append(dict(collection=name, documents=count,
                    action='absent' if count is None else ('keep_nonempty' if count else 'would_drop_empty')))
            folder.mkdir(parents=True, exist_ok=False)
            # A reviewable plan must exist before any namespace is removed.
            save()
            if options['apply']:
                for row in manifest['collections']:
                    if row['action'] == 'would_drop_empty':
                        count = db[row['collection']].count_documents({})
                        if count:
                            row.update(documents=count, action='keep_nonempty')
                        else:
                            db.drop_collection(row['collection']); row['action'] = 'dropped_empty'
                        save()
            manifest['status'] = 'complete'; save()
            lines = [f"Database: {db.name}", f"Apply: {options['apply']}"] + [f"{row['collection']}: {row['action']} (documents={row['documents']})" for row in manifest['collections']]
            (folder / 'cleanup.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
            for line in lines:
                self.stdout.write(line)
            self.stdout.write(f'Report: {folder / "cleanup.json"}')
            if not options['apply']:
                self.stdout.write('Preview only. Use --apply to drop empty allowlisted collections.')
        except Exception as exc:
            manifest.update(status='failed', error=str(exc))
            if folder.exists():
                save()
            raise CommandError(f'Legacy collection cleanup failed: {exc}') from exc
