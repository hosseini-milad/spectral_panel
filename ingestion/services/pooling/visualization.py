
import os
import math
import time
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import networkx as nx
from matplotlib.lines import Line2D


def save_representative_graph(
    edges,
    representatives,
    path,
    all_nodes=None,
    max_normal=12,
    max_attack=12,
    max_mixed=6,
):
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
    for rep in representatives:
        node = rep.get("node_index")
        label = rep.get("label")

        if node is not None:
            node = int(node)
            G.add_node(node)

            if label in (0, 1):
                labels[node] = int(label)

    components = sorted(
        nx.connected_components(G),
        key=len,
        reverse=True,
    )

    groups = {
        "normal": [],
        "attack": [],
        "mixed": [],
    }

    for component in components:
        normal = sum(labels.get(n) == 0 for n in component)
        attack = sum(labels.get(n) == 1 for n in component)

        labeled = normal + attack

        if labeled == 0:
            group = "mixed"
        else:
            purity = max(normal, attack) / labeled

            if purity < 0.80:
                group = "mixed"
            elif normal > attack:
                group = "normal"
            elif attack > normal:
                group = "attack"
            else:
                group = "mixed"

        groups[group].append({
            "nodes": component,
            "size": len(component),
            "normal": normal,
            "attack": attack,
        })

    limits = {
        "normal": max_normal,
        "attack": max_attack,
        "mixed": max_mixed,
    }

    titles = {
        "normal": "Normal-dominant components",
        "attack": "Attack-dominant components",
        "mixed": "Mixed / Unlabeled components",
    }

    fig, axes = plt.subplots(
        1, 3, figsize=(21, 12),
    )

    for ax, group in zip(
        axes, ["normal", "mixed", "attack"]
    ):
        selected = groups[group][:limits[group]]

        columns = 3
        rows = max(1, math.ceil(len(selected) / columns))

        print(
            f"[VIS] {group}: displaying {len(selected)} "
            f"of {len(groups[group])} components",
            flush=True,
        )

        for i, item in enumerate(selected):
            sub = G.subgraph(item["nodes"])

            row = i // columns
            col = i % columns

            center_x = col * 3.5
            center_y = -row * 3.5

            if len(sub) == 1:
                node = next(iter(sub.nodes()))
                local_pos = {node: (0.0, 0.0)}
            else:
                local_pos = nx.spring_layout(
                    sub,
                    seed=42,
                    iterations=15,
                    weight="weight",
                )

            # Fit each component inside its own grid cell.
            max_coord = max(
                max(abs(float(x)), abs(float(y)))
                for x, y in local_pos.values()
            )

            scale = 1.2 / max(max_coord, 1e-9)

            pos = {
                node: (
                    center_x + float(x) * scale,
                    center_y + float(y) * scale,
                )
                for node, (x, y) in local_pos.items()
            }

            nx.draw_networkx_edges(
                sub,
                pos,
                ax=ax,
                width=0.35,
                alpha=0.20,
                edge_color="gray",
            )

            nx.draw_networkx_nodes(
                sub,
                pos,
                ax=ax,
                node_size=7,
                node_color="#3182bd",
            )

            normal_nodes = [
                n for n in sub
                if labels.get(n) == 0
            ]

            attack_nodes = [
                n for n in sub
                if labels.get(n) == 1
            ]

            if normal_nodes:
                nx.draw_networkx_nodes(
                    sub,
                    pos,
                    nodelist=normal_nodes,
                    ax=ax,
                    node_size=65,
                    node_color="#3182bd",
                    edgecolors="green",
                    linewidths=1.8,
                )

            if attack_nodes:
                nx.draw_networkx_nodes(
                    sub,
                    pos,
                    nodelist=attack_nodes,
                    ax=ax,
                    node_size=65,
                    node_color="#3182bd",
                    edgecolors="red",
                    linewidths=1.8,
                )

            ax.text(
                center_x,
                center_y - 1.55,
                f"{item['size']} nodes | "
                f"N:{item['normal']} A:{item['attack']}",
                ha="center",
                va="top",
                fontsize=7,
            )

            print(
                f"[VIS] {group}: "
                f"{i + 1}/{len(selected)} completed",
                flush=True,
            )

        ax.set_title(
            titles[group],
            fontsize=12,
            pad=20,
        )

        ax.set_xlim(-1.6, 8.6)
        ax.set_ylim(
            -(rows - 1) * 3.5 - 2.0,
            1.7,
        )
        ax.set_aspect("equal")
        ax.axis("off")

    legend = [
        Line2D(
            [0], [0],
            marker="o",
            color="w",
            markerfacecolor="#3182bd",
            markeredgecolor="green",
            markeredgewidth=2,
            markersize=9,
            label="Normal representative",
        ),
        Line2D(
            [0], [0],
            marker="o",
            color="w",
            markerfacecolor="#3182bd",
            markeredgecolor="red",
            markeredgewidth=2,
            markersize=9,
            label="Attack representative",
        ),
        Line2D(
            [0], [0],
            marker="o",
            color="w",
            markerfacecolor="#3182bd",
            markersize=5,
            label="Other graph nodes",
        ),
    ]

    fig.legend(
        handles=legend,
        loc="lower center",
        ncol=3,
        fontsize=10,
    )

    shown = sum(
        min(len(groups[g]), limits[g])
        for g in groups
    )

    fig.suptitle(
        f"Representative Graph | "
        f"{len(representatives)} representatives | "
        f"{shown} of {len(components)} components shown",
        fontsize=15,
    )

    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    print("[VIS] Saving image...", flush=True)

    fig.savefig(
        path,
        dpi=180,
        bbox_inches="tight",
    )

    plt.close(fig)

    print(
        f"[VIS] Saved: {path} | "
        f"Elapsed: {time.perf_counter() - start:.1f}s",
        flush=True,
    )
