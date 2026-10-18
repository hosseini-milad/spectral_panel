def normalize_dict(d):
    if not d:
        return {}

    vals = list(d.values())
    min_v = min(vals)
    max_v = max(vals)

    if max_v - min_v == 0:
        return {k: 0.0 for k in d}

    return {
        k: (v - min_v) / (max_v - min_v)
        for k, v in d.items()
    }


def compute_score(centralities, anomaly_scores=None):
    eigen = normalize_dict(centralities["eigenvector"])
    degree = normalize_dict(centralities["degree"])
    between = normalize_dict(
        centralities.get("betweenness", {})
    )

    if anomaly_scores:
        anomaly = normalize_dict(anomaly_scores)
    else:
        anomaly = {k: 0.0 for k in eigen}

    score = {}

    for node in eigen:
        score[node] = (
            0.2 * eigen.get(node, 0) +
            0.1 * degree.get(node, 0) +
            0.3 * between.get(node, 0) +
            0.3 * anomaly.get(node, 0)
        )

    return score