from ingestion.utils.document_paths import document_directory
import json
import math
import re
import time
from pathlib import Path
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from mongoengine import get_connection

DAY_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _largest_remainder_quotas(sizes, total_reps):
    total_nodes = sum(sizes)
    if not sizes or total_nodes <= 0 or total_reps <= 0:
        return [0] * len(sizes)
    exact = [total_reps * size / total_nodes for size in sizes]
    quotas = [math.floor(value) for value in exact]
    remainder = total_reps - sum(quotas)
    order = sorted(range(len(sizes)), key=lambda i: (exact[i] - quotas[i], sizes[i], -i), reverse=True)
    for i in order[:remainder]:
        quotas[i] += 1
    return quotas


def _safe_corr(x, y):
    if len(x) < 2 or np.std(x) <= 1e-12 or np.std(y) <= 1e-12:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def _component_allocation(graph, representative_indices):
    components = sorted(nx.connected_components(graph), key=len, reverse=True)
    node_to_component = {}
    for cid, nodes in enumerate(components):
        for node in nodes:
            node_to_component[node] = cid
    counts = Counter(node_to_component[i] for i in representative_indices if i in node_to_component)
    sizes = [len(nodes) for nodes in components]
    total_nodes, total_reps = graph.number_of_nodes(), len(representative_indices)
    quotas = _largest_remainder_quotas(sizes, total_reps)
    rows = []
    for cid, size in enumerate(sizes):
        actual = int(counts.get(cid, 0))
        expected = total_reps * size / max(1, total_nodes)
        node_share = size / max(1, total_nodes)
        rep_share = actual / max(1, total_reps)
        index = rep_share / node_share if node_share else None
        status = "NO_REPRESENTATIVE" if actual == 0 else (
            "UNDER_ALLOCATED" if actual < quotas[cid] else
            "OVER_ALLOCATED" if actual > quotas[cid] else "PROPORTIONAL"
        )
        rows.append({
            "component_id": cid, "nodes": int(size), "node_share": float(node_share),
            "representatives": actual, "representative_share": float(rep_share),
            "expected_representatives_exact": float(expected),
            "expected_representatives_integer": int(quotas[cid]),
            "allocation_index": float(index) if index is not None else None,
            "difference_from_exact_expectation": float(actual - expected), "status": status,
        })
    actual = np.asarray([r["representatives"] for r in rows], dtype=float)
    expected = np.asarray([r["expected_representatives_exact"] for r in rows], dtype=float)
    deviation = float(np.abs(actual - expected).sum() / (2 * max(1, total_reps)))
    top = rows[:min(10, len(rows))]
    top_nodes = sum(r["nodes"] for r in top)
    top_reps = sum(r["representatives"] for r in top)
    large_cutoff = max(2, math.ceil(total_nodes * 0.01))
    large_missing = [r for r in rows if r["nodes"] >= large_cutoff and r["representatives"] == 0]
    return {
        "method": "component_size_proportional_largest_remainder",
        "total_components": len(rows), "total_nodes": int(total_nodes),
        "total_representatives": int(total_reps),
        "components_with_representatives": sum(r["representatives"] > 0 for r in rows),
        "components_without_representatives": sum(r["representatives"] == 0 for r in rows),
        "large_component_cutoff_nodes": int(large_cutoff),
        "large_components_without_representatives": large_missing,
        "under_allocated_components": sum(r["status"] == "UNDER_ALLOCATED" for r in rows),
        "over_allocated_components": sum(r["status"] == "OVER_ALLOCATED" for r in rows),
        "proportional_components": sum(r["status"] == "PROPORTIONAL" for r in rows),
        "allocation_deviation_index": deviation,
        "size_representative_count_pearson": _safe_corr(
            np.asarray([r["nodes"] for r in rows], dtype=float), actual
        ),
        "top_10_components": {
            "component_count": len(top), "nodes": int(top_nodes),
            "node_share": float(top_nodes / max(1, total_nodes)),
            "representatives": int(top_reps),
            "representative_share": float(top_reps / max(1, total_reps)),
            "expected_representatives": float(sum(r["expected_representatives_exact"] for r in top)),
        },
        "components": rows,
        "interpretation": [
            "Expected representatives are proportional to component node counts.",
            "Integer quotas use largest-remainder allocation and sum to the available representative count.",
            "Small components may legitimately receive zero representatives.",
            "Large components with zero representatives deserve manual review.",
            "This measures size-based allocation, not behavioral or security importance.",
        ],
    }


def _save_plot(result, path, top_n=30):
    rows = result["components"][:top_n]
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    fig.suptitle(
        f"Component Representation Allocation | {result['total_nodes']:,} nodes | "
        f"{result['total_representatives']:,} representatives", fontsize=13
    )
    ax = axes[0]
    x = np.arange(len(rows))
    width = 0.38
    ax.bar(x - width / 2, [r["expected_representatives_exact"] for r in rows], width,
           label="Expected (size-proportional)")
    ax.bar(x + width / 2, [r["representatives"] for r in rows], width, label="Actual")
    ax.set_xlabel("Component ID (ranked by size)")
    ax.set_ylabel("Representative count")
    ax.set_title(f"Top {len(rows)} components: expected vs actual")
    ax.set_xticks(x)
    ax.set_xticklabels([str(r["component_id"]) for r in rows], rotation=90, fontsize=7)
    ax.legend()

    ax = axes[1]
    sizes = np.asarray([r["nodes"] for r in result["components"]], dtype=float)
    counts = np.asarray([r["representatives"] for r in result["components"]], dtype=float)
    ax.scatter(sizes, counts, alpha=0.65, label="Components")
    if len(sizes):
        xx = np.linspace(max(1, sizes.min()), sizes.max(), 100)
        ax.plot(xx, xx * result["total_representatives"] / max(1, result["total_nodes"]),
                label="Ideal proportional allocation")
    zero = counts == 0
    if np.any(zero):
        ax.scatter(sizes[zero], counts[zero], marker="x", label="No representative")
    ax.set_xscale("log")
    ax.set_xlabel("Component size (nodes, log scale)")
    ax.set_ylabel("Actual representative count")
    ax.set_title("All components: size vs representative count")
    ax.legend()
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)


def _save_summary(result, path):
    top = result["top_10_components"]
    lines = [
        "COMPONENT REPRESENTATION ALLOCATION EVALUATION", "=" * 52,
        f"Source: {result['source_file']}", f"Method: {result['method']}",
        f"Graph nodes: {result['total_nodes']:,}",
        f"Representatives: {result['total_representatives']:,}",
        f"Connected components: {result['total_components']:,}", "",
        "ALLOCATION OVERVIEW",
        f"Components with representatives: {result['components_with_representatives']:,}",
        f"Components without representatives: {result['components_without_representatives']:,}",
        f"Large component cutoff (1% of graph): {result['large_component_cutoff_nodes']:,} nodes",
        f"Large components without representatives: {len(result['large_components_without_representatives']):,}",
        f"Under-allocated components: {result['under_allocated_components']:,}",
        f"Proportional components: {result['proportional_components']:,}",
        f"Over-allocated components: {result['over_allocated_components']:,}",
        f"Allocation deviation index (0 is ideal): {result['allocation_deviation_index']:.6f}",
        f"Pearson correlation (size vs representative count): {result['size_representative_count_pearson']}", "",
        "TOP 10 COMPONENTS",
        f"Nodes: {top['nodes']:,} ({top['node_share']:.2%} of graph)",
        f"Actual representatives: {top['representatives']:,} ({top['representative_share']:.2%} of representatives)",
        f"Expected representatives: {top['expected_representatives']:.2f}", "",
        "LARGEST 30 COMPONENTS",
        "ID | Nodes | Actual reps | Expected reps | Allocation index | Status",
    ]
    for r in result["components"][:30]:
        idx = "n/a" if r["allocation_index"] is None else f"{r['allocation_index']:.3f}"
        lines.append(
            f"{r['component_id']} | {r['nodes']} | {r['representatives']} | "
            f"{r['expected_representatives_exact']:.2f} | {idx} | {r['status']}"
        )
    lines += ["", "LARGE COMPONENTS WITHOUT REPRESENTATIVES", "ID | Nodes | Expected reps"]
    if result["large_components_without_representatives"]:
        for r in result["large_components_without_representatives"]:
            lines.append(f"{r['component_id']} | {r['nodes']} | {r['expected_representatives_exact']:.2f}")
    else:
        lines.append("None")
    lines += [
        "", "INTERPRETATION",
        "- Expected counts are proportional to component size, not risk score.",
        "- Largest-remainder integer quotas sum to the total representative count.",
        "- Zero representatives in tiny components is not automatically a defect.",
        "- Large components with zero or substantially fewer representatives deserve review.",
        "- This report evaluates component allocation, not downstream attack detection.",
    ]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


class Command(BaseCommand):
    help = "Evaluate size-proportional representative allocation across hierarchy connected components."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--source-file", required=True)

    def handle(self, *args, **options):
        started = time.perf_counter()
        source_file = options["source_file"].strip()
        if not source_file:
            raise CommandError("--source-file cannot be empty.")
        db = get_connection(alias="default")["siem_db"]
        graph_doc = db["hyper_graph_metadata"].find_one(
            {"source_file": source_file, "status": "complete"}
        )
        if graph_doc is None:
            raise CommandError(f"Completed hierarchy graph not found: {source_file}")
        node_ids = list(graph_doc.get("node_ids") or [])
        n = len(node_ids)
        if not n:
            raise CommandError("Graph metadata has no node_ids.")

        reps = list(db["hyper_representatives"].find(
            {"source_file": source_file}, {"_id": 0, "node_index": 1}
        ))
        if not reps:
            raise CommandError(f"No hyper_representatives found for {source_file}")
        rep_indices = set()
        invalid = 0
        for rep in reps:
            try:
                idx = int(rep["node_index"])
            except (KeyError, TypeError, ValueError, OverflowError):
                invalid += 1
                continue
            if not 0 <= idx < n:
                invalid += 1
            else:
                rep_indices.add(idx)
        if invalid:
            raise CommandError(f"Found {invalid} invalid representative node_index values.")
        if len(rep_indices) != len(reps):
            raise CommandError("Duplicate representative node_index values detected.")

        graph = nx.Graph()
        graph.add_nodes_from(range(n))
        cursor = db["hyper_graph_edges"].find(
            {"source_file": source_file}, {"_id": 0, "source": 1, "target": 1}
        ).batch_size(10000)
        try:
            for edge in cursor:
                u, v = int(edge["source"]), int(edge["target"])
                if not (0 <= u < n and 0 <= v < n):
                    raise CommandError(f"Invalid edge endpoint ({u}, {v}) for {n} nodes.")
                graph.add_edge(u, v)
        finally:
            cursor.close()
        expected_edges = int(graph_doc.get("edge_count", graph.number_of_edges()))
        if graph.number_of_edges() != expected_edges:
            raise CommandError("hyper_graph_edges count differs from metadata; incomplete evaluation.")

        result = _component_allocation(graph, rep_indices)
        result.update({
            "source_file": source_file,
            "graph_edges": graph.number_of_edges(),
            "generated_at_epoch": time.time(),
        })
        match = DAY_RE.search(source_file)
        day = match.group(1) if match else "unknown-day"
        folder = document_directory("hierarchy", source_file, layer=2, day=day)
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"{source_file}_component_allocation"
        json_path = folder / f"{stem}.json"
        image_path = folder / f"{stem}.png"
        text_path = folder / f"{stem}.txt"
        json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        _save_plot(result, image_path)
        _save_summary(result, text_path)

        self.stdout.write(self.style.SUCCESS(f"[COMP-ALLOC] JSON saved: {json_path}"))
        self.stdout.write(self.style.SUCCESS(f"[COMP-ALLOC] Diagram saved: {image_path}"))
        self.stdout.write(self.style.SUCCESS(f"[COMP-ALLOC] Text saved: {text_path}"))
        self.stdout.write(
            f"[COMP-ALLOC] components={result['total_components']:,}; "
            f"representatives={result['total_representatives']:,}; "
            f"without_representatives={result['components_without_representatives']:,}; "
            f"large_without_representatives={len(result['large_components_without_representatives']):,}; "
            f"deviation={result['allocation_deviation_index']:.4f}; "
            f"elapsed={time.perf_counter() - started:.2f}s"
        )
