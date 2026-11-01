import math

import networkx as nx
import community.community_louvain as community_louvain


def build_weighted_graph(edges, all_nodes=None):
    """
    Build an undirected weighted similarity graph.

    all_nodes is optional but should be supplied when isolates must be
    preserved. Edge weights are expected to be finite, non-negative
    similarities.
    """
    graph = nx.Graph()

    if all_nodes is not None:
        for node in all_nodes:
            try:
                graph.add_node(int(node))
            except (TypeError, ValueError, OverflowError):
                continue

    for edge in edges:
        try:
            source = int(edge["source"])
            target = int(edge["target"])
            weight = float(edge.get("weight", 1.0))
            if source == target:
                graph.add_node(source)
                continue
            if not math.isfinite(weight) or weight < 0:
                continue
            graph.add_edge(source, target, weight=weight)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue

    return graph


def detect_communities(G, resolution=1.0, random_state=42):
    """Return node -> community ID, retaining every node in G."""
    if G.number_of_nodes() == 0:
        return {}
    if resolution <= 0:
        raise ValueError("resolution must be positive.")

    total_weight = sum(
        float(data.get("weight", 1.0))
        for _, _, data in G.edges(data=True)
    )
    if not math.isfinite(total_weight) or total_weight <= 0:
        return {
            node: index
            for index, node in enumerate(sorted(G.nodes(), key=int))
        }

    partition = community_louvain.best_partition(
        G,
        weight="weight",
        resolution=float(resolution),
        random_state=random_state,
    )

    next_id = max(partition.values(), default=-1) + 1
    for node in sorted(G.nodes(), key=int):
        if node not in partition:
            partition[node] = next_id
            next_id += 1
    return partition


def get_community_statistics(G, partition):
    """Return node membership and basic unweighted/weighted community stats."""
    communities = {}

    for node in G.nodes():
        community_id = partition.get(node, -1)
        communities.setdefault(
            community_id,
            {
                "nodes": [],
                "size": 0,
                "internal_edges": 0,
                "internal_weight": 0.0,
                "density": 0.0,
            },
        )["nodes"].append(node)

    for data in communities.values():
        data["nodes"].sort(key=int)
        subgraph = G.subgraph(data["nodes"])
        data["size"] = subgraph.number_of_nodes()
        data["internal_edges"] = subgraph.number_of_edges()
        data["internal_weight"] = float(
            sum(
                float(edge_data.get("weight", 1.0))
                for _, _, edge_data in subgraph.edges(data=True)
            )
        )
        data["density"] = (
            float(nx.density(subgraph)) if data["size"] > 1 else 0.0
        )

    return communities


def assign_node_communities(nodes, partition):
    """Map requested nodes to community IDs; missing nodes receive -1."""
    return {node: partition.get(node, -1) for node in nodes}
