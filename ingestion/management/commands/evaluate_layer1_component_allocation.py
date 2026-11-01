from ingestion.utils.document_paths import document_directory
import json
import math
import time
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from bson import ObjectId

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from mongoengine.connection import get_db

from ingestion.models.graph_metadata import GraphMetadata
from ingestion.models.graph_representative import GraphRepresentative


def _as_label(value):
    try:
        value = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if value in (0, 1) else None


def _load_node_labels(node_ids, batch_size=750):
    """
    Layer-1 graph node_ids are sampled_security_data document IDs.
    Resolve labels from the source candidate documents; never infer labels
    from representative labels or from component membership.
    """
    db = get_db(alias="default")
    collection = db["sampled_security_data"]
    labels_by_id = {}
    invalid_ids = []

    for start in range(0, len(node_ids), batch_size):
        raw_batch = node_ids[start:start + batch_size]
        object_ids = []
        string_ids = []

        for raw_id in raw_batch:
            text_id = str(raw_id)
            try:
                object_ids.append(ObjectId(text_id))
            except (TypeError, ValueError):
                string_ids.append(raw_id)

        query_values = object_ids + string_ids
        if not query_values:
            continue

        cursor = collection.find(
            {"_id": {"$in": query_values}},
            {"_id": 1, "label": 1, "label_binary": 1},
        )
        for doc in cursor:
            label = _as_label(doc.get("label", doc.get("label_binary")))
            labels_by_id[str(doc["_id"])] = label

    labels = []
    for raw_id in node_ids:
        key = str(raw_id)
        if key not in labels_by_id:
            invalid_ids.append(key)
            labels.append(None)
        else:
            labels.append(labels_by_id[key])

    return labels, invalid_ids


def _largest_remainder_quotas(component_sizes, total_representatives):
    total_nodes = sum(component_sizes)
    if not component_sizes or total_nodes <= 0 or total_representatives <= 0:
        return [0] * len(component_sizes)

    exact = [total_representatives * size / total_nodes for size in component_sizes]
    quotas = [math.floor(value) for value in exact]
    remainder = total_representatives - sum(quotas)
    order = sorted(
        range(len(component_sizes)),
        key=lambda i: (exact[i] - quotas[i], component_sizes[i], -i),
        reverse=True,
    )
    for index in order[:remainder]:
        quotas[index] += 1
    return [int(value) for value in quotas]


def _safe_corr(x, y):
    if len(x) < 2:
        return None
    if np.std(x) <= 1e-12 or np.std(y) <= 1e-12:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def _build_graph(graph_doc):
    node_ids = list(graph_doc.node_ids or [])
    if not node_ids:
        raise CommandError("graph_metadata.node_ids is empty.")

    G = nx.Graph()
    G.add_nodes_from(range(len(node_ids)))

    edges = graph_doc.edges or []
    for edge in edges:
        try:
            source = int(edge["source"])
            target = int(edge["target"])
            weight = float(edge.get("weight", 1.0))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise CommandError(f"Invalid graph edge: {exc}") from exc

        if not (0 <= source < len(node_ids) and 0 <= target < len(node_ids)):
            raise CommandError(
                f"Edge endpoint ({source}, {target}) is outside node range "
                f"0..{len(node_ids)-1}."
            )
        if source == target:
            G.add_node(source)
        else:
            G.add_edge(source, target, weight=weight if math.isfinite(weight) else 1.0)

    if G.number_of_edges() != len(edges):
        raise CommandError(
            "Duplicate edges detected in graph_metadata.edges; refusing to "
            "evaluate a topology different from the stored graph."
        )
    return node_ids, G


def _evaluate(graph_doc, representatives, source_file):
    node_ids, G = _build_graph(graph_doc)
    labels, missing_label_ids = _load_node_labels(node_ids)

    selected = set()
    for rep in representatives:
        try:
            index = int(rep.node_index)
        except (TypeError, ValueError, OverflowError):
            raise CommandError(f"Invalid representative node_index: {rep.node_index!r}")
        if not 0 <= index < len(node_ids):
            raise CommandError(
                f"Representative node_index={index} outside graph node range."
            )
        if index in selected:
            raise CommandError(f"Duplicate representative node_index={index}.")
        selected.add(index)

    if not selected:
        raise CommandError("No valid representatives found.")

    components = sorted(nx.connected_components(G), key=len, reverse=True)
    node_to_component = {}
    rows = []

    for component_id, members in enumerate(components):
        for node in members:
            node_to_component[node] = component_id

        member_labels = [labels[node] for node in members]
        known = [value for value in member_labels if value in (0, 1)]
        attack_nodes = sum(value == 1 for value in known)
        normal_nodes = sum(value == 0 for value in known)
        unknown_nodes = len(members) - len(known)

        if attack_nodes:
            component_type = "ATTACK_PRESENT"
        elif unknown_nodes:
            component_type = "UNKNOWN_LABELS"
        else:
            component_type = "NORMAL_ONLY"

        reps_here = sorted(set(members) & selected)
        attack_reps = [node for node in reps_here if labels[node] == 1]
        normal_reps = [node for node in reps_here if labels[node] == 0]
        unknown_reps = [node for node in reps_here if labels[node] is None]

        rows.append({
            "component_id": int(component_id),
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
            "is_isolate": bool(len(members) == 1 and G.degree(next(iter(members))) == 0),
        })

    attack_components = [r for r in rows if r["attack_nodes"] > 0]
    attack_components_with_any_rep = [
        r for r in attack_components if r["has_any_representative"]
    ]
    attack_components_with_attack_rep = [
        r for r in attack_components if r["has_attack_representative"]
    ]
    attack_components_without_any_rep = [
        r for r in attack_components if not r["has_any_representative"]
    ]
    attack_components_without_attack_rep = [
        r for r in attack_components if not r["has_attack_representative"]
    ]

    total_known_attack_nodes = sum(r["attack_nodes"] for r in rows)
    attack_nodes_in_components_without_any_rep = sum(
        r["attack_nodes"] for r in attack_components_without_any_rep
    )
    attack_nodes_in_components_without_attack_rep = sum(
        r["attack_nodes"] for r in attack_components_without_attack_rep
    )

    isolate_rows = [r for r in rows if r["is_isolate"]]
    attack_isolates = sum(r["attack_nodes"] for r in isolate_rows)
    represented_attack_isolates = sum(
        r["attack_nodes"] for r in isolate_rows if r["has_attack_representative"]
    )
    represented_any_attack_isolates = sum(
        r["attack_nodes"] for r in isolate_rows if r["has_any_representative"]
    )

    sizes = [r["nodes"] for r in rows]
    quotas = _largest_remainder_quotas(sizes, len(selected))
    for row, quota in zip(rows, quotas):
        row["expected_representatives_exact"] = (
            len(selected) * row["nodes"] / max(1, len(node_ids))
        )
        row["expected_representatives_integer"] = int(quota)
        row["allocation_difference"] = (
            row["representatives"] - row["expected_representatives_exact"]
        )

    actual = np.asarray([r["representatives"] for r in rows], dtype=float)
    expected = np.asarray(
        [r["expected_representatives_exact"] for r in rows], dtype=float
    )
    deviation = float(np.abs(actual - expected).sum() / (2 * max(1, len(selected))))

    known_count = len(node_ids) - len(missing_label_ids)
    attack_rep_count = sum(labels[node] == 1 for node in selected)
    normal_rep_count = sum(labels[node] == 0 for node in selected)
    unknown_rep_count = sum(labels[node] is None for node in selected)

    def rate(numerator, denominator):
        return float(numerator / denominator) if denominator else None

    return {
        "source_file": source_file,
        "layer": 1,
        "label_source": "siem_db.sampled_security_data.label (fallback: label_binary)",
        "graph": {
            "nodes": len(node_ids),
            "edges": G.number_of_edges(),
            "components": len(components),
            "isolates": len(isolate_rows),
            "label_resolved_nodes": known_count,
            "label_missing_nodes": len(missing_label_ids),
            "label_resolution_rate": rate(known_count, len(node_ids)),
        },
        "representatives": {
            "total": len(selected),
            "normal": normal_rep_count,
            "attack": attack_rep_count,
            "unknown_label": unknown_rep_count,
            "attack_ratio": rate(attack_rep_count, len(selected)),
        },
        "attack_component_coverage": {
            "total_attack_components": len(attack_components),
            "attack_components_with_any_representative": len(attack_components_with_any_rep),
            "attack_components_without_any_representative": len(attack_components_without_any_rep),
            "any_representative_coverage_rate": rate(
                len(attack_components_with_any_rep), len(attack_components)
            ),
            "any_representative_miss_rate": rate(
                len(attack_components_without_any_rep), len(attack_components)
            ),
            "attack_components_with_attack_representative": len(
                attack_components_with_attack_rep
            ),
            "attack_components_without_attack_representative": len(
                attack_components_without_attack_rep
            ),
            "attack_representative_component_coverage_rate": rate(
                len(attack_components_with_attack_rep), len(attack_components)
            ),
            "attack_representative_component_miss_rate": rate(
                len(attack_components_without_attack_rep), len(attack_components)
            ),
            "attack_nodes_total": total_known_attack_nodes,
            "attack_nodes_in_components_without_any_representative": (
                attack_nodes_in_components_without_any_rep
            ),
            "attack_node_mass_miss_rate_any_representative": rate(
                attack_nodes_in_components_without_any_rep,
                total_known_attack_nodes,
            ),
            "attack_nodes_in_components_without_attack_representative": (
                attack_nodes_in_components_without_attack_rep
            ),
            "attack_node_mass_miss_rate_attack_representative": rate(
                attack_nodes_in_components_without_attack_rep,
                total_known_attack_nodes,
            ),
            "attack_isolates": attack_isolates,
            "attack_isolates_with_any_representative": represented_any_attack_isolates,
            "attack_isolates_with_attack_representative": represented_attack_isolates,
            "attack_isolate_miss_rate_any_representative": rate(
                attack_isolates - represented_any_attack_isolates, attack_isolates
            ),
            "attack_isolate_miss_rate_attack_representative": rate(
                attack_isolates - represented_attack_isolates, attack_isolates
            ),
            "unrepresented_attack_component_details": attack_components_without_any_rep,
            "no_attack_representative_component_details": attack_components_without_attack_rep,
        },
        "allocation": {
            "components_with_representatives": sum(r["representatives"] > 0 for r in rows),
            "components_without_representatives": sum(r["representatives"] == 0 for r in rows),
            "allocation_deviation_index": deviation,
            "size_representative_count_pearson": _safe_corr(
                np.asarray(sizes, dtype=float), actual
            ),
            "top_30_components": rows[:30],
        },
        "components": rows,
        "missing_label_node_ids_sample": missing_label_ids[:100],
        "interpretation": [
            "Any-representative component coverage and attack-representative coverage are reported separately.",
            "An attack-containing component with only a normal representative counts as structurally represented, but not attack-represented.",
            "Attack-node mass miss rate counts attack nodes located in components with no representative of the specified kind.",
            "Attack isolates are reported separately; a single-node component can be represented if that node is selected.",
            "Unknown labels are not silently treated as normal.",
            "Component coverage is not equivalent to classification recall or detection accuracy.",
        ],
    }


def _save_dashboard(results, image_path):
    rows = results["components"]
    top = rows[:min(30, len(rows))]
    attack = results["attack_component_coverage"]

    fig, axes = plt.subplots(2, 2, figsize=(17, 12))
    fig.suptitle(
        f"Layer 1 Structural & Attack Component Evaluation | {results['source_file']}",
        fontsize=14,
    )

    ax = axes[0, 0]
    ids = [r["component_id"] for r in top]
    expected = [r["expected_representatives_exact"] for r in top]
    actual = [r["representatives"] for r in top]
    x = np.arange(len(ids))
    width = 0.38
    ax.bar(x - width / 2, expected, width, label="Expected (size proportional)")
    ax.bar(x + width / 2, actual, width, label="Actual")
    ax.set_title("Top 30 components: expected vs actual")
    ax.set_xlabel("Component ID (ranked by size)")
    ax.set_ylabel("Representative count")
    ax.set_xticks(x)
    ax.set_xticklabels(ids, rotation=90, fontsize=7)
    ax.legend()

    ax = axes[0, 1]
    sizes = np.asarray([r["nodes"] for r in rows], dtype=float)
    counts = np.asarray([r["representatives"] for r in rows], dtype=float)
    attack_present = np.asarray([r["attack_nodes"] > 0 for r in rows])
    no_rep = counts == 0
    ax.scatter(sizes[~attack_present], counts[~attack_present],
               alpha=0.55, label="No known attack nodes")
    ax.scatter(sizes[attack_present & ~no_rep], counts[attack_present & ~no_rep],
               alpha=0.8, label="Attack component: represented")
    ax.scatter(sizes[attack_present & no_rep], counts[attack_present & no_rep],
               marker="x", s=55, label="Attack component: NO representative")
    if len(sizes):
        line_x = np.linspace(max(1, sizes.min()), sizes.max(), 100)
        slope = results["representatives"]["total"] / max(1, results["graph"]["nodes"])
        ax.plot(line_x, line_x * slope, label="Ideal size-proportional")
    ax.set_xscale("log")
    ax.set_title("Component size vs representatives")
    ax.set_xlabel("Component size (log scale)")
    ax.set_ylabel("Representative count")
    ax.legend(fontsize=8)

    ax = axes[1, 0]
    labels = [
        "Any representative",
        "Attack representative",
    ]
    coverage = [
        attack["any_representative_coverage_rate"],
        attack["attack_representative_component_coverage_rate"],
    ]
    misses = [
        attack["any_representative_miss_rate"],
        attack["attack_representative_component_miss_rate"],
    ]
    coverage_values = [v * 100 if v is not None else 0 for v in coverage]
    miss_values = [v * 100 if v is not None else 0 for v in misses]
    xx = np.arange(2)
    ax.bar(xx, coverage_values, label="Covered")
    ax.bar(xx, miss_values, bottom=coverage_values, label="Missed")
    ax.set_ylim(0, 100)
    ax.set_xticks(xx)
    ax.set_xticklabels(labels)
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
    Path(image_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(image_path, dpi=170, bbox_inches="tight")
    plt.close(fig)


def _save_summary(results, text_path):
    graph = results["graph"]
    reps = results["representatives"]
    attack = results["attack_component_coverage"]
    allocation = results["allocation"]

    def pct(value):
        return "N/A" if value is None else f"{value:.2%}"

    lines = [
        "LAYER 1 STRUCTURAL & ATTACK COMPONENT EVALUATION",
        "=" * 64,
        f"Source: {results['source_file']}",
        "",
        "GRAPH",
        f"Nodes: {graph['nodes']:,}",
        f"Edges: {graph['edges']:,}",
        f"Components: {graph['components']:,}",
        f"Isolates: {graph['isolates']:,}",
        f"Resolved labels: {graph['label_resolved_nodes']:,}/{graph['nodes']:,} "
        f"({pct(graph['label_resolution_rate'])})",
        f"Missing labels: {graph['label_missing_nodes']:,}",
        "",
        "REPRESENTATIVES",
        f"Total: {reps['total']:,}",
        f"Normal: {reps['normal']:,}",
        f"Attack: {reps['attack']:,}",
        f"Unknown label: {reps['unknown_label']:,}",
        "",
        "ATTACK COMPONENT COVERAGE",
        f"Attack-containing components: {attack['total_attack_components']:,}",
        f"With any representative: {attack['attack_components_with_any_representative']:,}",
        f"Without any representative: {attack['attack_components_without_any_representative']:,}",
        f"Any-representative coverage: {pct(attack['any_representative_coverage_rate'])}",
        f"Any-representative miss rate: {pct(attack['any_representative_miss_rate'])}",
        f"With attack representative: {attack['attack_components_with_attack_representative']:,}",
        f"Without attack representative: {attack['attack_components_without_attack_representative']:,}",
        f"Attack-representative component coverage: "
        f"{pct(attack['attack_representative_component_coverage_rate'])}",
        f"Attack-representative component miss rate: "
        f"{pct(attack['attack_representative_component_miss_rate'])}",
        "",
        "ATTACK NODE MASS",
        f"Total known attack nodes: {attack['attack_nodes_total']:,}",
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
        f"Miss rate (any representative): "
        f"{pct(attack['attack_isolate_miss_rate_any_representative'])}",
        f"Miss rate (attack representative): "
        f"{pct(attack['attack_isolate_miss_rate_attack_representative'])}",
        "",
        "STRUCTURAL ALLOCATION",
        f"Components with representatives: {allocation['components_with_representatives']:,}",
        f"Components without representatives: {allocation['components_without_representatives']:,}",
        f"Allocation deviation index: {allocation['allocation_deviation_index']:.6f}",
        f"Size/representative Pearson correlation: "
        f"{allocation['size_representative_count_pearson']}",
        "",
        "ATTACK COMPONENTS WITHOUT ANY REPRESENTATIVE",
        "ID | Nodes | Attack nodes | Normal nodes | Unknown labels",
    ]

    missing = attack["unrepresented_attack_component_details"]
    if missing:
        for row in missing:
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
    no_attack_rep = attack["no_attack_representative_component_details"]
    if no_attack_rep:
        for row in no_attack_rep:
            lines.append(
                f"{row['component_id']} | {row['nodes']} | {row['attack_nodes']} | "
                f"{row['representatives']} | {row['normal_representatives']}"
            )
    else:
        lines.append("None")

    lines.extend([
        "",
        "NOTES",
        "- Labels are loaded from sampled_security_data by graph node ID.",
        "- Missing labels remain unknown; they are not converted to normal.",
        "- Any representative coverage differs from attack-representative coverage.",
        "- Attack-node mass miss rate counts attack nodes in components with no representative.",
        "- These are structural preservation metrics, not classifier recall or detection accuracy.",
    ])
    Path(text_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


class Command(BaseCommand):
    help = (
        "Evaluate layer-1 component allocation and attack-component preservation; "
        "save JSON, PNG and TXT reports."
    )
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-file",
            required=True,
            help="Exact layer-1 graph key, e.g. clustered-day-2026-06-21-chunk-0",
        )

    def handle(self, *args, **options):
        started = time.perf_counter()
        source_file = options["source_file"].strip()
        if not source_file:
            raise CommandError("--source-file cannot be empty.")

        graph = (
            GraphMetadata.objects(source_file=source_file)
            .order_by("-created_at")
            .first()
        )
        if graph is None:
            raise CommandError(f"GraphMetadata not found: {source_file}")

        representatives = list(
            GraphRepresentative.objects(source_file=source_file)
        )
        if not representatives:
            raise CommandError(f"No representatives found: {source_file}")

        self.stdout.write(
            f"[L1-ATTACK-EVAL] source_file={source_file}; "
            f"nodes={len(graph.node_ids or [])}; edges={len(graph.edges or [])}; "
            f"representatives={len(representatives)}"
        )

        results = _evaluate(graph, representatives, source_file)
        # Keep each graph/chunk evaluation in its own directory.
        # Example: files/evaluation/clustered-day-2026-06-21-chunk-0/
        output_dir = document_directory("component", source_file)
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = "component_allocation"

        json_path = output_dir / f"{stem}.json"
        image_path = output_dir / f"{stem}.png"
        text_path = output_dir / f"{stem}.txt"

        json_path.write_text(
            json.dumps(results, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _save_dashboard(results, image_path)
        _save_summary(results, text_path)

        attack = results["attack_component_coverage"]
        self.stdout.write(self.style.SUCCESS(f"[L1-ATTACK-EVAL] JSON: {json_path}"))
        self.stdout.write(self.style.SUCCESS(f"[L1-ATTACK-EVAL] PNG: {image_path}"))
        self.stdout.write(self.style.SUCCESS(f"[L1-ATTACK-EVAL] TXT: {text_path}"))
        self.stdout.write(
            f"[L1-ATTACK-EVAL] attack_components="
            f"{attack['total_attack_components']}; "
            f"without_any_rep={attack['attack_components_without_any_representative']}; "
            f"without_attack_rep={attack['attack_components_without_attack_representative']}; "
            f"attack_mass_miss_any="
            f"{attack['attack_node_mass_miss_rate_any_representative']}; "
            f"elapsed={time.perf_counter() - started:.1f}s"
        )
