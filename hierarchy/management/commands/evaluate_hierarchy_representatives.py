import json
import math
import os
import re
import time
from collections import Counter, deque
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from mongoengine import get_connection
from scipy.spatial import cKDTree
from bson import ObjectId


DAY_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _safe_label(value):
    try:
        value = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if value in (0, 1) else None


def _f1_for_label(y_true, y_pred, label):
    tp = sum(a == label and b == label for a, b in zip(y_true, y_pred))
    fp = sum(a != label and b == label for a, b in zip(y_true, y_pred))
    fn = sum(a == label and b != label for a, b in zip(y_true, y_pred))
    denom = 2 * tp + fp + fn
    return (2 * tp / denom) if denom else 0.0


def _classification_metrics(y_true, y_pred):
    if not y_true:
        return {"accuracy": None, "macro_f1": None, "weighted_f1": None, "evaluated_nodes": 0}
    accuracy = sum(a == b for a, b in zip(y_true, y_pred)) / len(y_true)
    f1_0 = _f1_for_label(y_true, y_pred, 0)
    f1_1 = _f1_for_label(y_true, y_pred, 1)
    supports = Counter(y_true)
    weighted = (f1_0 * supports[0] + f1_1 * supports[1]) / len(y_true)
    return {
        "accuracy": float(accuracy),
        "macro_f1": float((f1_0 + f1_1) / 2),
        "weighted_f1": float(weighted),
        "normal_f1": float(f1_0),
        "attack_f1": float(f1_1),
        "evaluated_nodes": len(y_true),
    }


def _float_or_none(value):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _top_decile(values, eligible_nodes=None):
    """Return actual highest-ranked 10% of valid values (not tied quantile)."""
    eligible = set(eligible_nodes) if eligible_nodes is not None else None
    items = [(i, v) for i, v in values.items()
             if v is not None and (eligible is None or i in eligible)]
    if not items or max(v for _, v in items) - min(v for _, v in items) <= 1e-12:
        return set()
    count = max(1, math.ceil(0.10 * len(items)))
    return {i for i, _ in sorted(items, key=lambda x: (-x[1], x[0]))[:count]}


def _retention_audit(values, selected, eligible_nodes=None):
    eligible = set(eligible_nodes) if eligible_nodes is not None else None
    scored = {i: v for i, v in values.items() if v is not None
              and (eligible is None or i in eligible)}
    top = _top_decile(scored)
    chosen = top & selected
    return {
        "scored_nodes": len(scored),
        "ranking_available": bool(top),
        "top_decile_nodes": len(top),
        "top_decile_selected": len(chosen),
        "top_decile_recall": len(chosen) / len(top) if top else None,
        "top_decile_precision_among_selected": (
            len(chosen) / len(selected & set(scored)) if selected & set(scored) else None
        ),
        "top_decile_selection_rate": len(chosen) / len(top) if top else None,
    }


def _load_parent_context(db, node_ids, feature_fields):
    """Resolve hierarchy node -> layer-1 representative -> sampled document.

    Never assume hierarchy node_ids are sampled document IDs: they are IDs
    of graph_representatives documents in the current layer-2 schema.
    """
    parent_col = db["graph_representatives"]
    sampled_col = db["sampled_security_data"]

    node_oid = {}
    for i, val in enumerate(node_ids):
        try:
            node_oid[i] = ObjectId(str(val))
        except (TypeError, ValueError):
            continue
    parents = {}
    pairs = list(node_oid.items())
    for st in range(0, len(pairs), 750):
        batch = [oid for _, oid in pairs[st:st+750]]
        for d in parent_col.find({"_id": {"$in": batch}}, {"_id": 1, "original_id": 1, "source_file": 1}):
            parents[str(d["_id"])] = d

    sampled_ids = {}
    missing_parent = 0
    for i, oid in node_oid.items():
        parent = parents.get(str(oid))
        if not parent or not parent.get("original_id"):
            missing_parent += 1
            continue
        try:
            sampled_ids[i] = ObjectId(str(parent["original_id"]))
        except (TypeError, ValueError):
            missing_parent += 1

    projection = {field: 1 for field in feature_fields}
    projection.update({"_id": 1, "flow_file": 1, "threat_intel_score": 1,
                       "source_file": 1, "flow_start": 1})
    samples = {}
    vals = list(sampled_ids.values())
    for st in range(0, len(vals), 750):
        for d in sampled_col.find({"_id": {"$in": vals[st:st+750]}}, projection):
            samples[str(d["_id"])] = d

    context = {}
    for i, oid in sampled_ids.items():
        sample = samples.get(str(oid))
        if sample is not None:
            context[i] = sample
    return context, {
        "node_count": len(node_ids),
        "resolved_parent_records": len(parents),
        "missing_parent_records": len(node_ids) - len(sampled_ids),
        "resolved_sampled_records": len(context),
        "missing_sampled_records": len(sampled_ids) - len(context),
    }


def _enrichment_metrics(db, node_ids, graph_doc, selected, G):
    feature_fields = (graph_doc.get("graph_parameters") or {}).get("feature_fields") or []
    # threat_intel_score is evaluated separately; exclude it from novelty distance.
    novelty_fields = [f for f in feature_fields if f != "threat_intel_score"]
    context, provenance = _load_parent_context(db, node_ids, novelty_fields)
    if not context:
        return {
            "provenance": provenance, "available": False,
            "reason": "Cannot resolve hierarchy parent representatives to sampled records",
        }

    flows = {i: str(d.get("flow_file") or "").strip()
             for i, d in context.items() if d.get("flow_file")}
    full_flows = set(flows.values())
    selected_flows = {flows[i] for i in selected if i in flows}
    flow_counts = Counter(flows.values())
    unique_flow_nodes = {i for i, f in flows.items() if flow_counts[f] == 1}
    risk = {i: _float_or_none(d.get("threat_intel_score"))
            for i, d in context.items()}
    risk = {i: v for i, v in risk.items() if v is not None}

    novelty = {}
    active_fields = []
    if len(context) >= 3 and novelty_fields:
        indices = sorted(context)
        X = np.array([[(_float_or_none(context[i].get(f)) or 0.0)
                       for f in novelty_fields] for i in indices], dtype=np.float64)
        variances = np.std(X, axis=0)
        active = variances > 1e-12
        if np.any(active):
            active_fields = [f for f, keep in zip(novelty_fields, active) if keep]
            X = X[:, active]
            # Inputs are already normalized; use Euclidean NN in this fixed
            # feature space as a transparent novelty proxy, not anomaly truth.
            distances, _ = cKDTree(X).query(X, k=2)
            local_distances = distances[:, 1]
            for idx, v in zip(indices, local_distances):
                novelty[idx] = float(v)

    articulation = set(nx.articulation_points(G))
    selected_articulation = articulation & selected
    return {
        "available": True,
        "provenance": provenance,
        "flow_coverage": {
            "known_flow_nodes": len(flows),
            "unknown_flow_nodes": len(node_ids) - len(flows),
            "total_distinct_flow_files": len(full_flows),
            "selected_distinct_flow_files": len(selected_flows),
            "flow_file_coverage_fraction": len(selected_flows) / len(full_flows) if full_flows else None,
            "flow_files_without_representatives": len(full_flows - selected_flows),
            "single_occurrence_flow_nodes": len(unique_flow_nodes),
            "single_occurrence_flow_nodes_selected": len(unique_flow_nodes & selected),
            "single_occurrence_flow_recall": (
                len(unique_flow_nodes & selected) / len(unique_flow_nodes) if unique_flow_nodes else None
            ),
        },
        "risk_preservation": {
            **_retention_audit(risk, selected),
            "source_field": "threat_intel_score (sampled normalized value)",
            "interpretation": "Ranking proxy; not a calibrated attack probability",
        },
        "local_novelty_preservation": {
            **_retention_audit(novelty, selected),
            "feature_count": len(active_fields),
            "method": "nearest-neighbor Euclidean distance in normalized features (risk excluded)",
            "interpretation": "Feature-space rarity proxy, not a confirmed anomaly",
        },
        "structural_chain_proxy": {
            "method": "articulation points in undirected similarity graph",
            "articulation_points": len(articulation),
            "articulation_points_selected": len(selected_articulation),
            "articulation_recall": len(selected_articulation) / len(articulation) if articulation else None,
            "interpretation": "Connectivity sensitivity only; does NOT prove attack-chain continuity",
        },
    }


def _nearest_label_proxy(G, labels, selected):
    """Exclude representatives, unreachable nodes and mixed-label shortest ties."""
    masks = [0] * G.number_of_nodes()
    distances = [-1] * G.number_of_nodes()
    queue = deque()
    for source in sorted(selected):
        if source not in labels:
            continue
        distances[source] = 0
        masks[source] = 1 << labels[source]
        queue.append(source)

    while queue:
        node = queue.popleft()
        for neighbor in G[node]:
            candidate_distance = distances[node] + 1
            if distances[neighbor] == -1:
                distances[neighbor] = candidate_distance
                masks[neighbor] = masks[node]
                queue.append(neighbor)
            elif distances[neighbor] == candidate_distance:
                expanded = masks[neighbor] | masks[node]
                if expanded != masks[neighbor]:
                    masks[neighbor] = expanded
                    queue.append(neighbor)

    eligible = [i for i in range(len(distances))
                if i in labels and i not in selected and masks[i] in (1, 2)]
    y_true = [labels[i] for i in eligible]
    y_pred = [0 if masks[i] == 1 else 1 for i in eligible]
    result = _classification_metrics(y_true, y_pred)
    result.update({
        "excluded_selected_nodes": len(selected),
        "excluded_unreachable_nodes": sum(d == -1 for d in distances),
        "excluded_tied_nearest_label_nodes": sum(
            masks[i] == 3 for i in range(len(masks)) if i not in selected
        ),
        "method": "minimum unweighted hop distance, exclude tied labels",
    })
    return result


def _save_dashboard(results, output_path):
    graph = results["graph"]
    coverage = results["coverage"]
    degree = results["degree_distribution"]
    components = results["components"]
    classes = results["class_balance"]

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    fig.suptitle(f"Hierarchy Representative Evaluation | {results['source_file']}", fontsize=13)

    ax = axes[0, 0]
    sizes = components["largest_component_sizes"]
    if sizes:
        ax.bar(range(1, len(sizes) + 1), sizes)
        ax.set_xlabel("Component rank")
        ax.set_ylabel("Nodes")
        ax.set_title("Largest connected components")
    else:
        ax.text(0.5, 0.5, "No components", ha="center", va="center")

    ax = axes[0, 1]
    hist = degree.get("histogram", {})
    if hist:
        keys = list(hist.keys())
        ax.bar([int(k) for k in keys], [hist[k] for k in keys], width=0.85)
        ax.set_xlabel("Node degree")
        ax.set_ylabel("Number of nodes")
        ax.set_title("Degree distribution (capped display)")
    else:
        ax.text(0.5, 0.5, "No degree data", ha="center", va="center")

    ax = axes[1, 0]
    labels = ["Normal", "Attack"]
    graph_vals = [classes["graph"].get("normal", 0), classes["graph"].get("attack", 0)]
    rep_vals = [classes["representatives"].get("normal", 0), classes["representatives"].get("attack", 0)]
    x = np.arange(2)
    width = 0.36
    ax.bar(x - width / 2, graph_vals, width, label="Full graph")
    ax.bar(x + width / 2, rep_vals, width, label="Representatives")
    ax.set_xticks(x, labels)
    ax.set_ylabel("Count")
    ax.set_title("Class balance")
    ax.legend()

    ax = axes[1, 1]
    metric_names = ["Reachable", "1-hop", "2-hop", "Component"]
    metric_values = [
        coverage.get("reachable_fraction", 0),
        coverage.get("one_hop_fraction", 0),
        coverage.get("two_hop_fraction", 0),
        coverage.get("component_coverage_fraction", 0),
    ]
    ax.bar(metric_names, [v * 100 for v in metric_values])
    ax.set_ylim(0, 100)
    ax.set_ylabel("Percent")
    ax.set_title("Representative coverage")
    ax.tick_params(axis="x", rotation=15)

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _save_summary(results, output_path):
    g = results["graph"]
    c = results["components"]
    cov = results["coverage"]
    d = results["degree_distribution"]
    classes = results["class_balance"]
    proxy = results["nearest_representative_label_proxy"]
    lines = [
        "HIERARCHY REPRESENTATIVE EVALUATION",
        "=" * 44,
        f"Source: {results['source_file']}",
        f"Graph: {g['nodes']:,} nodes, {g['edges']:,} edges",
        f"Density: {g['density']:.6f}",
        f"Components: {c['count']:,} | Isolates: {g['isolates']:,}",
        f"Representatives: {results['representatives']['count']:,} ({results['representatives']['ratio']:.1%})",
        f"Normal / Attack representatives: {classes['representatives'].get('normal', 0)} / {classes['representatives'].get('attack', 0)}",
        "",
        "COVERAGE",
        f"Reachable: {cov['reachable_fraction']:.1%}",
        f"1-hop: {cov['one_hop_fraction']:.1%}",
        f"2-hop: {cov['two_hop_fraction']:.1%}",
        f"Component coverage: {cov['component_coverage_fraction']:.1%}",
        f"Mean hops to nearest representative: {cov['mean_hops']}",
        f"Max hops to nearest representative: {cov['max_hops']}",
        "",
        "STRUCTURE",
        f"Largest component: {c['largest_component_size']:,} nodes",
        f"Top 10 component sizes: {c['largest_component_sizes']}",
        f"Representative-free components: {c['components_without_representatives']:,}",
        f"Representatives in induced subgraph: {results['representative_subgraph']['edges']:,} edges; {results['representative_subgraph']['components']:,} components; {results['representative_subgraph']['isolates']:,} isolates",
        f"Cross-label edge fraction: {results['cross_label_edge_fraction']:.4%}" if results['cross_label_edge_fraction'] is not None else "Cross-label edge fraction: unavailable",
        f"Degree mean / median / p95 / max: {d['mean']:.2f} / {d['median']:.2f} / {d['p95']:.2f} / {d['max']}",
        "",
        "NEAREST-REPRESENTATIVE LABEL PROXY",
        f"Accuracy: {proxy.get('accuracy')}",
        f"Macro-F1: {proxy.get('macro_f1')}",
        f"Weighted-F1: {proxy.get('weighted_f1')}",
        "This proxy is not the F1 score of a downstream classifier.",
        "",
        "FLOW / RISK / NOVELTY / STRUCTURAL BRIDGES",
        f"Flow coverage: {results.get('enrichment', {}).get('flow_coverage', {}).get('flow_file_coverage_fraction')}",
        f"Top-risk decile recall: {results.get('enrichment', {}).get('risk_preservation', {}).get('top_decile_recall')}",
        f"Top-novelty decile recall: {results.get('enrichment', {}).get('local_novelty_preservation', {}).get('top_decile_recall')}",
        f"Articulation-point recall: {results.get('enrichment', {}).get('structural_chain_proxy', {}).get('articulation_recall')}",
        "Articulation points are not evidence of a true attack chain.",
        "Interpret metrics jointly. High label-proxy scores do not guarantee structural coverage.",
    ]
    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


class Command(BaseCommand):
    help = "Evaluate hierarchy graph representatives and save JSON, PNG and TXT reports."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--source-file", required=True)
        parser.add_argument("--output", default=None, help="Optional output JSON path.")

    def handle(self, *args, **options):
        started = time.perf_counter()
        source_file = options["source_file"].strip()
        if not source_file:
            raise CommandError("--source-file cannot be empty.")

        db = get_connection(alias="default")["siem_db"]
        graph_doc = db["hyper_graph_metadata"].find_one({"source_file": source_file, "status": "complete"})
        if graph_doc is None:
            raise CommandError(f"Completed hierarchy graph not found: {source_file}")

        node_ids = list(graph_doc.get("node_ids") or [])
        raw_labels = list(graph_doc.get("node_labels") or [])
        n = len(node_ids)
        if n == 0:
            raise CommandError("Graph metadata has no node_ids.")

        labels = {}
        for i in range(n):
            label = _safe_label(raw_labels[i]) if i < len(raw_labels) else None
            if label is not None:
                labels[i] = label

        reps = list(db["hyper_representatives"].find(
            {"source_file": source_file},
            {"_id": 0, "node_index": 1, "label": 1, "centrality": 1, "attention": 1, "component_id": 1},
        ))
        if not reps:
            raise CommandError(f"No hyper_representatives found for {source_file}")

        rep_labels = {}
        for rep in reps:
            try:
                idx = int(rep["node_index"])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if 0 <= idx < n:
                label = _safe_label(rep.get("label"))
                if label is not None:
                    rep_labels[idx] = label
        if not rep_labels:
            raise CommandError("No valid representative node_index values found.")
        if len(rep_labels) != len(reps):
            raise CommandError("Duplicate/invalid representative node_index or label; refusing inaccurate evaluation.")
        if len(labels) != n:
            raise CommandError("Graph metadata lacks labels for some nodes; evaluation requires complete node_labels.")
        for idx, label in rep_labels.items():
            if labels[idx] != label:
                raise CommandError(f"Representative label mismatch for node {idx}.")

        G = nx.Graph()
        G.add_nodes_from(range(n))
        edge_cursor = db["hyper_graph_edges"].find(
            {"source_file": source_file},
            {"_id": 0, "source": 1, "target": 1, "weight": 1},
        ).batch_size(10000)
        edge_weights = []
        cross_label_edges = 0
        labeled_edges = 0
        try:
            for edge in edge_cursor:
                u, v = int(edge["source"]), int(edge["target"])
                if not (0 <= u < n and 0 <= v < n):
                    raise CommandError(f"Invalid edge endpoint ({u}, {v}) for {n} nodes.")
                w = float(edge.get("weight", 1.0))
                G.add_edge(u, v, weight=w)
                if math.isfinite(w):
                    edge_weights.append(w)
                if u in labels and v in labels:
                    labeled_edges += 1
                    cross_label_edges += int(labels[u] != labels[v])
        finally:
            edge_cursor.close()

        if G.number_of_edges() != int(graph_doc.get("edge_count", G.number_of_edges())):
            raise CommandError("hyper_graph_edges count differs from metadata; incomplete edge storage.")

        components = sorted(nx.connected_components(G), key=len, reverse=True)
        component_id = {}
        component_has_rep = set()
        for cid, comp in enumerate(components):
            for node in comp:
                component_id[node] = cid
        for node in rep_labels:
            component_has_rep.add(component_id[node])

        # Shortest-path distance from each node to its nearest representative.
        distances = nx.multi_source_dijkstra_path_length(G, sources=sorted(rep_labels), weight=None)
        reachable_distances = list(distances.values())
        reachable_nodes = set(distances)
        one_hop = sum(distance <= 1 for distance in reachable_distances)
        two_hop = sum(distance <= 2 for distance in reachable_distances)
        total_nodes = G.number_of_nodes()
        degree_values = np.asarray([G.degree(node) for node in G.nodes()], dtype=np.int64)
        degree_hist = Counter(min(int(value), 100) for value in degree_values)

        rep_subgraph = G.subgraph(rep_labels.keys()).copy()
        graph_class_counts = Counter(labels.values())
        rep_class_counts = Counter(rep_labels.values())
        proxy = _nearest_label_proxy(G, labels, set(rep_labels))
        self.stdout.write("[HIER-EVAL] Loading provenance, flow, risk and novelty metrics...")
        enrichment = _enrichment_metrics(db, node_ids, graph_doc, set(rep_labels), G)

        largest_sizes = [len(comp) for comp in components[:10]]
        rep_component_counts = Counter(component_id[node] for node in rep_labels)
        results = {
            "source_file": source_file,
            "layer": 2,
            "generated_at_epoch": time.time(),
            "graph": {
                "nodes": total_nodes,
                "edges": G.number_of_edges(),
                "density": float(nx.density(G)),
                "isolates": sum(G.degree(node) == 0 for node in G.nodes()),
                "possible_pairs": int(total_nodes * (total_nodes - 1) / 2),
                "edge_weight_quantiles": {str(q): float(np.quantile(edge_weights, q)) for q in (0.1, 0.5, 0.9)} if edge_weights else {},
            },
            "representatives": {
                "count": len(rep_labels),
                "ratio": len(rep_labels) / max(1, total_nodes),
                "components_covered": len(rep_component_counts),
                "component_coverage_fraction": len(rep_component_counts) / max(1, len(components)),
                "component_counts": {str(k): int(v) for k, v in rep_component_counts.items()},
            },
            "components": {
                "count": len(components),
                "largest_component_size": largest_sizes[0] if largest_sizes else 0,
                "largest_component_sizes": largest_sizes,
                "components_without_representatives": len(components) - len(rep_component_counts),
            },
            "degree_distribution": {
                "mean": float(degree_values.mean()) if len(degree_values) else 0.0,
                "median": float(np.median(degree_values)) if len(degree_values) else 0.0,
                "p95": float(np.quantile(degree_values, 0.95)) if len(degree_values) else 0.0,
                "max": int(degree_values.max()) if len(degree_values) else 0,
                "histogram": {str(k): int(v) for k, v in sorted(degree_hist.items())},
            },
            "coverage": {
                "reachable_nodes": len(reachable_nodes),
                "reachable_fraction": len(reachable_nodes) / max(1, total_nodes),
                "one_hop_nodes": one_hop,
                "one_hop_fraction": one_hop / max(1, total_nodes),
                "two_hop_nodes": two_hop,
                "two_hop_fraction": two_hop / max(1, total_nodes),
                "component_coverage_fraction": len(rep_component_counts) / max(1, len(components)),
                "mean_hops": float(np.mean(reachable_distances)) if reachable_distances else None,
                "max_hops": int(max(reachable_distances)) if reachable_distances else None,
            },
            "class_balance": {
                "graph": {"normal": int(graph_class_counts.get(0, 0)), "attack": int(graph_class_counts.get(1, 0)), "unknown": int(total_nodes - len(labels))},
                "representatives": {"normal": int(rep_class_counts.get(0, 0)), "attack": int(rep_class_counts.get(1, 0)), "unknown": int(len(rep_labels) - sum(rep_class_counts.values()))},
                "attack_ratio_graph": graph_class_counts.get(1, 0) / max(1, len(labels)),
                "attack_ratio_representatives": rep_class_counts.get(1, 0) / max(1, len(rep_labels)),
            },
            "representative_subgraph": {
                "nodes": rep_subgraph.number_of_nodes(),
                "edges": rep_subgraph.number_of_edges(),
                "components": nx.number_connected_components(rep_subgraph) if rep_subgraph.number_of_nodes() else 0,
                "isolates": sum(rep_subgraph.degree(node) == 0 for node in rep_subgraph.nodes()),
                "density": float(nx.density(rep_subgraph)),
            },
            "cross_label_edge_fraction": cross_label_edges / labeled_edges if labeled_edges else None,
            "nearest_representative_label_proxy": proxy,
            "enrichment": enrichment,
            "notes": [
                "Nearest-representative label proxy is not a downstream classifier metric.",
                "Reachability is graph-theoretic: nodes in components without representatives are unreachable.",
                "Component coverage should be interpreted together with component sizes; covering many tiny components may not imply broad node coverage.",
                "Flow-file coverage counts source files, not verified cross-time attack relationships.",
                "Risk and novelty deciles are selection-recall proxies, not calibrated detection rates.",
                "Articulation points indicate graph connectivity, not necessarily malicious chains.",
            ],
        }

        day_match = DAY_RE.search(source_file)
        day = day_match.group(1) if day_match else "unknown-day"
        folder = Path(settings.BASE_DIR) / "files" / "evaluation" / "hierarchy" / day
        folder.mkdir(parents=True, exist_ok=True)
        json_path = Path(options["output"]) if options["output"] else folder / f"{source_file}_evaluation.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        dashboard_path = folder / f"{source_file}_evaluation_dashboard.png"
        summary_path = folder / f"{source_file}_evaluation_summary.txt"
        _save_dashboard(results, str(dashboard_path))
        _save_summary(results, str(summary_path))

        self.stdout.write(self.style.SUCCESS(f"[HIER-EVAL] JSON saved: {json_path}"))
        self.stdout.write(self.style.SUCCESS(f"[HIER-EVAL] Dashboard saved: {dashboard_path}"))
        self.stdout.write(self.style.SUCCESS(f"[HIER-EVAL] Summary saved: {summary_path}"))
        self.stdout.write(f"[HIER-EVAL] nodes={total_nodes:,}; edges={G.number_of_edges():,}; components={len(components):,}; isolates={results['graph']['isolates']:,}; reps={len(rep_labels):,}")
        self.stdout.write(f"[HIER-EVAL] coverage reachable={results['coverage']['reachable_fraction']:.1%}; 1-hop={results['coverage']['one_hop_fraction']:.1%}; 2-hop={results['coverage']['two_hop_fraction']:.1%}; component={results['coverage']['component_coverage_fraction']:.1%}")
        self.stdout.write(self.style.SUCCESS(f"[HIER-EVAL] completed in {time.perf_counter() - started:.2f}s"))
