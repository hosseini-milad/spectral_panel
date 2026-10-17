from django.core.management.base import BaseCommand, CommandError

from spectral_learning.services.temporal_dataset import (
    build_hierarchical_temporal_dataset,
)


class Command(BaseCommand):
    help = "Build the event-level minute/hour/day temporal dataset."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("source_file", type=str)

    def handle(self, *args, **options):
        try:
            result = build_hierarchical_temporal_dataset(options["source_file"])
        except Exception as exc:
            raise CommandError(f"Temporal dataset build failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS("Temporal dataset build completed."))
        for key, value in result.items():
            self.stdout.write(f"{key}: {value}")
