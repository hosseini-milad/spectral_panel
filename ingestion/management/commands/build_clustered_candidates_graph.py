from datetime import datetime
import math
import time

import networkx as nx
import numpy as np
from bson import ObjectId
from django.core.management.base import BaseCommand, CommandError
from mongoengine import get_connection
from pymongo import InsertOne
from sklearn.neighbors import NearestNeighbors

from ingestion.management.commands.normalize_parquet_dataset import NUMERIC_FIELDS
from ingestion.services.pooling.centrality import compute_centralities
from ingestion.services.pooling.scoring import compute_score
from ingestion.services.pooling.representative import select_representatives


GENERATION = "graph_score_centrality_representatives_v1"
FEATURE_FIELDS = tuple(NUMERIC_FIELDS)
DEFAULT_RATIO = 0.10
DEFAULT_K = 12
DEFAULT_COSINE_THRESHOLD = 0.995
DEFAULT_DEGREE_CAP = 20


def _safe_float(value):
    try:
        result = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def _label(record):
    value = record.get("label", record.get("label_binary", 0))
    try:
        value = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return 0
    return value if value in (0, 1) else 0


def _make_feature_matrix(records, fields):
    matrix = np.zeros((len(records), len(fields)), dtype=np.float32)
    for row, record in enumerate(records):
        for col, field in enumerate(fields):
            matrix[row, col] = _safe_float(record.get(field, 0))
    if matrix.size:
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        np.divide(matrix, np.maximum(norms, 1e-12), out=matrix)
    return matrix


def _build_cosine_graph(matrix, k=DEFAULT_K, threshold=DEFAULT_COSINE_THRESHOLD,
                        degree_cap=DEFAULT_DEGREE_CAP):
    """Deterministic bounded-degree cosine kNN graph; no random candidate selection."""
    n = matrix.shape[0]
    graph = nx.Graph()
    graph.add_nodes_from(range(n))
    if n < 2:
        return graph

    neighbor_count = min(n, max(2, k + 1))
    nn = NearestNeighbors(
        n_neighbors=neighbor_count, metric="cosine",
        algorithm="brute", n_jobs=-1,
    )
    nn.fit(matrix)
    distances, indices = nn.kneighbors(matrix, return_distance=True)

    strongest = {}
    for source in range(n):
        for distance, target_value in zip(distances[source], indices[source]):
            target = int(target_value)
            if target == source:
                continue
            similarity = 1.0 - float(distance)
            if similarity < threshold:
                continue
            a, b = (source, target) if source < target else (target, source)
            strongest[(a, b)] = max(similarity, strongest.get((a, b), -1.0))

    ranked_edges = sorted(
        ((weight, a, b) for (a, b), weight in strongest.items()),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    degree = [0] * n
    for weight, source, target in ranked_edges:
        if degree[source] >= degree_cap or degree[target] >= degree_cap:
            continue
        graph.add_edge(source, target, weight=max(0.0, weight))
        degree[source] += 1
        degree[target] += 1
    return graph


class Command(BaseCommand):
    help = (
        "Select exactly 10% graph-based candidates using existing centrality, "
        "combined-score, and representative-selection functions."
    )
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--day", required=True)
        parser.add_argument("--chunk-index", type=int, required=True)
        parser.add_argument("--count", type=int, default=20000)
        parser.add_argument("--ratio", type=float, default=DEFAULT_RATIO)
        parser.add_argument("--k", type=int, default=DEFAULT_K)
        parser.add_argument("--cosine-threshold", type=float,
                            default=DEFAULT_COSINE_THRESHOLD)
        parser.add_argument("--degree-cap", type=int, default=DEFAULT_DEGREE_CAP)
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **options):
        started = time.perf_counter()
        day = options["day"]
        chunk_index = options["chunk_index"]
        input_limit = options["count"]
        ratio = options["ratio"]
        k = options["k"]
        threshold = options["cosine_threshold"]
        degree_cap = options["degree_cap"]
        batch_size = options["batch_size"]

        if chunk_index < 0 or input_limit < 1 or batch_size < 1:
            raise CommandError("chunk-index must be >= 0; count and batch-size must be positive.")
        if not 0 < ratio < 1:
            raise CommandError("--ratio must be greater than 0 and less than 1.")
        if k < 1 or degree_cap < 1:
            raise CommandError("--k and --degree-cap must be positive.")
        if not -1.0 <= threshold <= 1.0:
            raise CommandError("--cosine-threshold must be in [-1, 1].")

        db = get_connection(alias="default")["siem_db"]
        normalized = db["normalized_security_data"]
        sampled = db["sampled_security_data"]
        source_filter = {
            "source_day": day,
            "normalization_chunk_index": chunk_index,
        }
        available = normalized.count_documents(source_filter)
        if available == 0:
            raise CommandError(
                f"No normalized records found for source_day={day!r}, "
                f"normalization_chunk_index={chunk_index}."
            )

        input_count = min(available, input_limit)
        target = max(1, int(round(input_count * ratio)))
        output_filter = {
            "source_day": day,
            "chunk_index": chunk_index,
            "candidate_generation": GENERATION,
            "isRandom": False,
        }
        existing = sampled.count_documents(output_filter)
        if existing and not options["force"]:
            raise CommandError(
                f"{existing} candidates already exist for this day/chunk. "
                "Use --force to replace them."
            )

        projection = {field: 1 for field in FEATURE_FIELDS}
        projection.update({
            "_id": 1, "label": 1, "label_binary": 1, "original_id": 1,
            "source_file": 1, "source_path": 1, "source_day": 1,
            "source_type": 1, "type": 1, "row_index": 1,
            "window_start": 1, "flow_start": 1, "timestamp": 1,
            "attack_category": 1, "attack_type": 1,
        })
        docs = list(
            normalized.find(source_filter, projection)
            .sort("_id", 1)
            .limit(input_count)
        )
        if len(docs) != input_count:
            raise CommandError(f"Expected {input_count} inputs, read {len(docs)}.")

        fields = [field for field in FEATURE_FIELDS if any(field in doc for doc in docs)]
        if not fields:
            raise CommandError("No numeric feature fields were found in the input chunk.")
        matrix = _make_feature_matrix(docs, fields)

        self.stdout.write(
            f"[CANDIDATES] Input={len(docs):,}; target={target:,}; "
            f"ratio={ratio:.3f}; fields={len(fields)}"
        )
        self.stdout.write("[CANDIDATES] Building cosine kNN graph...")
        graph = _build_cosine_graph(
            matrix, k=k, threshold=threshold, degree_cap=degree_cap
        )
        self.stdout.write(
            f"[CANDIDATES] Graph: nodes={graph.number_of_nodes():,}; "
            f"edges={graph.number_of_edges():,}; "
            f"components={nx.number_connected_components(graph):,}"
        )

        labels = {i: _label(doc) for i, doc in enumerate(docs)}
        self.stdout.write("[CANDIDATES] Computing existing centrality functions...")
        centralities = compute_centralities(graph)
        scores = compute_score(centralities, anomaly_scores=None)

        self.stdout.write("[CANDIDATES] Selecting via select_representatives...")
        selected = select_representatives(
            score=scores,
            G=graph,
            k=target,
            labels=labels,
            attack_ratio=sum(v == 1 for v in labels.values()) / max(1, len(labels)),
            eigenvector_scores=centralities.get("eigenvector", {}),
            anomaly_scores=None,
        )
        selected = list(dict.fromkeys(int(i) for i in selected))
        if len(selected) != target:
            raise CommandError(
                f"Representative function returned {len(selected)} candidates; "
                f"expected {target}. No records were written."
            )

        if options["force"]:
            sampled.delete_many(output_filter)

        created_at = datetime.utcnow()
        operations = []
        try:
            for number, index in enumerate(selected, start=1):
                record = dict(docs[index])
                record.pop("_id", None)
                record["_id"] = ObjectId()
                record["isRandom"] = False
                record["candidate_generation"] = GENERATION
                record["candidate_sampled_at"] = created_at
                record["selection_role"] = "graph_score_centrality_representative"
                record["candidate_score"] = _safe_float(scores.get(index, 0.0))
                record["candidate_eigenvector_centrality"] = _safe_float(
                    centralities.get("eigenvector", {}).get(index, 0.0)
                )
                record["candidate_degree"] = int(graph.degree(index))
                record["chunk_index"] = chunk_index
                record["normalization_chunk_index"] = chunk_index
                record["source_day"] = day
                record["source_file"] = f"clustered-day-{day}-chunk-{chunk_index}"
                operations.append(InsertOne(record))

                if len(operations) >= batch_size:
                    sampled.bulk_write(operations, ordered=False)
                    operations.clear()
                if number % 250 == 0 or number == target:
                    self.stdout.write(f"[CANDIDATES] Stored {number:,}/{target:,}")

            if operations:
                sampled.bulk_write(operations, ordered=False)
        except Exception:
            sampled.delete_many(output_filter)
            raise

        stored = sampled.count_documents(output_filter)
        if stored != target:
            raise CommandError(f"Stored {stored} records; expected exactly {target}.")

        label_counts = {
            str(label): sampled.count_documents({**output_filter, "label": label})
            for label in (0, 1)
        }
        self.stdout.write(self.style.SUCCESS(
            f"[CANDIDATES] SUCCESS: {stored:,}/{input_count:,} records "
            f"({100 * stored / input_count:.1f}%); labels={label_counts}; "
            f"elapsed={time.perf_counter() - started:.1f}s"
        ))
