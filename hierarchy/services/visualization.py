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
    """Lay out each connected component locally, then pack them without overlap.

    This is much faster and more stable than a global spring layout for graphs
    with many disconnected components.
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
            local = {
                n: (float(x) / max_coord, float(y) / max_coord)
                for n, (x, y) in local.items()
            }

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
        f"[HIER-VIS] Layout ready for {len(components)} components "
        f"in {time.perf_counter() - start:.1f}s",
        flush=True,
    )
    return positions


def _draw_graph(ax, G, pos, labels, rep_labels, title, draw_all_edges=True):
    representative_nodes = set(rep_labels)
    normal_nodes = [n for n in G if labels.get(n) == 0 and n not in representative_nodes]
    attack_nodes = [n for n in G if labels.get(n) == 1 and n not in representative_nodes]
    unknown_nodes = [n for n in G if labels.get(n) not in (0, 1) and n not in representative_nodes]

    if draw_all_edges and G.number_of_edges() > 0:
        nx.draw_networkx_edges(
            G,
            pos,
            ax=ax,
            width=0.18,
            alpha=0.08,
            edge_color="#666666",
        )

    if normal_nodes:
        nx.draw_networkx_nodes(
            G, pos, nodelist=normal_nodes, ax=ax,
            node_color=NORMAL_COLOR, node_size=7, linewidths=0, alpha=0.90,
        )
    if attack_nodes:
        nx.draw_networkx_nodes(
            G, pos, nodelist=attack_nodes, ax=ax,
            node_color=ATTACK_COLOR, node_size=8, linewidths=0, alpha=0.92,
        )
    if unknown_nodes:
        nx.draw_networkx_nodes(
            G, pos, nodelist=unknown_nodes, ax=ax,
            node_color=UNKNOWN_COLOR, node_size=6, linewidths=0, alpha=0.75,
        )

    normal_reps = [n for n in representative_nodes if rep_labels.get(n) == 0]
    attack_reps = [n for n in representative_nodes if rep_labels.get(n) == 1]
    unknown_reps = [n for n in representative_nodes if rep_labels.get(n) not in (0, 1)]

    if normal_reps:
        nx.draw_networkx_nodes(
            G, pos, nodelist=normal_reps, ax=ax,
            node_color=NORMAL_COLOR, node_size=54,
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
            node_color=UNKNOWN_COLOR, node_size=54,
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
                   markersize=5, label="Unknown / unlabeled")
        )

    ax.legend(
        handles=legend,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.03),
        ncol=min(len(legend), 5),
        fontsize=9,
        frameon=True,
    )
    ax.set_title(title, fontsize=15, pad=14)
    ax.axis("off")
    ax.margins(0.02)


def save_hierarchy_representative_graph(
    edges,
    representatives,
    full_path,
    reps_only_path=None,
    all_nodes=None,
    node_labels=None,
    title_prefix="Hierarchy Representative Graph",
):
    """Save two hierarchy views:
    1) full graph with representatives highlighted;
    2) representatives-only induced view (optional).
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
        rep_label = rep.get("label")
        try:
            rep_label = int(rep_label)
        except (TypeError, ValueError, OverflowError):
            rep_label = None
        if node not in labels and rep_label in (0, 1):
            labels[node] = rep_label
        representatives_by_node[node] = labels.get(node, rep_label)

    components = sorted(nx.connected_components(G), key=len, reverse=True)
    print(
        f"[HIER-VIS] Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges, {len(components)} components",
        flush=True,
    )
    pos = _pack_component_positions(G, components)

    directory = os.path.dirname(full_path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    # Full graph view
    fig, ax = plt.subplots(figsize=(18, 13))
    _draw_graph(
        ax=ax,
        G=G,
        pos=pos,
        labels=labels,
        rep_labels=representatives_by_node,
        title=(
            f"{title_prefix} | full graph | {G.number_of_nodes():,} nodes | "
            f"{G.number_of_edges():,} edges | {len(representatives_by_node):,} representatives"
        ),
        draw_all_edges=True,
    )
    fig.tight_layout()
    fig.savefig(full_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"[HIER-VIS] Saved full graph: {full_path}", flush=True)

    # Representatives-only induced view
    if reps_only_path:
        rep_nodes = sorted(representatives_by_node)
        R = G.subgraph(rep_nodes).copy()
        fig, ax = plt.subplots(figsize=(16, 12))
        rep_pos = {node: pos[node] for node in R.nodes() if node in pos}
        _draw_graph(
            ax=ax,
            G=R,
            pos=rep_pos,
            labels={node: labels.get(node) for node in R.nodes()},
            rep_labels=representatives_by_node,
            title=(
                f"{title_prefix} | representatives only | {R.number_of_nodes():,} nodes | "
                f"{R.number_of_edges():,} edges"
            ),
            draw_all_edges=True,
        )
        fig.tight_layout()
        fig.savefig(reps_only_path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        print(f"[HIER-VIS] Saved representative-only graph: {reps_only_path}", flush=True)

    print(
        f"[HIER-VIS] Visualization completed in {time.perf_counter() - start:.1f}s",
        flush=True,
    )
