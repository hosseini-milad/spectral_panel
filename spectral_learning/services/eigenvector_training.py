import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from mongoengine import get_connection
from pymongo import ReplaceOne

from .temporal_graph import GRAPH_COLLECTION


EMBEDDING_COLLECTION = "temporal_node_embeddings"
RUN_COLLECTION = "temporal_graph_training_runs"
PE_DIM = 8
SCALE_IDS = {"minute": 0, "hour": 1, "day": 2}
NON_MODEL_FEATURES = {
    "src_ip", "dst_ip", "src_port", "dst_port", "flow_id", "timestamp",
    "protocol", "label",
}


def _load_snapshots(database, source_file, scales):
    snapshots = list(
        database[GRAPH_COLLECTION].find(
            {"source_file": source_file, "scale": {"$in": scales}}
        ).sort([("scale", 1), ("window_start", 1)])
    )
    if not snapshots:
        raise ValueError(
            f"No temporal graph snapshots for {source_file!r}; build graphs first."
        )
    return snapshots


def _feature_schema(snapshots):
    return sorted({
        key
        for snapshot in snapshots
        for node in snapshot["nodes"]
        for key, value in node.get("features", {}).items()
        if key not in NON_MODEL_FEATURES and isinstance(value, (int, float))
    })


def _torch_graph(snapshot, feature_names, torch, device):
    nodes = {node["node_id"]: node for node in snapshot["nodes"]}
    node_ids = snapshot["spectral"]["node_order"]
    node_index = {node_id: index for index, node_id in enumerate(node_ids)}
    features = np.asarray(
        [
            [float(nodes[node_id].get("features", {}).get(key, 0.0)) for key in feature_names]
            for node_id in node_ids
        ],
        dtype=np.float32,
    )

    positional = np.zeros((len(node_ids), PE_DIM), dtype=np.float32)
    for index, eigenvector in enumerate(snapshot["spectral"].get("eigenvectors", [])[:PE_DIM]):
        values = np.asarray(eigenvector["values"], dtype=np.float32)
        positional[:, index] = values * np.sqrt(max(float(eigenvector["eigenvalue"]), 0.0))

    edges = snapshot.get("edges", [])
    pairs = np.asarray(
        [
            [node_index[edge["source"]], node_index[edge["target"]]]
            for edge in edges
        ],
        dtype=np.int64,
    ).reshape(-1, 2)
    edge_values = np.asarray(
        [
            [
                np.log1p(max(float(edge.get("flow_count", 0)), 0.0)),
                np.log1p(max(float(edge.get("bytes", 0)), 0.0)),
                np.log1p(max(float(edge.get("packets", 0)), 0.0)),
            ]
            for edge in edges
        ],
        dtype=np.float32,
    ).reshape(-1, 3)
    if len(edge_values):
        edge_values /= np.maximum(edge_values.max(axis=0, keepdims=True), 1.0)

    return {
        "node_ids": node_ids,
        "nodes": nodes,
        "features": torch.tensor(features, device=device),
        "positional": torch.tensor(positional, device=device),
        "edge_index": torch.tensor(pairs.T.copy(), dtype=torch.long, device=device),
        "edge_features": torch.tensor(edge_values, device=device),
        "positive_pairs": torch.tensor(pairs, dtype=torch.long, device=device),
        "scale_id": torch.tensor(SCALE_IDS[snapshot["scale"]], dtype=torch.long, device=device),
        "snapshot": snapshot,
    }


def _negative_pairs(graph, count, torch, device, rng):
    node_count = graph["features"].shape[0]
    positives = {
        (int(source), int(target))
        for source, target in graph["positive_pairs"].detach().cpu().tolist()
    }
    candidates = [
        (source, target)
        for source in range(node_count)
        for target in range(node_count)
        if source != target and (source, target) not in positives
    ]
    if not candidates or count == 0:
        return torch.empty((0, 2), dtype=torch.long, device=device)
    picked = rng.sample(candidates, min(count, len(candidates)))
    return torch.tensor(picked, dtype=torch.long, device=device)


def _loss_for_graph(model, graph, torch, functional, rng, mask_rate, spectral_weight):
    features = graph["features"]
    mask = torch.rand_like(features) < mask_rate
    if not mask.any():
        mask[0, 0] = True
    corrupted = features.masked_fill(mask, 0.0)
    embeddings = model.encode(
        corrupted,
        graph["positional"],
        graph["edge_index"],
        graph["edge_features"],
        graph["scale_id"],
    )

    reconstructed = model.reconstruct_features(embeddings)
    feature_loss = functional.mse_loss(reconstructed[mask], features[mask])

    positive = graph["positive_pairs"]
    negative = _negative_pairs(graph, len(positive), torch, features.device, rng)
    if len(positive) and len(negative):
        pairs = torch.cat([positive, negative], dim=0)
        targets = torch.cat([
            torch.ones(len(positive), device=features.device),
            torch.zeros(len(negative), device=features.device),
        ])
        link_logits = model.decode_links(embeddings, pairs)
        link_loss = functional.binary_cross_entropy_with_logits(link_logits, targets)
    else:
        link_loss = features.new_tensor(0.0)

    positional = graph["positional"]
    if positional.shape[1] and torch.count_nonzero(positional):
        target_gram = positional @ positional.T
        target_norm = target_gram.diag().clamp_min(1e-8).sqrt()
        target_gram = target_gram / (target_norm[:, None] * target_norm[None, :]).clamp_min(1e-8)
        embedding_norm = functional.normalize(embeddings, p=2, dim=-1)
        embedding_gram = embedding_norm @ embedding_norm.T
        spectral_loss = functional.mse_loss(embedding_gram, target_gram)
    else:
        spectral_loss = features.new_tensor(0.0)

    total = feature_loss + link_loss + spectral_weight * spectral_loss
    return total, {
        "feature": feature_loss.detach(),
        "link": link_loss.detach(),
        "spectral": spectral_loss.detach(),
    }


def train_eigenvector_encoder(
    source_file,
    scales=("minute",),
    epochs=50,
    hidden_dim=64,
    embedding_dim=32,
    learning_rate=0.001,
    mask_rate=0.15,
    spectral_weight=0.2,
    seed=17,
    checkpoint_path=None,
):
    try:
        import torch
        from torch.nn import functional as F
        from ..models.eigenvector_gnn import EigenvectorAwareGraphEncoder
    except ImportError as exc:
        raise RuntimeError(
            "PyTorch is required for eigenvector-aware training. "
            "Install the project requirements first."
        ) from exc

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    database = get_connection(alias="default")["siem_db"]
    snapshots = _load_snapshots(database, source_file, list(scales))
    feature_names = _feature_schema(snapshots)
    if not feature_names:
        raise ValueError("Graph snapshots do not contain numeric node features.")
    graphs = [_torch_graph(snapshot, feature_names, torch, device) for snapshot in snapshots]

    model = EigenvectorAwareGraphEncoder(
        input_dim=len(feature_names),
        pe_dim=PE_DIM,
        edge_dim=3,
        hidden_dim=hidden_dim,
        embedding_dim=embedding_dim,
    ).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=1e-5)
    rng = random.Random(seed)
    history = []

    for epoch in range(epochs):
        model.train()
        optimizer.zero_grad()
        losses = []
        component_losses = []
        for graph in graphs:
            loss, components = _loss_for_graph(
                model, graph, torch, F, rng, mask_rate, spectral_weight
            )
            losses.append(loss)
            component_losses.append(components)
        epoch_loss = torch.stack(losses).mean()
        epoch_loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()
        history.append({
            "epoch": epoch + 1,
            "loss": float(epoch_loss.detach().cpu()),
            "feature_loss": float(torch.stack([item["feature"] for item in component_losses]).mean().cpu()),
            "link_loss": float(torch.stack([item["link"] for item in component_losses]).mean().cpu()),
            "spectral_loss": float(torch.stack([item["spectral"] for item in component_losses]).mean().cpu()),
        })

    model.eval()
    embedding_documents = []
    with torch.no_grad():
        for graph in graphs:
            embeddings = model.encode(
                graph["features"], graph["positional"], graph["edge_index"],
                graph["edge_features"], graph["scale_id"],
            ).cpu().numpy()
            snapshot = graph["snapshot"]
            for index, node_id in enumerate(graph["node_ids"]):
                node = graph["nodes"][node_id]
                embedding_documents.append({
                    "_id": f"{source_file}:{snapshot['window_key']}:{node_id}",
                    "source_file": source_file,
                    "scale": snapshot["scale"],
                    "window_key": snapshot["window_key"],
                    "window_start": snapshot["window_start"],
                    "node_id": node_id,
                    "embedding": [float(value) for value in embeddings[index]],
                    "in_degree": node["in_degree"],
                    "out_degree": node["out_degree"],
                    "model_id": f"{source_file}:eigenvector-aware:{','.join(scales)}:latest",
                })

    client = get_connection(alias="default")
    embedding_collection = client["siem_db"][EMBEDDING_COLLECTION]
    embedding_collection.create_index([("source_file", 1), ("scale", 1), ("window_start", 1)])
    embedding_collection.create_index([("source_file", 1), ("node_id", 1)])
    for start in range(0, len(embedding_documents), 500):
        batch = embedding_documents[start : start + 500]
        embedding_collection.bulk_write(
            [ReplaceOne({"_id": item["_id"]}, item, upsert=True) for item in batch],
            ordered=False,
        )
    expected_ids = [item["_id"] for item in embedding_documents]
    embedding_collection.delete_many({"source_file": source_file, "_id": {"$nin": expected_ids}})

    model_id = f"{source_file}:eigenvector-aware:{','.join(scales)}:latest"
    run_document = {
        "_id": model_id,
        "source_file": source_file,
        "scales": list(scales),
        "model_type": "eigenvector_aware_graph_autoencoder",
        "objective": "masked_features+directed_links+spectral_gram",
        "feature_names": feature_names,
        "hidden_dim": hidden_dim,
        "embedding_dim": embedding_dim,
        "epochs": epochs,
        "learning_rate": learning_rate,
        "mask_rate": mask_rate,
        "spectral_weight": spectral_weight,
        "device": str(device),
        "graph_count": len(graphs),
        "node_embedding_count": len(embedding_documents),
        "training_history": history,
        "completed_at": datetime.now(timezone.utc),
    }
    database[RUN_COLLECTION].replace_one({"_id": model_id}, run_document, upsert=True)

    if checkpoint_path is None:
        safe_name = "".join(character if character.isalnum() else "_" for character in source_file)
        checkpoint_path = Path("artifacts") / f"eigenvector_encoder_{safe_name}.pt"
    checkpoint_path = Path(checkpoint_path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "model_state_dict": model.state_dict(),
        "model_id": model_id,
        "feature_names": feature_names,
        "scales": list(scales),
        "scale_ids": SCALE_IDS,
        "input_dim": len(feature_names),
        "pe_dim": PE_DIM,
        "edge_dim": 3,
        "hidden_dim": hidden_dim,
        "embedding_dim": embedding_dim,
    }, checkpoint_path)

    return {
        "source_file": source_file,
        "model_id": model_id,
        "embedding_collection": EMBEDDING_COLLECTION,
        "embedding_count": len(embedding_documents),
        "graph_count": len(graphs),
        "feature_count": len(feature_names),
        "embedding_dim": embedding_dim,
        "scales": list(scales),
        "device": str(device),
        "final_loss": history[-1]["loss"],
        "checkpoint_path": str(checkpoint_path),
    }
