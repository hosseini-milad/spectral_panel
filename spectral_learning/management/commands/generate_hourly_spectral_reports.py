from django.core.management.base import BaseCommand, CommandError

from spectral_learning.services.hourly_spectral_report import (
    create_hourly_spectral_reports,
)


class Command(BaseCommand):
    help = "Create per-workbook hourly spectral reports and one overall report."
    requires_system_checks = []

    def handle(self, *args, **options):
        try:
            result = create_hourly_spectral_reports()
        except Exception as exc:
            raise CommandError(f"Hourly spectral report generation failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS("Hourly spectral reports created."))
        for key, value in result.items():
            self.stdout.write(f"{key}: {value}")
