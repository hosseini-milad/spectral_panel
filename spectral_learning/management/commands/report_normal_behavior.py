from django.core.management.base import BaseCommand, CommandError

from spectral_learning.services.normal_behavior_report import create_normal_behavior_reports


class Command(BaseCommand):
    help = "Create per-hour and overall normal-reference behavior schematics."
    requires_system_checks = []

    def handle(self, *args, **options):
        try:
            result = create_normal_behavior_reports()
        except Exception as exc:
            raise CommandError(f"Normal-behavior report generation failed: {exc}") from exc
        self.stdout.write(self.style.SUCCESS("Normal-behavior reports created."))
        for key, value in result.items():
            self.stdout.write(f"{key}: {value}")
