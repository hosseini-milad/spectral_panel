import numpy as np
import networkx as nx


def build_graph(edges):
    graph = nx.Graph()
    for edge in edges:
        source = int(edge["source"])
        target = int(edge["target"])
        weight = float(edge.get("weight", 1.0))
        graph.add_edge(source, target, weight=weight)
    return graph


def _component_eigenvector_centrality(graph):
    """Compute local eigenvector centrality for every connected component."""
    result = {}
    for component in nx.connected_components(graph):
        nodes = sorted(component)
        subgraph = graph.subgraph(nodes)
        if len(nodes) == 1:
            result[nodes[0]] = 1.0
            continue

        try:
            values = nx.eigenvector_centrality(
                subgraph,
                max_iter=5000,
                tol=1e-8,
                weight="weight",
            )
        except nx.PowerIterationFailedConvergence:
            adjacency = nx.to_numpy_array(
                subgraph,
                nodelist=nodes,
                weight="weight",
            )
            eigenvalues, eigenvectors = np.linalg.eigh(adjacency)
            vector = np.abs(eigenvectors[:, int(np.argmax(eigenvalues))])
            norm = np.linalg.norm(vector)
            vector = vector / norm if norm else vector
            values = dict(zip(nodes, vector.tolist()))

        result.update(values)
    return result


def compute_centralities(graph):
    if graph.number_of_nodes() == 0:
        return {"eigenvector": {}, "degree": {}, 
        #"betweenness": {}
        }

    eigen = _component_eigenvector_centrality(graph)
    degree = dict(graph.degree())
    #betweenness = nx.betweenness_centrality(
    #    graph,
    #    k=min(100, graph.number_of_nodes()),
    #    seed=42,
    #)
    return {
        "eigenvector": eigen,
        "degree": degree,
        #"betweenness": betweenness,
    }
