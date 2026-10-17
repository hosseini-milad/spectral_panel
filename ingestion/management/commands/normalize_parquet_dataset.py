from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from mongoengine import get_connection
from pymongo import ReplaceOne

from ingestion.services.normalization.normalize_service import Normalizer
from ingestion.utils.constants import BINARY_FIELDS, EXCLUDED_FIELDS, PASSTHROUGH_FIELDS


# Numeric Parquet fields identified during schema inspection. The binary fields
# are retained as 0/1 and all remaining numeric fields are fitted with Min-Max.
NUMERIC_FIELDS = (
    "bytes", "bytes_per_packet", "bytes_per_sec", "dst_port", "duration_s",
    "flag_ack", "flag_count", "flag_fin", "flag_psh", "flag_rst", "flag_syn",
    "flag_urg", "iat_cv", "iat_mean", "iat_std", "is_encrypted_port",
    "is_syn_only", "log_bytes", "log_duration", "log_packets", "packets",
    "packets_per_sec", "payload_entropy", "proto_icmp", "proto_tcp", "proto_udp",
    "src_port", "tos", "threat_intel_score",
)

PRESERVED_METADATA = (
    "source_file", "source_path", "source_day", "source_type", "type",
    "row_index", "window_start", "flow_start", "timestamp", "created_at",
)


class Command(BaseCommand):
    help = "Standardize all ingested Parquet flows into normalized_security_data only."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=2000)
        parser.add_argument(
            "--day-count", type=int,
            help="Process the earliest N source_day partitions only.",
        )
        parser.add_argument(
            "--days", type=str,
            help="Comma-separated source_day values; overrides --day-count.",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        if batch_size < 1:
            raise CommandError("--batch-size must be positive")

        database = get_connection(alias="default")["siem_db"]
        raw = database["security_data"]
        normalized = database["normalized_security_data"]
        available_days = sorted(day for day in raw.distinct("source_day") if day)
        if options["days"]:
            selected_days = [day.strip() for day in options["days"].split(",") if day.strip()]
            unknown_days = sorted(set(selected_days) - set(available_days))
            if unknown_days:
                raise CommandError(f"Unknown source_day partition(s): {unknown_days}")
        elif options["day_count"] is not None:
            if options["day_count"] < 1:
                raise CommandError("--day-count must be positive")
            selected_days = available_days[:options["day_count"]]
        else:
            selected_days = available_days
        if not selected_days:
            raise CommandError("No source_day partitions were selected.")
        match = {"source_day": {"$in": selected_days}}
        total = raw.count_documents(match)
        if total == 0:
            raise CommandError("No raw records found in the selected source_day partitions.")

        numeric_fields = [
            field for field in NUMERIC_FIELDS
            if field not in BINARY_FIELDS and field not in EXCLUDED_FIELDS
        ]
        group = {"_id": None}
        for field in numeric_fields:
            group[f"{field}__min"] = {"$min": f"${field}"}
            group[f"{field}__max"] = {"$max": f"${field}"}
        result = next(raw.aggregate([
            {"$match": match}, {"$group": group},
        ], allowDiskUse=True), None)
        if result is None:
            raise CommandError("Could not compute global numeric ranges.")
        min_max = {
            field: {"min": result.get(f"{field}__min"), "max": result.get(f"{field}__max")}
            for field in numeric_fields
            if result.get(f"{field}__min") is not None and result.get(f"{field}__max") is not None
        }
        normalizer = Normalizer(min_max)
        self.stdout.write(
            f"Global ranges computed for {len(min_max)} numeric fields; "
            f"processing {total:,} raw records from {selected_days}."
        )

        cursor = raw.find(match, no_cursor_timeout=True).batch_size(batch_size)
        operations = []
        processed = 0
        try:
            for record in cursor:
                raw_id = record["_id"]
                label = normalizer.normalize_label(record.get("label", 0))
                output = {
                    "_id": raw_id,
                    "original_id": str(raw_id),
                    "source_file": record.get("source_file", ""),
                    "label": label,
                    "label_binary": label,
                    "normalization_version": 1,
                    "normalization_method": "global_min_max_3dp",
                    "normalized_at": datetime.utcnow(),
                }
                for field in PRESERVED_METADATA:
                    if field in record:
                        output[field] = record[field]
                for field in PASSTHROUGH_FIELDS:
                    if field in record:
                        output[field] = record[field]
                for field, value in record.items():
                    if field == "_id" or field in EXCLUDED_FIELDS or field in PASSTHROUGH_FIELDS:
                        continue
                    if field == "label":
                        continue
                    output[field] = normalizer.normalize(field, value)

                operations.append(ReplaceOne({"_id": raw_id}, output, upsert=True))
                processed += 1
                if len(operations) >= batch_size:
                    normalized.bulk_write(operations, ordered=False)
                    operations.clear()
                if processed % 100_000 == 0:
                    self.stdout.write(f"Standardized {processed:,}/{total:,} records")

            if operations:
                normalized.bulk_write(operations, ordered=False)
        finally:
            cursor.close()

        # Keep this run's output limited to selected days while preserving any
        # legacy normalized records that do not carry our version marker.
        normalized.delete_many({
            "normalization_version": 1,
            "source_day": {"$nin": selected_days},
        })
        normalized.delete_many({"normalization_preview": True})
        self.stdout.write(self.style.SUCCESS(
            f"Standardization completed: {processed:,} records written to "
            "siem_db.normalized_security_data."
        ))
        self.stdout.write(
            "Raw records were preserved. No sampling, graph construction, or training was run."
        )
