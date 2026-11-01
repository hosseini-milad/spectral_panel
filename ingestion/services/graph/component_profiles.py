"""Detailed all-node and representative profiles retained from the layer-1 patch."""
import math
import numpy as np

# Explicit allowlist for component summaries. These are numeric/behavioral
# flow features only; labels, attack descriptors, IPs and threat scores are excluded.
# Explicit, unsupervised feature schema for component profiles.
# Threat intelligence, labels, attack descriptors, IPs, ports-as-identifiers,
# timestamps and provenance fields are intentionally excluded.
COMPONENT_EXCLUDED_FIELDS = {
    "label", "label_binary", "source_label", "source_label_binary",
    "source_label_multiclass", "attack_type", "attack_category",
    "confidence", "evidence_source", "mitre_tactic", "mitre_technique",
    "threat_intel_score", "src_ip", "dst_ip", "src_port", "dst_port",
    "country", "date", "flow_start", "window_start", "flow_file",
    "source_file", "source_path", "source_day", "source_type", "type",
    "original_id", "row_index", "behavioral_flags", "dns_query",
}

# Categorical descriptors retained only as descriptive profiles, never as
# attack labels or high-cardinality identifiers.
COMPONENT_CATEGORICAL_FIELDS = (
    "protocol", "src_port_category", "dst_port_category",
    "flow_duration_class",
)

# Legacy representative-only summary fields retained for backward compatibility.
COMPONENT_MEAN_FIELDS = (
    "bytes", "bytes_per_packet", "bytes_per_sec",
    "duration_s", "packets", "packets_per_sec",
    "flag_ack", "flag_syn", "flag_fin", "flag_psh", "flag_rst", "flag_urg",
)

COMPONENT_BEHAVIOR_FIELDS = (
    "flag_ack", "flag_syn", "flag_fin", "flag_psh", "flag_rst", "flag_urg",
    "is_encrypted_port", "is_syn_only", "proto_icmp", "proto_tcp", "proto_udp",
)


def _finite_numeric(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _component_feature_summary(representative_docs):
    """Mean/std of allow-listed features across this component's reps."""
    means, stds, counts = {}, {}, {}
    for field in COMPONENT_MEAN_FIELDS:
        values = [
            number
            for doc in representative_docs
            if (number := _finite_numeric(doc.get(field))) is not None
        ]
        counts[field] = len(values)
        means[field] = float(np.mean(values)) if values else None
        stds[field] = float(np.std(values)) if values else None
    return means, stds, counts


def _profile_numeric_matrix(matrix, indices, feature_fields):
    """Summarize allowed numeric dimensions over the supplied node indices."""
    result = {}
    if matrix is None or not feature_fields:
        return result

    arr = np.asarray(matrix, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != len(feature_fields):
        return result

    valid_indices = [int(i) for i in indices if 0 <= int(i) < arr.shape[0]]
    if not valid_indices:
        return result

    block = arr[valid_indices]
    for column, field in enumerate(feature_fields):
        if field in COMPONENT_EXCLUDED_FIELDS:
            continue
        values = block[:, column]
        values = values[np.isfinite(values)]
        if values.size == 0:
            result[field] = {"count": 0}
            continue
        result[field] = {
            "count": int(values.size),
            "mean": float(np.mean(values)),
            "std": float(np.std(values)),
            "min": float(np.min(values)),
            "q25": float(np.percentile(values, 25)),
            "median": float(np.percentile(values, 50)),
            "q75": float(np.percentile(values, 75)),
            "max": float(np.max(values)),
        }
    return result


def _profile_categorical(docs):
    """Frequency profiles for a small, explicit non-label categorical allowlist."""
    profile = {}
    for field in COMPONENT_CATEGORICAL_FIELDS:
        counts = {}
        valid = 0
        for doc in docs:
            value = doc.get(field)
            if value is None or value == "":
                continue
            # Bound cardinality to avoid turning arbitrary strings into features.
            key = str(value)[:80]
            counts[key] = counts.get(key, 0) + 1
            valid += 1
        profile[field] = {
            "count": int(valid),
            "categories": {
                key: {
                    "count": int(count),
                    "fraction": float(count / valid) if valid else 0.0,
                }
                for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
            },
        }
    return profile


def _profile_behavior(docs):
    """Prevalence of approved binary/behavioral flags; no label fields."""
    result = {}
    for field in COMPONENT_BEHAVIOR_FIELDS:
        values = []
        for doc in docs:
            number = _finite_numeric(doc.get(field))
            if number is not None:
                values.append(number)
        result[field] = {
            "count": len(values),
            "present_count": int(sum(value > 0.5 for value in values)),
            "prevalence": (
                float(sum(value > 0.5 for value in values) / len(values))
                if values else None
            ),
        }
    return result


def _component_profile_payload(
    member_indices,
    representative_indices,
    docs,
    feature_matrix,
    feature_fields,
    raw_docs_by_id=None,
):
    member_docs = [docs[index] for index in member_indices]
    representative_docs = [docs[index] for index in representative_indices]
    raw_docs_by_id = raw_docs_by_id or {}
    member_raw_docs = [
        raw_docs_by_id[str(doc.get("_id"))]
        for doc in member_docs
        if str(doc.get("_id")) in raw_docs_by_id
    ]
    representative_raw_docs = [
        raw_docs_by_id[str(doc.get("_id"))]
        for doc in representative_docs
        if str(doc.get("_id")) in raw_docs_by_id
    ]

    node_numeric = _profile_numeric_matrix(
        feature_matrix, member_indices, feature_fields
    )
    representative_numeric = _profile_numeric_matrix(
        feature_matrix, representative_indices, feature_fields
    )

    # Fallback for legacy graph metadata without a stored feature matrix.
    if not node_numeric:
        fallback_fields = [
            field for field in COMPONENT_MEAN_FIELDS
            if field not in COMPONENT_EXCLUDED_FIELDS
        ]
        for field in fallback_fields:
            values = [
                number for doc in member_docs
                if (number := _finite_numeric(doc.get(field))) is not None
            ]
            if values:
                arr = np.asarray(values, dtype=np.float64)
                node_numeric[field] = {
                    "count": int(arr.size),
                    "mean": float(np.mean(arr)),
                    "std": float(np.std(arr)),
                    "min": float(np.min(arr)),
                    "q25": float(np.percentile(arr, 25)),
                    "median": float(np.percentile(arr, 50)),
                    "q75": float(np.percentile(arr, 75)),
                    "max": float(np.max(arr)),
                }

    return {
        "node_feature_profile": node_numeric,
        "representative_feature_profile": representative_numeric,
        "categorical_profile": _profile_categorical(member_raw_docs),
        "representative_categorical_profile": _profile_categorical(representative_raw_docs),
        "behavioral_profile": _profile_behavior(member_docs),
    }


