from django.core.management.base import BaseCommand, CommandError

from ingestion.services.reporting.ingest_report import create_ingest_report


class Command(BaseCommand):
    help = "Render the ingestion candidate/representative schematic."

    def add_arguments(self, parser):
        parser.add_argument("source_file", type=str)

    def handle(self, *args, **options):
        try:
            result = create_ingest_report(options["source_file"])
        except Exception as exc:
            raise CommandError(f"Ingestion report generation failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS("Ingestion report created."))
        for key, value in result.items():
            self.stdout.write(f"{key}: {value}")
