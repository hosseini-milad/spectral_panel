import numpy as np
import networkx as nx


def compute_graph_stats(A):

    degrees = np.sum(A > 0, axis=1)

    return {
        "num_nodes": int(A.shape[0]),
        "num_edges": int(np.sum(A > 0) // 2),
        "avg_degree": float(np.mean(degrees)),
        "max_degree": int(np.max(degrees)),
        "density": float(np.sum(A > 0) / (A.shape[0] ** 2))
    }


def compute_sparse_graph_stats(n, edges):
    """Compute undirected graph statistics directly from a sparse edge list."""
    degrees = np.zeros(n, dtype=np.int64)
    graph = nx.Graph()
    graph.add_nodes_from(range(n))
    for left, right, weight in edges:
        if weight > 0:
            degrees[left] += 1
            degrees[right] += 1
            graph.add_edge(left, right, weight=float(weight))
    edge_count = len(graph.edges)
    return {
        "num_nodes": int(n),
        "num_edges": int(edge_count),
        "avg_degree": float(degrees.mean()) if n else 0.0,
        "max_degree": int(degrees.max()) if n else 0,
        "isolated_nodes": int(np.count_nonzero(degrees == 0)),
        "num_components": int(nx.number_connected_components(graph)) if n else 0,
        "density": float(2 * edge_count / (n * (n - 1))) if n > 1 else 0.0,
    }
