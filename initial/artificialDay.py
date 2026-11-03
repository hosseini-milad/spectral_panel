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
READ_BATCH_SIZE = 256
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
    if not ordered:
        with _operation(name, seconds, progress):
            with collection.find(query).max_time_ms(max(1, int(seconds * 1000))) as cursor:
                records = list(cursor)
        yield from records
        return

    # New indexed query per page: the timeout cannot accumulate across the
    # entire day's cursor, BSON encoding or temporary-file I/O.
    remaining = limit
    last_id = None
    first = True
    while remaining:
        page_query = query if first else {**query, "_id": {"$gt": last_id}}
        take = min(READ_BATCH_SIZE, remaining)
        with _operation(f"{name}: fetch up to {take} records ({limit - remaining:,}/{limit:,})",
                        seconds, progress):
            cursor = (collection.find(page_query).hint(SOURCE_INDEX).sort("_id", 1)
                      .skip(skip if first else 0).limit(take)
                      .max_time_ms(max(1, int(seconds * 1000))))
            try:
                records = list(cursor)
            finally:
                cursor.close()
        if not records:
            return
        last_id = records[-1]["_id"]
        remaining -= len(records)
        yield from records
        if len(records) < take:
            return
        first = False


def _selection_plan(day=None, offset=None, limit=None):
    if day is None and offset is None and limit is None:
        return [{"source_day": (START + timedelta(days=index)).isoformat(),
                 "skip": index * BLOCK_SIZE, "take": BLOCK_SIZE}
                for index in range(DAY_COUNT)]
    if day is None or offset is None or limit is None:
        raise ValueError("Provide --day, --offset and --limit together")
    try:
        parsed = date.fromisoformat(day)
    except (ValueError, TypeError):
        raise ValueError("--day must be a valid date in YYYY-MM-DD format") from None
    if parsed.isoformat() != day:
        raise ValueError("--day must use YYYY-MM-DD format")
    if day == TARGET:
        raise ValueError("Source --day cannot equal destination day " + TARGET)
    if not isinstance(offset, int) or offset < 0:
        raise ValueError("--offset must be a nonnegative integer")
    if not isinstance(limit, int) or limit <= 0:
        raise ValueError("--limit must be a positive integer")
    return [{"source_day": day, "skip": offset, "take": limit}]


def build_artificial_day(db, dry_run=True, *, operation_timeout=60, progress=None,
                         index_timeout=600, day=None, offset=None, limit=None):
    if not 0 < operation_timeout <= 3600:
        raise ValueError("operation_timeout must be between 0 and 3600 seconds")
    plan = _selection_plan(day, offset, limit)
    collection = db.security_data
    ensure_source_index(collection, allow_create=not dry_run, seconds=index_timeout, progress=progress)

    run_id = uuid4().hex
    expected = sum(row["take"] for row in plan)
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
                raise ValueError(
                    f"Insufficient raw data for {row['source_day']}: "
                    f"skip={row['skip']:,}, required={row['take']:,}, selected={count:,}. "
                    "The day is missing, insufficient, or changed during selection; nothing written."
                )
            row["selected"] = count
            if progress:
                progress(f"Validated {row['source_day']}: {count:,}/{row['take']:,}; no copies written yet")

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
    parser.add_argument("--day", help="Read only this source day (YYYY-MM-DD); destination remains 2026-06-20")
    parser.add_argument("--offset", type=int, help="Number of eligible records to skip in _id order")
    parser.add_argument("--limit", type=int, help="Number of records to copy from the selected day")
    parser.add_argument("--timeout-seconds", type=float, default=60,
                        help="Time limit per database request/page, not per whole day (default: 60)")
    parser.add_argument("--index-timeout-seconds", type=float, default=600,
                        help="Separate time limit for one-time index preparation (default: 600)")
    args = parser.parse_args(argv)
    try:
        _selection_plan(args.day, args.offset, args.limit)
    except ValueError as exc:
        parser.error(str(exc))
    if args.prepare_index and args.day is not None:
        parser.error("--prepare-index cannot be combined with --day/--offset/--limit")
    if not math.isfinite(args.timeout_seconds) or not 0 < args.timeout_seconds <= 3600:
        parser.error("--timeout-seconds must be between 0 and 3600")
    if not math.isfinite(args.index_timeout_seconds) or not 0 < args.index_timeout_seconds <= 3600:
        parser.error("--index-timeout-seconds must be between 0 and 3600")

    stage = "Connect to localhost:27017 / siem_db"
    writes_started = False

    def progress(message):
        nonlocal stage, writes_started
        stage = message
        if message.startswith("Write batch:"):
            writes_started = True
        print(f"[{datetime.now().isoformat(timespec='seconds')}] {message}", file=sys.stderr, flush=True)

    try:
        progress(f"Mode: {'PREPARE INDEX ONLY' if args.prepare_index else 'WRITE' if args.write else 'DRY RUN (no writes)'}; "
                 f"database request/page limit={args.timeout_seconds:g}s")
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
                                              index_timeout=args.index_timeout_seconds,
                                              day=args.day, offset=args.offset, limit=args.limit)
        print(json.dumps(result, indent=2), flush=True)
        return 0
    except KeyboardInterrupt:
        status = ("Copies may be partial; rerun to resume safely." if writes_started
                  else "No copies were written by this run.")
        print(f"ERROR: Interrupted during {stage}. {status}", file=sys.stderr, flush=True)
        return 130
    except Exception as exc:
        print(f"ERROR during {stage}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        if args.write:
            print("Copies may be partial; no deletion was performed. Rerun to resume."
                  if writes_started else "No copies were written by this run; validation did not finish.",
                  file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
