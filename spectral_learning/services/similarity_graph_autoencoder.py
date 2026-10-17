"""Self-supervised anomaly scoring for persisted hourly similarity graphs."""

import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from mongoengine import get_connection
from pymongo import ReplaceOne

from .hourly_spectral_report import SPECTRAL_COLLECTION
from ..models.eigenvector_gnn import EigenvectorAwareGraphEncoder


SCORE_COLLECTION = "hourly_similarity_anomaly_scores"
RUN_COLLECTION = "hourly_similarity_autoencoder_runs"
FEATURE_EXCLUDE = {"_id", "label", "source_file", "created_at", "original_id"}
PE_DIM = 8


def _load_graphs(database, torch, device):
    spectral_docs = list(database[SPECTRAL_COLLECTION].find({}).sort("hour_index", 1))
    if not spectral_docs:
        raise ValueError(f"No stored hourly spectra found in {SPECTRAL_COLLECTION}.")
    graphs = []
    feature_names = None
    for spectral in spectral_docs:
        source = spectral["source_file"]
        samples = list(database.sampled_security_data.find({"source_file": source}).sort("_id", 1))
        sample_ids = [str(item["_id"]) for item in samples]
        if sample_ids != spectral["node_order"]:
            raise ValueError(f"Sample node order differs from saved spectrum for {source}.")
        if feature_names is None:
            feature_names = sorted({
                key for item in samples for key, value in item.items()
                if key not in FEATURE_EXCLUDE and isinstance(value, (int, float))
            })
        def number(value):
            try:
                value = float(value)
                return value if np.isfinite(value) else 0.0
            except (TypeError, ValueError):
                return 0.0

        features = np.asarray([
            [number(item.get(key, 0.0)) for key in feature_names] for item in samples
        ], dtype=np.float32)
        # Non-finite or null values are replaced by zero before tensor creation.
        features = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
        count = len(samples)
        positional = np.zeros((count, PE_DIM), dtype=np.float32)
        for column, vector in enumerate(spectral["spectrum"].get("eigenvectors", [])[:PE_DIM]):
            positional[:, column] = np.asarray(vector["values"], dtype=np.float32) * np.sqrt(
                max(float(vector["eigenvalue"]), 0.0)
            )
        graph_doc = database.graph_metadata.find_one({"source_file": source}, {"edges": 1})
        if graph_doc is None:
            raise ValueError(f"No graph_metadata document for {source}.")
        pairs = np.asarray([
            [int(edge["source"]), int(edge["target"])] for edge in graph_doc.get("edges", [])
            if 0 <= int(edge["source"]) < count and 0 <= int(edge["target"]) < count
            and int(edge["source"]) != int(edge["target"])
        ], dtype=np.int64).reshape(-1, 2)
        weights = np.asarray([
            [float(edge.get("weight", 1.0)), 0.0, 0.0] for edge in graph_doc.get("edges", [])
            if 0 <= int(edge["source"]) < count and 0 <= int(edge["target"]) < count
            and int(edge["source"]) != int(edge["target"])
        ], dtype=np.float32).reshape(-1, 3)
        if len(weights):
            weights[:, 0] = np.clip(weights[:, 0], 0.0, 1.0)
        graphs.append({
            "source_file": source,
            "hour_index": int(spectral["hour_index"]),
            "ids": sample_ids,
            "raw_ids": [item.get("original_id") for item in samples],
            "labels": np.asarray([int(item.get("label", -1)) for item in samples]),
            "features_np": features,
            "positional_np": positional,
            "pairs_np": pairs,
            "weights_np": weights,
            "features": torch.tensor(features, device=device),
            "positional": torch.tensor(positional, device=device),
            "spectral_target": torch.tensor(np.abs(positional) * np.sqrt(max(count, 1)), device=device),
            "edge_index": torch.tensor(pairs.T.copy(), dtype=torch.long, device=device),
            "edge_features": torch.tensor(weights, device=device),
            "positive_pairs": torch.tensor(pairs, dtype=torch.long, device=device),
        })
    return graphs, feature_names


def _induced_training_graph(graph, torch, device):
    normal_indices = np.flatnonzero(graph["labels"] == 0)
    if not len(normal_indices):
        return None
    remap = np.full(len(graph["ids"]), -1, dtype=np.int64)
    remap[normal_indices] = np.arange(len(normal_indices))
    keep = (remap[graph["pairs_np"][:, 0]] >= 0) & (remap[graph["pairs_np"][:, 1]] >= 0)
    pairs = remap[graph["pairs_np"][keep]]
    return {
        "indices": normal_indices,
        "features": graph["features"][normal_indices],
        "positional": graph["positional"][normal_indices],
        "spectral_target": graph["spectral_target"][normal_indices],
        "edge_index": torch.tensor(pairs.T.copy(), dtype=torch.long, device=device),
        "edge_features": torch.tensor(graph["weights_np"][keep], device=device),
        "positive_pairs": torch.tensor(pairs, dtype=torch.long, device=device),
    }


def _sample_negative_pairs(node_count, positive_pairs, count, torch, device, rng):
    positive = {int(a) * node_count + int(b) for a, b in positive_pairs.detach().cpu().tolist()}
    result = set()
    attempts = 0
    max_attempts = max(count * 20, 100)
    while len(result) < count and attempts < max_attempts:
        a, b = rng.randrange(node_count), rng.randrange(node_count)
        key = a * node_count + b
        if a != b and key not in positive:
            result.add((a, b))
        attempts += 1
    return torch.tensor(sorted(result), dtype=torch.long, device=device).reshape(-1, 2)


def _robust_z(values, median, mad):
    return np.maximum((values - median) / max(1.4826 * mad, 1e-8), 0.0)


def _binary_metrics(labels, scores, threshold):
    from scipy.stats import rankdata

    labels = np.asarray(labels, dtype=np.int64)
    scores = np.asarray(scores, dtype=np.float64)
    predictions = scores > threshold
    tp = int(np.count_nonzero((labels == 1) & predictions))
    fp = int(np.count_nonzero((labels == 0) & predictions))
    fn = int(np.count_nonzero((labels == 1) & ~predictions))
    tn = int(np.count_nonzero((labels == 0) & ~predictions))
    positives, negatives = int(np.count_nonzero(labels == 1)), int(np.count_nonzero(labels == 0))
    auc = None
    max_f2 = None
    best_threshold = None
    if positives and negatives:
        ranks = rankdata(scores)
        auc = float((ranks[labels == 1].sum() - positives * (positives + 1) / 2)
                    / (positives * negatives))
        order = np.argsort(-scores)
        ordered_labels = labels[order]
        cumulative_tp = np.cumsum(ordered_labels == 1)
        cumulative_fp = np.cumsum(ordered_labels == 0)
        ends = np.r_[np.flatnonzero(np.diff(scores[order]) != 0), len(order) - 1]
        tp_values, fp_values = cumulative_tp[ends], cumulative_fp[ends]
        f2_values = 5 * tp_values / np.maximum(5 * tp_values + 4 * (positives - tp_values) + fp_values, 1)
        best = int(np.argmax(f2_values))
        max_f2, best_threshold = float(f2_values[best]), float(scores[order[ends[best]]])
    return {
        "normal_count": negatives, "attack_count": positives,
        "true_positive": tp, "false_positive": fp,
        "false_negative": fn, "true_negative": tn,
        "precision": tp / max(tp + fp, 1),
        "recall": tp / max(tp + fn, 1),
        "f2_at_normal_calibrated_threshold": 5 * tp / max(5 * tp + 4 * fn + fp, 1),
        "best_f2_diagnostic_only": max_f2,
        "best_f2_threshold_diagnostic_only": best_threshold,
        "roc_auc": auc,
    }


def train_similarity_graph_autoencoder(
    epochs=40, hidden_dim=64, embedding_dim=32, learning_rate=0.001,
    mask_rate=0.15, seed=17, checkpoint_path=None, threshold_quantile=0.99,
):
    import torch
    from torch.nn import functional as F

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    database = get_connection(alias="default")["siem_db"]
    graphs, feature_names = _load_graphs(database, torch, device)
    training_graphs = [item for graph in graphs if (item := _induced_training_graph(graph, torch, device))]
    if not training_graphs:
        raise ValueError("No label=0 nodes available to establish a normal reference.")

    model = EigenvectorAwareGraphEncoder(
        input_dim=len(feature_names), pe_dim=PE_DIM, edge_dim=3, hidden_dim=hidden_dim,
        embedding_dim=embedding_dim,
    ).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=1e-5)
    rng = random.Random(seed)
    history = []
    for epoch in range(epochs):
        model.train()
        losses = []
        optimizer.zero_grad()
        for graph in training_graphs:
            features = graph["features"]
            mask = torch.rand_like(features) < mask_rate
            if not mask.any():
                mask[0, 0] = True
            embeddings = model.encode(
                features.masked_fill(mask, 0.0), graph["positional"], graph["edge_index"],
                graph["edge_features"], torch.tensor(1, dtype=torch.long, device=device),
            )
            feature_loss = F.mse_loss(model.reconstruct_features(embeddings)[mask], features[mask])
            positive = graph["positive_pairs"]
            negative = _sample_negative_pairs(len(features), positive, len(positive), torch, device, rng)
            if len(positive) and len(negative):
                pair_set = torch.cat((positive, negative))
                targets = torch.cat((torch.ones(len(positive), device=device), torch.zeros(len(negative), device=device)))
                link_loss = F.binary_cross_entropy_with_logits(model.decode_links(embeddings, pair_set), targets)
            else:
                link_loss = feature_loss.new_tensor(0.0)
            # Preserve the spectral neighborhood geometry in the learned space.
            norm_embedding = F.normalize(embeddings, p=2, dim=-1)
            norm_pe = F.normalize(graph["positional"], p=2, dim=-1)
            spectral_loss = F.mse_loss(norm_embedding @ norm_embedding.T, norm_pe @ norm_pe.T)
            spectral_prediction_loss = F.mse_loss(
                model.predict_spectrum(embeddings), graph["spectral_target"]
            )
            losses.append(feature_loss + link_loss + 0.2 * spectral_loss + 0.2 * spectral_prediction_loss)
        loss = torch.stack(losses).mean()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        history.append(float(loss.detach().cpu()))

    model.eval()
    component_rows = []
    output_docs = []
    normal_embeddings = []
    with torch.no_grad():
        for graph in graphs:
            embeddings = model.encode(
                graph["features"], graph["positional"], graph["edge_index"], graph["edge_features"],
                torch.tensor(1, dtype=torch.long, device=device),
            )
            recon = model.reconstruct_features(embeddings)
            feature_error = ((recon - graph["features"]) ** 2).mean(dim=1).cpu().numpy()
            spectral_error = (
                (model.predict_spectrum(embeddings) - graph["spectral_target"]) ** 2
            ).mean(dim=1).cpu().numpy()
            edge_error = np.zeros(len(graph["ids"]), dtype=np.float64)
            edge_counts = np.zeros(len(graph["ids"]), dtype=np.int64)
            pairs = graph["positive_pairs"]
            if len(pairs):
                logits = model.decode_links(embeddings, pairs)
                errors = F.softplus(-logits).cpu().numpy()
                pair_np = graph["pairs_np"]
                np.add.at(edge_error, pair_np[:, 0], errors)
                np.add.at(edge_error, pair_np[:, 1], errors)
                np.add.at(edge_counts, pair_np[:, 0], 1)
                np.add.at(edge_counts, pair_np[:, 1], 1)
            edge_error /= np.maximum(edge_counts, 1)
            emb = embeddings.cpu().numpy()
            normal_embeddings.extend(emb[graph["labels"] == 0])
            component_rows.extend((graph, i, float(feature_error[i]), float(edge_error[i]),
                                   float(spectral_error[i]), emb[i])
                                  for i in range(len(graph["ids"])))

    normal_embeddings = np.asarray(normal_embeddings)
    from scipy.spatial import cKDTree
    normal_tree = cKDTree(normal_embeddings)
    all_embeddings = np.asarray([row[5] for row in component_rows])
    neighbor_distances, _ = normal_tree.query(all_embeddings, k=min(10, len(normal_embeddings)))
    if neighbor_distances.ndim == 1:
        neighbor_distances = neighbor_distances[:, None]
    manifold_scores = np.asarray(neighbor_distances).mean(axis=1)
    raw_components = np.asarray([
        [row[2], row[3], row[4], manifold_scores[index]]
        for index, row in enumerate(component_rows)
    ])
    normal_mask = np.asarray([row[0]["labels"][row[1]] == 0 for row in component_rows])
    medians = np.median(raw_components[normal_mask], axis=0)
    mads = np.median(np.abs(raw_components[normal_mask] - medians), axis=0)
    normalized = np.column_stack([
        _robust_z(raw_components[:, col], medians[col], mads[col])
        for col in range(raw_components.shape[1])
    ])
    scores = normalized.mean(axis=1)
    threshold = float(np.quantile(scores[normal_mask], threshold_quantile))
    labels = np.asarray([row[0]["labels"][row[1]] for row in component_rows])
    predictions = scores > threshold
    true_positive = int(np.count_nonzero((labels == 1) & predictions))
    false_positive = int(np.count_nonzero((labels == 0) & predictions))
    false_negative = int(np.count_nonzero((labels == 1) & ~predictions))
    true_negative = int(np.count_nonzero((labels == 0) & ~predictions))
    positive_count = int(np.count_nonzero(labels == 1))
    negative_count = int(np.count_nonzero(labels == 0))
    roc_curve = []
    best_f2 = {"score": None, "threshold_diagnostic_only": None}
    if positive_count and negative_count:
        from scipy.stats import rankdata
        ranks = rankdata(scores)
        roc_auc = float(
            (ranks[labels == 1].sum() - positive_count * (positive_count + 1) / 2)
            / (positive_count * negative_count)
        )
        order = np.argsort(-scores)
        sorted_labels = labels[order]
        cumulative_tp = np.cumsum(sorted_labels == 1)
        cumulative_fp = np.cumsum(sorted_labels == 0)
        distinct_ends = np.r_[np.flatnonzero(np.diff(scores[order]) != 0), len(order) - 1]
        curve_tp = np.r_[0, cumulative_tp[distinct_ends]]
        curve_fp = np.r_[0, cumulative_fp[distinct_ends]]
        curve_tpr = curve_tp / positive_count
        curve_fpr = curve_fp / negative_count
        curve_thresholds = np.r_[float(scores.max()) + 1e-12, scores[order[distinct_ends]]]
        curve_f2 = 5 * curve_tp / np.maximum(
            5 * curve_tp + 4 * (positive_count - curve_tp) + curve_fp, 1
        )
        best_f2_index = int(np.argmax(curve_f2))
        best_f2 = {"score": float(curve_f2[best_f2_index]),
                   "threshold_diagnostic_only": float(curve_thresholds[best_f2_index])}
        roc_indices = np.unique(np.linspace(
            0, len(curve_fpr) - 1, min(101, len(curve_fpr))
        ).round().astype(int))
        roc_curve = [
            {"false_positive_rate": float(curve_fpr[i]),
             "true_positive_rate": float(curve_tpr[i]),
             "threshold": float(curve_thresholds[i])}
            for i in roc_indices
        ]
    else:
        roc_auc = None
    operating_f2 = 5 * true_positive / max(
        5 * true_positive + 4 * false_negative + false_positive, 1
    )
    evaluation = {
        "true_positive": true_positive, "false_positive": false_positive,
        "false_negative": false_negative, "true_negative": true_negative,
        "precision": true_positive / max(true_positive + false_positive, 1),
        "recall": true_positive / max(true_positive + false_negative, 1),
        "normal_false_positive_rate": false_positive / max(false_positive + true_negative, 1),
        "f2_at_normal_calibrated_threshold": operating_f2,
        "best_f2_diagnostic_only": best_f2,
        "roc_auc": roc_auc,
        "roc_curve": roc_curve,
        "note": "Diagnostic only: labels are not model targets; score threshold is calibrated on the normal training nodes.",
    }
    component_auc = {}
    if positive_count and negative_count:
        from scipy.stats import rankdata
        for column, name in enumerate(("feature_reconstruction_error", "structure_error",
                                       "spectral_prediction_error", "manifold_distance")):
            component_ranks = rankdata(normalized[:, column])
            component_auc[name] = float(
                (component_ranks[labels == 1].sum() - positive_count * (positive_count + 1) / 2)
                / (positive_count * negative_count)
            )
    hourly_evaluation = []
    for graph in graphs:
        indices = [index for index, row in enumerate(component_rows)
                   if row[0]["source_file"] == graph["source_file"]]
        hourly_evaluation.append({
            "source_file": graph["source_file"], "hour_index": graph["hour_index"],
            **_binary_metrics(labels[indices], scores[indices], threshold),
        })

    model_id = "hourly-similarity-eigenvector-autoencoder:latest"
    component_names = ["feature_reconstruction_error", "structure_error",
                       "spectral_prediction_error", "manifold_distance"]
    for index, (graph, node_index, feature_error, edge_error, spectral_error, embedding) in enumerate(component_rows):
        output_docs.append({
            "_id": f"{graph['source_file']}:{graph['ids'][node_index]}:{model_id}",
            "model_id": model_id,
            "source_file": graph["source_file"],
            "hour_index": graph["hour_index"],
            "sampled_id": graph["ids"][node_index],
            "raw_id": str(graph["raw_ids"][node_index]) if graph["raw_ids"][node_index] is not None else None,
            "label_for_evaluation": int(graph["labels"][node_index]),
            "feature_reconstruction_error": feature_error,
            "structure_error": edge_error,
            "neighbor_link_error": edge_error,
            "spectral_prediction_error": spectral_error,
            "manifold_distance": float(manifold_scores[index]),
            "anomaly_score_components": {
                name: {"raw": float(raw_components[index, component]),
                      "robust_z": float(normalized[index, component])}
                for component, name in enumerate(component_names)
            },
            "anomaly_score": float(scores[index]),
            "threshold": threshold,
            "is_anomaly": bool(scores[index] > threshold),
            "embedding": [float(value) for value in embedding],
        })
    score_collection = database[SCORE_COLLECTION]
    score_collection.create_index([("source_file", 1), ("is_anomaly", 1)])
    score_collection.bulk_write([ReplaceOne({"_id": doc["_id"]}, doc, upsert=True) for doc in output_docs], ordered=False)
    score_collection.delete_many({"model_id": model_id, "_id": {"$nin": [doc["_id"] for doc in output_docs]}})

    summaries = []
    for graph in graphs:
        docs = [doc for doc in output_docs if doc["source_file"] == graph["source_file"]]
        summaries.append({
            "source_file": graph["source_file"], "hour_index": graph["hour_index"],
            "nodes": len(docs), "anomaly_count": sum(doc["is_anomaly"] for doc in docs),
            "normal_count": int(np.count_nonzero(graph["labels"] == 0)),
            "attack_count": int(np.count_nonzero(graph["labels"] == 1)),
        })
    run = {
        "_id": model_id, "model_type": "eigenvector_aware_self_supervised_graph_autoencoder",
        "training_scope": "label=0 induced subgraphs; labels are used only to form normal reference and evaluate outputs",
        "objective": "masked_feature_reconstruction+link_reconstruction+spectral_prediction+spectral_gram_consistency",
        "anomaly_score_method": "equal-weight mean of nonnegative robust-z feature, structure, spectral-prediction, and normal-manifold errors",
        "feature_names": feature_names, "hidden_dim": hidden_dim, "embedding_dim": embedding_dim,
        "epochs": epochs, "learning_rate": learning_rate, "mask_rate": mask_rate,
        "threshold_quantile": threshold_quantile, "threshold": threshold,
        "component_names": component_names,
        "component_medians": medians.tolist(), "component_mads": mads.tolist(),
        "device": str(device), "graph_count": len(graphs), "node_count": len(output_docs),
        "normal_training_nodes": int(normal_mask.sum()), "training_loss_history": history,
        "hourly_summary": summaries, "label_diagnostic_metrics": evaluation,
        "component_roc_auc": component_auc,
        "hourly_label_diagnostic_metrics": hourly_evaluation,
        "completed_at": datetime.now(timezone.utc),
        "time_basis": "ordinal source-file hour; original timestamps are unavailable",
        "graph_interpretation": "feature-similarity graph; not IP-level traffic topology",
    }
    database[RUN_COLLECTION].replace_one({"_id": model_id}, run, upsert=True)

    if checkpoint_path is None:
        checkpoint_path = Path("artifacts") / "hourly_similarity_eigenvector_autoencoder.pt"
    checkpoint_path = Path(checkpoint_path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"model_state_dict": model.state_dict(), "model_id": model_id,
                "feature_names": feature_names, "input_dim": len(feature_names),
                "pe_dim": PE_DIM, "edge_dim": 3, "hidden_dim": hidden_dim,
                "embedding_dim": embedding_dim, "threshold": threshold,
                "component_medians": medians, "component_mads": mads}, checkpoint_path)
    evaluation_summary = {key: value for key, value in evaluation.items() if key != "roc_curve"}
    return {"model_id": model_id, "score_collection": SCORE_COLLECTION,
            "run_collection": RUN_COLLECTION, "node_count": len(output_docs),
            "normal_training_nodes": int(normal_mask.sum()), "threshold": threshold,
            "hourly_summary": summaries, "evaluation_metrics": evaluation_summary,
            "hourly_evaluation_metrics": hourly_evaluation,
            "component_roc_auc": component_auc,
            "final_loss": history[-1],
            "checkpoint_path": str(checkpoint_path), "device": str(device)}
