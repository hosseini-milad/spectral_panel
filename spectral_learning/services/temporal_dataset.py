from collections import Counter
from datetime import datetime

from mongoengine import get_connection
from pymongo import ReplaceOne

from ..repositories.data_repository import SecurityDataRepository


COLLECTION_NAME = "hierarchical_temporal_data"
EXCLUDED_FEATURES = {
    "_id",
    "source_file",
    "original_id",
    "created_at",
    "label",
    # This is a min-max normalized feature in the source collection, not time.
    "timestamp",
}
TIME_FORMATS = (
    "%d/%m/%Y %I:%M:%S %p",
    "%d/%m/%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
)


def parse_event_time(value):
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Unsupported or empty timestamp: {value!r}")

    value = value.strip()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        pass

    for time_format in TIME_FORMATS:
        try:
            return datetime.strptime(value, time_format)
        except ValueError:
            continue
    raise ValueError(f"Unsupported timestamp format: {value!r}")


def make_time_windows(event_time, source_file):
    minute_start = event_time.replace(second=0, microsecond=0)
    hour_start = event_time.replace(minute=0, second=0, microsecond=0)
    day_start = event_time.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "minute": {
            "key": f"{source_file}|minute|{minute_start.isoformat()}",
            "start": minute_start,
        },
        "hour": {
            "key": f"{source_file}|hour|{hour_start.isoformat()}",
            "start": hour_start,
        },
        "day": {
            "key": f"{source_file}|day|{day_start.isoformat()}",
            "start": day_start,
        },
    }


def _build_records(source_file):
    normalized = SecurityDataRepository.get_normalized_records(source_file)
    raw = SecurityDataRepository.get_collection_records("security_data", source_file)
    sampled = SecurityDataRepository.get_collection_records("sampled_security_data", source_file)
    representatives = SecurityDataRepository.get_representatives(source_file)

    if not normalized:
        raise ValueError(f"No normalized records found for source_file={source_file!r}")

    raw_by_id = {str(record["_id"]): record for record in raw}
    sampled_by_raw_id = {}
    for record in sampled:
        raw_id = record.get("original_id")
        if raw_id is not None:
            sampled_by_raw_id[str(raw_id)] = record

    representative_by_sampled_id = {}
    for record in representatives:
        sampled_id = record.get("original_id")
        if sampled_id is not None:
            representative_by_sampled_id.setdefault(str(sampled_id), []).append(record)

    documents = []
    bad_links = Counter()
    bad_timestamps = []

    for record in normalized:
        raw_id = str(record.get("original_id", ""))
        raw_record = raw_by_id.get(raw_id)
        if not raw_id or raw_record is None:
            bad_links["normalized_to_raw"] += 1
            continue

        try:
            event_time = parse_event_time(raw_record.get("timestamp"))
        except ValueError as exc:
            if len(bad_timestamps) < 10:
                bad_timestamps.append({"raw_id": raw_id, "error": str(exc)})
            continue

        sampled_record = sampled_by_raw_id.get(raw_id)
        sampled_id = str(sampled_record["_id"]) if sampled_record else None
        representative_docs = representative_by_sampled_id.get(sampled_id, []) if sampled_id else []
        features = {
            key: value
            for key, value in record.items()
            if key not in EXCLUDED_FEATURES
        }

        documents.append({
            "_id": f"{source_file}:{record['_id']}",
            "source_file": source_file,
            "normalized_id": str(record["_id"]),
            "raw_id": raw_id,
            "sampled_id": sampled_id,
            "representative_node_indices": [
                item.get("node_index") for item in representative_docs
            ],
            "is_sampled": sampled_record is not None,
            "is_representative": bool(representative_docs),
            "event_time": event_time,
            "event_time_source": raw_record.get("timestamp"),
            "time_basis": "source_timezone_unspecified",
            "windows": make_time_windows(event_time, source_file),
            "label": record.get("label"),
            "raw_label": raw_record.get("label"),
            "features": features,
        })

    if bad_links or bad_timestamps or len(documents) != len(normalized):
        details = []
        if bad_links:
            details.append(f"invalid links: {dict(bad_links)}")
        if bad_timestamps:
            details.append(f"invalid timestamps (up to 10 shown): {bad_timestamps}")
        details.append(f"prepared {len(documents)} of {len(normalized)} normalized records")
        raise ValueError("; ".join(details))

    return documents


def build_hierarchical_temporal_dataset(source_file, batch_size=500):
    """Idempotently materialize event-level records with minute/hour/day keys."""
    documents = _build_records(source_file)
    collection = get_connection(alias="default")["siem_db"][COLLECTION_NAME]

    collection.create_index([("source_file", 1), ("event_time", 1)])
    collection.create_index([("source_file", 1), ("windows.minute.key", 1)])
    collection.create_index([("source_file", 1), ("windows.hour.key", 1)])
    collection.create_index([("source_file", 1), ("windows.day.key", 1)])
    collection.create_index([("source_file", 1), ("label", 1)])

    expected_ids = [document["_id"] for document in documents]
    for start in range(0, len(documents), batch_size):
        batch = documents[start : start + batch_size]
        collection.bulk_write(
            [ReplaceOne({"_id": document["_id"]}, document, upsert=True) for document in batch],
            ordered=False,
        )

    collection.delete_many({
        "source_file": source_file,
        "_id": {"$nin": expected_ids},
    })

    time_values = [document["event_time"] for document in documents]
    return {
        "source_file": source_file,
        "collection": COLLECTION_NAME,
        "record_count": len(documents),
        "label_distribution": dict(Counter(document["label"] for document in documents)),
        "sampled_count": sum(document["is_sampled"] for document in documents),
        "representative_count": sum(document["is_representative"] for document in documents),
        "time_min": min(time_values),
        "time_max": max(time_values),
        "window_counts": {
            scale: len({document["windows"][scale]["key"] for document in documents})
            for scale in ("minute", "hour", "day")
        },
        "time_basis": "source_timezone_unspecified",
    }
