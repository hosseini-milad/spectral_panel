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


def _as_label(value):
    try:
        value = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if value in (0, 1) else None


def _largest_remainder_quotas(sizes, total_reps):
    total_nodes = sum(sizes)
    if not sizes or total_nodes <= 0 or total_reps <= 0:
        return [0] * len(sizes)
    exact = [total_reps * size / total_nodes for size in sizes]
    quotas = [math.floor(value) for value in exact]
    remainder = total_reps - sum(quotas)
    order = sorted(
        range(len(sizes)),
        key=lambda i: (exact[i] - quotas[i], sizes[i], -i),
        reverse=True,
    )
    for i in order[:remainder]:
        quotas[i] += 1
    return quotas


def _safe_corr(x, y):
    if len(x) < 2 or np.std(x) <= 1e-12 or np.std(y) <= 1e-12:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def _component_allocation(graph, representative_indices, labels, source_file):
    """
    Preserve the original size-proportional allocation evaluation and add
    attack-aware structural coverage metrics using graph-level node_labels.
    Labels: 0=normal, 1=attack, None=unknown.
    """
    n = graph.number_of_nodes()
    if len(labels) != n:
        raise CommandError(
            f"node_labels length ({len(labels)}) does not match graph nodes ({n})."
        )

    components = sorted(nx.connected_components(graph), key=len, reverse=True)
    node_to_component = {}
    rows = []

    for cid, members in enumerate(components):
        for node in members:
            node_to_component[node] = cid

        member_labels = [labels[node] for node in members]
        known = [value for value in member_labels if value in (0, 1)]
        attack_nodes = sum(value == 1 for value in known)
        normal_nodes = sum(value == 0 for value in known)
        unknown_nodes = len(members) - len(known)

        reps_here = sorted(set(members) & representative_indices)
        attack_reps = [node for node in reps_here if labels[node] == 1]
        normal_reps = [node for node in reps_here if labels[node] == 0]
        unknown_reps = [node for node in reps_here if labels[node] is None]

        if attack_nodes:
            component_type = "ATTACK_PRESENT"
        elif unknown_nodes:
            component_type = "UNKNOWN_LABELS"
        else:
            component_type = "NORMAL_ONLY"

        rows.append({
            "component_id": int(cid),
            "nodes": int(len(members)),
            "attack_nodes": int(attack_nodes),
            "normal_nodes": int(normal_nodes),
            "unknown_label_nodes": int(unknown_nodes),
            "attack_node_ratio_known": (
                float(attack_nodes / len(known)) if known else None
            ),
            "type": component_type,
            "representatives": int(len(reps_here)),
            "attack_representatives": int(len(attack_reps)),
            "normal_representatives": int(len(normal_reps)),
            "unknown_label_representatives": int(len(unknown_reps)),
            "has_any_representative": bool(reps_here),
            "has_attack_representative": bool(attack_reps),
            "is_isolate": bool(
                len(members) == 1 and graph.degree(next(iter(members))) == 0
            ),
        })

    attack_components = [r for r in rows if r["attack_nodes"] > 0]
    attack_with_any = [r for r in attack_components if r["has_any_representative"]]
    attack_with_attack_rep = [
        r for r in attack_components if r["has_attack_representative"]
    ]
    attack_without_any = [
        r for r in attack_components if not r["has_any_representative"]
    ]
    attack_without_attack_rep = [
        r for r in attack_components if not r["has_attack_representative"]
    ]

    total_attack_nodes = sum(r["attack_nodes"] for r in rows)
    attack_nodes_without_any = sum(r["attack_nodes"] for r in attack_without_any)
    attack_nodes_without_attack_rep = sum(
        r["attack_nodes"] for r in attack_without_attack_rep
    )

    isolate_rows = [r for r in rows if r["is_isolate"]]
    attack_isolates = sum(r["attack_nodes"] for r in isolate_rows)
    attack_isolates_with_any = sum(
        r["attack_nodes"] for r in isolate_rows if r["has_any_representative"]
    )
    attack_isolates_with_attack_rep = sum(
        r["attack_nodes"] for r in isolate_rows if r["has_attack_representative"]
    )

    sizes = [r["nodes"] for r in rows]
    total_nodes = graph.number_of_nodes()
    total_reps = len(representative_indices)
    quotas = _largest_remainder_quotas(sizes, total_reps)

    for row, quota in zip(rows, quotas):
        row["expected_representatives_exact"] = (
            total_reps * row["nodes"] / max(1, total_nodes)
        )
        row["expected_representatives_integer"] = int(quota)
        row["allocation_difference"] = (
            row["representatives"] - row["expected_representatives_exact"]
        )
        row["allocation_index"] = (
            (row["representatives"] / max(1, total_reps))
            / (row["nodes"] / max(1, total_nodes))
            if row["nodes"] and total_reps else None
        )

    actual = np.asarray([r["representatives"] for r in rows], dtype=float)
    expected = np.asarray(
        [r["expected_representatives_exact"] for r in rows], dtype=float
    )
    deviation = float(np.abs(actual - expected).sum() / (2 * max(1, total_reps)))

    def rate(numerator, denominator):
        return float(numerator / denominator) if denominator else None

    normal_rep_count = sum(labels[node] == 0 for node in representative_indices)
    attack_rep_count = sum(labels[node] == 1 for node in representative_indices)
    unknown_rep_count = sum(labels[node] is None for node in representative_indices)
    known_labels = sum(value in (0, 1) for value in labels)

    top = rows[:min(10, len(rows))]
    top_nodes = sum(r["nodes"] for r in top)
    top_reps = sum(r["representatives"] for r in top)
    large_cutoff = max(2, math.ceil(total_nodes * 0.01))
    large_missing = [
        r for r in rows
        if r["nodes"] >= large_cutoff and r["representatives"] == 0
    ]

    return {
        "source_file": source_file,
        "layer": 2,
        "label_source": "hyper_graph_metadata.node_labels (0=normal, 1=attack)",
        "method": "component_size_proportional_largest_remainder_plus_attack_coverage",
        "total_components": len(rows),
        "total_nodes": int(total_nodes),
        "total_representatives": int(total_reps),
        "graph_label_resolved_nodes": int(known_labels),
        "graph_label_missing_nodes": int(total_nodes - known_labels),
        "graph_label_resolution_rate": rate(known_labels, total_nodes),
        "representative_labels": {
            "normal": int(normal_rep_count),
            "attack": int(attack_rep_count),
            "unknown": int(unknown_rep_count),
            "attack_ratio": rate(attack_rep_count, total_reps),
        },
        "components_with_representatives": sum(
            r["representatives"] > 0 for r in rows
        ),
        "components_without_representatives": sum(
            r["representatives"] == 0 for r in rows
        ),
        "large_component_cutoff_nodes": int(large_cutoff),
        "large_components_without_representatives": large_missing,
        "under_allocated_components": sum(
            r["representatives"] < r["expected_representatives_integer"]
            for r in rows
        ),
        "over_allocated_components": sum(
            r["representatives"] > r["expected_representatives_integer"]
            for r in rows
        ),
        "proportional_components": sum(
            r["representatives"] == r["expected_representatives_integer"]
            for r in rows
        ),
        "allocation_deviation_index": deviation,
        "size_representative_count_pearson": _safe_corr(
            np.asarray(sizes, dtype=float), actual
        ),
        "top_10_components": {
            "component_count": len(top),
            "nodes": int(top_nodes),
            "node_share": float(top_nodes / max(1, total_nodes)),
            "representatives": int(top_reps),
            "representative_share": float(top_reps / max(1, total_reps)),
            "expected_representatives": float(
                sum(r["expected_representatives_exact"] for r in top)
            ),
        },
        "attack_component_coverage": {
            "total_attack_components": len(attack_components),
            "attack_components_with_any_representative": len(attack_with_any),
            "attack_components_without_any_representative": len(attack_without_any),
            "any_representative_coverage_rate": rate(
                len(attack_with_any), len(attack_components)
            ),
            "any_representative_miss_rate": rate(
                len(attack_without_any), len(attack_components)
            ),
            "attack_components_with_attack_representative": len(
                attack_with_attack_rep
            ),
            "attack_components_without_attack_representative": len(
                attack_without_attack_rep
            ),
            "attack_representative_component_coverage_rate": rate(
                len(attack_with_attack_rep), len(attack_components)
            ),
            "attack_representative_component_miss_rate": rate(
                len(attack_without_attack_rep), len(attack_components)
            ),
            "attack_nodes_total": int(total_attack_nodes),
            "attack_nodes_in_components_without_any_representative": int(
                attack_nodes_without_any
            ),
            "attack_node_mass_miss_rate_any_representative": rate(
                attack_nodes_without_any, total_attack_nodes
            ),
            "attack_nodes_in_components_without_attack_representative": int(
                attack_nodes_without_attack_rep
            ),
            "attack_node_mass_miss_rate_attack_representative": rate(
                attack_nodes_without_attack_rep, total_attack_nodes
            ),
            "attack_isolates": int(attack_isolates),
            "attack_isolates_with_any_representative": int(attack_isolates_with_any),
            "attack_isolates_with_attack_representative": int(
                attack_isolates_with_attack_rep
            ),
            "attack_isolate_miss_rate_any_representative": rate(
                attack_isolates - attack_isolates_with_any, attack_isolates
            ),
            "attack_isolate_miss_rate_attack_representative": rate(
                attack_isolates - attack_isolates_with_attack_rep, attack_isolates
            ),
            "unrepresented_attack_component_details": attack_without_any,
            "no_attack_representative_component_details": attack_without_attack_rep,
        },
        "components": rows,
        "interpretation": [
            "The original size-proportional component allocation metrics are retained.",
            "Attack labels are read positionally from hyper_graph_metadata.node_labels.",
            "Any-representative coverage and attack-representative coverage are distinct.",
            "An attack-containing component with only normal representatives is structurally represented, but not attack-represented.",
            "Attack-node mass miss rate counts attack nodes in components without the specified representative type.",
            "Attack isolates are reported separately.",
            "Unknown labels remain unknown and are not treated as normal.",
            "These are structural preservation metrics, not classifier recall or detection accuracy.",
        ],
    }


def _save_plot(result, path, top_n=30):
    rows = result["components"][:top_n]
    attack = result["attack_component_coverage"]

    fig, axes = plt.subplots(2, 2, figsize=(17, 12))
    fig.suptitle(
        f"Layer 2 Structural & Attack Component Evaluation | {result['source_file']}",
        fontsize=14,
    )

    ax = axes[0, 0]
    x = np.arange(len(rows))
    width = 0.38
    ax.bar(
        x - width / 2,
        [r["expected_representatives_exact"] for r in rows],
        width,
        label="Expected (size proportional)",
    )
    ax.bar(
        x + width / 2,
        [r["representatives"] for r in rows],
        width,
        label="Actual",
    )
    ax.set_xlabel("Component ID (ranked by size)")
    ax.set_ylabel("Representative count")
    ax.set_title(f"Top {len(rows)} components: expected vs actual")
    ax.set_xticks(x)
    ax.set_xticklabels([str(r["component_id"]) for r in rows], rotation=90, fontsize=7)
    ax.legend()

    ax = axes[0, 1]
    sizes = np.asarray([r["nodes"] for r in result["components"]], dtype=float)
    counts = np.asarray(
        [r["representatives"] for r in result["components"]], dtype=float
    )
    attack_present = np.asarray(
        [r["attack_nodes"] > 0 for r in result["components"]], dtype=bool
    )
    no_rep = counts == 0
    ax.scatter(
        sizes[~attack_present], counts[~attack_present],
        alpha=0.55, label="No known attack nodes",
    )
    ax.scatter(
        sizes[attack_present & ~no_rep], counts[attack_present & ~no_rep],
        alpha=0.8, label="Attack component: represented",
    )
    ax.scatter(
        sizes[attack_present & no_rep], counts[attack_present & no_rep],
        marker="x", s=55, label="Attack component: NO representative",
    )
    if len(sizes):
        line_x = np.linspace(max(1, sizes.min()), sizes.max(), 100)
        slope = result["total_representatives"] / max(1, result["total_nodes"])
        ax.plot(line_x, line_x * slope, label="Ideal size-proportional")
    ax.set_xscale("log")
    ax.set_xlabel("Component size (nodes, log scale)")
    ax.set_ylabel("Representative count")
    ax.set_title("Component size vs representatives")
    ax.legend(fontsize=8)

    ax = axes[1, 0]
    coverages = [
        attack["any_representative_coverage_rate"],
        attack["attack_representative_component_coverage_rate"],
    ]
    misses = [
        attack["any_representative_miss_rate"],
        attack["attack_representative_component_miss_rate"],
    ]
    coverage_pct = [v * 100 if v is not None else 0 for v in coverages]
    miss_pct = [v * 100 if v is not None else 0 for v in misses]
    xx = np.arange(2)
    ax.bar(xx, coverage_pct, label="Covered")
    ax.bar(xx, miss_pct, bottom=coverage_pct, label="Missed")
    ax.set_ylim(0, 100)
    ax.set_xticks(xx)
    ax.set_xticklabels(["Any representative", "Attack representative"])
    ax.set_ylabel("Attack-containing components (%)")
    ax.set_title("Attack component coverage")
    ax.legend()

    ax = axes[1, 1]
    isolate_values = [
        attack["attack_isolates_with_any_representative"],
        attack["attack_isolates_with_attack_representative"],
        attack["attack_isolates"] - attack["attack_isolates_with_any_representative"],
    ]
    isolate_labels = [
        "Attack isolates with any rep",
        "Attack isolates with attack rep",
        "Attack isolates without rep",
    ]
    ax.bar(isolate_labels, isolate_values)
    ax.set_title("Attack isolates: representative status")
    ax.set_ylabel("Number of attack isolates")
    ax.tick_params(axis="x", rotation=15)

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)


def _save_summary(result, path):
    attack = result["attack_component_coverage"]
    top = result["top_10_components"]

    def pct(value):
        return "N/A" if value is None else f"{value:.2%}"

    lines = [
        "HIERARCHY STRUCTURAL & ATTACK COMPONENT EVALUATION",
        "=" * 62,
        f"Source: {result['source_file']}",
        f"Method: {result['method']}",
        f"Graph nodes: {result['total_nodes']:,}",
        f"Graph edges: {result['graph_edges']:,}",
        f"Representatives: {result['total_representatives']:,}",
        f"Connected components: {result['total_components']:,}",
        f"Resolved labels: {result['graph_label_resolved_nodes']:,}/"
        f"{result['total_nodes']:,} ({pct(result['graph_label_resolution_rate'])})",
        f"Missing labels: {result['graph_label_missing_nodes']:,}",
        "",
        "REPRESENTATIVE LABELS",
        f"Normal: {result['representative_labels']['normal']:,}",
        f"Attack: {result['representative_labels']['attack']:,}",
        f"Unknown: {result['representative_labels']['unknown']:,}",
        f"Attack ratio: {pct(result['representative_labels']['attack_ratio'])}",
        "",
        "ATTACK COMPONENT COVERAGE",
        f"Attack-containing components: {attack['total_attack_components']:,}",
        f"With any representative: {attack['attack_components_with_any_representative']:,}",
        f"Without any representative: {attack['attack_components_without_any_representative']:,}",
        f"Any-representative coverage: {pct(attack['any_representative_coverage_rate'])}",
        f"Any-representative miss rate: {pct(attack['any_representative_miss_rate'])}",
        f"With attack representative: {attack['attack_components_with_attack_representative']:,}",
        f"Without attack representative: {attack['attack_components_without_attack_representative']:,}",
        f"Attack-representative coverage: {pct(attack['attack_representative_component_coverage_rate'])}",
        f"Attack-representative miss rate: {pct(attack['attack_representative_component_miss_rate'])}",
        "",
        "ATTACK NODE MASS",
        f"Total attack nodes: {attack['attack_nodes_total']:,}",
        f"Attack nodes in components without any representative: "
        f"{attack['attack_nodes_in_components_without_any_representative']:,}",
        f"Attack-node mass miss rate (any representative): "
        f"{pct(attack['attack_node_mass_miss_rate_any_representative'])}",
        f"Attack nodes in components without attack representative: "
        f"{attack['attack_nodes_in_components_without_attack_representative']:,}",
        f"Attack-node mass miss rate (attack representative): "
        f"{pct(attack['attack_node_mass_miss_rate_attack_representative'])}",
        "",
        "ATTACK ISOLATES",
        f"Attack isolates: {attack['attack_isolates']:,}",
        f"With any representative: {attack['attack_isolates_with_any_representative']:,}",
        f"With attack representative: {attack['attack_isolates_with_attack_representative']:,}",
        f"Miss rate (any representative): {pct(attack['attack_isolate_miss_rate_any_representative'])}",
        f"Miss rate (attack representative): {pct(attack['attack_isolate_miss_rate_attack_representative'])}",
        "",
        "ORIGINAL STRUCTURAL ALLOCATION METRICS",
        f"Components with representatives: {result['components_with_representatives']:,}",
        f"Components without representatives: {result['components_without_representatives']:,}",
        f"Large component cutoff (1% of graph): {result['large_component_cutoff_nodes']:,} nodes",
        f"Large components without representatives: "
        f"{len(result['large_components_without_representatives']):,}",
        f"Under-allocated components: {result['under_allocated_components']:,}",
        f"Proportional components: {result['proportional_components']:,}",
        f"Over-allocated components: {result['over_allocated_components']:,}",
        f"Allocation deviation index (0 is ideal): {result['allocation_deviation_index']:.6f}",
        f"Pearson correlation (size vs representative count): "
        f"{result['size_representative_count_pearson']}",
        "",
        "TOP 10 COMPONENTS",
        f"Nodes: {top['nodes']:,} ({top['node_share']:.2%} of graph)",
        f"Representatives: {top['representatives']:,} "
        f"({top['representative_share']:.2%} of representatives)",
        f"Expected representatives: {top['expected_representatives']:.2f}",
        "",
        "ATTACK COMPONENTS WITHOUT ANY REPRESENTATIVE",
        "ID | Nodes | Attack nodes | Normal nodes | Unknown labels",
    ]

    missing_any = attack["unrepresented_attack_component_details"]
    if missing_any:
        for row in missing_any:
            lines.append(
                f"{row['component_id']} | {row['nodes']} | {row['attack_nodes']} | "
                f"{row['normal_nodes']} | {row['unknown_label_nodes']}"
            )
    else:
        lines.append("None")

    lines.extend([
        "",
        "ATTACK COMPONENTS WITHOUT AN ATTACK REPRESENTATIVE",
        "ID | Nodes | Attack nodes | Any reps | Normal reps",
    ])
    missing_attack = attack["no_attack_representative_component_details"]
    if missing_attack:
        for row in missing_attack:
            lines.append(
                f"{row['component_id']} | {row['nodes']} | {row['attack_nodes']} | "
                f"{row['representatives']} | {row['normal_representatives']}"
            )
    else:
        lines.append("None")

    lines.extend([
        "",
        "LARGEST 30 COMPONENTS",
        "ID | Nodes | Attack nodes | Actual reps | Expected reps | Status",
    ])
    for row in result["components"][:30]:
        expected = row["expected_representatives_exact"]
        actual = row["representatives"]
        quota = row["expected_representatives_integer"]
        status = (
            "NO_REPRESENTATIVE" if actual == 0 else
            "UNDER_ALLOCATED" if actual < quota else
            "OVER_ALLOCATED" if actual > quota else "PROPORTIONAL"
        )
        lines.append(
            f"{row['component_id']} | {row['nodes']} | {row['attack_nodes']} | "
            f"{actual} | {expected:.2f} | {status}"
        )

    lines.extend([
        "",
        "NOTES",
        "- The original size-proportional allocation evaluation is retained.",
        "- Labels are read from hyper_graph_metadata.node_labels by node_index.",
        "- Any-representative coverage differs from attack-representative coverage.",
        "- Unknown labels remain unknown; they are not converted to normal.",
        "- These are structural preservation metrics, not classifier recall or detection accuracy.",
    ])
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


class Command(BaseCommand):
    help = (
        "Evaluate hierarchy component allocation and attack-component preservation; "
        "save JSON, PNG and TXT reports."
    )
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

        raw_labels = graph_doc.get("node_labels")
        if raw_labels is None:
            raise CommandError(
                "hyper_graph_metadata.node_labels is missing. "
                "Cannot perform attack-aware evaluation without source labels. "
                "Rebuild hierarchy metadata with node_labels or add labels from "
                "the original graph_representatives lineage."
            )
        if len(raw_labels) != n:
            raise CommandError(
                f"node_labels length ({len(raw_labels)}) does not match node_ids ({n})."
            )
        labels = [_as_label(value) for value in raw_labels]

        reps = list(db["hyper_representatives"].find(
            {"source_file": source_file},
            {"_id": 0, "node_index": 1, "label": 1},
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
                continue
            rep_label = _as_label(rep.get("label"))
            if rep_label is not None and labels[idx] is not None and rep_label != labels[idx]:
                raise CommandError(
                    f"Representative label mismatch at node_index={idx}: "
                    f"hyper_representatives.label={rep_label}, "
                    f"hyper_graph_metadata.node_labels={labels[idx]}."
                )
            rep_indices.add(idx)

        if invalid:
            raise CommandError(f"Found {invalid} invalid representative node_index values.")
        if len(rep_indices) != len(reps):
            raise CommandError("Duplicate representative node_index values detected.")

        graph = nx.Graph()
        graph.add_nodes_from(range(n))
        cursor = db["hyper_graph_edges"].find(
            {"source_file": source_file},
            {"_id": 0, "source": 1, "target": 1},
        ).batch_size(10000)
        try:
            for edge in cursor:
                u, v = int(edge["source"]), int(edge["target"])
                if not (0 <= u < n and 0 <= v < n):
                    raise CommandError(
                        f"Invalid edge endpoint ({u}, {v}) for {n} nodes."
                    )
                graph.add_edge(u, v)
        finally:
            cursor.close()

        expected_edges = int(graph_doc.get("edge_count", graph.number_of_edges()))
        if graph.number_of_edges() != expected_edges:
            raise CommandError(
                "hyper_graph_edges count differs from metadata; incomplete evaluation."
            )

        result = _component_allocation(graph, rep_indices, labels, source_file)
        result.update({
            "graph_edges": graph.number_of_edges(),
            "generated_at_epoch": time.time(),
            "graph_key_node_id_count": len(node_ids),
        })

        match = DAY_RE.search(source_file)
        day = match.group(1) if match else "unknown-day"

        # Keep the prior hierarchy allocation reports untouched. New attack-aware
        # outputs are stored in a dedicated source-specific folder with new names.
        folder = document_directory("hierarchy", source_file, layer=2, day=day)
        folder.mkdir(parents=True, exist_ok=True)
        stem = "component_allocation_attack_aware"

        json_path = folder / f"{stem}.json"
        image_path = folder / f"{stem}.png"
        text_path = folder / f"{stem}.txt"

        json_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _save_plot(result, image_path)
        _save_summary(result, text_path)

        attack = result["attack_component_coverage"]
        self.stdout.write(self.style.SUCCESS(f"[HIER-EVAL] JSON saved: {json_path}"))
        self.stdout.write(self.style.SUCCESS(f"[HIER-EVAL] Diagram saved: {image_path}"))
        self.stdout.write(self.style.SUCCESS(f"[HIER-EVAL] Text saved: {text_path}"))
        self.stdout.write(
            f"[HIER-EVAL] nodes={n:,}; edges={graph.number_of_edges():,}; "
            f"components={result['total_components']:,}; "
            f"representatives={result['total_representatives']:,}; "
            f"attack_components={attack['total_attack_components']:,}; "
            f"without_any_rep={attack['attack_components_without_any_representative']:,}; "
            f"without_attack_rep={attack['attack_components_without_attack_representative']:,}; "
            f"attack_mass_miss_any={attack['attack_node_mass_miss_rate_any_representative']}; "
            f"elapsed={time.perf_counter() - started:.2f}s"
        )
