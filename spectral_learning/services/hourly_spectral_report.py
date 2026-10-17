import json
import math
import re
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from django.conf import settings
from mongoengine import get_connection
from pymongo import ReplaceOne

from ingestion.models.graph_metadata import GraphMetadata
from ingestion.models.graph_representative import GraphRepresentative
from ingestion.models.sampled_data import SampledSecurityData


SPECTRAL_BINS = 32
EIGENVECTOR_COUNT = 8
EIGEN_TOLERANCE = 1e-8
SPECTRAL_COLLECTION = "hourly_similarity_spectral_snapshots"
SPECTRAL_VERSION = "hourly_similarity_spectrum_v1"


def _source_number(source_file):
    match = re.search(r"\d+", source_file)
    return int(match.group()) if match else 0


def _label_counts(collection, source_file):
    return Counter(
        item.get("label")
        for item in collection.objects(source_file=source_file).only("label").as_pymongo()
        if item.get("label") in (0, 1)
    )


def _analyze_graph(source_file, hour_index):
    graph_doc = GraphMetadata.objects(source_file=source_file).only("edges", "stats").first()
    if graph_doc is None:
        raise ValueError(f"No similarity graph found for {source_file!r}")

    sampled_ids = [
        str(item["_id"])
        for item in SampledSecurityData.objects(source_file=source_file)
        .only("id")
        .order_by("id")
        .as_pymongo()
    ]
    node_count = len(sampled_ids)
    if node_count < 2:
        raise ValueError(f"Not enough sampled nodes for {source_file!r}")

    adjacency = np.zeros((node_count, node_count), dtype=np.float64)
    invalid_edges = 0
    for edge in graph_doc.edges:
        left, right = int(edge["source"]), int(edge["target"])
        weight = float(edge.get("weight", 1.0))
        if left < 0 or right < 0 or left >= node_count or right >= node_count:
            invalid_edges += 1
            continue
        if left != right and math.isfinite(weight) and weight > 0:
            adjacency[left, right] = weight
            adjacency[right, left] = weight

    degrees = adjacency.sum(axis=1)
    nonzero = degrees > 0
    inverse_sqrt = np.zeros_like(degrees)
    inverse_sqrt[nonzero] = 1.0 / np.sqrt(degrees[nonzero])
    laplacian = np.diag(nonzero.astype(np.float64)) - (
        inverse_sqrt[:, None] * adjacency * inverse_sqrt[None, :]
    )
    eigenvalues, eigenvectors = np.linalg.eigh(laplacian)
    eigenvalues = np.clip(eigenvalues, 0.0, 2.0)

    histogram, bin_edges = np.histogram(
        eigenvalues, bins=SPECTRAL_BINS, range=(0.0, 2.0)
    )
    histogram = histogram.astype(np.float64)
    if histogram.sum():
        histogram /= histogram.sum()

    positive_indices = np.flatnonzero(eigenvalues > EIGEN_TOLERANCE)[:EIGENVECTOR_COUNT]
    selected_vectors = eigenvectors[:, positive_indices]
    vector_norm_errors = [
        abs(float(np.linalg.norm(selected_vectors[:, column])) - 1.0)
        for column in range(selected_vectors.shape[1])
    ]
    vector_residuals = [
        float(
            np.linalg.norm(
                laplacian @ selected_vectors[:, column]
                - eigenvalues[index] * selected_vectors[:, column]
            )
        )
        for column, index in enumerate(positive_indices)
    ]
    orthogonality_error = (
        float(np.max(np.abs(selected_vectors.T @ selected_vectors - np.eye(len(positive_indices)))))
        if len(positive_indices)
        else 0.0
    )

    graph = nx.from_numpy_array(adjacency)
    component_count = nx.number_connected_components(graph)
    zero_multiplicity = int(np.count_nonzero(eigenvalues < EIGEN_TOLERANCE))
    spectral_entropy = (
        float(-np.sum(histogram[histogram > 0] * np.log(histogram[histogram > 0])) / np.log(SPECTRAL_BINS))
        if histogram.sum()
        else 0.0
    )
    sampled_labels = _label_counts(SampledSecurityData, source_file)
    representative_labels = _label_counts(GraphRepresentative, source_file)

    checks = {
        "all_edges_reference_existing_nodes": invalid_edges == 0,
        "eigenvalues_are_finite": bool(np.isfinite(eigenvalues).all()),
        "eigenvalues_in_0_2": bool(
            eigenvalues.size
            and eigenvalues.min() >= -EIGEN_TOLERANCE
            and eigenvalues.max() <= 2.0 + EIGEN_TOLERANCE
        ),
        "eigenvalues_sorted": bool(np.all(np.diff(eigenvalues) >= -EIGEN_TOLERANCE)),
        "histogram_sums_to_one": abs(float(histogram.sum()) - 1.0) < 1e-8,
        "zero_multiplicity_matches_components": zero_multiplicity == component_count,
        "eigenvectors_unit_norm": max(vector_norm_errors, default=0.0) < 1e-6,
        "eigenvectors_orthogonal": orthogonality_error < 1e-6,
        "eigenvector_residuals_small": max(vector_residuals, default=0.0) < 1e-6,
    }

    positive_values = [float(eigenvalues[index]) for index in positive_indices]
    degree_counts = np.count_nonzero(adjacency, axis=1)
    return {
        "representation_version": SPECTRAL_VERSION,
        "scale": "hour",
        "window_key": f"ordinal-hour-{hour_index:02d}",
        "hour_index": hour_index,
        "hour_label": f"Hour {hour_index}",
        "source_file": source_file,
        "graph_type": "undirected weighted mutual-kNN cosine-similarity graph",
        "node_order": sampled_ids,
        "node_count": node_count,
        "edge_count": int(np.count_nonzero(np.triu(adjacency, k=1))),
        "_degree_counts": [int(value) for value in np.count_nonzero(adjacency, axis=1)],
        "component_count": int(component_count),
        "isolated_node_count": int(np.count_nonzero(degree_counts == 0)),
        "average_degree": float(degree_counts.mean()),
        "density": float(nx.density(graph)),
        "sampled_label_counts": {str(key): int(value) for key, value in sampled_labels.items()},
        "representative_label_counts": {
            str(key): int(value) for key, value in representative_labels.items()
        },
        "spectrum": {
            "minimum_eigenvalue": float(eigenvalues.min()),
            "maximum_eigenvalue": float(eigenvalues.max()),
            "algebraic_connectivity_lambda2": float(eigenvalues[1]),
            "smallest_positive_eigenvalues": positive_values,
            "eigenvalues": [float(value) for value in eigenvalues],
            "histogram_bins": [float(value) for value in bin_edges],
            "normalized_histogram": [float(value) for value in histogram],
            "normalized_spectral_entropy": spectral_entropy,
            "zero_eigenvalue_multiplicity": zero_multiplicity,
            "eigenvectors": [
                {
                    "eigenvalue": float(eigenvalues[index]),
                    "values": [float(value) for value in eigenvectors[:, index]],
                }
                for index in positive_indices
            ],
            "eigenvector_max_norm_error": max(vector_norm_errors, default=0.0),
            "eigenvector_max_orthogonality_error": orthogonality_error,
            "eigenvector_max_residual": max(vector_residuals, default=0.0),
        },
        "checks": checks,
        "passed": all(checks.values()),
        "time_basis": (
            "Synthetic ordinal hour assigned by natural source-file number; "
            "the workbook contains no event timestamp."
        ),
        "interpretation_limit": (
            "Spectrum describes the feature-similarity graph built from sampled flows. "
            "Source/destination IP fields are absent, so this is not a network-topology graph."
        ),
    }


def build_hourly_spectral_data(source_files=None):
    """Compute spectra from saved similarity graphs and persist them in MongoDB."""
    sources = source_files or sorted(
        GraphMetadata.objects.distinct("source_file"),
        key=lambda source: (_source_number(source), source),
    )
    if not sources:
        raise ValueError("No similarity graph metadata found")

    database = get_connection(alias="default")["siem_db"]
    collection = database[SPECTRAL_COLLECTION]
    collection.create_index([("hour_index", 1)])
    documents = []
    for hour_index, source_file in enumerate(sources, start=1):
        document = _analyze_graph(source_file, hour_index)
        document["_id"] = document["window_key"]
        document["graph_source_collection"] = "graph_metadata"
        document["graph_parameters"] = {
            "similarity": "cosine",
            "knn": 10,
            "mutual": True,
            "threshold": 0.5,
            "laplacian": "symmetric normalized",
            "histogram_bins": SPECTRAL_BINS,
            "saved_positive_eigenvectors": EIGENVECTOR_COUNT,
        }
        documents.append(document)

    collection.bulk_write(
        [ReplaceOne({"_id": item["_id"]}, item, upsert=True) for item in documents],
        ordered=False,
    )
    collection.delete_many({
        "representation_version": SPECTRAL_VERSION,
        "_id": {"$nin": [item["_id"] for item in documents]},
    })
    return {
        "snapshot_count": len(documents),
        "passed_snapshots": sum(item["passed"] for item in documents),
        "failed_snapshots": sum(not item["passed"] for item in documents),
        "collection": SPECTRAL_COLLECTION,
        "time_basis": "ordinal source-file order; no source timestamps",
    }


def _save_hour_figure(report, output_path):
    spectrum = report["spectrum"]
    values = np.asarray(spectrum["eigenvalues"], dtype=np.float64)
    bins = np.asarray(spectrum["histogram_bins"], dtype=np.float64)
    histogram = np.asarray(spectrum["normalized_histogram"], dtype=np.float64)
    positive = np.asarray(spectrum["smallest_positive_eigenvalues"], dtype=np.float64)
    degree_info = f"nodes={report['node_count']:,}  edges={report['edge_count']:,}  " \
        f"components={report['component_count']:,}  isolates={report['isolated_node_count']:,}"

    fig, axes = plt.subplots(2, 2, figsize=(14, 9), facecolor="white")
    histogram_ax, eigen_ax, degree_ax, summary_ax = axes.flat
    histogram_ax.bar(
        bins[:-1], histogram, width=np.diff(bins), align="edge",
        color="#3973ac", edgecolor="white", linewidth=0.35,
    )
    histogram_ax.set_title("Normalized Laplacian spectrum (32 bins)")
    histogram_ax.set_xlabel("Eigenvalue λ ∈ [0, 2]")
    histogram_ax.set_ylabel("Fraction of eigenvalues")
    histogram_ax.grid(axis="y", alpha=0.2)

    shown = min(20, len(positive))
    eigen_ax.plot(range(1, shown + 1), positive[:shown], marker="o", markersize=3, color="#7b3294")
    eigen_ax.set_title(
        f"Smallest positive eigenvalues ({spectrum['zero_eigenvalue_multiplicity']} zero modes)"
    )
    eigen_ax.set_xlabel("Positive eigenvalue rank")
    eigen_ax.set_ylabel("λ")
    eigen_ax.grid(alpha=0.25)

    degrees = np.asarray(report["_degree_counts"], dtype=np.int64)
    if degrees.size:
        degree_ax.hist(degrees, bins=min(25, max(5, int(np.sqrt(len(degrees))))), color="#53a567")
        degree_ax.set_title("Node degree distribution")
        degree_ax.set_xlabel("Degree")
        degree_ax.set_ylabel("Node count")
        degree_ax.grid(axis="y", alpha=0.2)
    else:
        degree_ax.axis("off")

    degree_ax.text(0.02, 0.98, degree_info, transform=degree_ax.transAxes,
                   va="top", fontsize=9, color="#344054")
    checks = report["checks"]
    status = "PASS" if report["passed"] else "CHECK REQUIRED"
    check_lines = "\n".join(
        f"{'✓' if passed else '✗'} {name.replace('_', ' ')}"
        for name, passed in checks.items()
    )
    summary_ax.axis("off")
    summary_ax.text(
        0.02, 0.98,
        f"{report['hour_label']} — {report['source_file']}\n"
        f"Spectral checks: {status}\n"
        f"λ₂: {spectrum['algebraic_connectivity_lambda2']:.6g}\n"
        f"Zero-eigenvalue multiplicity: {spectrum['zero_eigenvalue_multiplicity']}\n"
        f"Smallest positive eigenvalues: {', '.join(f'{v:.4f}' for v in positive[:8])}\n"
        f"Normalized spectral entropy: {spectrum['normalized_spectral_entropy']:.4f}\n"
        f"Sampled labels (0/1): {report['sampled_label_counts']}\n"
        f"Representative labels (0/1): {report['representative_label_counts']}\n\n"
        f"Validation\n{check_lines}\n\n"
        "Hour is ordinal only; source data has no event timestamp.\n"
        "Graph edges represent feature similarity, not source/destination IP flows.",
        transform=summary_ax.transAxes,
        va="top",
        fontsize=9,
        family="monospace",
        color="#1f2937",
    )

    fig.suptitle("Hourly Similarity-Graph Spectral Analysis", fontsize=16, y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _save_overall_figure(reports, changes, output_path):
    hours = [report["hour_index"] for report in reports]
    labels = [f"H{hour}\n{Path(report['source_file']).stem}" for hour, report in zip(hours, reports)]
    histograms = np.asarray(
        [report["spectrum"]["normalized_histogram"] for report in reports], dtype=np.float64
    ).T
    bins = np.asarray(reports[0]["spectrum"]["histogram_bins"], dtype=np.float64)

    fig, axes = plt.subplots(2, 2, figsize=(16, 10), facecolor="white")
    heat_ax, eig_ax, change_ax, volume_ax = axes.flat
    heat = heat_ax.imshow(
        histograms, origin="lower", aspect="auto", interpolation="nearest",
        extent=(-0.5, len(reports) - 0.5, 0.0, 2.0), cmap="viridis",
    )
    heat_ax.set_xticks(range(len(labels)))
    heat_ax.set_xticklabels(labels, fontsize=8)
    heat_ax.set_title("Normalized Laplacian spectrum by ordinal hour")
    heat_ax.set_ylabel("Eigenvalue λ ∈ [0, 2]")
    fig.colorbar(heat, ax=heat_ax, label="Fraction of eigenvalues")

    for rank in range(EIGENVECTOR_COUNT):
        series = []
        for report in reports:
            values = report["spectrum"]["smallest_positive_eigenvalues"]
            series.append(values[rank] if len(values) > rank else np.nan)
        eig_ax.plot(hours, series, marker="o", linewidth=1.2, label=f"λ+{rank + 1}")
    eig_ax.set_title("Smallest positive eigenvalues across hours")
    eig_ax.set_xlabel("Ordinal hour")
    eig_ax.set_ylabel("Eigenvalue")
    eig_ax.set_xticks(hours, labels, fontsize=8)
    eig_ax.tick_params(axis="x", rotation=20)
    eig_ax.grid(alpha=0.25)
    eig_ax.legend(ncol=2, fontsize=8)

    if changes:
        change_hours = [item["to_hour"] for item in changes]
        change_ax.plot(
            change_hours,
            [item["spectral_histogram_l1_distance"] for item in changes],
            marker="s",
            color="#c62828",
        )
        change_ax.set_xticks(change_hours, [f"H{i}" for i in change_hours])
    change_ax.set_title("Consecutive-hour spectral histogram change")
    change_ax.set_xlabel("Hour transition")
    change_ax.set_ylabel("L1 distance (0–2)")
    change_ax.grid(alpha=0.25)

    x = np.arange(len(reports))
    normal = [int(report["sampled_label_counts"].get("0", 0)) for report in reports]
    attack = [int(report["sampled_label_counts"].get("1", 0)) for report in reports]
    volume_ax.bar(x, normal, label="Normal (0)", color="#4f81bd")
    volume_ax.bar(x, attack, bottom=normal, label="Attack (1)", color="#c62828")
    volume_ax.set_xticks(x, labels, fontsize=8)
    volume_ax.tick_params(axis="x", rotation=20)
    volume_ax.set_ylabel("Sampled candidate count")
    volume_ax.set_title("Candidate class composition per hour")
    volume_ax.grid(axis="y", alpha=0.2)
    volume_ax.legend(fontsize=8)

    passed = sum(report["passed"] for report in reports)
    max_change = max(changes, key=lambda item: item["spectral_histogram_l1_distance"], default=None)
    overall_status = "PASS" if passed == len(reports) else "CHECK REQUIRED"
    note = (
        f"Numerical checks: {passed}/{len(reports)} hours passed  |  "
        f"max consecutive spectral histogram shift: "
        f"{max_change['spectral_histogram_l1_distance']:.4f} "
        f"(H{max_change['from_hour']}→H{max_change['to_hour']})\n"
        "Hours are assigned by natural file order because timestamps are absent. "
        "These are feature-similarity graphs; no IP-level temporal topology or anomaly accuracy is evaluated."
    ) if max_change else f"Numerical checks: {passed}/{len(reports)} hours passed."
    fig.suptitle(f"Overall Hourly Spectral Analysis — {overall_status}", fontsize=17, y=0.99)
    fig.text(0.5, 0.015, note, ha="center", va="bottom", fontsize=9, color="#4b5563", wrap=True)
    fig.tight_layout(rect=(0, 0.07, 1, 0.96))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=210, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def create_hourly_spectral_reports(source_files=None):
    database = get_connection(alias="default")["siem_db"]
    collection = database[SPECTRAL_COLLECTION]
    query = {"representation_version": SPECTRAL_VERSION}
    if source_files:
        query["source_file"] = {"$in": list(source_files)}
    reports = list(collection.find(query).sort("hour_index", 1))
    if not reports:
        raise ValueError(
            f"No persisted spectral records in {SPECTRAL_COLLECTION!r}; "
            "build hourly spectral data before rendering reports."
        )
    output_dir = Path(settings.BASE_DIR) / "files" / "report" / "spectral"

    # The node identifiers are intentionally not matched across workbooks;
    # only normalized-Laplacian spectra are compared from hour to hour.
    changes = []
    for previous, current in zip(reports, reports[1:]):
        left = np.asarray(previous["spectrum"]["normalized_histogram"], dtype=np.float64)
        right = np.asarray(current["spectrum"]["normalized_histogram"], dtype=np.float64)
        changes.append({
            "from_hour": previous["hour_index"],
            "to_hour": current["hour_index"],
            "from_source": previous["source_file"],
            "to_source": current["source_file"],
            "spectral_histogram_l1_distance": float(np.abs(right - left).sum()),
            "comparison_basis": "normalized-Laplacian histogram; node identities are not aligned",
        })

    for report in reports:
        safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(report["source_file"]).stem).strip("-")
        base_name = f"report-spectral-hour-{report['hour_index']:02d}-{safe_stem}"
        json_path = output_dir / f"{base_name}.json"
        image_path = output_dir / f"{base_name}.png"
        _save_hour_figure(report, image_path)
        plot_report = dict(report)
        plot_report.pop("_id", None)
        plot_report.pop("_degree_counts", None)
        with json_path.open("w", encoding="utf-8") as report_file:
            json.dump(plot_report, report_file, ensure_ascii=False, indent=2)

    summary = {
        "report_type": "hourly spectral analysis of feature-similarity graphs",
        "hour_assignment": (
            "One workbook is one ordinal hour, ordered by the numeric part of its filename. "
            "No event timestamp exists in the source records."
        ),
        "graph_basis": (
            "Existing mutual-kNN cosine-similarity graphs over stratified sampled normalized features; "
            "not an IP-level traffic graph."
        ),
        "hours": [
            {
                key: report[key]
                for key in (
                    "hour_index", "hour_label", "source_file", "node_count", "edge_count",
                    "component_count", "isolated_node_count", "average_degree", "density",
                    "sampled_label_counts", "representative_label_counts", "passed",
                )
            }
            | {
                "minimum_eigenvalue": report["spectrum"]["minimum_eigenvalue"],
                "algebraic_connectivity_lambda2": report["spectrum"]["algebraic_connectivity_lambda2"],
                "smallest_positive_eigenvalues": report["spectrum"]["smallest_positive_eigenvalues"],
                "normalized_spectral_entropy": report["spectrum"]["normalized_spectral_entropy"],
                "normalized_histogram": report["spectrum"]["normalized_histogram"],
                "checks": report["checks"],
            }
            for report in reports
        ],
        "consecutive_hour_changes": changes,
        "passed_hours": sum(report["passed"] for report in reports),
        "failed_hours": sum(not report["passed"] for report in reports),
        "spectral_collection": SPECTRAL_COLLECTION,
        "temporal_collection": "hierarchical_temporal_data",
        "temporal_window_collection": "hierarchical_temporal_windows",
        "limitations": [
            "Ordinal hours do not represent verified clock times or chronological event timestamps.",
            "Source and destination IP fields are absent; the analyzed edges encode feature similarity.",
            "These numerical and structural diagnostics do not establish anomaly-detection accuracy.",
            "Cross-hour eigenvectors are not directly compared because sampled nodes are not identity-aligned.",
        ],
    }
    overall_json = output_dir / "report-spectral-overall.json"
    overall_image = output_dir / "report-spectral-overall.png"
    _save_overall_figure(reports, changes, overall_image)
    with overall_json.open("w", encoding="utf-8") as report_file:
        json.dump(summary, report_file, ensure_ascii=False, indent=2)

    return {
        "hour_count": len(reports),
        "passed_hours": summary["passed_hours"],
        "failed_hours": summary["failed_hours"],
        "overall_image": str(overall_image),
        "overall_json": str(overall_json),
        "output_dir": str(output_dir),
    }
