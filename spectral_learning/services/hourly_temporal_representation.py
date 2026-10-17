import re
from collections import Counter, defaultdict
from numbers import Real

from mongoengine import get_connection
from pymongo import ReplaceOne

from ingestion.models.dataset_metadata import DatasetMetadata
from ingestion.models.graph_representative import GraphRepresentative
from ingestion.models.normalized_data import NormalizedSecurityData
from ingestion.models.raw_data import RawSecurityData
from ingestion.models.sampled_data import SampledSecurityData


TEMPORAL_COLLECTION = "hierarchical_temporal_data"
WINDOW_COLLECTION = "hierarchical_temporal_windows"
TIME_BASIS = "ordinal_source_file_hour_v1"
REPRESENTATION_VERSION = "ordinal_hour_hierarchy_v1"


def _source_number(source_file):
    match = re.search(r"\d+", source_file)
    return int(match.group()) if match else 0


def _source_files():
    return sorted(
        {
            item.source_file
            for item in DatasetMetadata.objects.only("source_file")
            if item.source_file
        },
        key=lambda source: (_source_number(source), source),
    )


def build_hourly_temporal_representation(batch_size=500):
    """Persist event-level rows and hour/day/sequence windows without fake timestamps."""
    sources = _source_files()
    if not sources:
        raise ValueError("No source files found in dataset metadata")

    # Validate the sources before writing so a missing source/link does not leave
    # a partially rebuilt temporal dataset.
    counts = {}
    for source_file in sources:
        normalized_count = NormalizedSecurityData.objects(source_file=source_file).count()
        raw_count = RawSecurityData.objects(source_file=source_file).count()
        if normalized_count == 0 or normalized_count != raw_count:
            raise ValueError(
                f"{source_file}: expected matching non-zero raw/normalized counts; "
                f"raw={raw_count}, normalized={normalized_count}"
            )
        counts[source_file] = normalized_count

    database = get_connection(alias="default")["siem_db"]
    temporal = database[TEMPORAL_COLLECTION]
    windows_collection = database[WINDOW_COLLECTION]
    temporal.create_index([("source_file", 1), ("hour_index", 1)])
    temporal.create_index([("sequence_key", 1), ("hour_index", 1)])
    temporal.create_index([("windows.hour.key", 1)])
    windows_collection.create_index([("level", 1), ("hour_index", 1)])

    window_docs = []
    total_records = 0
    total_sampled = 0
    total_representatives = 0
    for hour_index, source_file in enumerate(sources, start=1):
        raw_by_id = {
            str(item["_id"]): item
            for item in RawSecurityData.objects(source_file=source_file).as_pymongo()
        }
        sampled_by_raw_id = {
            str(item.get("original_id")): item
            for item in SampledSecurityData.objects(source_file=source_file).as_pymongo()
            if item.get("original_id") is not None
        }
        representatives_by_sampled_id = defaultdict(list)
        for item in GraphRepresentative.objects(source_file=source_file).as_pymongo():
            if item.get("original_id") is not None:
                representatives_by_sampled_id[str(item["original_id"])].append(item)

        hour_key = f"ordinal-day-{(hour_index - 1) // 24 + 1:02d}:hour-{(hour_index - 1) % 24 + 1:02d}"
        day_index = (hour_index - 1) // 24 + 1
        day_key = f"ordinal-day-{day_index:02d}"
        sequence_key = "ordinal-sequence-01"
        event_documents = []
        label_counts = Counter()
        raw_label_counts = Counter()
        feature_sums = Counter()
        feature_observations = Counter()
        sampled_count = 0
        representative_count = 0

        normalized_cursor = NormalizedSecurityData.objects(source_file=source_file).as_pymongo()
        for normalized in normalized_cursor:
            normalized_id = str(normalized["_id"])
            raw_id = str(normalized.get("original_id", ""))
            raw = raw_by_id.get(raw_id)
            if raw is None:
                raise ValueError(f"Missing raw link for {source_file}, normalized_id={normalized_id}")

            sampled = sampled_by_raw_id.get(raw_id)
            sampled_id = str(sampled["_id"]) if sampled else None
            selected = representatives_by_sampled_id.get(sampled_id, []) if sampled_id else []
            label = normalized.get("label")
            raw_label = raw.get("label")
            label_counts[str(label)] += 1
            if raw_label is not None:
                raw_label_counts[str(raw_label)] += 1

            features = {
                key: value
                for key, value in normalized.items()
                if key not in {"_id", "source_file", "created_at", "original_id", "label"}
            }
            for key, value in features.items():
                if isinstance(value, Real) and not isinstance(value, bool):
                    feature_sums[key] += float(value)
                    feature_observations[key] += 1

            is_representative = bool(selected)
            sampled_count += sampled is not None
            representative_count += is_representative
            event_documents.append({
                "_id": f"{source_file}:{normalized_id}",
                "representation_version": REPRESENTATION_VERSION,
                "time_basis": TIME_BASIS,
                "source_file": source_file,
                "normalized_id": normalized_id,
                "raw_id": raw_id,
                "sampled_id": sampled_id,
                "representative_node_indices": [item.get("node_index") for item in selected],
                "is_sampled": sampled is not None,
                "is_representative": is_representative,
                "hour_index": hour_index,
                "day_index": day_index,
                "sequence_key": sequence_key,
                "windows": {
                    "hour": {"key": hour_key, "index": hour_index, "source_file": source_file},
                    "day": {"key": day_key, "index": day_index},
                    "sequence": {"key": sequence_key, "index": 1},
                },
                "label": label,
                "raw_label": raw_label,
                "features": features,
            })

        expected = counts[source_file]
        if len(event_documents) != expected:
            raise ValueError(
                f"{source_file}: built {len(event_documents)} of {expected} temporal records"
            )

        expected_ids = [item["_id"] for item in event_documents]
        for start in range(0, len(event_documents), batch_size):
            batch = event_documents[start : start + batch_size]
            temporal.bulk_write(
                [ReplaceOne({"_id": item["_id"]}, item, upsert=True) for item in batch],
                ordered=False,
            )
        temporal.delete_many({
            "source_file": source_file,
            "representation_version": REPRESENTATION_VERSION,
            "_id": {"$nin": expected_ids},
        })

        total_records += len(event_documents)
        total_sampled += sampled_count
        total_representatives += representative_count
        window_docs.append({
            "_id": hour_key,
            "representation_version": REPRESENTATION_VERSION,
            "level": "hour",
            "time_basis": TIME_BASIS,
            "hour_index": hour_index,
            "day_index": day_index,
            "sequence_key": sequence_key,
            "window_key": hour_key,
            "source_file": source_file,
            "record_count": len(event_documents),
            "sampled_count": sampled_count,
            "representative_count": representative_count,
            "label_counts": dict(label_counts),
            "raw_label_counts": dict(raw_label_counts),
            "mean_normalized_features": {
                key: float(value / feature_observations[key])
                for key, value in feature_sums.items()
                if feature_observations[key]
            },
            "window_start": None,
            "contains_real_event_time": False,
        })

    by_day = defaultdict(list)
    for item in window_docs:
        by_day[item["day_index"]].append(item)
    for day_index, day_windows in by_day.items():
        day_key = f"ordinal-day-{day_index:02d}"
        window_docs.append({
            "_id": day_key,
            "representation_version": REPRESENTATION_VERSION,
            "level": "day",
            "time_basis": TIME_BASIS,
            "day_index": day_index,
            "sequence_key": "ordinal-sequence-01",
            "child_window_keys": [item["window_key"] for item in day_windows],
            "record_count": sum(item["record_count"] for item in day_windows),
            "sampled_count": sum(item["sampled_count"] for item in day_windows),
            "representative_count": sum(item["representative_count"] for item in day_windows),
            "label_counts": dict(sum((Counter(item["label_counts"]) for item in day_windows), Counter())),
            "window_start": None,
            "contains_real_event_time": False,
        })

    window_docs.append({
        "_id": "ordinal-sequence-01",
        "representation_version": REPRESENTATION_VERSION,
        "level": "sequence",
        "time_basis": TIME_BASIS,
        "sequence_key": "ordinal-sequence-01",
        "child_window_keys": [item["_id"] for item in window_docs if item["level"] == "day"],
        "hour_count": len(sources),
        "record_count": total_records,
        "sampled_count": total_sampled,
        "representative_count": total_representatives,
        "label_counts": dict(sum((Counter(item["label_counts"]) for item in window_docs if item["level"] == "day"), Counter())),
        "window_start": None,
        "contains_real_event_time": False,
    })

    expected_window_ids = [item["_id"] for item in window_docs]
    windows_collection.bulk_write(
        [ReplaceOne({"_id": item["_id"]}, item, upsert=True) for item in window_docs],
        ordered=False,
    )
    windows_collection.delete_many({
        "representation_version": REPRESENTATION_VERSION,
        "_id": {"$nin": expected_window_ids},
    })

    return {
        "source_count": len(sources),
        "event_record_count": total_records,
        "hour_window_count": sum(item["level"] == "hour" for item in window_docs),
        "day_window_count": sum(item["level"] == "day" for item in window_docs),
        "sequence_window_count": sum(item["level"] == "sequence" for item in window_docs),
        "sampled_record_count": total_sampled,
        "representative_record_count": total_representatives,
        "time_basis": TIME_BASIS,
        "note": "No minute windows or real timestamps are inferred from these files.",
    }
