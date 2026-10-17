from collections import Counter
from datetime import datetime

import numpy as np
from bson import ObjectId
from mongoengine import get_connection
from pymongo import ReplaceOne


GRAPH_COLLECTION = "temporal_graph_snapshots"
TEMPORAL_COLLECTION = "hierarchical_temporal_data"
RAW_COLLECTION = "security_data"
SPECTRAL_BINS = 32
EIGENVECTOR_COUNT = 8
NON_MODEL_FEATURES = {
    "src_ip", "dst_ip", "src_port", "dst_port", "flow_id", "timestamp",
    "protocol", "label",
}


def _safe_number(value):
    if isinstance(value, bool):
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if np.isfinite(number) else 0.0


def _counter_document(counter):
    return {str(key): int(value) for key, value in counter.items()}


def _feature_values(event):
    result = {}
    for key, value in event.get("features", {}).items():
        if key in NON_MODEL_FEATURES or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and np.isfinite(value):
            result[key] = float(value)
    return result


def _new_window(window_key, window_start, scale):
    return {
        "_id": window_key,
        "window_key": window_key,
        "scale": scale,
        "window_start": window_start,
        "nodes": {},
        "edges": {},
        "label_counts": Counter(),
        "raw_label_counts": Counter(),
    }


def _add_flow(window, event, raw):
    source = raw.get("src_ip")
    target = raw.get("dst_ip")
    if source is None or target is None or source == "" or target == "":
        raise ValueError(f"Missing src_ip/dst_ip for raw_id={event.get('raw_id')}")
    source = str(source)
    target = str(target)

    src_node = window["nodes"].setdefault(source, {
        "node_id": source, "in_degree": 0, "out_degree": 0,
        "_feature_sums": Counter(), "_feature_observations": 0,
    })
    dst_node = window["nodes"].setdefault(target, {
        "node_id": target, "in_degree": 0, "out_degree": 0,
        "_feature_sums": Counter(), "_feature_observations": 0,
    })
    src_node["out_degree"] += 1
    dst_node["in_degree"] += 1

    flow_features = _feature_values(event)
    for node in {source: src_node, target: dst_node}.values():
        node["_feature_observations"] += 1
        node["_feature_sums"].update(flow_features)

    edge_key = f"{source}->{target}"
    edge = window["edges"].setdefault(edge_key, {
        "source": source,
        "target": target,
        "flow_count": 0,
        "bytes": 0.0,
        "packets": 0.0,
        "protocol_counts": Counter(),
        "source_ports": Counter(),
        "destination_ports": Counter(),
        "label_counts": Counter(),
        "raw_label_counts": Counter(),
    })
    edge["flow_count"] += 1
    edge["bytes"] += _safe_number(raw.get("total_length_of_fwd_packet")) + _safe_number(raw.get("total_length_of_bwd_packet"))
    edge["packets"] += _safe_number(raw.get("total_fwd_packet")) + _safe_number(raw.get("total_bwd_packets"))
    edge["protocol_counts"][str(raw.get("protocol", "unknown"))] += 1
    edge["source_ports"][str(raw.get("src_port", "unknown"))] += 1
    edge["destination_ports"][str(raw.get("dst_port", "unknown"))] += 1
    if event.get("label") is not None:
        edge["label_counts"][event["label"]] += 1
        window["label_counts"][event["label"]] += 1
    if event.get("raw_label") is not None:
        edge["raw_label_counts"][event["raw_label"]] += 1
        window["raw_label_counts"][event["raw_label"]] += 1


def _spectral_summary(window):
    node_ids = sorted(window["nodes"])
    index = {node_id: i for i, node_id in enumerate(node_ids)}
    adjacency = np.zeros((len(node_ids), len(node_ids)), dtype=float)
    directed_weights = {}

    for edge_key, edge in window["edges"].items():
        weight = float(edge["flow_count"])
        directed_weights[edge_key] = weight
        left, right = index[edge["source"]], index[edge["target"]]
        if left == right:
            continue
        # Store directed flows in edge records, and symmetrize them for the
        # standard undirected normalized-Laplacian spectrum.
        adjacency[left, right] += weight
        adjacency[right, left] += weight

    degrees = adjacency.sum(axis=1)
    inv_sqrt = np.zeros_like(degrees)
    nonzero = degrees > 0
    inv_sqrt[nonzero] = 1.0 / np.sqrt(degrees[nonzero])
    laplacian = np.diag(nonzero.astype(float)) - (
        inv_sqrt[:, None] * adjacency * inv_sqrt[None, :]
    )
    eigenvalues, eigenvectors = np.linalg.eigh(laplacian)
    eigenvalues = np.clip(eigenvalues, 0.0, 2.0)
    histogram, _ = np.histogram(eigenvalues, bins=SPECTRAL_BINS, range=(0.0, 2.0))
    histogram = histogram.astype(float)
    if histogram.sum():
        histogram /= histogram.sum()

    positive_indices = [i for i, value in enumerate(eigenvalues) if value > 1e-8]
    selected = positive_indices[:EIGENVECTOR_COUNT]
    vectors = [
        {
            "eigenvalue": float(eigenvalues[i]),
            "values": [float(value) for value in eigenvectors[:, i]],
        }
        for i in selected
    ]
    component_count = int(np.sum(eigenvalues < 1e-8)) if len(node_ids) else 0
    return {
        "node_order": node_ids,
        "eigenvalues": [float(value) for value in eigenvalues],
        "eigenvectors": vectors,
        "eigenvector_count": len(vectors),
        "histogram": histogram.tolist(),
        "component_count": component_count,
    }, directed_weights, adjacency


def _finalize_window(window):
    nodes = []
    for node in window["nodes"].values():
        observations = node.pop("_feature_observations")
        feature_sums = node.pop("_feature_sums")
        nodes.append({
            **node,
            "features": {
                key: float(value / observations)
                for key, value in feature_sums.items()
            },
        })
    edges = []
    for edge in window["edges"].values():
        edges.append({
            **edge,
            "protocol_counts": _counter_document(edge["protocol_counts"]),
            "source_ports": _counter_document(edge["source_ports"]),
            "destination_ports": _counter_document(edge["destination_ports"]),
            "label_counts": _counter_document(edge["label_counts"]),
            "raw_label_counts": _counter_document(edge["raw_label_counts"]),
        })
    spectral, directed_weights, adjacency = _spectral_summary(window)
    max_degree = max((node["in_degree"] + node["out_degree"] for node in nodes), default=0)
    return {
        "_id": window["_id"],
        "window_key": window["window_key"],
        "scale": window["scale"],
        "window_start": window["window_start"],
        "node_count": len(nodes),
        "edge_count": len(edges),
        "flow_count": sum(edge["flow_count"] for edge in edges),
        "density": (
            len(edges) / (len(nodes) * (len(nodes) - 1))
            if len(nodes) > 1 else 0.0
        ),
        "max_degree": max_degree,
        "nodes": nodes,
        "edges": edges,
        "label_counts": _counter_document(window["label_counts"]),
        "raw_label_counts": _counter_document(window["raw_label_counts"]),
        "spectral": spectral,
        "_directed_weights": directed_weights,
        "_adjacency": adjacency,
    }


def _add_change_metrics(snapshots):
    previous_by_scale = {}
    for snapshot in snapshots:
        previous = previous_by_scale.get(snapshot["scale"])
        if previous is None:
            snapshot["change"] = None
            previous_by_scale[snapshot["scale"]] = snapshot
            continue

        previous_edges = set(previous["_directed_weights"])
        current_edges = set(snapshot["_directed_weights"])
        union = previous_edges | current_edges
        intersection = previous_edges & current_edges
        edge_jaccard = 1.0 - (len(intersection) / len(union)) if union else 0.0

        previous_nodes = set(previous["spectral"]["node_order"])
        current_nodes = set(snapshot["spectral"]["node_order"])
        node_union = previous_nodes | current_nodes
        node_jaccard = 1.0 - (len(previous_nodes & current_nodes) / len(node_union)) if node_union else 0.0

        previous_weights = previous["_directed_weights"]
        current_weights = snapshot["_directed_weights"]
        weight_delta = sum(
            abs(current_weights.get(edge, 0.0) - previous_weights.get(edge, 0.0))
            for edge in union
        )
        weight_scale = max(
            sum(current_weights.values()),
            sum(previous_weights.values()),
            1.0,
        )
        histogram_delta = np.asarray(snapshot["spectral"]["histogram"]) - np.asarray(previous["spectral"]["histogram"])

        snapshot["change"] = {
            "compared_to": previous["window_key"],
            "new_edge_count": len(current_edges - previous_edges),
            "removed_edge_count": len(previous_edges - current_edges),
            "edge_jaccard_distance": float(edge_jaccard),
            "node_jaccard_distance": float(node_jaccard),
            "relative_edge_weight_change": float(weight_delta / weight_scale),
            "spectral_histogram_l1_distance": float(np.abs(histogram_delta).sum() / 2.0),
            "component_count_delta": (
                snapshot["spectral"]["component_count"]
                - previous["spectral"]["component_count"]
            ),
            "flow_count_delta": snapshot["flow_count"] - previous["flow_count"],
        }
        previous_by_scale[snapshot["scale"]] = snapshot


def build_temporal_graph(source_file, batch_size=200):
    client = get_connection(alias="default")
    database = client["siem_db"]
    temporal_collection = database[TEMPORAL_COLLECTION]
    raw_collection = database[RAW_COLLECTION]
    output_collection = database[GRAPH_COLLECTION]

    events = list(temporal_collection.find({"source_file": source_file}))
    if not events:
        raise ValueError(f"No hierarchical temporal records for source_file={source_file!r}")
    raw_ids = [ObjectId(event["raw_id"]) for event in events]
    raw_records = raw_collection.find(
        {"source_file": source_file, "_id": {"$in": raw_ids}},
        {"_id": 1, "src_ip": 1, "dst_ip": 1, "src_port": 1, "dst_port": 1, "protocol": 1,
         "total_length_of_fwd_packet": 1, "total_length_of_bwd_packet": 1,
         "total_fwd_packet": 1, "total_bwd_packets": 1},
    )
    raw_by_id = {str(record["_id"]): record for record in raw_records}
    windows = {}

    for event in events:
        raw = raw_by_id.get(str(event.get("raw_id")))
        if raw is None:
            raise ValueError(f"No raw record for raw_id={event.get('raw_id')}")
        for scale in ("minute", "hour", "day"):
            temporal_window = event["windows"][scale]
            window = windows.setdefault(
                temporal_window["key"],
                _new_window(temporal_window["key"], temporal_window["start"], scale),
            )
            _add_flow(window, event, raw)

    snapshots = [_finalize_window(window) for window in windows.values()]
    snapshots.sort(key=lambda item: (item["scale"], item["window_start"]))
    _add_change_metrics(snapshots)

    output_documents = []
    for snapshot in snapshots:
        snapshot.pop("_directed_weights", None)
        snapshot.pop("_adjacency", None)
        snapshot["source_file"] = source_file
        output_documents.append(snapshot)

    output_collection.create_index([("source_file", 1), ("scale", 1), ("window_start", 1)])
    for start in range(0, len(output_documents), batch_size):
        batch = output_documents[start : start + batch_size]
        output_collection.bulk_write(
            [ReplaceOne({"_id": document["_id"]}, document, upsert=True) for document in batch],
            ordered=False,
        )
    expected_ids = [document["_id"] for document in output_documents]
    output_collection.delete_many({"source_file": source_file, "_id": {"$nin": expected_ids}})

    return {
        "source_file": source_file,
        "collection": GRAPH_COLLECTION,
        "snapshot_count": len(output_documents),
        "snapshots_by_scale": dict(Counter(item["scale"] for item in output_documents)),
        "total_nodes_across_snapshots": sum(item["node_count"] for item in output_documents),
        "total_directed_edges_across_snapshots": sum(item["edge_count"] for item in output_documents),
        "snapshots_with_spectral_comparison": sum(item["change"] is not None for item in output_documents),
    }
