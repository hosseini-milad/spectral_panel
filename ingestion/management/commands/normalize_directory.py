from django.core.management.base import BaseCommand, CommandError

from ingestion.models.dataset_metadata import DatasetMetadata
from ingestion.models.normalized_data import NormalizedSecurityData
from ingestion.models.raw_data import RawSecurityData
from ingestion.pipelines.normalize_pipeline import run_normalization


class Command(BaseCommand):
    help = "Rebuild normalized records from already ingested raw sources."
    requires_system_checks = []

    def handle(self, *args, **options):
        sources = sorted(
            item.source_file
            for item in DatasetMetadata.objects.only("source_file")
            if item.source_file
        )
        if not sources:
            raise CommandError("No ingested sources found in dataset metadata.")

        total = 0
        for source_file in sources:
            raw_count = RawSecurityData.objects(source_file=source_file).count()
            if not raw_count:
                raise CommandError(f"No raw records found for {source_file}.")
            try:
                normalized_count = run_normalization(source_file)
            except Exception as exc:
                raise CommandError(f"Normalization failed for {source_file}: {exc}") from exc
            if normalized_count != raw_count:
                raise CommandError(
                    f"{source_file}: normalized {normalized_count} of {raw_count} records."
                )
            total += normalized_count
            self.stdout.write(f"{source_file}: {normalized_count} normalized records")

        self.stdout.write(
            self.style.SUCCESS(
                f"Rebuilt normalized data for {len(sources)} sources ({total} records)."
            )
        )
