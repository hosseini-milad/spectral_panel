from collections import Counter

from ..repositories.data_repository import SecurityDataRepository


EXCLUDED_FIELDS = {
    "_id",
    "source_file",
    "original_id",
    "created_at",
    "label",
}


def validate_normalized_range(records):
    """
    Check numeric feature values.

    All numeric model features are expected to be in [0, 1].
    """

    violations = []

    for record in records:

        record_id = str(record.get("_id"))

        for key, value in record.items():

            if key in EXCLUDED_FIELDS:
                continue

            if isinstance(value, bool):
                continue

            if isinstance(value, (int, float)):

                if value < 0 or value > 1:
                    violations.append(
                        {
                            "record_id": record_id,
                            "feature": key,
                            "value": value,
                        }
                    )

    return violations


def _validate_id_links(records, field, target_ids, link_name):
    violations = []
    seen = Counter()

    for record in records:
        value = record.get(field)
        source_id = str(record.get("_id", ""))
        if value is None or value == "":
            violations.append({"record_id": source_id, "reason": f"missing_{field}"})
            continue
        value = str(value)
        seen[value] += 1
        if value not in target_ids:
            violations.append({"record_id": source_id, field: value, "reason": f"{link_name}_not_found"})

    for value, count in seen.items():
        if count > 1:
            violations.append({field: value, "count": count, "reason": f"duplicate_{field}"})
    return violations


def validate_representative_links(representatives, sampled_records, raw_records):
    """Validate representative -> sampled -> raw security record links."""
    sampled_ids = {str(record["_id"]) for record in sampled_records}
    raw_ids = {str(record["_id"]) for record in raw_records}
    return {
        "representative_to_sampled": _validate_id_links(
            representatives, "original_id", sampled_ids, "sampled_record"
        ),
        "sampled_to_raw": _validate_id_links(
            sampled_records, "original_id", raw_ids, "raw_record"
        ),
    }


def collect_feature_schema(records):
    """
    Build the feature schema dynamically from normalized data.
    """

    feature_keys = set()

    for record in records:

        for key in record.keys():

            if key not in EXCLUDED_FIELDS:
                feature_keys.add(key)

    return sorted(feature_keys)


def _label_counts(records):
    return Counter(
        record.get("label")
        for record in records
        if record.get("label") is not None
    )


def _class_retention(numerator, denominator):
    return {
        label: round(numerator.get(label, 0) / count, 6) if count else None
        for label, count in denominator.items()
    }


def _proportional_class_counts(class_counts, total):
    """Allocate a target total across classes using largest remainders."""
    population = sum(class_counts.values())
    if not population or not total:
        return {label: 0 for label in class_counts}

    exact = {
        label: total * count / population
        for label, count in class_counts.items()
    }
    allocated = {label: int(value) for label, value in exact.items()}
    remaining = total - sum(allocated.values())
    order = sorted(
        class_counts,
        key=lambda label: (exact[label] - allocated[label], str(label)),
        reverse=True,
    )
    for label in order[:remaining]:
        allocated[label] += 1
    return allocated


def summarize_dataset(normalized_records, representatives, sampled_records, raw_records):
    normalized_labels = _label_counts(normalized_records)
    sampled_labels = _label_counts(sampled_records)
    representative_labels = _label_counts(representatives)
    # Representatives should preserve the source class prior. The sampled
    # collection may itself be class-balanced/oversampled, so it is not a
    # reliable denominator for this check.
    expected_representative_labels = _proportional_class_counts(
        normalized_labels, len(representatives)
    )

    return {
        "normalized_count": len(normalized_records),
        "sampled_count": len(sampled_records),
        "raw_count": len(raw_records),
        "representative_count": len(representatives),
        "feature_count": len(
            collect_feature_schema(normalized_records)
        ),
        "label_distribution": {
            "normalized": dict(normalized_labels),
            # Raw labels are retained separately: this collection uses
            # multiclass text labels while downstream collections use 0/1.
            "raw_multiclass": dict(_label_counts(raw_records)),
            "sampled": dict(sampled_labels),
            "representatives": dict(representative_labels),
            "representatives_expected_from_source_ratio": expected_representative_labels,
        },
        "sampled_fraction_of_normalized_by_label": dict(
            _class_retention(sampled_labels, normalized_labels)
        ),
        "representative_fraction_of_sampled_by_label": dict(
            _class_retention(representative_labels, sampled_labels)
        ),
        "representative_label_deviation_from_expected": {
            label: representative_labels.get(label, 0) - expected
            for label, expected in expected_representative_labels.items()
        },
    }


def validate_dataset(source_file=None):

    normalized_records = (
        SecurityDataRepository.get_normalized_records(
            source_file=source_file
        )
    )

    representatives = (
        SecurityDataRepository.get_representatives(
            source_file=source_file
        )
    )
    sampled_records = SecurityDataRepository.get_collection_records(
        "sampled_security_data", source_file=source_file
    )
    raw_records = SecurityDataRepository.get_collection_records(
        "security_data", source_file=source_file
    )

    range_violations = validate_normalized_range(
        normalized_records
    )

    link_violations = validate_representative_links(
        representatives, sampled_records, raw_records
    )

    expected_representative_labels = _proportional_class_counts(
        _label_counts(normalized_records), len(representatives)
    )
    representative_labels = _label_counts(representatives)
    class_balance_violations = [
        {
            "label": label,
            "actual": representative_labels.get(label, 0),
            "expected": expected,
            "deviation": representative_labels.get(label, 0) - expected,
        }
        for label, expected in expected_representative_labels.items()
        if abs(representative_labels.get(label, 0) - expected) > 1
    ]

    summary = summarize_dataset(
        normalized_records, representatives, sampled_records, raw_records
    )

    return {
        "summary": summary,
        "sampled_count": len(sampled_records),
        "raw_count": len(raw_records),
        "range_violations": range_violations,
        "link_violations": link_violations,
        "representative_class_balance_violations": class_balance_violations,
        "feature_schema": collect_feature_schema(
            normalized_records
        ),
    }
