import math
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from mongoengine import get_connection

from ingestion.services.normalization.normalize_service import Normalizer
from ingestion.utils.constants import BINARY_FIELDS, EXCLUDED_FIELDS, PASSTHROUGH_FIELDS


class Command(BaseCommand):
    help = "Normalize a small balanced sample and store it for inspection."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--per-class", type=int, default=5)

    def handle(self, *args, **options):
        per_class = options["per_class"]
        if per_class < 1:
            raise CommandError("--per-class must be positive")

        database = get_connection(alias="default")["siem_db"]
        raw = database["security_data"]
        normalized = database["normalized_security_data"]
        records = []
        for label in (0, 1):
            batch = list(raw.find({"label": label}).limit(per_class))
            if len(batch) < per_class:
                raise CommandError(
                    f"Expected {per_class} records for label={label}, found {len(batch)}; "
                    "nothing was written."
                )
            records.extend(batch)

        # These ranges are deliberately fitted on the preview sample only.
        min_max = {}
        for record in records:
            for key, value in record.items():
                if key in EXCLUDED_FIELDS or key in BINARY_FIELDS or isinstance(value, bool):
                    continue
                try:
                    number = float(value)
                except (TypeError, ValueError, OverflowError):
                    continue
                if not math.isfinite(number):
                    continue
                bounds = min_max.setdefault(key, {"min": number, "max": number})
                bounds["min"] = min(bounds["min"], number)
                bounds["max"] = max(bounds["max"], number)

        normalizer = Normalizer(min_max)
        stored = []
        now = datetime.utcnow()
        for record in records:
            raw_id = str(record["_id"])
            output = {
                "_id": f"preview10:{raw_id}",
                "original_id": raw_id,
                "source_file": record.get("source_file", ""),
                "normalization_preview": True,
                "normalization_range_basis": "balanced_preview_sample",
                "normalized_at": now,
            }
            for key in PASSTHROUGH_FIELDS:
                if key in record:
                    output[key] = record[key]
            for key, value in record.items():
                if key in EXCLUDED_FIELDS:
                    continue
                output[key] = normalizer.normalize(key, value)
            normalized.replace_one({"_id": output["_id"]}, output, upsert=True)
            stored.append(output)

        self.stdout.write(self.style.SUCCESS(
            f"Stored {len(stored)} normalized preview records in "
            "siem_db.normalized_security_data (raw records unchanged)."
        ))
        self.stdout.write("Ranges were fitted on this preview sample only; do not use for model training.")
        for item in stored:
            self.stdout.write(
                f"label={item.get('label')} original_id={item['original_id']} "
                f"bytes={item.get('bytes')} duration_s={item.get('duration_s')} "
                f"packets={item.get('packets')} flag_syn={item.get('flag_syn')}"
            )
