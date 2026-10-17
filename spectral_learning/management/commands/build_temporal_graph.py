from django.core.management.base import BaseCommand, CommandError

from spectral_learning.services.temporal_graph import build_temporal_graph


class Command(BaseCommand):
    help = "Build temporal graph snapshots and spectral/change features."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("source_file", type=str)

    def handle(self, *args, **options):
        try:
            result = build_temporal_graph(options["source_file"])
        except Exception as exc:
            raise CommandError(f"Temporal graph build failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS("Temporal graph build completed."))
        for key, value in result.items():
            self.stdout.write(f"{key}: {value}")
