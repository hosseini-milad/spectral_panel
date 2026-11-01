
import math
import time

import numpy as np
import networkx as nx
from sklearn.ensemble import IsolationForest

from bson import ObjectId

from ingestion.models.graph_representative import GraphRepresentative
from ingestion.services.graph.components import persist_components, ordered_components
from ingestion.utils.document_paths import document_directory, safe_name

from ingestion.services.pooling.centrality import (
    build_graph,
    compute_centralities,
)
from ingestion.services.pooling.community import (
    detect_communities,
    get_community_statistics,
)
from ingestion.services.pooling.scoring import compute_score
from ingestion.services.pooling.representative import (
    select_representatives,
)
from ingestion.services.pooling.visualization import (
    save_representative_graph,
)


ANOMALY_FIELDS = (
    "bytes",
    "bytes_per_packet",
    "bytes_per_sec",
    "dst_port",
    "duration_s",
    "flag_ack",
    "flag_count",
    "flag_fin",
    "flag_psh",
    "flag_rst",
    "flag_syn",
    "flag_urg",
    "iat_cv",
    "iat_mean",
    "iat_std",
    "is_encrypted_port",
    "is_syn_only",
    "log_bytes",
    "log_duration",
    "log_packets",
    "packets",
    "packets_per_sec",
    "payload_entropy",
    "proto_icmp",
    "proto_tcp",
    "proto_udp",
    "src_port",
    "tos",
)


<<<<<<< HEAD
# Explicit allowlist for component summaries. These are numeric/behavioral
# flow features only; labels, attack descriptors, IPs and threat scores are excluded.
# Explicit, unsupervised feature schema for component profiles.
# Threat intelligence, labels, attack descriptors, IPs, ports-as-identifiers,
# timestamps and provenance fields are intentionally excluded.
COMPONENT_EXCLUDED_FIELDS = {
    "label", "label_binary", "source_label", "source_label_binary",
    "source_label_multiclass", "attack_type", "attack_category",
    "confidence", "evidence_source", "mitre_tactic", "mitre_technique",
    "threat_intel_score", "src_ip", "dst_ip", "src_port", "dst_port",
    "country", "date", "flow_start", "window_start", "flow_file",
    "source_file", "source_path", "source_day", "source_type", "type",
    "original_id", "row_index", "behavioral_flags", "dns_query",
}

# Categorical descriptors retained only as descriptive profiles, never as
# attack labels or high-cardinality identifiers.
COMPONENT_CATEGORICAL_FIELDS = (
    "protocol", "src_port_category", "dst_port_category",
    "flow_duration_class",
)

# Legacy representative-only summary fields retained for backward compatibility.
COMPONENT_MEAN_FIELDS = (
    "bytes", "bytes_per_packet", "bytes_per_sec",
    "duration_s", "packets", "packets_per_sec",
    "flag_ack", "flag_syn", "flag_fin", "flag_psh", "flag_rst", "flag_urg",
)

COMPONENT_BEHAVIOR_FIELDS = (
    "flag_ack", "flag_syn", "flag_fin", "flag_psh", "flag_rst", "flag_urg",
    "is_encrypted_port", "is_syn_only", "proto_icmp", "proto_tcp", "proto_udp",
)


def _finite_numeric(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _component_feature_summary(representative_docs):
    """Mean/std of allow-listed features across this component's reps."""
    means, stds, counts = {}, {}, {}
    for field in COMPONENT_MEAN_FIELDS:
        values = [
            number
            for doc in representative_docs
            if (number := _finite_numeric(doc.get(field))) is not None
        ]
        counts[field] = len(values)
        means[field] = float(np.mean(values)) if values else None
        stds[field] = float(np.std(values)) if values else None
    return means, stds, counts


def _profile_numeric_matrix(matrix, indices, feature_fields):
    """Summarize allowed numeric dimensions over the supplied node indices."""
    result = {}
    if matrix is None or not feature_fields:
        return result

    arr = np.asarray(matrix, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != len(feature_fields):
        return result

    valid_indices = [int(i) for i in indices if 0 <= int(i) < arr.shape[0]]
    if not valid_indices:
        return result

    block = arr[valid_indices]
    for column, field in enumerate(feature_fields):
        if field in COMPONENT_EXCLUDED_FIELDS:
            continue
        values = block[:, column]
        values = values[np.isfinite(values)]
        if values.size == 0:
            result[field] = {"count": 0}
            continue
        result[field] = {
            "count": int(values.size),
            "mean": float(np.mean(values)),
            "std": float(np.std(values)),
            "min": float(np.min(values)),
            "q25": float(np.percentile(values, 25)),
            "median": float(np.percentile(values, 50)),
            "q75": float(np.percentile(values, 75)),
            "max": float(np.max(values)),
        }
    return result


def _profile_categorical(docs):
    """Frequency profiles for a small, explicit non-label categorical allowlist."""
    profile = {}
    for field in COMPONENT_CATEGORICAL_FIELDS:
        counts = {}
        valid = 0
        for doc in docs:
            value = doc.get(field)
            if value is None or value == "":
                continue
            # Bound cardinality to avoid turning arbitrary strings into features.
            key = str(value)[:80]
            counts[key] = counts.get(key, 0) + 1
            valid += 1
        profile[field] = {
            "count": int(valid),
            "categories": {
                key: {
                    "count": int(count),
                    "fraction": float(count / valid) if valid else 0.0,
                }
                for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
            },
        }
    return profile


def _profile_behavior(docs):
    """Prevalence of approved binary/behavioral flags; no label fields."""
    result = {}
    for field in COMPONENT_BEHAVIOR_FIELDS:
        values = []
        for doc in docs:
            number = _finite_numeric(doc.get(field))
            if number is not None:
                values.append(number)
        result[field] = {
            "count": len(values),
            "present_count": int(sum(value > 0.5 for value in values)),
            "prevalence": (
                float(sum(value > 0.5 for value in values) / len(values))
                if values else None
            ),
        }
    return result


def _component_profile_payload(
    member_indices,
    representative_indices,
    docs,
    feature_matrix,
    feature_fields,
    raw_docs_by_id=None,
):
    member_docs = [docs[index] for index in member_indices]
    representative_docs = [docs[index] for index in representative_indices]
    raw_docs_by_id = raw_docs_by_id or {}
    member_raw_docs = [
        raw_docs_by_id[str(doc.get("_id"))]
        for doc in member_docs
        if str(doc.get("_id")) in raw_docs_by_id
    ]
    representative_raw_docs = [
        raw_docs_by_id[str(doc.get("_id"))]
        for doc in representative_docs
        if str(doc.get("_id")) in raw_docs_by_id
    ]

    node_numeric = _profile_numeric_matrix(
        feature_matrix, member_indices, feature_fields
    )
    representative_numeric = _profile_numeric_matrix(
        feature_matrix, representative_indices, feature_fields
    )

    # Fallback for legacy graph metadata without a stored feature matrix.
    if not node_numeric:
        fallback_fields = [
            field for field in COMPONENT_MEAN_FIELDS
            if field not in COMPONENT_EXCLUDED_FIELDS
        ]
        for field in fallback_fields:
            values = [
                number for doc in member_docs
                if (number := _finite_numeric(doc.get(field))) is not None
            ]
            if values:
                arr = np.asarray(values, dtype=np.float64)
                node_numeric[field] = {
                    "count": int(arr.size),
                    "mean": float(np.mean(arr)),
                    "std": float(np.std(arr)),
                    "min": float(np.min(arr)),
                    "q25": float(np.percentile(arr, 25)),
                    "median": float(np.percentile(arr, 50)),
                    "q75": float(np.percentile(arr, 75)),
                    "max": float(np.max(arr)),
                }

    return {
        "node_feature_profile": node_numeric,
        "representative_feature_profile": representative_numeric,
        "categorical_profile": _profile_categorical(member_raw_docs),
        "representative_categorical_profile": _profile_categorical(representative_raw_docs),
        "behavioral_profile": _profile_behavior(member_docs),
    }


=======
>>>>>>> df7795357c49159db67c2c63606e58e16bf6aae4
def _percentile_rank(values):
    """Return deterministic percentile ranks in [0, 1], handling ties."""
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0:
        return values
    if not np.all(np.isfinite(values)):
        values = np.where(np.isfinite(values), values, 0.0)
    order = np.argsort(values, kind="stable")
    ranks = np.empty(values.size, dtype=np.float64)
    ranks[order] = np.linspace(0.0, 1.0, values.size)
    return ranks


def _compute_anomaly_scores(docs):
    """
    Estimate selection priority from three independent signals:
      1. IsolationForest novelty,
      2. local feature-space rarity,
      3. threat_intel_score, when available.

    This is a representative-selection priority, not a calibrated attack
    probability. Labels are deliberately excluded from all anomaly features.
    """
    count = len(docs)
    if count < 3:
        return {index: 0.0 for index in range(count)}

    columns = []
    for field in ANOMALY_FIELDS:
        values = []
        for doc in docs:
            try:
                value = float(doc.get(field, 0.0) or 0.0)
            except (TypeError, ValueError, OverflowError):
                value = 0.0
            values.append(value if math.isfinite(value) else 0.0)

        # Constant features add no information to novelty estimation.
        if float(np.std(values)) > 1e-12:
            columns.append(values)

    if not columns:
        return {index: 0.0 for index in range(count)}

    X = np.asarray(columns, dtype=np.float64)
    X = X.T

    # Robust per-feature scaling limits the effect of outliers and prevents
    # high-range numeric fields from dominating the local-distance signal.
    medians = np.median(X, axis=0)
    q25 = np.percentile(X, 25, axis=0)
    q75 = np.percentile(X, 75, axis=0)
    scales = q75 - q25
    scales[scales < 1e-9] = 1.0
    X_scaled = np.clip((X - medians) / scales, -8.0, 8.0)

    # Signal A: global novelty from Isolation Forest.
    try:
        model = IsolationForest(
            n_estimators=100,
            max_samples=min(256, count),
            contamination="auto",
            random_state=42,
            n_jobs=-1,
        )
        model.fit(X_scaled)
        raw_iforest = -model.score_samples(X_scaled)
        if np.all(np.isfinite(raw_iforest)):
            iforest_rank = _percentile_rank(raw_iforest)
        else:
            iforest_rank = np.zeros(count, dtype=np.float64)
    except Exception as exc:
        print(
            f"[POOLING] WARNING: IsolationForest failed; "
            f"using local rarity only. Cause: {exc}",
            flush=True,
        )
        iforest_rank = np.zeros(count, dtype=np.float64)

    # Signal B: local rarity. A record farther from its nearest distinct
    # feature vector receives higher priority. Duplicate vectors are allowed;
    # their zero distance is meaningful and is not artificially inflated.
    try:
        from sklearn.neighbors import NearestNeighbors

        n_neighbors = min(2, count)
        nn = NearestNeighbors(n_neighbors=n_neighbors, metric="euclidean", n_jobs=-1)
        nn.fit(X_scaled)
        distances, _ = nn.kneighbors(X_scaled)
        # With n_neighbors=2, the first result is usually the point itself;
        # the second is its nearest other record. For duplicate points this
        # distance correctly remains zero.
        local_distance = distances[:, -1]
        local_rarity_rank = _percentile_rank(local_distance)
    except Exception as exc:
        print(
            f"[POOLING] WARNING: local-rarity calculation failed; "
            f"using IsolationForest only. Cause: {exc}",
            flush=True,
        )
        local_rarity_rank = np.zeros(count, dtype=np.float64)

    # Signal C: external threat score, if present. Rank-normalization tolerates
    # scores expressed on different numeric scales without assuming that 0.6
    # has a universal probabilistic meaning.
    threat_values = []
    for doc in docs:
        try:
            value = float(doc.get("threat_intel_score", 0.0) or 0.0)
        except (TypeError, ValueError, OverflowError):
            value = 0.0
        threat_values.append(value if math.isfinite(value) else 0.0)

    threat_array = np.asarray(threat_values, dtype=np.float64)
    if np.any(np.abs(threat_array) > 1e-12):
        threat_rank = _percentile_rank(threat_array)
        # Keep the external threat score as a supporting signal rather than
        # allowing it to overwhelm novelty and structural centrality.
        combined = (
            0.45 * iforest_rank
            + 0.35 * local_rarity_rank
            + 0.20 * threat_rank
        )
    else:
        combined = 0.56 * iforest_rank + 0.44 * local_rarity_rank

    combined = np.clip(combined, 0.0, 1.0)
    return {index: float(value) for index, value in enumerate(combined)}


def run_pooling(
    source_file,
    edges,
    features,
    docs,
    feature_fields=None,
    raw_docs_by_id=None,
    ratio=0.05,
    labels=None,
    anomaly_scores=None,
    attack_ratio=None,
    create_visualization=True,
):
    started_at = time.perf_counter()

    def log_progress(message):
        elapsed = time.perf_counter() - started_at
        print(
            f"[POOLING +{elapsed:8.1f}s] {message}",
            flush=True,
        )

    if not docs:
        raise ValueError("Cannot select representatives from empty docs.")

    if not 0 < ratio < 1:
        raise ValueError("ratio must be strictly between 0 and 1.")

    # --------------------------------------------------
    # 1. Build graph
    # --------------------------------------------------
    log_progress("STEP 1/6: Building graph...")

    G = build_graph(edges)

    # Include sampled nodes without graph edges.
    G.add_nodes_from(range(len(docs)))

    if G.number_of_nodes() != len(docs):
        raise ValueError(
            f"Graph/document mismatch: graph_nodes={G.number_of_nodes()}, "
            f"documents={len(docs)}"
        )

    log_progress(
        f"Graph ready: nodes={G.number_of_nodes()}, "
        f"edges={G.number_of_edges()}"
    )

    log_progress("Detecting communities...")

    partition = detect_communities(G)
    community_stats = get_community_statistics(G, partition)

    log_progress(f"Louvain communities detected: {len(community_stats)}")

    # "Component" in the layer-1 evaluation means a connected component,
    # not a Louvain community. Keep that definition consistent here.
<<<<<<< HEAD
    connected_components = sorted(
        (set(component) for component in nx.connected_components(G)),
        key=lambda component: (-len(component), min(component)),
    )
    log_progress(
        f"Connected components identified: {len(connected_components)}"
    )
=======
    connected_components = ordered_components(G)
>>>>>>> df7795357c49159db67c2c63606e58e16bf6aae4
    node_to_component_index = {}
    for component_index, component_nodes in enumerate(connected_components):
        for node in component_nodes:
            node_to_component_index[int(node)] = int(component_index)

    # --------------------------------------------------
    # 2. Calculate centralities
    # --------------------------------------------------
    log_progress("STEP 2/6: Computing centralities...")

    centrality_started = time.perf_counter()
    centralities = compute_centralities(G)

    log_progress(
        "Centralities completed in "
        f"{time.perf_counter() - centrality_started:.1f}s"
    )

    # --------------------------------------------------
    # 3. Calculate anomaly scores
    # --------------------------------------------------
    log_progress("STEP 3/6: Computing anomaly scores...")

    if anomaly_scores is None:
        anomaly_scores = _compute_anomaly_scores(docs)

    if len(anomaly_scores) != len(docs):
        raise ValueError(
            f"Anomaly score/document mismatch: "
            f"scores={len(anomaly_scores)}, documents={len(docs)}"
        )

    log_progress(
        f"Anomaly scores ready: {len(anomaly_scores)} nodes"
    )

    # --------------------------------------------------
    # 4. Calculate combined scores
    # --------------------------------------------------
    log_progress("STEP 4/6: Computing combined node scores...")

    scores = compute_score(
        centralities,
        anomaly_scores,
    )

    if len(scores) != len(docs):
        raise ValueError(
            f"Score/document mismatch: scores={len(scores)}, "
            f"documents={len(docs)}"
        )

    log_progress(f"Combined scores completed: {len(scores)} nodes")

    # --------------------------------------------------
    # 5. Select representatives
    # --------------------------------------------------
    k = max(1, int(len(docs) * ratio + 0.5))

    if labels is None:
        labels = {
            index: int(doc.get("label", 0) or 0)
            for index, doc in enumerate(docs)
        }

    if len(labels) != len(docs):
        raise ValueError(
            f"Label/document mismatch: labels={len(labels)}, "
            f"documents={len(docs)}"
        )

    if not all(labels.get(i) in (0, 1) for i in range(len(docs))):
        raise ValueError("Labels must be binary values 0 or 1.")

    if attack_ratio is None:
        attack_ratio = (
            sum(labels[i] == 1 for i in range(len(docs))) / len(docs)
        )

    log_progress(
        f"STEP 5/6: Selecting representatives, target={k}..."
    )

    selection_started = time.perf_counter()

    selected_nodes = select_representatives(
        score=scores,
        G=G,
        k=k,
        labels=labels,
        attack_ratio=attack_ratio,
        eigenvector_scores=centralities.get("eigenvector", {}),
        anomaly_scores=anomaly_scores,
    )

    if len(selected_nodes) != k:
        raise ValueError(
            f"Expected {k} representatives, got {len(selected_nodes)}."
        )

    log_progress(
        f"Selection completed: {len(selected_nodes)} representatives "
        f"in {time.perf_counter() - selection_started:.1f}s"
    )

    # Create one persistent entity ID per connected component. This is the
    # same component definition/order used by evaluate_layer1_component_allocation.
    component_metadata = {
        'source_file': source_file,
        'source_day': docs[0].get('source_day'),
        'node_ids': [str(doc['_id']) for doc in docs],
        'edges': edges,
        'graph_parameters': {'layer': 1, 'chunk_index': docs[0].get('chunk_index')},
    }
    component_result = persist_components(component_metadata, docs=docs, write_reports=False)
    component_object_ids = {
        row['component_index']: row['_id'] for row in component_result['components']
    }

    # Prepare all outputs before deleting existing representatives.
    reps = []

    for node_index in selected_nodes:
        node_index = int(node_index)

        if not 0 <= node_index < len(docs):
            raise ValueError(f"Invalid selected node index: {node_index}")

        doc = docs[node_index]

        reps.append({
            "node_index": node_index,
            "original_id": str(doc["_id"]),
            "component_id": str(
                component_object_ids[node_to_component_index[node_index]]
            ),
            "component_index": int(node_to_component_index[node_index]),
            "label": int(labels[node_index]),
            "score": float(scores.get(node_index, 0.0)),
            "centrality": {
                "eigenvector": float(
                    centralities.get("eigenvector", {}).get(
                        node_index, 0.0
                    )
                ),
                "degree": float(
                    centralities.get("degree", {}).get(
                        node_index, 0.0
                    )
                ),
                "betweenness": float(
                    centralities.get("betweenness", {}).get(
                        node_index, 0.0
                    )
                ),
                "anomaly": float(
                    anomaly_scores.get(node_index, 0.0)
                ),
            },
        })

    # --------------------------------------------------
    # 6. Persist layer-1 components and representatives
    # --------------------------------------------------
    log_progress(
        f"STEP 6/6: Saving {len(connected_components)} components and "
        f"{len(reps)} representatives..."
    )

    representative_object_ids = [ObjectId() for _ in reps]
<<<<<<< HEAD
    rep_ids_by_component = {}
    rep_original_ids_by_component = {}
    rep_node_indices_by_component = {}

    for item, rep_id in zip(reps, representative_object_ids):
        component_id = item["component_id"]
        rep_ids_by_component.setdefault(component_id, []).append(str(rep_id))
        rep_original_ids_by_component.setdefault(component_id, []).append(item["original_id"])
        rep_node_indices_by_component.setdefault(component_id, []).append(int(item["node_index"]))

    component_documents = []
    for component_index, member_set in enumerate(connected_components):
        member_indices = sorted(int(node) for node in member_set)
        member_docs = [docs[index] for index in member_indices]
        component_oid = component_object_ids[component_index]
        component_key = str(component_oid)

        selected_rep_indices = rep_node_indices_by_component.get(component_key, [])
        selected_rep_docs = [docs[index] for index in selected_rep_indices]
        mean_features, feature_std, feature_counts = _component_feature_summary(
            selected_rep_docs
        )
        profiles = _component_profile_payload(
            member_indices=member_indices,
            representative_indices=selected_rep_indices,
            docs=docs,
            feature_matrix=features,
            feature_fields=feature_fields or [],
            raw_docs_by_id=raw_docs_by_id,
        )
        subgraph = G.subgraph(member_set)
        degrees = [int(degree) for _, degree in subgraph.degree()]

        component_documents.append(
            GraphComponent(
                id=component_oid,
                component_id=component_key,
                source_file=source_file,
                source_day=(
                    str(member_docs[0].get("source_day"))
                    if member_docs and member_docs[0].get("source_day") is not None
                    else None
                ),
                layer=1,
                component_index=int(component_index),
                node_indices=member_indices,
                node_ids=[str(doc["_id"]) for doc in member_docs],
                node_count=len(member_indices),
                representative_ids=rep_ids_by_component.get(component_key, []),
                representative_original_ids=rep_original_ids_by_component.get(component_key, []),
                representative_node_indices=rep_node_indices_by_component.get(component_key, []),
                representative_count=len(rep_ids_by_component.get(component_key, [])),
                mean_features=mean_features,
                feature_std=feature_std,
                feature_observation_counts=feature_counts,
                feature_fields=sorted(profiles["node_feature_profile"].keys()),
                node_feature_profile=profiles["node_feature_profile"],
                representative_feature_profile=profiles["representative_feature_profile"],
                categorical_profile=profiles["categorical_profile"],
                representative_categorical_profile=profiles["representative_categorical_profile"],
                behavioral_profile=profiles["behavioral_profile"],
                component_statistics={
                    "internal_edges": int(subgraph.number_of_edges()),
                    "density": float(nx.density(subgraph)) if len(member_set) > 1 else 0.0,
                    "avg_degree": float(np.mean(degrees)) if degrees else 0.0,
                    "max_degree": int(max(degrees)) if degrees else 0,
                    "min_degree": int(min(degrees)) if degrees else 0,
                    "is_isolate": bool(len(member_set) == 1 and G.degree(next(iter(member_set))) == 0),
                },
            )
        )

=======
>>>>>>> df7795357c49159db67c2c63606e58e16bf6aae4
    representative_documents = []
    for item, rep_id in zip(reps, representative_object_ids):
        representative_documents.append(
            GraphRepresentative(
                id=rep_id,
                source_file=source_file,
                original_id=item["original_id"],
                node_index=item["node_index"],
                component_id=item["component_id"],
                component_index=item["component_index"],
                attention=item["score"],
                label=item["label"],
                centrality=item["centrality"]["eigenvector"],
            )
        )

    # Keep the prior representative set until the replacement inserts succeed.
    try:
        if representative_documents:
            GraphRepresentative.objects.insert(
                representative_documents, load_bulk=False
            )
    except Exception:
        GraphRepresentative.objects(id__in=representative_object_ids).delete()
        raise

    GraphRepresentative.objects(source_file=source_file, id__nin=representative_object_ids).delete()
    component_result = persist_components(component_metadata, docs=docs)
    log_progress(
        f"Saved components={component_result['component_count']}; "
        f"representatives={len(representative_documents)}"
    )

    if create_visualization:
        image_dir = document_directory('nominal', source_file, day=docs[0].get('source_day'), chunk=docs[0].get('chunk_index'))
        image_path = str(image_dir / f"{safe_name(source_file)}_representatives.png")

        save_representative_graph(
            edges=edges,
            representatives=reps,
            path=image_path,
            all_nodes=range(len(docs)),
        )

        print("Representative graph:", image_path)

    log_progress(
        f"ALL STEPS COMPLETED: components={len(connected_components)}, "
        f"representatives={len(reps)} in {time.perf_counter() - started_at:.1f}s"
    )

    return reps
