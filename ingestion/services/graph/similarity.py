import numpy as np
from scipy.spatial import cKDTree


def cosine_similarity_matrix(X):

    norm = np.linalg.norm(X, axis=1, keepdims=True)
    X_norm = X / (norm + 1e-10)

    return np.dot(X_norm, X_norm.T)


def build_cosine_sparse_knn(X, k=12, threshold=0.995, workers=-1, degree_cap=20,target_edges=None):
    """Build a sparse union-kNN cosine graph without an N x N matrix."""
    X = np.asarray(X, dtype=np.float32)
    if X.ndim != 2:
        raise ValueError("X must be a two-dimensional feature matrix.")
    if k < 1:
        raise ValueError("k must be positive.")
    if not -1.0 <= threshold <= 1.0:
        raise ValueError("threshold must be in [-1, 1].")
    n = X.shape[0]
    if n < 2:
        cap = 4 * k if degree_cap is None else degree_cap
        if cap < 1:
            raise ValueError('degree_cap must be positive.')
        return [], {
            'knn_union_candidates': 0, 'mutual_knn_candidates': 0,
            'duplicate_ring_edges': 0, 'similarity_quantiles': {},
            'threshold_edge_counts': {str(value): 0 for value in (.95, .99, .995, .999, .9995, .9999, .99995)},
            'degree_cap': int(cap), 'thresholded_edges_before_cap': 0,
            'nodes_without_qualifying_neighbors': n,
        }

    norms = np.linalg.norm(X, axis=1, keepdims=True)
    X_unit = np.divide(X, norms, out=np.zeros_like(X), where=norms > 1e-12)
    # For unit vectors, Euclidean nearest neighbors have the same ordering as
    # cosine similarity: ||x-y||^2 = 2 - 2*cos(x,y).
    tree = cKDTree(X_unit)
    neighbor_count = min(k + 1, n)
    distances, indices = tree.query(X_unit, k=neighbor_count, workers=workers)
    if neighbor_count == 1:
        distances = distances[:, None]
        indices = indices[:, None]

    neighbors = []
    for node_index, row in enumerate(indices):
        selected = [int(index) for index in row if int(index) != node_index]
        neighbors.append(set(selected[:k]))

    union_pairs = set()
    mutual_pairs = set()
    for left, row in enumerate(neighbors):
        for right in row:
            pair = (min(left, right), max(left, right))
            union_pairs.add(pair)
            if left in neighbors[right]:
                mutual_pairs.add(pair)

    # cKDTree may return the same few rows for thousands of exact duplicate
    # vectors. Connect each duplicate group as a ring so degree capping does
    # not leave otherwise identical records disconnected around one hub.
    _, duplicate_group, duplicate_counts = np.unique(
        X_unit, axis=0, return_inverse=True, return_counts=True
    )
    duplicate_order = np.argsort(duplicate_group, kind="stable")
    duplicate_pairs = set()
    duplicate_ring_edges = 0
    start = 0
    for group_id, count in enumerate(duplicate_counts):
        end = start + int(count)
        if count > 1:
            members = duplicate_order[start:end]
            for offset in range(len(members)):
                left = int(members[offset])
                right = int(members[(offset + 1) % len(members)])
                pair = (min(left, right), max(left, right))
                if pair[0] != pair[1] and pair not in union_pairs:
                    duplicate_ring_edges += 1
                if pair[0] != pair[1]:
                    union_pairs.add(pair)
                    duplicate_pairs.add(pair)
        start = end

    candidates = [
        (left, right, float(np.clip(np.dot(X_unit[left], X_unit[right]), -1.0, 1.0)))
        for left, right in union_pairs
    ]

    if candidates:
        values = np.asarray([edge[2] for edge in candidates], dtype=np.float64)
        quantiles = {
            str(q): float(np.quantile(values, q))
            for q in (0.1, 0.25, 0.5, 0.75, 0.9)
        }
    else:
        quantiles = {}
    thresholded = [edge for edge in candidates if edge[2] >= threshold]
    qualifying_degree = np.zeros(n, dtype=np.int32)
    for left, right, _ in thresholded:
        qualifying_degree[left] += 1
        qualifying_degree[right] += 1
    if degree_cap is None:
        degree_cap = 4 * k
    if degree_cap < 1:
        raise ValueError("degree_cap must be positive.")
    # First give low-choice nodes the best available qualifying edge so that
    # repeated/common records do not consume the whole degree budget as hubs.
    thresholded.sort(key=lambda edge: (-edge[2], edge[0], edge[1]))
    edges = []
    degree = np.zeros(n, dtype=np.int32)
    for left, right in sorted(duplicate_pairs):
        if degree[left] < degree_cap and degree[right] < degree_cap:
            similarity = float(np.clip(np.dot(X_unit[left], X_unit[right]), -1.0, 1.0))
            if similarity >= threshold:
                edges.append((left, right, similarity))
                degree[left] += 1
                degree[right] += 1
    selected_pairs = {(left, right) for left, right, _ in edges}
    candidate_neighbors = [[] for _ in range(n)]
    for left, right, similarity in thresholded:
        candidate_neighbors[left].append((similarity, right))
        candidate_neighbors[right].append((similarity, left))
    node_order = sorted(range(n), key=lambda node: (len(candidate_neighbors[node]), node))
    for node in node_order:
        if degree[node]:
            continue
        for similarity, neighbor in sorted(candidate_neighbors[node], reverse=True):
            if degree[node] < degree_cap and degree[neighbor] < degree_cap:
                left, right = min(node, neighbor), max(node, neighbor)
                edges.append((left, right, similarity))
                selected_pairs.add((left, right))
                degree[node] += 1
                degree[neighbor] += 1
                break

    # Fill remaining degree capacity with the strongest remaining edges.
    for left, right, similarity in thresholded:
        if (left, right) in selected_pairs:
            continue
        if degree[left] >= degree_cap or degree[right] >= degree_cap:
            continue
        edges.append((left, right, similarity))
        selected_pairs.add((left, right))
        degree[left] += 1
        degree[right] += 1

    threshold_counts = {
        str(value): int(sum(edge[2] >= value for edge in candidates))
        for value in (0.95, 0.99, 0.995, 0.999, 0.9995, 0.9999, 0.99995)
    }
    return edges, {
        "knn_union_candidates": len(candidates),
        "mutual_knn_candidates": len(mutual_pairs),
        "duplicate_ring_edges": duplicate_ring_edges,
        "similarity_quantiles": quantiles,
        "threshold_edge_counts": threshold_counts,
        "degree_cap": int(degree_cap),
        "thresholded_edges_before_cap": len(thresholded),
        "nodes_without_qualifying_neighbors": int(np.count_nonzero(qualifying_degree == 0)),
    }
