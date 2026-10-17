from django.core.management.base import BaseCommand, CommandError

from spectral_learning.services.model_evaluation_report import create_model_evaluation_report


class Command(BaseCommand):
    help = "Create JSON and graphical evaluation reports for the latest anomaly model run."
    requires_system_checks = []

    def handle(self, *args, **options):
        try:
            result = create_model_evaluation_report()
        except Exception as exc:
            raise CommandError(f"Model evaluation report generation failed: {exc}") from exc
        self.stdout.write(self.style.SUCCESS("Model evaluation reports created."))
        for key, value in result.items():
            self.stdout.write(f"{key}: {value}")
