from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from mongoengine import get_connection
from pymongo import ReplaceOne

from ingestion.services.normalization.minmax import LOG_FIELDS
from ingestion.services.normalization.normalize_service import Normalizer
from ingestion.utils.constants import (
    BINARY_FIELDS,
    EXCLUDED_FIELDS,
    PASSTHROUGH_FIELDS,
)


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
    "flow_file",
)


class Command(BaseCommand):
    help = (
        "Normalize source_day partitions using full-range Min-Max and log1p. "
        "When --sample-per-day is supplied, process a deterministic sequential "
        "chunk from one day; normalization bounds are computed from the full day. "
        "Chunk reads use a compound MongoDB index to avoid blocking in-memory sorts."
    )
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=2000)
        parser.add_argument(
            "--day-count", type=int,
            help="Process the earliest N source_day partitions.",
        )
        parser.add_argument(
            "--days", type=str,
            help="Comma-separated source_day values; overrides --day-count.",
        )
        parser.add_argument(
            "--sample-per-day", type=int, default=None,
            help="Sequential chunk size per day (not random sampling).",
        )
        parser.add_argument(
            "--chunk-index", type=int, default=0,
            help="Zero-based sequential chunk index; requires --sample-per-day and exactly one day.",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        sample_per_day = options["sample_per_day"]
        chunk_index = options["chunk_index"]

        if batch_size < 1:
            raise CommandError("--batch-size must be positive")
        if sample_per_day is not None and sample_per_day < 1:
            raise CommandError("--sample-per-day must be positive")
        if chunk_index < 0:
            raise CommandError("--chunk-index cannot be negative")
        if sample_per_day is None and chunk_index != 0:
            raise CommandError("--chunk-index requires --sample-per-day")

        database = get_connection(alias="default")["siem_db"]
        raw = database["security_data"]
        normalized = database["normalized_security_data"]

        available_days = sorted(day for day in raw.distinct("source_day") if day)

        if options["days"]:
            selected_days = [
                day.strip() for day in options["days"].split(",") if day.strip()
            ]
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

        if sample_per_day is not None and len(selected_days) != 1:
            raise CommandError(
                "Sequential chunk mode requires exactly one day. "
                "Pass one value to --days, for example --days 2026-06-21."
            )

        # `bounds_match` defines the population used to calculate Min-Max limits.
        # In chunk mode this is the FULL DAY, not just the selected 20k records.
        if sample_per_day is not None:
            day = selected_days[0]
            bounds_match = {"source_day": day}

            # The chunk query sorts by source_file, row_index and _id.
            # Without this compound index MongoDB may perform an in-memory
            # blocking sort and fail at its 100 MB sort limit.
            chunk_sort_index = "source_day_source_file_row_index_id"
            try:
                raw.create_index(
                    [
                        ("source_day", 1),
                        ("source_file", 1),
                        ("row_index", 1),
                        ("_id", 1),
                    ],
                    name=chunk_sort_index,
                )
            except Exception as exc:
                raise CommandError(
                    "Could not create/verify the compound index required for "
                    "deterministic chunk sorting on security_data. "
                    f"Index={chunk_sort_index!r}; cause: {exc}"
                ) from exc

            day_total = raw.count_documents(bounds_match)
            offset = chunk_index * sample_per_day
            total = max(0, min(sample_per_day, day_total - offset))
            if total == 0:
                raise CommandError(
                    f"Chunk {chunk_index} is empty for {day}. "
                    f"Day has {day_total:,} records; requested offset={offset:,}."
                )

            selected_cursor = (
                raw.find(bounds_match, no_cursor_timeout=True)
                .hint(chunk_sort_index)
                .sort([("source_file", 1), ("row_index", 1), ("_id", 1)])
                .skip(offset)
                .limit(sample_per_day)
                .batch_size(batch_size)
            )
            self.stdout.write(
                f"Sequential chunk: day={day}; chunk_index={chunk_index}; "
                f"offset={offset:,}; records={total:,}; day_total={day_total:,}."
            )
        else:
            bounds_match = {"source_day": {"$in": selected_days}}
            total = raw.count_documents(bounds_match)
            if total == 0:
                raise CommandError("No raw records found in the selected partitions.")
            selected_cursor = raw.find(
                bounds_match, no_cursor_timeout=True
            ).sort([("source_day", 1), ("source_file", 1), ("row_index", 1), ("_id", 1)]).batch_size(batch_size)

        numeric_fields = [
            field for field in NUMERIC_FIELDS
            if field not in BINARY_FIELDS and field not in EXCLUDED_FIELDS
        ]

        # Compute Min-Max bounds over the full selected day(s), not the chunk.
        group = {"_id": None}
        for field in numeric_fields:
            group[f"{field}__min"] = {"$min": f"${field}"}
            group[f"{field}__max"] = {"$max": f"${field}"}
            if field in LOG_FIELDS:
                converted = {
                    "$convert": {
                        "input": f"${field}", "to": "double",
                        "onError": 0, "onNull": 0,
                    }
                }
                nonnegative = {"$max": [0, converted]}
                log_value = {"$ln": {"$add": [nonnegative, 1]}}
                group[f"{field}__log_min"] = {"$min": log_value}
                group[f"{field}__log_max"] = {"$max": log_value}

        result = next(
            raw.aggregate(
                [{"$match": bounds_match}, {"$group": group}],
                allowDiskUse=True,
            ),
            None,
        )
        if result is None:
            selected_cursor.close()
            raise CommandError("Could not compute numeric ranges.")

        min_max = {}
        for field in numeric_fields:
            minimum = result.get(f"{field}__min")
            maximum = result.get(f"{field}__max")
            if minimum is None or maximum is None:
                continue
            bounds = {"min": minimum, "max": maximum}
            if field in LOG_FIELDS:
                log_min = result.get(f"{field}__log_min")
                log_max = result.get(f"{field}__log_max")
                if log_min is None or log_max is None:
                    selected_cursor.close()
                    raise CommandError(f"Missing logarithmic bounds for '{field}'.")
                bounds["log_min"] = log_min
                bounds["log_max"] = log_max
            min_max[field] = bounds

        normalizer = Normalizer(min_max)
        self.stdout.write(
            f"Computed full-population ranges for {len(min_max)} fields; "
            f"processing {total:,} records from {selected_days}."
        )

        operations = []
        processed = 0
        try:
            for record in selected_cursor:
                raw_id = record["_id"]
                label = normalizer.normalize_label(record.get("label", 0))
                output = {
                    "_id": raw_id,
                    "original_id": str(raw_id),
                    "source_file": record.get("source_file", ""),
                    "label": label,
                    "label_binary": label,
                    "normalization_version": 2,
                    "normalization_method": (
                        "sequential_chunk_log1p_minmax_full_day"
                        if sample_per_day is not None
                        else "global_log1p_minmax_full_range"
                    ),
                    "normalization_sample": sample_per_day is not None,
                    "normalization_sample_per_day": sample_per_day,
                    "normalization_chunk_index": chunk_index if sample_per_day is not None else None,
                    "normalized_at": datetime.utcnow(),
                }
                for field in PRESERVED_METADATA:
                    if field in record:
                        output[field] = record[field]
                for field in PASSTHROUGH_FIELDS:
                    if field in record:
                        output[field] = record[field]
                for field, value in record.items():
                    if (
                        field == "_id"
                        or field in EXCLUDED_FIELDS
                        or field in PASSTHROUGH_FIELDS
                        or field in PRESERVED_METADATA
                        or field == "label"
                    ):
                        continue
                    output[field] = normalizer.normalize(field, value)

                operations.append(ReplaceOne({"_id": raw_id}, output, upsert=True))
                processed += 1
                if len(operations) >= batch_size:
                    normalized.bulk_write(operations, ordered=False)
                    operations.clear()
                if processed % 5000 == 0:
                    self.stdout.write(f"Normalized {processed:,}/{total:,} records.")
            if operations:
                normalized.bulk_write(operations, ordered=False)
        finally:
            selected_cursor.close()

        self.stdout.write(self.style.SUCCESS(
            f"Normalization completed: {processed:,} records written to "
            "siem_db.normalized_security_data."
        ))
        self.stdout.write(
            "Chunk selection is deterministic and non-random. Re-running a chunk "
            "updates the same raw IDs; other chunks are preserved."
        )
