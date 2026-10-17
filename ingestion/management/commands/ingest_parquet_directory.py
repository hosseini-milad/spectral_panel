from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ingestion.services.ingestion.parquet_ingest import ingest_parquet_directory


class Command(BaseCommand):
    help = "Store raw flow Parquet records in security_data without normalization or downstream processing."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument(
            "--directory", type=str,
            default=str(Path(settings.BASE_DIR) / "files" / "parquet"),
        )
        parser.add_argument("--batch-size", type=int, default=3000)

    def handle(self, *args, **options):
        def progress(done, total, records):
            self.stdout.write(f"Files stored: {done}/{total}; new rows inserted: {records:,}")

        try:
            result = ingest_parquet_directory(
                options["directory"], batch_size=options["batch_size"], progress=progress,
            )
        except Exception as exc:
            raise CommandError(f"Parquet raw ingestion failed: {exc}") from exc
        self.stdout.write(self.style.SUCCESS("Raw Parquet ingestion completed."))
        for key, value in result.items():
            self.stdout.write(f"{key}: {value}")
