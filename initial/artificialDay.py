"""Copy mixed raw records into a processing day; this is NOT a normal baseline.

Only source_day changes. Event timestamps, labels and raw features stay intact.
Interrupted writes are retained and can be resumed; no records are deleted.
"""

from contextlib import contextmanager
from copy import deepcopy
from datetime import date, timedelta
from hashlib import sha256
from tempfile import TemporaryFile
from uuid import uuid4

from bson import BSON, ObjectId, decode_file_iter
from pymongo import MongoClient, UpdateOne, timeout
from pymongo.errors import PyMongoError


START = date(2026, 6, 21)
TARGET = "2026-06-20"
DAY_COUNT = 10
BLOCK_SIZE = 20_000
BATCH_SIZE = 1000
VERSION = "mixed-raw-v1"
SOURCE_INDEX = [("source_day", 1), ("_id", 1)]


def ensure_source_index(collection, *, allow_create, seconds=600, progress=None):
    """Use an ordered day index; never create indexes during a dry run."""
    with _operation("Check source_day/_id index", seconds, progress):
        for index in collection.list_indexes():
            if (list(index["key"].items()) == SOURCE_INDEX
                    and not index.get("partialFilterExpression")
                    and not index.get("sparse") and not index.get("hidden")
                    and index.get("collation", {}).get("locale", "simple") == "simple"):
                if progress:
                    progress(f"Using source index: {index['name']}")
                return
    if not allow_create:
        raise ValueError("Missing compound index {source_day: 1, _id: 1}. "
                         "Run python -u initial/artificialDay.py --prepare-index once, "
                         "then repeat the dry run. No raw records were written.")
    with _operation("Create source_day/_id index (one-time database index build)", seconds, progress):
        collection.create_index(SOURCE_INDEX, maxTimeMS=max(1, int(seconds * 1000)))
    if progress:
        progress("Source index ready; no raw records changed by index preparation")


def source_query(day):
    return {
        "source_day": day,
        "is_synthetic_normal": {"$ne": True},
        "is_artificial_day": {"$ne": True},
        "artificial_day": {"$exists": False},
    }


def _batches(spool):
    spool.seek(0)
    batch = []
    for record in decode_file_iter(spool):
        batch.append(record)
        if len(batch) == BATCH_SIZE:
            yield batch
            batch = []
    if batch:
        yield batch


def _content(record):
    record = deepcopy(record)
    record["artificial_day"].pop("run_id", None)
    return record


@contextmanager
def _operation(name, seconds, progress):
    if progress:
        progress(name)
    try:
        with timeout(seconds):
            yield
    except PyMongoError as exc:
        detail = "time limit exceeded" if exc.timeout else type(exc).__name__
        raise RuntimeError(
            f"{name}: MongoDB {detail} (limit={seconds:g}s). "
            "Check MongoDB availability and the source_day index/query plan. "
            "No existing records were deleted; interrupted writes may be partial and can be resumed."
        ) from exc


def _read(collection, query, seconds, progress, name, skip=0, limit=0, ordered=False):
    with _operation(name, seconds, progress):
        cursor = collection.find(query)
        try:
            if ordered:
                cursor = cursor.hint(SOURCE_INDEX).sort("_id", 1)
            cursor = cursor.skip(skip).limit(limit).max_time_ms(max(1, int(seconds * 1000)))
            yield from cursor
        finally:
            cursor.close()


def build_artificial_day(db, dry_run=True, *, operation_timeout=60, progress=None,
                         index_timeout=600):
    if not 0 < operation_timeout <= 3600:
        raise ValueError("operation_timeout must be between 0 and 3600 seconds")
    collection = db.security_data
    ensure_source_index(collection, allow_create=not dry_run, seconds=index_timeout, progress=progress)
    plan = []
    for index in range(DAY_COUNT):
        day = (START + timedelta(days=index)).isoformat()
        with _operation(f"Capacity {index + 1}/{DAY_COUNT}: {day}", operation_timeout, progress):
            available = collection.count_documents(
                source_query(day), limit=(index + 1) * BLOCK_SIZE,
                hint=SOURCE_INDEX, maxTimeMS=max(1, int(operation_timeout * 1000)))
        if available == 0:
            raise ValueError(f"No eligible raw data in siem_db.security_data for source_day={day}; nothing written.")
        if progress:
            progress(f"{day}: eligible found (capped)={available:,}; required={(index + 1) * BLOCK_SIZE:,}")
        plan.append({"source_day": day, "skip": index * BLOCK_SIZE,
                     "take": BLOCK_SIZE, "available": available,
                     "count_capped_at": (index + 1) * BLOCK_SIZE})
    shortages = [row for row in plan if row["available"] < row["skip"] + row["take"]]
    if shortages:
        raise ValueError(f"Insufficient raw source data: {shortages}")

    run_id = uuid4().hex
    expected = DAY_COUNT * BLOCK_SIZE
    inserted = 0
    existing = 0
    # Spool the complete selection before writing. Memory is bounded by a batch.
    with TemporaryFile() as spool:
        for row in plan:
            count = 0
            cursor = _read(collection, source_query(row["source_day"]), operation_timeout,
                           progress, f"Select {row['source_day']} (skip={row['skip']:,}, take={row['take']:,})",
                           skip=row["skip"], limit=row["take"], ordered=True)
            for position, original in enumerate(cursor):
                record = deepcopy(original)
                original_id = record["_id"]
                # Keep the previous script's deterministic ID namespace so old
                # copies are detected as conflicts, rather than copied again.
                identity = (str(original_id) if isinstance(original_id, ObjectId)
                            else BSON.encode({"_id": original_id}).hex())
                key = f"artificial-v2|{TARGET}|{identity}"
                record["_id"] = ObjectId(sha256(key.encode()).hexdigest()[:24])
                record["source_day"] = TARGET
                record["is_artificial_day"] = True
                record["artificial_day"] = {
                    "version": VERSION, "run_id": run_id,
                    "original_id": original_id,
                    "original_source_day": original["source_day"],
                    "source_rank": row["skip"] + position,
                    "original_digest": sha256(BSON.encode(original)).hexdigest(),
                }
                spool.write(BSON.encode(record))
                count += 1
                if progress and count % BATCH_SIZE == 0:
                    progress(f"Selected {row['source_day']}: {count:,}/{row['take']:,}")
            if count != row["take"]:
                raise ValueError("Source selection changed; no copies were written.")

        # Validate every existing ID before any writes. Original/unknown target
        # records are preserved; incompatible copies stop the operation.
        for batch in _batches(spool):
            wanted = {record["_id"]: record for record in batch}
            for saved in _read(collection, {"_id": {"$in": list(wanted)}},
                               operation_timeout, progress, "Check existing copies"):
                if (not isinstance(saved.get("artificial_day"), dict)
                        or _content(saved) != _content(wanted[saved["_id"]])):
                    raise ValueError(f"Conflicting existing copy: {saved['_id']}; nothing written.")
                existing += 1

        if not dry_run:
            for batch in _batches(spool):
                operations = []
                for record in batch:
                    metadata = record["artificial_day"]
                    # A concurrent conflicting insert produces a duplicate-key
                    # error, never an overwrite. Completed batches remain resumable.
                    selector = {"_id": record["_id"], "source_day": TARGET,
                                "is_artificial_day": True,
                                **{f"artificial_day.{key}": metadata[key] for key in
                                   ("version", "original_id", "original_source_day",
                                    "source_rank", "original_digest")}}
                    operations.append(UpdateOne(selector, {"$setOnInsert": record}, upsert=True))
                with _operation(f"Write batch: {inserted:,} new records acknowledged so far",
                                operation_timeout, progress):
                    inserted += collection.bulk_write(operations, ordered=True).upserted_count
            verified = 0
            for batch in _batches(spool):
                wanted = {record["_id"]: record for record in batch}
                for saved in _read(collection, {"_id": {"$in": list(wanted)}},
                                   operation_timeout, progress, f"Verify copies: {verified:,}/{expected:,}"):
                    if _content(saved) != _content(wanted[saved["_id"]]):
                        raise ValueError("A copied record changed during verification.")
                    verified += 1
            if verified != expected:
                raise ValueError(f"Unexpected selected-copy count: {verified}, expected {expected}")

    return {"target_day": TARGET, "dry_run": dry_run, "expected_total": expected,
            "existing_selected": existing, "would_insert": expected - existing,
            "inserted": inserted, "run_id": run_id, "plan": plan,
            "normal_baseline": False}


def build_normal_day(db, dry_run=True):
    """Compatibility alias only; the generated day is not certified normal."""
    return build_artificial_day(db, dry_run=dry_run)


def main(argv=None):
    import argparse
    import json
    import math
    import sys
    from datetime import datetime

    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="Prepare source index if needed, then write copies")
    mode.add_argument("--prepare-index", action="store_true", help="Create source index only; do not copy records")
    parser.add_argument("--timeout-seconds", type=float, default=60,
                        help="Time limit for each database stage, in seconds (default: 60)")
    parser.add_argument("--index-timeout-seconds", type=float, default=600,
                        help="Separate time limit for one-time index preparation (default: 600)")
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout_seconds) or not 0 < args.timeout_seconds <= 3600:
        parser.error("--timeout-seconds must be between 0 and 3600")
    if not math.isfinite(args.index_timeout_seconds) or not 0 < args.index_timeout_seconds <= 3600:
        parser.error("--index-timeout-seconds must be between 0 and 3600")

    stage = "Connect to localhost:27017 / siem_db"

    def progress(message):
        nonlocal stage
        stage = message
        print(f"[{datetime.now().isoformat(timespec='seconds')}] {message}", file=sys.stderr, flush=True)

    try:
        progress(f"Mode: {'PREPARE INDEX ONLY' if args.prepare_index else 'WRITE' if args.write else 'DRY RUN (no writes)'}; "
                 f"database stage limit={args.timeout_seconds:g}s")
        with MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=5000,
                         connectTimeoutMS=5000,
                         socketTimeoutMS=max(1, int(max(args.timeout_seconds, args.index_timeout_seconds) * 1000)),
                         retryReads=False, retryWrites=False) as client:
            with _operation("Ping MongoDB", args.timeout_seconds, progress):
                client.admin.command("ping")
            if args.prepare_index:
                ensure_source_index(client["siem_db"].security_data, allow_create=True,
                                    seconds=args.index_timeout_seconds, progress=progress)
                result = {"index_ready": True, "inserted": 0}
            else:
                result = build_artificial_day(client["siem_db"], dry_run=not args.write,
                                              operation_timeout=args.timeout_seconds, progress=progress,
                                              index_timeout=args.index_timeout_seconds)
        print(json.dumps(result, indent=2), flush=True)
        return 0
    except KeyboardInterrupt:
        print(f"ERROR: Interrupted during {stage}. Existing records were preserved; "
              "writes may be partial. Rerun to resume safely.", file=sys.stderr, flush=True)
        return 130
    except Exception as exc:
        print(f"ERROR during {stage}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        if args.write:
            print("No rollback/deletion was performed. If writing had started, copies may be partial; "
                  "rerun after resolving the error to resume.", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
