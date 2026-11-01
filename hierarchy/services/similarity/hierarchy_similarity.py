"""
Independent layer-2 similarity module.

Three equally important families:
    combined = (numeric + categorical + behavioral) / 3

No labels, attack classifications, threat scores, IP addresses, or raw port
numbers are used. Numeric inputs must already be normalized to [0, 1].
Missing values are excluded from pairwise denominators, never silently
replaced with zero.

This module is independent: it does not modify ingestion, MongoDB, or the
existing hierarchy graph builder.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np


NUMERIC_FIELDS = (
    "bytes",
    "bytes_per_packet",
    "bytes_per_sec",
    "duration_s",
    "packets",
    "packets_per_sec",
    "iat_mean",
    "iat_std",
    "iat_cv",
    "payload_entropy",
)

CATEGORICAL_FIELDS = (
    "protocol",
    "src_port_category",
    "dst_port_category",
    "flow_duration_class",
)

BEHAVIOR_FLAG_FIELDS = (
    "flag_ack",
    "flag_syn",
    "flag_fin",
    "flag_psh",
    "flag_rst",
    "flag_urg",
)

BEHAVIOR_CATEGORICAL_FIELDS = ()

EXCLUDED_FIELDS = frozenset({
    "_id", "original_id", "src_ip", "dst_ip", "src_port", "dst_port",
    "label", "label_binary", "attack_type", "attack_category",
    "behavioral_flags", "confidence", "evidence_source", "mitre_tactic",
    "mitre_technique", "threat_intel_score", "zeek_available",
    "source_type", "type", "flow_file", "source_file", "source_day",
    "date", "window_start", "flow_start", "row_index",
    "normalization_version", "normalization_method",
})


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, (bool, np.bool_)):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _category(value: Any) -> Any | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return value


def _numeric_similarity(a, b, fields, require_unit_interval=True):
    scores, used = [], []
    for field in fields:
        x, y = _number(a.get(field)), _number(b.get(field))
        if x is None or y is None:
            continue
        if require_unit_interval and not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError(
                f"{field!r} must be normalized to [0, 1]; got {x} and {y}"
            )
        scores.append(max(0.0, 1.0 - abs(x - y)))
        used.append(field)
    return (float(np.mean(scores)) if scores else None, len(scores), used)


def _categorical_similarity(a, b, fields):
    scores, used = [], []
    for field in fields:
        x, y = _category(a.get(field)), _category(b.get(field))
        if x is None or y is None:
            continue
        scores.append(1.0 if x == y else 0.0)
        used.append(field)
    return (float(np.mean(scores)) if scores else None, len(scores), used)


def _behavioral_similarity(a, b, flag_fields, category_fields):
    # Jaccard over active flags prevents shared zero flags dominating.
    active_a, active_b, observed = set(), set(), []
    for field in flag_fields:
        x, y = _number(a.get(field)), _number(b.get(field))
        if x is None or y is None:
            continue
        observed.append(field)
        if x != 0:
            active_a.add(field)
        if y != 0:
            active_b.add(field)

    if not observed:
        flag_score = None
    else:
        union = active_a | active_b
        flag_score = (
            1.0 if not union else len(active_a & active_b) / len(union)
        )

    category_scores, category_used = [], []
    for field in category_fields:
        x, y = _category(a.get(field)), _category(b.get(field))
        if x is None or y is None:
            continue
        category_scores.append(1.0 if x == y else 0.0)
        category_used.append(field)

    parts = []
    if flag_score is not None:
        parts.append(flag_score)
    if category_scores:
        parts.append(float(np.mean(category_scores)))

    score = float(np.mean(parts)) if parts else None
    return score, {
        "flag_jaccard": flag_score,
        "flag_fields_compared": observed,
        "active_flags_a": sorted(active_a),
        "active_flags_b": sorted(active_b),
        "behavior_category_similarity": (
            float(np.mean(category_scores)) if category_scores else None
        ),
        "behavior_category_fields_compared": category_used,
    }


def pair_similarity(
    record_a: Mapping[str, Any],
    record_b: Mapping[str, Any],
    *,
    numeric_fields=NUMERIC_FIELDS,
    categorical_fields=CATEGORICAL_FIELDS,
    behavior_flag_fields=BEHAVIOR_FLAG_FIELDS,
    behavior_categorical_fields=BEHAVIOR_CATEGORICAL_FIELDS,
    require_unit_interval=True,
) -> dict[str, Any]:
    """Return numeric, categorical, behavioral, and combined similarities."""
    numeric, n_count, n_used = _numeric_similarity(
        record_a, record_b, numeric_fields, require_unit_interval
    )
    categorical, c_count, c_used = _categorical_similarity(
        record_a, record_b, categorical_fields
    )
    behavioral, behavior_details = _behavioral_similarity(
        record_a, record_b, behavior_flag_fields, behavior_categorical_fields
    )

    available = [
        score for score in (numeric, categorical, behavioral)
        if score is not None
    ]
    combined = float(np.mean(available)) if available else None

    return {
        "numeric_similarity": numeric,
        "categorical_similarity": categorical,
        "behavioral_similarity": behavioral,
        "combined_similarity": combined,
        "families_compared": len(available),
        "expected_families": 3,
        "feature_counts": {
            "numeric": n_count,
            "categorical": c_count,
            "behavior_flags": len(behavior_details["flag_fields_compared"]),
            "behavior_categories": len(
                behavior_details["behavior_category_fields_compared"]
            ),
        },
        "features_compared": {
            "numeric": n_used,
            "categorical": c_used,
            **behavior_details,
        },
    }


def build_similarity_edges(
    records: Sequence[Mapping[str, Any]],
    *,
    threshold=0.85,
    block_size=128,
    id_field="_id",
    require_all_families=True,
) -> list[dict[str, Any]]:
    """
    Exhaustively compare records and return edges at/above threshold.
    Diagnostic O(N^2) implementation; initially use on representative subsets.
    """
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    if block_size < 1:
        raise ValueError("block_size must be >= 1")

    edges = []
    n = len(records)
    for block_start in range(0, n, block_size):
        block_stop = min(n, block_start + block_size)
        for i in range(block_start, block_stop):
            for j in range(i + 1, n):
                result = pair_similarity(records[i], records[j])
                if result["combined_similarity"] is None:
                    continue
                if require_all_families and result["families_compared"] != 3:
                    continue
                if result["combined_similarity"] < threshold:
                    continue
                edges.append({
                    "source_index": i,
                    "target_index": j,
                    "source_id": (
                        str(records[i][id_field])
                        if records[i].get(id_field) is not None else None
                    ),
                    "target_id": (
                        str(records[j][id_field])
                        if records[j].get(id_field) is not None else None
                    ),
                    "weight": result["combined_similarity"],
                    "numeric_similarity": result["numeric_similarity"],
                    "categorical_similarity": result["categorical_similarity"],
                    "behavioral_similarity": result["behavioral_similarity"],
                    "families_compared": result["families_compared"],
                })
    return edges


def feature_schema_report(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Report missing rates and unique counts for the module's feature schema."""
    groups = {
        "numeric": NUMERIC_FIELDS,
        "categorical": CATEGORICAL_FIELDS,
        "behavior_flags": BEHAVIOR_FLAG_FIELDS,
        "behavior_categorical": BEHAVIOR_CATEGORICAL_FIELDS,
    }
    report = {"record_count": len(records), "groups": {}}
    for group, fields in groups.items():
        report["groups"][group] = {}
        for field in fields:
            vals = [_category(row.get(field)) for row in records]
            observed = [v for v in vals if v is not None]
            report["groups"][group][field] = {
                "observed": len(observed),
                "missing": len(records) - len(observed),
                "missing_ratio": (
                    (len(records) - len(observed)) / len(records)
                    if records else 0.0
                ),
                "unique_count": len({repr(v) for v in observed}),
            }
    report["excluded_fields"] = sorted(EXCLUDED_FIELDS)
    return report


if __name__ == "__main__":
    # Synthetic smoke test; no project data or database is accessed.
    a = {
        "bytes": 0.20, "bytes_per_packet": 0.30, "bytes_per_sec": 0.10,
        "duration_s": 0.0, "packets": 0.10, "packets_per_sec": 0.0,
        "iat_mean": 0.0, "iat_std": 0.0, "iat_cv": 0.0,
        "payload_entropy": 0.0, "protocol": "TCP",
        "src_port_category": "well-known", "dst_port_category": "registered",
        "flow_duration_class": "instant", "flag_ack": 1, "flag_syn": 0,
        "flag_fin": 0, "flag_psh": 0, "flag_rst": 0, "flag_urg": 0,
    }
    b = dict(a, bytes=0.22, flag_ack=0, flag_syn=1)
    print(pair_similarity(a, b))
