"""Evaluate stored graph representatives without modifying the graph or selection."""
from collections import Counter, defaultdict
import math
import time

import networkx as nx
import numpy as np
from scipy.sparse.linalg import eigsh, ArpackNoConvergence


def _weighted_eigenvector_with_sparse_fallback(subgraph, component_id, report):
    """Power iteration first; use a sparse eigensolver if it does not converge."""
    try:
        return nx.eigenvector_centrality(
            subgraph, max_iter=500, tol=1e-6, weight="weight"
        )
    except nx.PowerIterationFailedConvergence:
        report(
            f"[EVAL] Component {component_id}: power iteration did not "
            "converge; retrying with sparse eigsh...",
            flush=True,
        )

    # Largest algebraic eigenvector of the symmetric weighted adjacency matrix.
    # Do not create a dense matrix: O(nodes^2) memory would be costly.
    nodes = sorted(subgraph.nodes())
    adjacency = nx.to_scipy_sparse_array(
        subgraph, nodelist=nodes, weight="weight", format="csr", dtype=float
    )
    # scipy.sparse.linalg.eigsh requires floating sparse data and k < n.
    # For two-node components, exact positive eigenvector is trivial.
    if len(nodes) == 2:
        return {node: 2 ** -0.5 for node in nodes}

    try:
        _, eigenvectors = eigsh(
            adjacency,
            k=1,
            which="LA",
            v0=np.ones(len(nodes), dtype=float),
            tol=1e-6,
            maxiter=5000,
        )
    except (ArpackNoConvergence, ValueError, RuntimeError) as exc:
        raise RuntimeError(
            f"Sparse eigenvector solver failed on component {component_id} "
            f"({len(nodes)} nodes): {exc}"
        ) from exc

    eigenvector = np.abs(eigenvectors[:, 0])
    norm = np.linalg.norm(eigenvector)
    if not np.isfinite(norm) or norm == 0:
        raise RuntimeError(f"Invalid eigenvector on component {component_id}")
    eigenvector /= norm
    return dict(zip(nodes, map(float, eigenvector)))


def evaluate_representatives(graph, representatives, with_eigen=True, report=print):
    """Return JSON-compatible metrics. node_labels must match edge node indices."""
    start = time.perf_counter()
    node_ids = list(graph.node_ids or [])
    n = len(node_ids)
    if not n:
        raise ValueError("graph_metadata.node_ids is empty")

    all_labels = list(graph.node_labels or [])
    if len(all_labels) != n or any(x not in (0, 1) for x in all_labels):
        raise ValueError(
            "graph_metadata.node_labels must contain 0/1 labels for every node, "
            "in exactly the same node order as graph_metadata.node_ids. "
            "Cannot calculate trustworthy classification metrics otherwise."
        )

    G = nx.Graph()
    G.add_nodes_from(range(n))
    for edge in graph.edges:
        a, b = int(edge["source"]), int(edge["target"])
        if not (0 <= a < n and 0 <= b < n):
            raise ValueError(f"Invalid graph edge endpoint: {(a, b)}")
        G.add_edge(a, b, weight=float(edge.get("weight", 1.0)))

    selected = {}
    for rep in representatives:
        idx = rep.get("node_index")
        if idx is None:
            raise ValueError("Representative missing node_index")
        idx = int(idx)
        if idx in selected:
            raise ValueError(f"Duplicate representative node_index: {idx}")
        if not 0 <= idx < n:
            raise ValueError(f"Out-of-range representative node_index: {idx}")
        selected[idx] = rep
    if not selected:
        raise ValueError("No representatives found")

    wrong_labels = [i for i, rep in selected.items()
                    if rep.get("label") not in (None, all_labels[i])]
    if wrong_labels:
        raise ValueError(
            f"Representative labels disagree with graph_metadata.node_labels: "
            f"examples={wrong_labels[:10]}. Check node-index alignment before evaluation."
        )

    components = list(nx.connected_components(G))
    node_component = {}
    for cid, component in enumerate(components):
        for node in component:
            node_component[node] = cid

    selected_components = {node_component[i] for i in selected}
    represented_nodes = sum(len(components[cid]) for cid in selected_components)
    report(f"[EVAL] Graph: {n} nodes, {G.number_of_edges()} edges, "
           f"{len(components)} components, {len(selected)} representatives", flush=True)
    report("[EVAL] Computing multi-source hop coverage...", flush=True)
    distances = nx.multi_source_dijkstra_path_length(G, list(selected), weight=None)
    dist_values = list(distances.values())
    reachable = len(distances)
    count1 = sum(d <= 1 for d in dist_values)
    count2 = sum(d <= 2 for d in dist_values)

    # Label classification proxy: nearest representative by unweighted hops.
    # Use all equally-near representatives for honest tie reporting.
    report("[EVAL] Computing nearest-representative label agreement...", flush=True)
    from collections import deque
    d = [-1] * n
    nearest_label = [-1] * n
    ambiguous = [False] * n
    queue = deque()
    for node in sorted(selected):
        d[node] = 0
        nearest_label[node] = all_labels[node]
        queue.append(node)
    # propagate nearest label sets as two-bit masks, including ties
    masks = [0] * n
    for node in selected:
        masks[node] = 1 << all_labels[node]
    while queue:
        u = queue.popleft()
        for v in G[u]:
            if d[v] == -1:
                d[v] = d[u] + 1
                masks[v] = masks[u]
                queue.append(v)
            elif d[v] == d[u] + 1:
                newmask = masks[v] | masks[u]
                if newmask != masks[v]:
                    masks[v] = newmask
                    queue.append(v)
    # Unreachable nodes are excluded from F1 and separately reported.
    from sklearn.metrics import accuracy_score, f1_score, balanced_accuracy_score
    eligible = [i for i in range(n) if d[i] >= 0 and masks[i] in (1, 2) and i not in selected]
    y_true = [all_labels[i] for i in eligible]
    y_pred = [0 if masks[i] == 1 else 1 for i in eligible]
    classification = {
        "evaluation_nodes": len(eligible),
        "excluded_selected_nodes": len(selected),
        "excluded_unreachable_nodes": n - reachable,
        "excluded_tied_nearest_label_nodes": sum(m == 3 for m in masks),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", labels=[0, 1], zero_division=0)) if eligible else None,
        "weighted_f1": float(f1_score(y_true, y_pred, average="weighted", labels=[0, 1], zero_division=0)) if eligible else None,
        "accuracy": float(accuracy_score(y_true, y_pred)) if eligible else None,
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)) if len(set(y_true)) == 2 else None,
    }
    class_all = Counter(all_labels)
    class_selected = Counter(all_labels[i] for i in selected)
    cross = sum(all_labels[u] != all_labels[v] for u, v in G.edges())
    metrics = {
        "graph": {"nodes": n, "edges": G.number_of_edges(), "components": len(components), "isolates": nx.number_of_isolates(G)},
        "representatives": {"count": len(selected), "ratio": len(selected) / n, "normal": class_selected[0], "attack": class_selected[1]},
        "class_balance": {"all_normal": class_all[0], "all_attack": class_all[1],
                          "attack_fraction_all": class_all[1] / n,
                          "attack_fraction_selected": class_selected[1] / len(selected)},
        "edge_homophily": {"cross_label_edges": cross,
                           "cross_label_edge_fraction": cross / G.number_of_edges() if G.number_of_edges() else None},
        "coverage": {"reachable_fraction": reachable / n,
                     "one_hop_fraction": count1 / n,
                     "two_hop_fraction": count2 / n,
                     "mean_hops_reachable": sum(dist_values) / len(dist_values) if dist_values else None,
                     "max_hops_reachable": max(dist_values) if dist_values else None,
                     "represented_components": len(selected_components),
                     "total_components": len(components),
                     "component_coverage_fraction": len(selected_components) / len(components),
                     "nodes_in_represented_components_fraction": represented_nodes / n},
        "nearest_representative_proxy": classification,
    }
    report(f"[EVAL] Fast metrics completed in {time.perf_counter()-start:.1f}s", flush=True)

    if with_eigen:
        report("[EVAL] Recomputing weighted eigenvector centrality by component...", flush=True)
        eigen = {}
        for j, comp in enumerate(components, 1):
            if len(comp) == 1:
                eigen[next(iter(comp))] = 1.0  # matches current pooling implementation
            else:
                sub = G.subgraph(comp)
                values = _weighted_eigenvector_with_sparse_fallback(sub, j, report)
                eigen.update(values)
            if j % 25 == 0 or j == len(components):
                report(f"[EVAL] Eigenvector components {j}/{len(components)} "
                       f"({100*j/len(components):.1f}%)", flush=True)

        # Top decile *within each nontrivial connected component*; this avoids
        # comparing incompatible magnitudes between disconnected components.
        top_nodes = set()
        component_percentiles = {}
        for comp in components:
            if len(comp) < 2:
                continue
            ranked = sorted(comp, key=lambda node: (-eigen[node], node))
            top_nodes.update(ranked[:max(1, math.ceil(0.10 * len(ranked)))])
            # 1 = highest score, 0 = lowest; ties get same rank percentile.
            uniq = sorted({eigen[node] for node in comp})
            value_to_pct = {v: (pos / (len(uniq) - 1) if len(uniq) > 1 else 0.5)
                            for pos, v in enumerate(uniq)}
            for node in comp:
                component_percentiles[node] = value_to_pct[eigen[node]]
        chosen_nontrivial = [node for node in selected if node in component_percentiles]
        chosen_top = selected.keys() & top_nodes
        metrics["eigenvector"] = {
            "comparison": "within_connected_component_weighted_eigenvector",
            "top_decile_nodes": len(top_nodes),
            "top_decile_selected": len(chosen_top),
            "top_decile_recall": len(chosen_top) / len(top_nodes) if top_nodes else None,
            "top_decile_precision": len(chosen_top) / len(chosen_nontrivial) if chosen_nontrivial else None,
            "mean_selected_component_percentile": (
                sum(component_percentiles[i] for i in chosen_nontrivial) / len(chosen_nontrivial)
                if chosen_nontrivial else None
            ),
            "selected_nontrivial_count": len(chosen_nontrivial),
        }
        report(f"[EVAL] Eigenvector audit completed in {time.perf_counter()-start:.1f}s", flush=True)
    return metrics
