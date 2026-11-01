import math


# Structural score only. Anomaly and external risk are passed separately to
# select_representatives so that they are not counted twice.
STRUCTURAL_WEIGHTS = {
    "eigenvector": 0.50,
    "degree": 0.20,
    "betweenness": 0.15,
}


def normalize_dict(values):
    """Min-max normalize finite values; invalid values become zero."""
    if not values:
        return {}

    clean = {}
    for key, value in values.items():
        try:
            number = float(value)
            clean[key] = number if math.isfinite(number) else 0.0
        except (TypeError, ValueError, OverflowError):
            clean[key] = 0.0

    low = min(clean.values())
    high = max(clean.values())
    span = high - low
    if span <= 0.0:
        return {key: 0.0 for key in clean}

    return {key: (value - low) / span for key, value in clean.items()}


def compute_score(centralities, anomaly_scores=None):
    """Compute structural importance only.

    `anomaly_scores` is retained in the signature for backward compatibility,
    but deliberately excluded: anomaly is supplied independently to
    `select_representatives`, where it contributes to the rarity/anomaly path.
    This prevents anomaly from being counted both here and during selection.
    """
    centralities = centralities or {}

    normalized = {
        name: normalize_dict(centralities.get(name, {}))
        for name in STRUCTURAL_WEIGHTS
    }

    # Use the union so a node is not silently dropped if one centrality map is
    # incomplete. Missing centrality values contribute zero.
    nodes = set()
    for values in normalized.values():
        nodes.update(values)

    if not nodes:
        return {}

    weight_total = sum(STRUCTURAL_WEIGHTS.values())
    if weight_total <= 0.0:
        return {node: 0.0 for node in nodes}

    score = {}
    for node in nodes:
        score[node] = sum(
            (weight / weight_total) * normalized[name].get(node, 0.0)
            for name, weight in STRUCTURAL_WEIGHTS.items()
        )

    return score
