from django.core.management.base import BaseCommand,CommandError
from mongoengine import get_db
from ingestion.services.pooling.spread_preview import preview_spread


class Command(BaseCommand):
    help='Preview representative spreading on one stored chunk; exports before/after metrics and same-layout figure without changing MongoDB.'
    requires_system_checks=[]

    def add_arguments(self,parser):
        parser.add_argument('--day',required=True)
        parser.add_argument('--chunk-index',type=int,default=0)

    def handle(self,*args,**options):
        try:
            from datetime import date
            day=options['day']
            if date.fromisoformat(day).isoformat()!=day or options['chunk_index']<0:raise ValueError('Invalid day/chunk')
            source=f"clustered-day-{day}-chunk-{options['chunk_index']}"
            self.stdout.write(f'[SPREAD PREVIEW] {source}; read-only comparison')
            folder=preview_spread(get_db(),source)
        except Exception as exc:
            raise CommandError(f'Representative spread preview failed: {exc}') from exc
        self.stdout.write(self.style.SUCCESS(f'[SPREAD PREVIEW] COMPLETE: {folder}'))
