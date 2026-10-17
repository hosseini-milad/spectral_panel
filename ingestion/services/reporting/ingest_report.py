from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
from django.conf import settings
from matplotlib.lines import Line2D

from ingestion.models.graph_metadata import GraphMetadata
from ingestion.models.graph_representative import GraphRepresentative
from ingestion.models.sampled_data import SampledSecurityData


def create_ingest_report(source_file, output_path=None):
    """Render candidates and selected graph representatives for one dataset."""
    candidates = list(
        SampledSecurityData.objects(source_file=source_file)
        .order_by("id")
        .as_pymongo()
    )
    graph = GraphMetadata.objects(source_file=source_file).first()
    representatives = list(
        GraphRepresentative.objects(source_file=source_file).as_pymongo()
    )
    if not candidates:
        raise ValueError(f"No sampled records found for {source_file!r}")
    if graph is None:
        raise ValueError(f"No graph metadata found for {source_file!r}")
    if not representatives:
        raise ValueError(f"No graph representatives found for {source_file!r}")

    labels = [int(record.get("label", 0)) for record in candidates]
    graph_nodes = nx.Graph()
    graph_nodes.add_nodes_from(range(len(candidates)))
    for edge in graph.edges:
        graph_nodes.add_edge(
            int(edge["source"]),
            int(edge["target"]),
            weight=float(edge.get("weight", 1.0)),
        )

    representative_indices = {
        int(record["node_index"])
        for record in representatives
        if record.get("node_index") is not None
        and 0 <= int(record["node_index"]) < len(candidates)
    }
    if not representative_indices:
        raise ValueError("Representatives have no valid candidate node indexes")

    positions = nx.spring_layout(
        graph_nodes,
        seed=42,
        weight="weight",
        iterations=60,
    )
    fig, ax = plt.subplots(figsize=(14, 10), facecolor="white")
    ax.set_facecolor("white")

    nx.draw_networkx_edges(
        graph_nodes,
        positions,
        ax=ax,
        edge_color="#b8c0cc",
        alpha=0.14,
        width=0.45,
    )

    benign = [index for index, label in enumerate(labels) if label == 0]
    attacks = [index for index, label in enumerate(labels) if label == 1]
    ax.scatter(
        [positions[index][0] for index in benign],
        [positions[index][1] for index in benign],
        s=12,
        c="#ffffff",
        edgecolors="#cbd2dc",
        linewidths=0.45,
        alpha=0.82,
        zorder=2,
    )
    ax.scatter(
        [positions[index][0] for index in attacks],
        [positions[index][1] for index in attacks],
        s=17,
        c="#f3b1b1",
        edgecolors="#de8a8a",
        linewidths=0.5,
        alpha=0.82,
        zorder=3,
    )

    rep_benign = [index for index in representative_indices if labels[index] == 0]
    rep_attacks = [index for index in representative_indices if labels[index] == 1]
    for indices, color in ((rep_benign, "#173f73"), (rep_attacks, "#c62828")):
        if not indices:
            continue
        ax.scatter(
            [positions[index][0] for index in indices],
            [positions[index][1] for index in indices],
            s=84,
            c="#f4b400",
            edgecolors="#8a5b00",
            linewidths=0.8,
            alpha=0.96,
            zorder=4,
        )
        ax.scatter(
            [positions[index][0] for index in indices],
            [positions[index][1] for index in indices],
            s=40,
            c=color,
            edgecolors="#ffffff",
            linewidths=0.9,
            alpha=1.0,
            zorder=5,
        )

    handles = [
        Line2D([], [], marker="o", linestyle="", markersize=7,
               markerfacecolor="#ffffff", markeredgecolor="#aeb7c2",
               label=f"Candidate benign ({len(benign):,})"),
        Line2D([], [], marker="o", linestyle="", markersize=7,
               markerfacecolor="#f3b1b1", markeredgecolor="#de8a8a",
               label=f"Candidate attack ({len(attacks):,})"),
        Line2D([], [], marker="o", linestyle="", markersize=9,
               markerfacecolor="#173f73", markeredgecolor="#f4b400",
               markeredgewidth=2, label=f"Selected benign ({len(rep_benign):,})"),
        Line2D([], [], marker="o", linestyle="", markersize=9,
               markerfacecolor="#c62828", markeredgecolor="#f4b400",
               markeredgewidth=2, label=f"Selected attack ({len(rep_attacks):,})"),
    ]
    ax.legend(handles=handles, loc="upper right", frameon=True, framealpha=0.96)
    ax.set_title(
        "Graph Representative Selection\n"
        f"{source_file}  |  candidates: {len(candidates):,}  |  "
        f"representatives: {len(representative_indices):,}",
        fontsize=16,
        pad=18,
    )
    ax.text(
        0.01,
        0.015,
        "Pale nodes: sampled candidates   |   Bold nodes with gold halo: selected representatives",
        transform=ax.transAxes,
        fontsize=9,
        color="#4b5563",
    )
    ax.set_axis_off()
    fig.tight_layout()

    if output_path is None:
        output_path = Path(settings.BASE_DIR) / "files" / "report" / "report-ingest.png"
    else:
        output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    return {
        "path": str(output_path),
        "candidate_count": len(candidates),
        "candidate_labels": dict(Counter(labels)),
        "representative_count": len(representative_indices),
        "representative_labels": {
            0: len(rep_benign),
            1: len(rep_attacks),
        },
    }
