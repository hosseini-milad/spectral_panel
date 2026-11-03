"""Copy mixed raw records into a processing day; this is NOT a normal baseline.

Only source_day changes. Event timestamps, labels and raw features stay intact.
Interrupted writes are retained and can be resumed; no records are deleted.
"""

from copy import deepcopy
from datetime import date, timedelta
from hashlib import sha256
from tempfile import TemporaryFile
from uuid import uuid4

from bson import BSON, ObjectId, decode_file_iter
from pymongo import UpdateOne


START = date(2026, 6, 21)
TARGET = "2026-06-20"
DAY_COUNT = 10
BLOCK_SIZE = 20_000
BATCH_SIZE = 1000
VERSION = "mixed-raw-v1"


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


def build_artificial_day(db, dry_run=True):
    collection = db.security_data
    plan = []
    for index in range(DAY_COUNT):
        day = (START + timedelta(days=index)).isoformat()
        plan.append({"source_day": day, "skip": index * BLOCK_SIZE,
                     "take": BLOCK_SIZE,
                     "available": collection.count_documents(source_query(day))})
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
            cursor = (collection.find(source_query(row["source_day"]))
                      .sort("_id", 1).skip(row["skip"]).limit(row["take"]))
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
            if count != row["take"]:
                raise ValueError("Source selection changed; no copies were written.")

        # Validate every existing ID before any writes. Original/unknown target
        # records are preserved; incompatible copies stop the operation.
        for batch in _batches(spool):
            wanted = {record["_id"]: record for record in batch}
            for saved in collection.find({"_id": {"$in": list(wanted)}}):
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
                inserted += collection.bulk_write(operations, ordered=True).upserted_count
            verified = 0
            for batch in _batches(spool):
                wanted = {record["_id"]: record for record in batch}
                for saved in collection.find({"_id": {"$in": list(wanted)}}):
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


if __name__ == "__main__":
    import argparse
    import json
    from pymongo import MongoClient

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Write copies (default: inspect only)")
    args = parser.parse_args()
    with MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=5000) as client:
        print(json.dumps(build_artificial_day(client["siem_db"], dry_run=not args.write), indent=2))
