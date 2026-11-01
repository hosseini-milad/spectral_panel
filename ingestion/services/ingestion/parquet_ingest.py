"""Store partitioned flow Parquet files as raw MongoDB security records."""

import hashlib
import math
import re
from collections import Counter
from datetime import date, datetime, time, timezone
from pathlib import Path

from bson import ObjectId
from mongoengine import get_connection


DATABASE_NAME = "siem_db"
COLLECTION_NAME = "security_data"
FILENAME_TIME = re.compile(r"nfcapd\.(\d{12})_", re.IGNORECASE)
LABELS = {"attacks": 1, "normal": 0}


def _type_family(pa, data_type):
    if pa.types.is_null(data_type):
        return "null"
    if pa.types.is_boolean(data_type):
        return "boolean"
    if pa.types.is_integer(data_type) or pa.types.is_floating(data_type) or pa.types.is_decimal(data_type):
        return "numeric"
    if pa.types.is_string(data_type) or pa.types.is_large_string(data_type):
        return "string"
    if pa.types.is_temporal(data_type):
        return "temporal"
    return "unsupported"


def _common_field_families(pa, files):
    families = {}
    for path in files:
        schema = __import__("pyarrow.parquet", fromlist=["read_schema"]).read_schema(path)
        for field in schema:
            families.setdefault(field.name, set()).add(_type_family(pa, field.type))
    common = {}
    for name, found in families.items():
        found.discard("null")
        if not found:
            common[name] = "unknown"
        elif len(found) == 1:
            common[name] = next(iter(found))
        else:
            common[name] = "incompatible"
    return common


def _clean(value, family):
    if value is None:
        return 0, True
    if isinstance(value, str) and not value.strip():
        return 0, True
    if family in {"incompatible", "unsupported", "unknown"}:
        return 0, True
    if family == "numeric":
        if isinstance(value, bool):
            return int(value), False
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return 0, True
        if not math.isfinite(number):
            return 0, True
        if isinstance(value, int):
            return value, False
        return number, False
    if family == "boolean":
        return (int(value), False) if isinstance(value, bool) else (0, True)
    if family == "string":
        return (value, False) if isinstance(value, str) else (0, True)
    if family == "temporal":
        if isinstance(value, datetime):
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value, False
        if isinstance(value, date):
            return datetime.combine(value, time.min, tzinfo=timezone.utc), False
        return 0, True
    return 0, True


def _label_for_path(path):
    for part in path.parts:
        if part.startswith("type="):
            source_type = part.split("=", 1)[1].lower()
            if source_type in LABELS:
                return source_type, LABELS[source_type]
            raise ValueError(f"Unsupported class partition {part!r} in {path}")
    raise ValueError(f"Expected a type=attacks or type=normal folder in {path}")


def _document_id(relative_path, row_index):
    key = f"{relative_path.as_posix()}:{row_index}".encode("utf-8")
    return ObjectId(hashlib.sha256(key).digest()[:12])


def _insert_unstored(collection, documents, totals):
    if not documents:
        return
    ids = [document["_id"] for document in documents]
    existing_ids = {
        item["_id"]
        for item in collection.find({"_id": {"$in": ids}}, {"_id": 1})
    }
    new_documents = [document for document in documents if document["_id"] not in existing_ids]
    if new_documents:
        collection.insert_many(new_documents, ordered=False)
    totals["records_inserted"] += len(new_documents)
    totals["records_already_present"] += len(existing_ids)


def ingest_parquet_directory(root, batch_size=3000, progress=None):
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("Parquet ingest requires pyarrow. Install it from requirements.txt.") from exc

    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"Parquet directory does not exist: {root}")
    files = sorted(root.rglob("*.parquet"), key=lambda item: item.as_posix().lower())
    if not files:
        raise ValueError(f"No .parquet files found in {root}")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    # Validate the partition label and file naming before writing any rows.
    source_types = {path: _label_for_path(path) for path in files}
    field_families = _common_field_families(pa, files)
    if "label" not in field_families:
        raise ValueError("Parquet files have no original label column to preserve")

    client = get_connection(alias="default")
    collection = client[DATABASE_NAME][COLLECTION_NAME]
    collection.create_index([("source_day", 1), ("label", 1)])
    collection.create_index([("flow_start", 1)])
    collection.create_index([("source_file", 1)])

    totals = Counter()
    zero_filled = Counter()
    incompatible_fields = sorted(name for name, family in field_families.items()
                                 if family in {"incompatible", "unsupported"})
    schema_fields = sorted(field_families)

    for file_number, path in enumerate(files, start=1):
        source_type, label = source_types[path]
        relative_path = path.relative_to(root)
        date_partition = next(
            (
                part.split("=", 1)[1]
                for part in path.parts
                if part.startswith("date=")
            ),
            None,
        )
        if date_partition is None:
            raise ValueError(
                f"Could not determine source_day from path: {path}"
            )
        time_match = FILENAME_TIME.search(path.name)
        window_start = datetime.strptime(time_match.group(1), "%Y%m%d%H%M").replace(
            tzinfo=timezone.utc
        ) if time_match else 0
        parquet_file = pq.ParquetFile(path)
        expected_rows = parquet_file.metadata.num_rows
        stored_rows = collection.count_documents({"source_file": path.name})
        if stored_rows == expected_rows:
            totals["records_processed"] += expected_rows
            totals["records_already_present"] += expected_rows
            totals[f"label_{label}"] += expected_rows
            totals["files"] += 1
            if progress and (file_number % 100 == 0 or file_number == len(files)):
                progress(file_number, len(files), totals["records_inserted"])
            continue
        row_offset = 0
        pending_documents = []

        for record_batch in parquet_file.iter_batches(batch_size=batch_size):
            for batch_record in record_batch.to_pylist():
                record = {}
                original_label = batch_record.get("label", 0)
                original_label_binary = batch_record.get("label_binary", 0)
                original_label_multiclass = batch_record.get("label_multiclass", 0)
                for field in schema_fields:
                    if field in {"label", "label_binary", "label_multiclass"}:
                        continue
                    value, was_zeroed = _clean(batch_record.get(field, 0), field_families[field])
                    record[field] = value
                    if was_zeroed:
                        zero_filled[field] += 1

                row_index = row_offset
                document = {
                    **record,
                    "_id": _document_id(relative_path, row_index),
                    "label": label,
                    "label_binary": label,
                    "source_label": _clean(original_label, field_families["label"])[0],
                    "source_label_binary": _clean(original_label_binary, field_families.get("label_binary", "unknown"))[0],
                    "source_label_multiclass": _clean(original_label_multiclass, field_families.get("label_multiclass", "unknown"))[0],
                    "source_type": source_type,
                    "type": source_type,
                    "source_day": date_partition,
                    "source_file": path.name,
                    "source_path": relative_path.as_posix(),
                    "row_index": row_index,
                    "window_start": window_start,
                }
                pending_documents.append(document)
                totals["records_processed"] += 1
                totals[f"label_{label}"] += 1
                row_offset += 1
                if len(pending_documents) >= batch_size:
                    if stored_rows:
                        _insert_unstored(collection, pending_documents, totals)
                    else:
                        collection.insert_many(pending_documents, ordered=False)
                        totals["records_inserted"] += len(pending_documents)
                    pending_documents.clear()
        if pending_documents:
            if stored_rows:
                _insert_unstored(collection, pending_documents, totals)
            else:
                collection.insert_many(pending_documents, ordered=False)
                totals["records_inserted"] += len(pending_documents)
        totals["files"] += 1
        if progress and (file_number % 100 == 0 or file_number == len(files)):
            progress(file_number, len(files), totals["records_inserted"])

    numeric_features = sorted(
        name for name, family in field_families.items()
        if family == "numeric" and name not in {
            "label", "label_binary", "label_multiclass", "threat_intel_score",
        }
    )
    return {
        "collection": COLLECTION_NAME,
        "database": DATABASE_NAME,
        "root": str(root),
        "files": totals["files"],
        "records_processed": totals["records_processed"],
        "records_inserted_this_run": totals["records_inserted"],
        "records_already_present": totals["records_already_present"],
        "normal_label_0": totals["label_0"],
        "attack_label_1": totals["label_1"],
        "schema_field_count": len(schema_fields),
        "numeric_feature_candidates": numeric_features,
        "numeric_feature_candidate_count": len(numeric_features),
        "incompatible_fields_zeroed": incompatible_fields,
        "zero_filled_value_counts": dict(sorted(zero_filled.items())),
        "normalization_performed": False,
        "graph_or_sampling_performed": False,
    }
