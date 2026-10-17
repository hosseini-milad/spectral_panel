from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from mongoengine import get_connection
from pymongo import InsertOne
from bson import ObjectId


class Command(BaseCommand):
    help = (
        "Uniformly sample initial candidates from one normalized source day; "
        "does not build a graph or compute spectral features."
    )
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--day", required=True, help="source_day partition, e.g. 2026-06-21")
        parser.add_argument("--count", type=int, default=20_000)
        parser.add_argument("--batch-size", type=int, default=2_000)

    def handle(self, *args, **options):
        day = options["day"]
        sample_count = options["count"]
        batch_size = options["batch_size"]
        if sample_count < 1 or batch_size < 1:
            raise CommandError("--count and --batch-size must be positive.")

        database = get_connection(alias="default")["siem_db"]
        normalized = database["normalized_security_data"]
        candidates = database["sampled_security_data"]
        day_filter = {"source_day": day, "normalization_version": 1}
        available = normalized.count_documents(day_filter)
        if available == 0:
            raise CommandError(f"No normalized records found for source_day={day!r}.")

        selected_count = min(sample_count, available)
        # Uniform random sampling preserves the source class distribution in
        # expectation and avoids loading millions of records into application RAM.
        cursor = normalized.aggregate(
            [{"$match": day_filter}, {"$sample": {"size": selected_count}}],
            allowDiskUse=True,
        )

        # Replace only this command's previous run for this day.
        candidates.delete_many({
            "source_day": day,
            "candidate_generation": "uniform_day_sample_v1",
        })

        operations = []
        processed = 0
        try:
            for record in cursor:
                record.pop("_id", None)
                record["_id"] = ObjectId()
                record["candidate_generation"] = "uniform_day_sample_v1"
                record["candidate_sampled_at"] = datetime.utcnow()
                operations.append(InsertOne(record))
                if len(operations) >= batch_size:
                    candidates.bulk_write(operations, ordered=False)
                    processed += len(operations)
                    operations.clear()
            if operations:
                candidates.bulk_write(operations, ordered=False)
                processed += len(operations)
        finally:
            cursor.close()

        stored = candidates.count_documents({
            "source_day": day,
            "candidate_generation": "uniform_day_sample_v1",
        })
        label_counts = {
            str(label): candidates.count_documents({
                "source_day": day,
                "candidate_generation": "uniform_day_sample_v1",
                "label": label,
            })
            for label in (0, 1)
        }
        self.stdout.write(self.style.SUCCESS(
            f"Stored {stored:,} initial candidates for {day} in "
            "siem_db.sampled_security_data."
        ))
        self.stdout.write(
            f"Normalized day records: {available:,}; requested: {sample_count:,}; "
            f"labels: {label_counts}. No graph or spectral computation was run."
        )
