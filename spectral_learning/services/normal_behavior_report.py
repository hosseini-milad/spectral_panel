"""Schematic reports for normal-reference behavior in hourly similarity graphs."""
from ingestion.utils.document_paths import document_directory

import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from django.conf import settings
from matplotlib.collections import LineCollection
from mongoengine import get_connection

from .similarity_graph_autoencoder import RUN_COLLECTION, SCORE_COLLECTION


def _projector(normal_embeddings):
    center = normal_embeddings.mean(axis=0)
    _, _, right = np.linalg.svd(normal_embeddings - center, full_matrices=False)
    components = right[:2].T
    projected = (normal_embeddings - center) @ components
    return center, components, projected


def _save_hour_figure(source, scores, coordinates, reference_points, threshold, output_path, edges):
    flagged = np.asarray([item["is_anomaly"] for item in scores], dtype=bool)
    labels = np.asarray([item.get("label_for_evaluation", -1) for item in scores])
    coords = np.asarray([coordinates[item["sampled_id"]] for item in scores])
    fig, axis = plt.subplots(figsize=(11, 8), facecolor="white")

    if len(reference_points) > 4000:
        rng = np.random.default_rng(23)
        reference_points = reference_points[rng.choice(len(reference_points), 4000, replace=False)]
    axis.scatter(reference_points[:, 0], reference_points[:, 1], s=5, color="#7cb5d8",
                 alpha=0.12, linewidths=0, label="Global normal-reference nodes")
    lines = []
    for left, right in edges:
        left_id, right_id = source["node_order"][left], source["node_order"][right]
        if left_id in coordinates and right_id in coordinates:
            lines.append([coordinates[left_id], coordinates[right_id]])
    if lines:
        axis.add_collection(LineCollection(lines, colors="#7f8c9a", linewidths=0.35, alpha=0.12,
                                          label="Feature-similarity edges"))

    axis.scatter(coords[~flagged, 0], coords[~flagged, 1], s=15, color="#65758b", alpha=0.55,
                 linewidths=0, label="Below anomaly threshold")
    if flagged.any():
        axis.scatter(coords[flagged, 0], coords[flagged, 1], s=30, color="#d94841", alpha=0.9,
                     marker="^", linewidths=0.25, edgecolors="white", label="Flagged by model")
    center = reference_points.mean(axis=0)
    axis.scatter([center[0]], [center[1]], marker="+", s=100, color="#153e75", linewidths=2,
                 label="Normal-reference center")
    axis.set_title(f"Normal-reference behavior — Hour {source['hour_index']} · {source['source_file']}")
    axis.set_xlabel("Embedding projection · principal component 1")
    axis.set_ylabel("Embedding projection · principal component 2")
    axis.grid(alpha=0.18)
    axis.legend(loc="best", fontsize=8, framealpha=0.9)
    axis.text(
        0.015, 0.015,
        f"Nodes: {len(scores):,}   flagged: {int(flagged.sum()):,}   "
        f"threshold: {threshold:.3f}\n"
        f"Known labels for diagnostic only: normal={int((labels == 0).sum()):,}, "
        f"attack={int((labels == 1).sum()):,}\n"
        "Ordinal file hour; graph edges encode feature similarity.",
        transform=axis.transAxes, fontsize=8, va="bottom", color="#344054",
        bbox={"boxstyle": "round,pad=0.5", "facecolor": "white", "alpha": 0.88, "edgecolor": "#d0d5dd"},
    )
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=190, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _save_overall_figure(reports, all_coordinates, reference_points, threshold, evaluation, output_path):
    fig, axes = plt.subplots(1, 3, figsize=(21, 7), facecolor="white")
    axis, bar_axis, roc_axis = axes
    axis.scatter(reference_points[:, 0], reference_points[:, 1], s=5, color="#438fbd",
                 alpha=0.18, linewidths=0, label="Normal reference")
    axis.scatter(all_coordinates[:, 0], all_coordinates[:, 1], s=5, color="#667085",
                 alpha=0.12, linewidths=0, label="All sampled nodes")
    axis.set_title("Shared projection of normal reference and all hourly graphs")
    axis.set_xlabel("Principal component 1")
    axis.set_ylabel("Principal component 2")
    axis.grid(alpha=0.18)
    axis.legend(fontsize=8)

    hours = [item["hour_index"] for item in reports]
    counts = [item["anomaly_count"] for item in reports]
    totals = [item["node_count"] for item in reports]
    unflagged = [total - count for total, count in zip(totals, counts)]
    bar_axis.bar(hours, unflagged, color="#dce5ef", label="Below threshold")
    bar_axis.bar(hours, counts, bottom=unflagged, color="#d94841", label="Flagged nodes")
    bar_axis.set_xticks(hours, [f"H{x}" for x in hours])
    bar_axis.set_ylabel("Node count")
    bar_axis.set_title("Per-file model flags")
    bar_axis.grid(axis="y", alpha=0.2)
    bar_axis.legend(fontsize=8)
    roc = evaluation.get("roc_curve", [])
    if roc:
        roc_axis.plot([point["false_positive_rate"] for point in roc],
                      [point["true_positive_rate"] for point in roc],
                      color="#7b3294", linewidth=2,
                      label=f"Combined score (AUC={evaluation.get('roc_auc', 0):.3f})")
        roc_axis.plot([0, 1], [0, 1], linestyle="--", color="#98a2b3", linewidth=1,
                      label="Chance")
        roc_axis.legend(fontsize=8)
    roc_axis.set_xlim(0, 1)
    roc_axis.set_ylim(0, 1.02)
    roc_axis.set_xlabel("False positive rate")
    roc_axis.set_ylabel("True positive rate")
    roc_axis.set_title("ROC — combined multi-signal score")
    roc_axis.grid(alpha=0.2)
    fig.suptitle(f"Normal behavior reference · threshold={threshold:.3f}", fontsize=15)
    fig.text(0.5, 0.01,
             "Files are used as ordinal hours. The graph represents feature similarity, not verified network topology.",
             ha="center", fontsize=9, color="#475467")
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def create_normal_behavior_reports():
    database = get_connection(alias="default")["siem_db"]
    run = database[RUN_COLLECTION].find_one({"_id": "hourly-similarity-eigenvector-autoencoder:latest"})
    if not run:
        raise ValueError("No autoencoder run is stored. Train the similarity-graph autoencoder first.")
    scores = list(database[SCORE_COLLECTION].find({"model_id": run["_id"]}).sort(
        [("hour_index", 1), ("sampled_id", 1)]
    ))
    normal = [item for item in scores if item.get("label_for_evaluation") == 0]
    if not scores or not normal:
        raise ValueError("Stored anomaly scores or normal-reference embeddings are missing.")
    normal_embeddings = np.asarray([item["embedding"] for item in normal], dtype=np.float64)
    center, components, reference_points = _projector(normal_embeddings)
    projected = {
        item["sampled_id"]: (np.asarray(item["embedding"], dtype=np.float64) - center) @ components
        for item in scores
    }
    all_coordinates = np.asarray(list(projected.values()))
    threshold = float(run["threshold"])
    reports = []
    hourly_metrics = {
        int(item["hour_index"]): item
        for item in run.get("hourly_label_diagnostic_metrics", [])
    }
    output_dir = document_directory("report") / "normal-behavior"
    output_dir.mkdir(parents=True, exist_ok=True)
    sources = list(database.hourly_similarity_spectral_snapshots.find({}).sort("hour_index", 1))
    for source in sources:
        source_dir = document_directory("report", source['source_file']) / 'normal-behavior'
        source_dir.mkdir(parents=True, exist_ok=True)
        source_scores = [item for item in scores if item["source_file"] == source["source_file"]]
        if not source_scores:
            continue
        graph = database.graph_metadata.find_one({"source_file": source["source_file"]}, {"edges": 1}) or {}
        edges = [(int(edge["source"]), int(edge["target"])) for edge in graph.get("edges", [])]
        flagged = [item for item in source_scores if item["is_anomaly"]]
        known_normal = [item for item in source_scores if item.get("label_for_evaluation") == 0]
        known_attack = [item for item in source_scores if item.get("label_for_evaluation") == 1]
        safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(source["source_file"]).stem).strip("-")
        base_name = f"normal-behavior-hour-{int(source['hour_index']):02d}-{safe_stem}"
        image_path = source_dir / f"{base_name}.png"
        _save_hour_figure(source, source_scores, projected, reference_points, threshold, image_path, edges)
        source_scores_sorted = sorted(source_scores, key=lambda item: item["anomaly_score"], reverse=True)
        detail = {
            "report_type": "hourly normal-reference graph-autoencoder schematic",
            "source_file": source["source_file"], "hour_index": int(source["hour_index"]),
            "hour_label": source.get("hour_label"), "model_id": run["_id"],
            "graph_type": "mutual-kNN cosine feature-similarity graph",
            "normal_reference_nodes": len(normal), "graph_node_count": len(source_scores),
            "normal_labeled_nodes_for_diagnostic": len(known_normal),
            "attack_labeled_nodes_for_diagnostic": len(known_attack),
            "flagged_node_count": len(flagged),
            "flagged_fraction": len(flagged) / max(len(source_scores), 1),
            "threshold": threshold,
            "anomaly_score_quantiles": {
                str(q): float(np.quantile([item["anomaly_score"] for item in source_scores], q))
                for q in (0.5, 0.9, 0.95, 0.99, 1.0)
            },
            "label_diagnostic_metrics": hourly_metrics.get(int(source["hour_index"])),
            "top_scoring_nodes": [
                {key: item[key] for key in ("sampled_id", "raw_id", "anomaly_score", "feature_reconstruction_error",
                                             "structure_error", "spectral_prediction_error", "manifold_distance",
                                             "is_anomaly")}
                for item in source_scores_sorted[:20]
            ],
            "figure": image_path.name,
            "projection": "PCA fitted once on all label=0 reference embeddings; reused for every ordinal hour.",
            "limitations": [
                "Source workbook number is used as ordinal hour; event timestamps are unavailable.",
                "Similarity edges do not establish IP-level communication or causal relationships.",
                "Normal reference is available only from records labeled normal in this dataset.",
            ],
        }
        with (source_dir / f"{base_name}.json").open("w", encoding="utf-8") as file:
            json.dump(detail, file, ensure_ascii=False, indent=2)
        reports.append({
            "hour_index": int(source["hour_index"]), "source_file": source["source_file"],
            "node_count": len(source_scores), "anomaly_count": len(flagged),
            "normal_labeled_count": len(known_normal), "attack_labeled_count": len(known_attack),
            "figure": str(image_path),
            "json": str(source_dir / f"{base_name}.json"),
        })

    overall_image = output_dir / "normal-behavior-overall.png"
    overall_json = output_dir / "normal-behavior-overall.json"
    _save_overall_figure(reports, all_coordinates, reference_points, threshold,
                         run.get("label_diagnostic_metrics", {}), overall_image)
    summary = {
        "report_type": "normal-reference behavior across hourly similarity graphs",
        "model_id": run["_id"], "threshold": threshold,
        "normal_reference_nodes": len(normal), "scored_nodes": len(scores),
        "normal_reference_source_files": sorted({item["source_file"] for item in normal}),
        "hours": reports,
        "training_objective": run["objective"],
        "time_basis": run["time_basis"],
        "graph_interpretation": run["graph_interpretation"],
        "label_diagnostic_metrics": run.get("label_diagnostic_metrics"),
        "component_roc_auc": run.get("component_roc_auc"),
        "hourly_label_diagnostic_metrics": run.get("hourly_label_diagnostic_metrics"),
        "limitations": [
            "PCA is a schematic projection and does not preserve every high-dimensional distance; flags use the full embedding and reconstruction signals.",
            "Ordinal hours are based on source-file order, not verified event times.",
            "Current edges encode feature similarity, not observed network communication.",
        ],
        "overall_figure": overall_image.name,
    }
    with overall_json.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
    return {"output_dir": str(output_dir), "hour_count": len(reports),
            "normal_reference_nodes": len(normal), "scored_nodes": len(scores),
            "overall_figure": str(overall_image), "overall_json": str(overall_json)}
