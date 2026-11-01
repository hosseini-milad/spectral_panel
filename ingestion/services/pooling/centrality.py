import math

import networkx as nx


def _finite_float(value, default=1.0):
    """Convert an edge weight to a finite float."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def build_graph(edges, nodes=None):
    """Build an undirected similarity graph.

    `weight` is treated as similarity/strength (larger means more similar).
    A separate positive `distance` attribute is stored for path algorithms,
    because NetworkX betweenness expects edge lengths/costs, not strengths.
    """
    graph = nx.Graph()

    if nodes is not None:
        graph.add_nodes_from(int(node) for node in nodes)

    for edge in edges:
        source = int(edge["source"])
        target = int(edge["target"])
        similarity = _finite_float(edge.get("weight", 1.0), default=1.0)

        if source == target:
            graph.add_node(source)
            continue

        # Cosine similarities used by this project should normally be in
        # [0, 1]. Clamp only the path-cost calculation; retain the original
        # similarity as the graph strength for eigenvector centrality.
        path_strength = max(abs(similarity), 1e-6)
        distance = 1.0 / path_strength

        graph.add_edge(
            source,
            target,
            weight=similarity,
            similarity=similarity,
            distance=distance,
        )

    return graph


def _component_eigenvector_centrality(graph):
    """Compute component-local eigenvector centrality with stable scaling.

    Eigenvector centrality on a disconnected graph has an arbitrary relative
    scale between components. We therefore normalize within each component
    and apply a modest log-size factor, as in the previous implementation.
    Isolates receive zero.
    """
    result = {}
    components = [sorted(component) for component in nx.connected_components(graph)]
    max_size = max((len(component) for component in components), default=1)
    denominator = math.log1p(max_size) or 1.0

    for component_nodes in components:
        size = len(component_nodes)
        if size == 1:
            result[component_nodes[0]] = 0.0
            continue

        subgraph = graph.subgraph(component_nodes)
        try:
            values = nx.eigenvector_centrality(
                subgraph,
                max_iter=1000,
                tol=1e-7,
                weight="weight",
            )
        except nx.PowerIterationFailedConvergence:
            try:
                values = nx.eigenvector_centrality_numpy(
                    subgraph,
                    weight="weight",
                )
            except (nx.NetworkXException, ValueError, ArithmeticError):
                # Deterministic fallback: weighted degree within this component.
                weighted_degree = dict(subgraph.degree(weight="weight"))
                maximum = max(weighted_degree.values(), default=0.0)
                values = {
                    node: (value / maximum if maximum > 0 else 0.0)
                    for node, value in weighted_degree.items()
                }

        local_max = max(values.values(), default=0.0)
        size_factor = math.log1p(size) / denominator
        for node in component_nodes:
            local_value = float(values.get(node, 0.0))
            result[node] = (
                (local_value / local_max) * size_factor
                if local_max > 0
                else 0.0
            )

    return result


def compute_centralities(graph, betweenness_k=100, seed=42):
    """Compute structural centralities for every node in `graph`.

    Betweenness uses the inverse-similarity `distance` attribute. This avoids
    the common error of treating a high similarity as a long path cost.
    For large graphs, deterministic source sampling approximates betweenness.
    """
    nodes = list(graph.nodes())
    if not nodes:
        return {
            "eigenvector": {},
            "degree": {},
            "betweenness": {},
        }

    eigen = _component_eigenvector_centrality(graph)
    degree = dict(graph.degree())

    n = len(nodes)
    if n <= 2:
        betweenness = nx.betweenness_centrality(
            graph,
            normalized=True,
            weight="distance",
        )
    else:
        sample_size = min(max(1, int(betweenness_k)), n - 1)
        betweenness = nx.betweenness_centrality(
            graph,
            k=sample_size,
            normalized=True,
            weight="distance",
            seed=seed,
        )

    # Ensure a complete, finite mapping for downstream score normalization.
    for mapping in (eigen, degree, betweenness):
        for node in nodes:
            value = mapping.get(node, 0.0)
            try:
                value = float(value)
            except (TypeError, ValueError, OverflowError):
                value = 0.0
            mapping[node] = value if math.isfinite(value) else 0.0

    return {
        "eigenvector": eigen,
        "degree": degree,
        "betweenness": betweenness,
    }
