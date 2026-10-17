import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from django.conf import settings
from matplotlib.gridspec import GridSpec

from mongoengine import get_connection

from .temporal_graph import GRAPH_COLLECTION, TEMPORAL_COLLECTION


SPECTRAL_BINS = 32
EIGEN_TOLERANCE = 1e-8


def _validate_snapshot(snapshot):
    spectral = snapshot.get("spectral", {})
    node_order = spectral.get("node_order", [])
    node_index = {node_id: index for index, node_id in enumerate(node_order)}
    adjacency = np.zeros((len(node_order), len(node_order)), dtype=np.float64)
    invalid_edges = 0
    flow_sum = 0

    for edge in snapshot.get("edges", []):
        flow_count = int(edge.get("flow_count", 0))
        flow_sum += flow_count
        source, target = edge.get("source"), edge.get("target")
        if source not in node_index or target not in node_index:
            invalid_edges += 1
            continue
        left, right = node_index[source], node_index[target]
        if left != right:
            adjacency[left, right] += flow_count
            adjacency[right, left] += flow_count

    degrees = adjacency.sum(axis=1)
    nonzero = degrees > 0
    inverse_sqrt = np.zeros_like(degrees)
    inverse_sqrt[nonzero] = 1.0 / np.sqrt(degrees[nonzero])
    laplacian = np.diag(nonzero.astype(float)) - (
        inverse_sqrt[:, None] * adjacency * inverse_sqrt[None, :]
    )
    recomputed, _ = np.linalg.eigh(laplacian)
    recomputed = np.clip(recomputed, 0.0, 2.0)
    stored = np.asarray(spectral.get("eigenvalues", []), dtype=np.float64)
    histogram = np.asarray(spectral.get("histogram", []), dtype=np.float64)
    recomputed_histogram, _ = np.histogram(
        recomputed, bins=SPECTRAL_BINS, range=(0.0, 2.0)
    )
    recomputed_histogram = recomputed_histogram.astype(np.float64)
    if recomputed_histogram.sum():
        recomputed_histogram /= recomputed_histogram.sum()

    eigen_delta = (
        float(np.max(np.abs(stored - recomputed)))
        if stored.shape == recomputed.shape and stored.size
        else float("inf")
    )
    histogram_delta = (
        float(np.max(np.abs(histogram - recomputed_histogram)))
        if histogram.shape == recomputed_histogram.shape and histogram.size
        else float("inf")
    )
    component_count = int(np.sum(recomputed < EIGEN_TOLERANCE))

    vectors = spectral.get("eigenvectors", [])
    vector_norm_errors = []
    vector_residuals = []
    vector_values = []
    valid_vector_shapes = True
    for item in vectors:
        vector = np.asarray(item.get("values", []), dtype=np.float64)
        eigenvalue = float(item.get("eigenvalue", np.nan))
        vector_values.append(vector)
        if vector.shape != (len(node_order),):
            valid_vector_shapes = False
            continue
        vector_norm_errors.append(abs(float(np.linalg.norm(vector)) - 1.0))
        vector_residuals.append(
            float(np.linalg.norm(laplacian @ vector - eigenvalue * vector))
        )

    orthogonality_error = 0.0
    for left in range(len(vector_values)):
        for right in range(left + 1, len(vector_values)):
            if vector_values[left].shape == vector_values[right].shape == (len(node_order),):
                orthogonality_error = max(
                    orthogonality_error,
                    abs(float(np.dot(vector_values[left], vector_values[right]))),
                )

    max_norm_error = max(vector_norm_errors, default=float("inf"))
    max_residual = max(vector_residuals, default=float("inf"))
    finite = bool(
        np.isfinite(recomputed).all()
        and np.isfinite(stored).all()
        and np.isfinite(histogram).all()
        and all(np.isfinite(vector).all() for vector in vector_values)
    )
    checks = {
        "finite_values": finite,
        "eigenvalues_in_0_2": bool(
            stored.size and stored.min() >= -EIGEN_TOLERANCE and stored.max() <= 2.0 + EIGEN_TOLERANCE
        ),
        "eigenvalues_sorted": bool(
            stored.size and np.all(np.diff(stored) >= -EIGEN_TOLERANCE)
        ),
        "eigenvalues_match_recomputed_laplacian": eigen_delta < 1e-7,
        "histogram_sums_to_one": bool(
            histogram.size and abs(float(histogram.sum()) - 1.0) < 1e-6
        ),
        "histogram_matches_recomputed_spectrum": histogram_delta < 1e-6,
        "zero_multiplicity_matches_component_count": (
            component_count == int(spectral.get("component_count", -1))
        ),
        "all_edges_reference_spectral_nodes": invalid_edges == 0,
        "edge_flow_counts_match_snapshot": flow_sum == int(snapshot.get("flow_count", -1)),
        "stored_eigenvectors_have_valid_shapes": bool(vectors) and valid_vector_shapes,
        "eigenvectors_unit_norm": max_norm_error < 1e-5,
        "eigenvectors_orthogonal": orthogonality_error < 1e-5,
        "eigenvector_residuals_small": max_residual < 1e-6,
    }
    return {
        "window_key": snapshot.get("window_key"),
        "scale": snapshot.get("scale"),
        "window_start": (
            snapshot["window_start"].isoformat()
            if isinstance(snapshot.get("window_start"), datetime)
            else snapshot.get("window_start")
        ),
        "node_count": len(node_order),
        "edge_count": len(snapshot.get("edges", [])),
        "flow_count": int(snapshot.get("flow_count", 0)),
        "component_count": component_count,
        "stored_component_count": int(spectral.get("component_count", -1)),
        "eigenvector_count": len(vectors),
        "minimum_eigenvalue": float(stored.min()) if stored.size else None,
        "maximum_eigenvalue": float(stored.max()) if stored.size else None,
        "eigenvalue_recompute_max_abs_error": eigen_delta,
        "histogram_recompute_max_abs_error": histogram_delta,
        "eigenvector_max_norm_error": max_norm_error,
        "eigenvector_max_orthogonality_error": orthogonality_error,
        "eigenvector_max_residual": max_residual,
        "invalid_edge_node_references": invalid_edges,
        "checks": checks,
        "passed": all(checks.values()),
    }


def _minute_snapshots(snapshots):
    return sorted(
        [snapshot for snapshot in snapshots if snapshot.get("scale") == "minute"],
        key=lambda item: item["window_start"],
    )


def _format_time(value):
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    return str(value)


def _write_figure(source_file, snapshots, diagnostics, summary, output_path):
    minute = _minute_snapshots(snapshots)
    times = [_format_time(item["window_start"]) for item in minute]
    histogram_matrix = np.asarray(
        [item["spectral"]["histogram"] for item in minute], dtype=np.float64
    ).T
    bins = np.linspace(0.0, 2.0, SPECTRAL_BINS + 1)

    fig = plt.figure(figsize=(16, 11), facecolor="white")
    grid = GridSpec(2, 2, figure=fig, hspace=0.34, wspace=0.26)
    heat_ax = fig.add_subplot(grid[0, 0])
    eig_ax = fig.add_subplot(grid[0, 1])
    change_ax = fig.add_subplot(grid[1, 0])
    flow_ax = fig.add_subplot(grid[1, 1])

    if len(minute):
        heat = heat_ax.imshow(
            histogram_matrix,
            origin="lower",
            aspect="auto",
            extent=(-0.5, len(minute) - 0.5, 0.0, 2.0),
            cmap="viridis",
            interpolation="nearest",
        )
        heat_ax.set_xticks(range(len(times)))
        heat_ax.set_xticklabels(times, rotation=45, ha="right", fontsize=8)
        fig.colorbar(heat, ax=heat_ax, label="Fraction of Laplacian eigenvalues")
    heat_ax.set_title("Normalized Laplacian spectrum by minute")
    heat_ax.set_xlabel("Minute window")
    heat_ax.set_ylabel("Eigenvalue λ ∈ [0, 2]")
    heat_ax.grid(False)

    for rank in range(8):
        values = []
        for item in minute:
            positive = [
                float(value)
                for value in item["spectral"]["eigenvalues"]
                if value > EIGEN_TOLERANCE
            ]
            values.append(positive[rank] if len(positive) > rank else np.nan)
        eig_ax.plot(times, values, marker="o", markersize=3, linewidth=1.2,
                    label=f"λ+{rank + 1}")
    eig_ax.set_title("Eight smallest positive eigenvalues")
    eig_ax.set_xlabel("Minute window")
    eig_ax.set_ylabel("Eigenvalue")
    eig_ax.tick_params(axis="x", rotation=45, labelsize=8)
    eig_ax.grid(True, alpha=0.25)
    eig_ax.legend(ncol=2, fontsize=8, loc="best")

    transitions = [item for item in minute if item.get("change")]
    transition_times = [_format_time(item["window_start"]) for item in transitions]
    edge_change = [item["change"]["edge_jaccard_distance"] for item in transitions]
    spectral_change = [item["change"]["spectral_histogram_l1_distance"] for item in transitions]
    change_ax.plot(transition_times, edge_change, marker="o", label="Edge Jaccard distance")
    change_ax.plot(transition_times, spectral_change, marker="s", label="Spectral histogram L1")
    change_ax.set_title("Minute-to-minute structural and spectral change")
    change_ax.set_xlabel("Minute window")
    change_ax.set_ylabel("Distance (0 = stable, 1 = maximum)")
    change_ax.set_ylim(0, 1.05)
    change_ax.tick_params(axis="x", rotation=45, labelsize=8)
    change_ax.grid(True, alpha=0.25)
    change_ax.legend(fontsize=8)

    flows = [int(item["flow_count"]) for item in minute]
    components = [int(item["spectral"]["component_count"]) for item in minute]
    flow_ax.bar(times, flows, color="#7aa6c2", alpha=0.8, label="Flows")
    flow_ax.set_title("Window volume and graph connectivity")
    flow_ax.set_xlabel("Minute window")
    flow_ax.set_ylabel("Flow count", color="#315d78")
    flow_ax.tick_params(axis="x", rotation=45, labelsize=8)
    flow_ax.grid(axis="y", alpha=0.2)
    component_ax = flow_ax.twinx()
    component_ax.plot(times, components, color="#c62828", marker="o",
                      linewidth=1.4, label="Connected components")
    component_ax.set_ylabel("Connected components", color="#c62828")
    handles1, labels1 = flow_ax.get_legend_handles_labels()
    handles2, labels2 = component_ax.get_legend_handles_labels()
    flow_ax.legend(handles1 + handles2, labels1 + labels2, fontsize=8, loc="upper left")

    passed = summary["passed_snapshots"]
    total = summary["snapshot_count"]
    status = "PASS" if passed == total else "CHECK REQUIRED"
    fig.suptitle(f"Temporal Graph Spectral Report — {source_file}", fontsize=18, y=0.985)
    fig.text(
        0.5,
        0.947,
        f"Spectral sanity checks: {status} ({passed}/{total} snapshots)  |  "
        f"minute/hour/day windows: {summary['snapshots_by_scale']}  |  "
        f"time coverage: {summary['time_min']} – {summary['time_max']}",
        ha="center",
        fontsize=10,
        color="#1f5135" if status == "PASS" else "#a11b1b",
    )

    max_spectral = summary.get("largest_spectral_change")
    max_edge = summary.get("largest_edge_change")
    limitation = (
        f"Largest spectral shift: {max_spectral['time']} (L1={max_spectral['value']:.3f})  |  "
        f"largest edge churn: {max_edge['time']} (Jaccard={max_edge['value']:.3f})  |  "
        f"training runs: {summary['training_run_count']}, saved embeddings: {summary['embedding_count']}\n"
        "Interpretation: spectral computation passes numerical checks; this is not yet evidence of anomaly-detection quality. "
        "The current source spans only about 15 minutes, so day-scale and long-term attack behavior are not evaluated."
    )
    fig.text(0.5, 0.015, limitation, ha="center", va="bottom", fontsize=9,
             color="#4b5563", wrap=True)
    fig.subplots_adjust(top=0.89, bottom=0.12, left=0.07, right=0.96)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def create_spectral_report(source_file):
    database = get_connection(alias="default")["siem_db"]
    snapshots = list(
        database[GRAPH_COLLECTION]
        .find({"source_file": source_file})
        .sort([("scale", 1), ("window_start", 1)])
    )
    if not snapshots:
        raise ValueError(f"No temporal graph snapshots for {source_file!r}")

    diagnostics = [_validate_snapshot(snapshot) for snapshot in snapshots]
    snapshots_by_scale = dict(Counter(item["scale"] for item in snapshots))
    flow_counts_by_scale = {
        scale: sum(item["flow_count"] for item in snapshots if item["scale"] == scale)
        for scale in snapshots_by_scale
    }
    minute = _minute_snapshots(snapshots)
    event_time_bounds = next(
        database[TEMPORAL_COLLECTION].aggregate([
            {"$match": {"source_file": source_file}},
            {"$group": {"_id": None, "minimum": {"$min": "$event_time"},
                        "maximum": {"$max": "$event_time"}}},
        ]),
        None,
    )
    transitions = [item for item in minute if item.get("change")]
    largest_spectral = max(
        transitions,
        key=lambda item: item["change"]["spectral_histogram_l1_distance"],
        default=None,
    )
    largest_edge = max(
        transitions,
        key=lambda item: item["change"]["edge_jaccard_distance"],
        default=None,
    )
    embedding_count = database["temporal_node_embeddings"].count_documents(
        {"source_file": source_file}
    )
    training_run_count = database["temporal_graph_training_runs"].count_documents(
        {"source_file": source_file}
    )

    all_checks = [
        check
        for item in diagnostics
        for check in item["checks"].values()
    ]
    summary = {
        "source_file": source_file,
        "snapshot_count": len(snapshots),
        "snapshots_by_scale": snapshots_by_scale,
        "flow_counts_by_scale": flow_counts_by_scale,
        "time_min": (
            event_time_bounds["minimum"].isoformat()
            if event_time_bounds else min(item["window_start"] for item in snapshots).isoformat()
        ),
        "time_max": (
            event_time_bounds["maximum"].isoformat()
            if event_time_bounds else max(item["window_start"] for item in snapshots).isoformat()
        ),
        "passed_snapshots": sum(item["passed"] for item in diagnostics),
        "failed_snapshots": sum(not item["passed"] for item in diagnostics),
        "check_count": len(all_checks),
        "passed_checks": sum(all_checks),
        "failed_checks": len(all_checks) - sum(all_checks),
        "largest_spectral_change": (
            {
                "time": _format_time(largest_spectral["window_start"]),
                "value": largest_spectral["change"]["spectral_histogram_l1_distance"],
            }
            if largest_spectral else None
        ),
        "largest_edge_change": (
            {
                "time": _format_time(largest_edge["window_start"]),
                "value": largest_edge["change"]["edge_jaccard_distance"],
            }
            if largest_edge else None
        ),
        "training_run_count": training_run_count,
        "embedding_count": embedding_count,
        "interpretation": (
            "Numerical spectral checks validate the stored normalized-Laplacian "
            "spectra and eigenvectors. They do not measure anomaly-detection accuracy. "
            "The current dataset covers a short interval and does not validate "
            "long-term or day-scale attack behavior."
        ),
        "snapshot_diagnostics": diagnostics,
    }

    report_dir = Path(settings.BASE_DIR) / "files" / "report"
    image_path = report_dir / "report-spectral.png"
    json_path = report_dir / "report-spectral.json"
    _write_figure(source_file, snapshots, diagnostics, summary, image_path)
    with json_path.open("w", encoding="utf-8") as report_file:
        json.dump(summary, report_file, ensure_ascii=False, indent=2)

    return {
        "image_path": str(image_path),
        "data_path": str(json_path),
        "snapshot_count": len(snapshots),
        "snapshots_by_scale": snapshots_by_scale,
        "passed_snapshots": summary["passed_snapshots"],
        "failed_snapshots": summary["failed_snapshots"],
        "passed_checks": summary["passed_checks"],
        "failed_checks": summary["failed_checks"],
        "flow_counts_by_scale": flow_counts_by_scale,
        "training_run_count": training_run_count,
        "embedding_count": embedding_count,
    }
