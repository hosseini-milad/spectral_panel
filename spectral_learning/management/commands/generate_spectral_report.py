from django.core.management.base import BaseCommand, CommandError

from spectral_learning.services.spectral_report import create_spectral_report


class Command(BaseCommand):
    help = "Validate and render a temporal-graph spectral report."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("source_file", type=str)

    def handle(self, *args, **options):
        try:
            result = create_spectral_report(options["source_file"])
        except Exception as exc:
            raise CommandError(f"Spectral report generation failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS("Spectral report created."))
        for key, value in result.items():
            self.stdout.write(f"{key}: {value}")
        if result["failed_checks"]:
            raise CommandError("Spectral checks failed; inspect report-spectral.json.")
