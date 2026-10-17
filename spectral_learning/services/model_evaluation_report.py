"""Render stored multi-signal anomaly-detection evaluation results."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from django.conf import settings
from mongoengine import get_connection

from .similarity_graph_autoencoder import RUN_COLLECTION


def _plot_evaluation(run, output_path):
    metrics = run["label_diagnostic_metrics"]
    hours = run.get("hourly_label_diagnostic_metrics", [])
    component_auc = run.get("component_roc_auc", {})
    fig, axes = plt.subplots(2, 2, figsize=(15, 11), facecolor="white")
    roc_axis, component_axis, confusion_axis, hourly_axis = axes.flat

    roc = metrics.get("roc_curve", [])
    if roc:
        roc_axis.plot(
            [point["false_positive_rate"] for point in roc],
            [point["true_positive_rate"] for point in roc],
            color="#7b3294", linewidth=2,
            label=f"Combined score (AUC={metrics.get('roc_auc', 0):.3f})",
        )
    roc_axis.plot([0, 1], [0, 1], "--", color="#98a2b3", label="Chance")
    roc_axis.set(xlim=(0, 1), ylim=(0, 1.02), xlabel="False positive rate",
                 ylabel="True positive rate", title="ROC curve — combined score")
    roc_axis.grid(alpha=0.2)
    roc_axis.legend(fontsize=8)

    names = list(component_auc)
    values = [component_auc[name] for name in names]
    labels = [name.replace("_", "\n") for name in names]
    colors = ["#3973ac" if name == max(component_auc, key=component_auc.get) else "#79a8c9"
              for name in names] if names else []
    component_axis.bar(range(len(names)), values, color=colors)
    component_axis.axhline(0.5, color="#98a2b3", linestyle="--", linewidth=1)
    component_axis.set_xticks(range(len(names)), labels, fontsize=8)
    component_axis.set_ylim(0, 1)
    component_axis.set_ylabel("ROC-AUC")
    component_axis.set_title("AUC by anomaly-score signal")
    component_axis.grid(axis="y", alpha=0.2)

    matrix = np.asarray([
        [metrics["true_negative"], metrics["false_positive"]],
        [metrics["false_negative"], metrics["true_positive"]],
    ])
    image = confusion_axis.imshow(matrix, cmap="Blues")
    confusion_axis.set_xticks([0, 1], ["Predicted normal", "Predicted anomaly"])
    confusion_axis.set_yticks([0, 1], ["Actual normal", "Actual attack"])
    confusion_axis.set_title("Confusion matrix — normal-calibrated threshold")
    for (row, column), value in np.ndenumerate(matrix):
        confusion_axis.text(column, row, f"{value:,}", ha="center", va="center",
                            color="white" if value > matrix.max() * 0.55 else "#1d2939",
                            fontsize=12, fontweight="bold")
    fig.colorbar(image, ax=confusion_axis, fraction=0.046, pad=0.04)

    eligible = [item for item in hours if item.get("roc_auc") is not None]
    if eligible:
        x = np.arange(len(eligible))
        width = 0.38
        hourly_axis.bar(x - width / 2, [item["roc_auc"] for item in eligible], width,
                        label="ROC-AUC", color="#6f4c9b")
        hourly_axis.bar(x + width / 2,
                        [item["f2_at_normal_calibrated_threshold"] for item in eligible], width,
                        label="F2 at calibrated threshold", color="#e07a5f")
        hourly_axis.set_xticks(x, [f"H{item['hour_index']}" for item in eligible])
        hourly_axis.set_ylim(0, 1)
        hourly_axis.legend(fontsize=8)
    else:
        hourly_axis.text(0.5, 0.5, "No file contains both classes", ha="center", va="center")
    hourly_axis.set_ylabel("Score")
    hourly_axis.set_title("Per-file metrics where both classes exist")
    hourly_axis.grid(axis="y", alpha=0.2)

    fig.suptitle("Multi-signal graph autoencoder — evaluation", fontsize=16)
    fig.text(
        0.5, 0.015,
        "Diagnostic evaluation only. Global metrics may be affected by class composition across source files; "
        "the best-F2 threshold is selected on these labels and is not a held-out result.",
        ha="center", fontsize=9, color="#475467", wrap=True,
    )
    fig.tight_layout(rect=(0, 0.045, 1, 0.96))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def create_model_evaluation_report():
    database = get_connection(alias="default")["siem_db"]
    model_id = "hourly-similarity-eigenvector-autoencoder:latest"
    run = database[RUN_COLLECTION].find_one({"_id": model_id})
    if not run:
        raise ValueError("No stored anomaly-detection model run was found; train the model first.")

    output_dir = Path(settings.BASE_DIR) / "files" / "report" / "evaluation"
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / "report-evaluation-overall.png"
    json_path = output_dir / "report-evaluation-overall.json"
    _plot_evaluation(run, image_path)

    document = {
        "report_type": "multi-signal eigenvector-aware graph autoencoder evaluation",
        "model_id": run["_id"],
        "model_type": run.get("model_type"),
        "objective": run.get("objective"),
        "anomaly_score_method": run.get("anomaly_score_method"),
        "component_names": run.get("component_names", []),
        "component_roc_auc": run.get("component_roc_auc", {}),
        "threshold": run.get("threshold"),
        "threshold_quantile": run.get("threshold_quantile"),
        "overall_metrics": run.get("label_diagnostic_metrics"),
        "per_file_metrics": run.get("hourly_label_diagnostic_metrics", []),
        "per_file_counts": run.get("hourly_summary", []),
        "training_scope": run.get("training_scope"),
        "normal_training_nodes": run.get("normal_training_nodes"),
        "scored_nodes": run.get("node_count"),
        "limitations": [
            "The attack/normal proportions differ strongly by source file, so global ROC-AUC may reflect file/domain shifts.",
            "Only files containing both labels support within-file ROC-AUC; most current files contain one class.",
            "The normal threshold was calibrated on the normal training nodes; this is not an independent false-positive estimate.",
            "Best-F2 diagnostic threshold is selected using the evaluated labels and is not a held-out operating point.",
            "Workbook order is an ordinal-hour proxy; event timestamps and IP-level graph topology are unavailable.",
        ],
        "figure": image_path.name,
    }
    with json_path.open("w", encoding="utf-8") as file:
        json.dump(document, file, ensure_ascii=False, indent=2)
    return {"output_dir": str(output_dir), "json_report": str(json_path),
            "figure": str(image_path), "roc_auc": document["overall_metrics"].get("roc_auc"),
            "f2": document["overall_metrics"].get("f2_at_normal_calibrated_threshold"),
            "file_count": len(document["per_file_metrics"])}
