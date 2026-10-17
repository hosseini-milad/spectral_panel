from django.core.management.base import BaseCommand, CommandError

from spectral_learning.services.hourly_spectral_report import build_hourly_spectral_data
from spectral_learning.services.hourly_temporal_representation import (
    build_hourly_temporal_representation,
)


class Command(BaseCommand):
    help = (
        "Persist ordinal hourly event representations and similarity-graph "
        "spectral snapshots; does not create reports or images."
    )
    requires_system_checks = []

    def handle(self, *args, **options):
        try:
            temporal = build_hourly_temporal_representation()
            spectral = build_hourly_spectral_data()
        except Exception as exc:
            raise CommandError(f"Hourly temporal/spectral build failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS("Hourly database representations built."))
        self.stdout.write(f"temporal: {temporal}")
        self.stdout.write(f"spectral: {spectral}")
        self.stdout.write(
            "No image was generated. Run generate_hourly_spectral_reports after verifying these records."
        )
