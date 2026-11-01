import math
import os
import time

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import networkx as nx
from matplotlib.lines import Line2D


NORMAL_COLOR = "#2583bd"   # blue
ATTACK_COLOR = "#f28e2b"   # orange
UNKNOWN_COLOR = "#9e9e9e"  # gray
NORMAL_REP_EDGE = "#008000"  # green outline
ATTACK_REP_EDGE = "#ff0000"  # red outline


def _pack_component_positions(G, components, weight="weight"):
    """Lay out each connected component, then pack components without overlap.

    This avoids running a global O(n^2) force layout on a large, disconnected
    graph. Component size controls its visual footprint.
    """
    start = time.perf_counter()
    local_layouts = []
    gap = 0.35

    for component in components:
        sub = G.subgraph(component)
        if len(sub) == 1:
            node = next(iter(sub.nodes()))
            local = {node: (0.0, 0.0)}
        else:
            iterations = min(30, max(10, int(10 + 3 * math.log2(len(sub)))))
            local = nx.spring_layout(
                sub,
                seed=42,
                iterations=iterations,
                weight=weight,
            )
            max_coord = max(
                max(abs(float(x)), abs(float(y)))
                for x, y in local.values()
            )
            max_coord = max(max_coord, 1e-9)
            local = {n: (float(x) / max_coord, float(y) / max_coord)
                     for n, (x, y) in local.items()}

        # Radius proportional to sqrt(size), so large components remain visible.
        radius = max(0.16, 0.16 * math.sqrt(len(component)))
        local_layouts.append((component, local, radius))

    target_width = max(
        12.0,
        math.sqrt(sum((2.0 * radius + gap) ** 2 for _, _, radius in local_layouts)) * 1.15,
    )
    positions = {}
    cursor_x = 0.0
    cursor_y = 0.0
    row_height = 0.0

    for component, local, radius in local_layouts:
        diameter = 2.0 * radius
        if cursor_x > 0 and cursor_x + diameter > target_width:
            cursor_x = 0.0
            cursor_y -= row_height + gap
            row_height = 0.0

        center_x = cursor_x + radius
        center_y = cursor_y - radius
        for node, (x, y) in local.items():
            positions[node] = (center_x + x * radius, center_y + y * radius)

        cursor_x += diameter + gap
        row_height = max(row_height, diameter)

    print(
        f"[VIS] Layout ready for {len(components)} components "
        f"in {time.perf_counter() - start:.1f}s",
        flush=True,
    )
    return positions


def save_representative_graph(
    edges,
    representatives,
    path,
    all_nodes=None,
    node_labels=None,
    max_normal=None,
    max_attack=None,
    max_mixed=None,
):
    """Save a full-graph view with class-colored nodes and outlined representatives.

    node_labels maps graph node_index -> binary label (0=normal, 1=attack).
    Representative node_index values use the same graph-index coordinate system.
    The max_* arguments remain accepted for compatibility with older callers.
    """
    start = time.perf_counter()
    G = nx.Graph()

    if all_nodes is not None:
        G.add_nodes_from(int(n) for n in all_nodes)

    for edge in edges:
        G.add_edge(
            int(edge["source"]),
            int(edge["target"]),
            weight=float(edge.get("weight", 1.0)),
        )

    labels = {}
    if node_labels:
        for node, label in node_labels.items():
            try:
                label = int(label)
            except (TypeError, ValueError, OverflowError):
                continue
            if label in (0, 1):
                labels[int(node)] = label

    representatives_by_node = {}
    for rep in representatives:
        node = rep.get("node_index")
        if node is None:
            continue
        node = int(node)
        G.add_node(node)
        rep_label = rep.get("label")
        try:
            rep_label = int(rep_label)
        except (TypeError, ValueError, OverflowError):
            rep_label = None
        # The full sampled-data labels are authoritative; use the stored
        # representative label only as a fallback for older callers.
        if node not in labels and rep_label in (0, 1):
            labels[node] = rep_label
        representatives_by_node[node] = labels.get(node, rep_label)

    components = sorted(nx.connected_components(G), key=len, reverse=True)
    print(
        f"[VIS] Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges, "
        f"{len(components)} components",
        flush=True,
    )
    print(
        f"[VIS] Labeled nodes: {sum(label in (0, 1) for label in labels.values())}; "
        f"normal={sum(label == 0 for label in labels.values())}; "
        f"attack={sum(label == 1 for label in labels.values())}; "
        f"representatives={len(representatives_by_node)}",
        flush=True,
    )

    # Use one global force-directed layout for the complete graph.
    # The previous component-packing layout placed many small components and
    # isolates into regular rows, which looked like artificial structure.
    
    # Compute layouts component-wise instead of applying one global layout.
    # This avoids expensive global force calculations on a disconnected graph.
    print("[VIS] Computing component-wise layouts...", flush=True)

    layout_start = time.perf_counter()
    pos = _pack_component_positions(
        G,
        components,
        weight="weight",
    )

    print(
        f"[VIS] Component-wise layout ready in "
        f"{time.perf_counter() - layout_start:.1f}s",
        flush=True,
    )

    fig, ax = plt.subplots(figsize=(18, 13))
    print("[VIS] Drawing edges...", flush=True)
    nx.draw_networkx_edges(
        G,
        pos,
        ax=ax,
        width=0.28,
        alpha=0.20,
        edge_color="#777777",
    )

    representative_nodes = set(representatives_by_node)
    normal_nodes = [n for n in G if labels.get(n) == 0 and n not in representative_nodes]
    attack_nodes = [n for n in G if labels.get(n) == 1 and n not in representative_nodes]
    unknown_nodes = [n for n in G if labels.get(n) not in (0, 1) and n not in representative_nodes]

    print("[VIS] Drawing non-representative nodes...", flush=True)
    if normal_nodes:
        nx.draw_networkx_nodes(
            G, pos, nodelist=normal_nodes, ax=ax,
            node_color=NORMAL_COLOR, node_size=7, linewidths=0, alpha=0.92,
        )
    if attack_nodes:
        nx.draw_networkx_nodes(
            G, pos, nodelist=attack_nodes, ax=ax,
            node_color=ATTACK_COLOR, node_size=9, linewidths=0, alpha=0.95,
        )
    if unknown_nodes:
        nx.draw_networkx_nodes(
            G, pos, nodelist=unknown_nodes, ax=ax,
            node_color=UNKNOWN_COLOR, node_size=6, linewidths=0, alpha=0.75,
        )

    normal_reps = [n for n in representative_nodes if representatives_by_node.get(n) == 0]
    attack_reps = [n for n in representative_nodes if representatives_by_node.get(n) == 1]
    unknown_reps = [n for n in representative_nodes if representatives_by_node.get(n) not in (0, 1)]

    print("[VIS] Drawing representatives...", flush=True)
    if normal_reps:
        nx.draw_networkx_nodes(
            G, pos, nodelist=normal_reps, ax=ax,
            node_color=NORMAL_COLOR, node_size=52,
            edgecolors=NORMAL_REP_EDGE, linewidths=2.0, alpha=1.0,
        )
    if attack_reps:
        nx.draw_networkx_nodes(
            G, pos, nodelist=attack_reps, ax=ax,
            node_color=ATTACK_COLOR, node_size=58,
            edgecolors=ATTACK_REP_EDGE, linewidths=2.0, alpha=1.0,
        )
    if unknown_reps:
        nx.draw_networkx_nodes(
            G, pos, nodelist=unknown_reps, ax=ax,
            node_color=UNKNOWN_COLOR, node_size=52,
            edgecolors="#222222", linewidths=1.8, alpha=1.0,
        )

    legend = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=NORMAL_COLOR,
               markersize=5, label="Normal graph node"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=ATTACK_COLOR,
               markersize=5, label="Attack graph node"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=NORMAL_COLOR,
               markeredgecolor=NORMAL_REP_EDGE, markeredgewidth=2,
               markersize=9, label="Normal representative"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=ATTACK_COLOR,
               markeredgecolor=ATTACK_REP_EDGE, markeredgewidth=2,
               markersize=9, label="Attack representative"),
    ]
    if unknown_nodes or unknown_reps:
        legend.append(
            Line2D([0], [0], marker="o", color="w", markerfacecolor=UNKNOWN_COLOR,
                   markersize=5, label="Unlabeled graph node / representative")
        )

    ax.legend(handles=legend, loc="upper center", bbox_to_anchor=(0.5, -0.025),
              ncol=min(len(legend), 5), fontsize=9, frameon=True)
    ax.set_title(
        f"Representative Graph | {G.number_of_nodes():,} nodes | "
        f"{G.number_of_edges():,} edges | {len(representatives_by_node):,} representatives",
        fontsize=15,
        pad=14,
    )
    ax.axis("off")
    ax.margins(0.02)
    fig.tight_layout()

    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    print("[VIS] Saving image...", flush=True)
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(
        f"[VIS] Saved: {path} | Elapsed: {time.perf_counter() - start:.1f}s",
        flush=True,
    )
