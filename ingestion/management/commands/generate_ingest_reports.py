import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ingestion.models.dataset_metadata import DatasetMetadata
from ingestion.services.reporting.ingest_report import create_ingest_report


class Command(BaseCommand):
    help = "Create one candidate/representative schematic per ingested dataset."
    requires_system_checks = []

    def handle(self, *args, **options):
        sources = sorted(
            {
                item.source_file
                for item in DatasetMetadata.objects.only("source_file")
                if item.source_file
            },
            key=lambda source: (
                re.sub(r"\d+", lambda match: f"{int(match.group()):08d}", source.lower())
            ),
        )
        if not sources:
            raise CommandError("No ingested datasets found in metadata.")

        output_dir = Path(settings.BASE_DIR) / "files" / "report" / "ingestion"
        results = []
        for source_file in sources:
            safe_stem = Path(source_file).stem
            output_path = output_dir / f"report-ingest-{safe_stem}.png"
            try:
                result = create_ingest_report(source_file, output_path=output_path)
            except Exception as exc:
                raise CommandError(
                    f"Could not create ingestion report for {source_file}: {exc}"
                ) from exc
            results.append(result)
            self.stdout.write(
                f"{source_file}: {result['path']} "
                f"(candidates={result['candidate_count']}, "
                f"representatives={result['representative_count']})"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {len(results)} ingestion reports in {output_dir}."
            )
        )
