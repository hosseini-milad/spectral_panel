import numpy as np

from ingestion.management.commands.normalize_parquet_dataset import NUMERIC_FIELDS
from ingestion.models.graph_metadata import GraphMetadata
from ingestion.models.sampled_data import SampledSecurityData
from ingestion.services.graph.graph_stats import compute_sparse_graph_stats
from ingestion.services.graph.graph_visualizer import save_graph
from ingestion.services.graph.similarity import build_cosine_sparse_knn
from ingestion.services.graph.components import persist_components
from ingestion.utils.document_paths import document_directory, safe_name


NON_FEATURE_FIELDS = {
    "_id", "source_file", "source_path", "source_day", "source_type", "type",
    "created_at", "candidate_sampled_at", "original_id", "label", "label_binary",
    "isRandom", "candidate_generation", "selection_role", "cluster_id",
    "chunk_index", "normalization_chunk_index",
    "is_outlier_candidate", "timestamp", "flow_start", "window_start", "date",
    "row_index", "normalization_version", "normalization_method", "normalized_at",
    "attack_category", "attack_type", "confidence", "country", "evidence_source",
    "mitre_tactic", "mitre_technique", "protocol", "src_ip", "dst_ip",
    "src_port_category", "dst_port_category", "tcp_flags", "dns_query", "zeek_available",
    "flow_file", "behavioral_flags", "threat_intel_score",
}


def run_graph_pipeline(
    source_file=None,
    create_visualization=True,
    *,
    source_day=None,
    chunk_index=None,
    candidate_generation=None,
    is_random=None,
    feature_fields=None,
    k=12, #12
    threshold=0.995, #0.999
    degree_cap=100, #None,
    target_edges=7000,
    workers=-1,
):
    """Build and persist a sparse, weighted cosine kNN graph.

    Pass source_day/candidate_generation/is_random to build a graph from a
    specific candidate cohort; legacy source_file calls remain supported.
    """
    if source_day is not None:
        query = {"source_day": source_day}
        if chunk_index is not None:
            query["chunk_index"] = int(chunk_index)
        if candidate_generation is not None:
            query["candidate_generation"] = candidate_generation
        if is_random is not None:
            query["isRandom"] = is_random
        base_key = f"clustered-day-{source_day}" if not is_random else f"random-day-{source_day}"
        graph_key = f"{base_key}-chunk-{int(chunk_index)}" if chunk_index is not None else base_key
    else:
        if not source_file:
            raise ValueError("source_file or source_day is required.")
        query = {"source_file": source_file}
        if is_random is not None:
            query["isRandom"] = is_random
        graph_key = source_file

    docs = list(
        SampledSecurityData.objects(__raw__=query)
        .order_by("id")
        .as_pymongo()
    )
    if not docs:
        return None

    if feature_fields is not None:
        requested_fields = list(dict.fromkeys(feature_fields))
        missing_fields = [field for field in requested_fields if field not in docs[0]]
        if missing_fields:
            raise ValueError(
                f"Requested feature field(s) missing from candidate records: {missing_fields}"
            )
        feature_keys = requested_fields
    else:
        available_numeric = [field for field in NUMERIC_FIELDS if field in docs[0]]
        if available_numeric:
            feature_keys = available_numeric
        else:
            feature_keys = [
            key for key, value in docs[0].items()
                if key not in NON_FEATURE_FIELDS and isinstance(value, (int, float))
                and not isinstance(value, bool)
            ]
    if not feature_keys:
        raise ValueError("No numeric feature fields were found for graph construction.")

    def number(value):
        try:
            result = float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
        return result if np.isfinite(result) else 0.0

    X = np.asarray(
        [[number(doc.get(key, 0.0)) for key in feature_keys] for doc in docs],
        dtype=np.float32,
    )
    variable = np.nanstd(X, axis=0) > 1e-8
    X = X[:, variable]
    feature_keys = [key for key, is_variable in zip(feature_keys, variable) if is_variable]
    if X.shape[1] == 0:
        raise ValueError("All graph feature dimensions are constant.")

    edges, diagnostics = build_cosine_sparse_knn(
        X,
        k=k,
        threshold=threshold,
        workers=workers,
        degree_cap=degree_cap,
        target_edges=target_edges,
    )
    stats = compute_sparse_graph_stats(len(docs), edges)
    weights = np.asarray([weight for _, _, weight in edges], dtype=np.float64)
    stats.update({
        "mean_edge_similarity": float(weights.mean()) if len(weights) else 0.0,
        "min_edge_similarity": float(weights.min()) if len(weights) else 0.0,
        "max_edge_similarity": float(weights.max()) if len(weights) else 0.0,
        "knn_union_candidates": diagnostics["knn_union_candidates"],
        "mutual_knn_candidates": diagnostics["mutual_knn_candidates"],
        "thresholded_edges_before_degree_cap": diagnostics["thresholded_edges_before_cap"],
        "nodes_without_qualifying_neighbors": diagnostics["nodes_without_qualifying_neighbors"],
        "threshold_edge_counts": diagnostics["threshold_edge_counts"],
        "candidate_similarity_quantiles": diagnostics["similarity_quantiles"],
        "degree_cap": diagnostics["degree_cap"],
        "similarity_threshold": float(threshold),
        "max_neighbors": int(k),
        "feature_count": int(X.shape[1]),
        "feature_fields": feature_keys,
        "chunk_index": int(chunk_index) if chunk_index is not None else None,
    })

    labels = [int(doc.get("label", 0) or 0) for doc in docs]
    from ingestion.models.graph_representative import GraphRepresentative
    if GraphRepresentative.objects(source_file=graph_key).count():
        raise ValueError('Cannot rebuild a graph with saved representatives; remove downstream artifacts deliberately first.')
    path = None
    if create_visualization and source_day is None and len(docs) <= 5_000:
        path = str(document_directory('nominal', graph_key, day=source_day, chunk=chunk_index) / f"{safe_name(graph_key)}_graph.png")
        save_graph(edges, labels, path)

    graph_doc = GraphMetadata(
        source_file=graph_key,
        source_day=source_day,
        candidate_generation=candidate_generation,
        is_random=is_random,
        graph_path=path,
        stats=stats,
        edges=[
            {"source": int(i), "target": int(j), "weight": float(weight)}
            for i, j, weight in edges
        ],
        node_ids=[str(doc["_id"]) for doc in docs],
        node_labels=labels,
        graph_parameters={
            "similarity": "cosine",
            "neighbor_selection": "union_knn_with_degree_cap",
            "max_neighbors": int(k),
            "degree_cap": diagnostics["degree_cap"],
            "similarity_threshold": float(threshold),
            "weight": "cosine_similarity",
            "feature_fields": feature_keys,
            "chunk_index": int(chunk_index) if chunk_index is not None else None,
        },
        # Avoid exceeding MongoDB's 16 MB document limit on large day graphs.
        features=X.tolist() if len(docs) <= 5_000 else [],
    )
    GraphMetadata.objects(source_file=graph_key).delete()
    graph_doc.save()
    component_result = persist_components(graph_doc.to_mongo().to_dict(), docs=docs)

    return {**stats, "graph_key": graph_key, "graph_path": path,
            "component_count": component_result['component_count'], "component_reports": component_result['paths']}
