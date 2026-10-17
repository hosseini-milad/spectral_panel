from collections import Counter
from pathlib import Path
import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ingestion.models.dataset_metadata import DatasetMetadata
from ingestion.models.normalized_data import NormalizedSecurityData
from ingestion.models.raw_data import RawSecurityData
from ingestion.pipelines.normalize_pipeline import run_normalization
from ingestion.services.ingestion.excel_ingest import (
    ingest_dataframe,
    read_standardized_excel,
)


class Command(BaseCommand):
    help = "Ingest and normalize Excel files from files/DS; does not build graphs."
    requires_system_checks = []

    def handle(self, *args, **options):
        data_dir = Path(settings.BASE_DIR) / "files" / "DS"
        paths = sorted(
            data_dir.glob("*.xlsx"),
            key=lambda path: (
                int(re.search(r"\d+", path.stem).group())
                if re.search(r"\d+", path.stem)
                else path.stem.lower()
            ),
        )
        if not paths:
            raise CommandError(f"No .xlsx files found in {data_dir}")

        # Read and validate every source before changing the database.
        prepared = []
        expected_columns = None
        for path in paths:
            try:
                frame = read_standardized_excel(path)
            except Exception as exc:
                raise CommandError(f"Could not read {path.name}: {exc}") from exc
            if frame.empty:
                raise CommandError(f"{path.name} contains no data rows.")
            if frame["label"].isna().any() or frame["label"].astype(str).str.strip().eq("").any():
                raise CommandError(f"{path.name} has missing labels.")
            columns = list(frame.columns)
            if expected_columns is None:
                expected_columns = set(columns)
            elif set(columns) != expected_columns:
                missing = sorted(expected_columns - set(columns))
                extra = sorted(set(columns) - expected_columns)
                raise CommandError(
                    f"Schema mismatch in {path.name}; missing={missing}, extra={extra}"
                )
            prepared.append((path.name, frame))

        total_rows = sum(len(frame) for _, frame in prepared)
        self.stdout.write(
            f"Preflight passed: {len(prepared)} files, {total_rows} rows, "
            f"{len(expected_columns)} columns."
        )

        for source_file, frame in prepared:
            try:
                raw_count, columns = ingest_dataframe(frame, source_file)
                DatasetMetadata.objects(source_file=source_file).delete()
                DatasetMetadata(
                    source_file=source_file,
                    columns=columns,
                    record_count=raw_count,
                ).save()
                normalized_count = run_normalization(source_file)
                if normalized_count != raw_count:
                    raise ValueError(
                        f"normalized {normalized_count} of {raw_count} records"
                    )
            except Exception as exc:
                raise CommandError(f"Processing failed for {source_file}: {exc}") from exc

            raw_labels = Counter(str(value).strip() for value in frame["label"])
            normalized_labels = Counter(
                doc.get("label")
                for doc in NormalizedSecurityData.objects(source_file=source_file)
                .only("label")
                .as_pymongo()
            )
            self.stdout.write(
                f"{source_file}: raw={raw_count}, normalized={normalized_count}, "
                f"raw_classes={dict(raw_labels)}, binary_labels={dict(normalized_labels)}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Ingestion and normalization completed. No sampling, representative "
                "selection, graph, temporal, or spectral step was run."
            )
        )
