import re
import time
from datetime import datetime

import numpy as np
from bson import ObjectId
from bson.errors import InvalidId
from django.core.management.base import BaseCommand, CommandError
from mongoengine import get_connection

from ingestion.models.graph_representative import GraphRepresentative
from ingestion.services.graph.graph_stats import compute_sparse_graph_stats


DEFAULT_FEATURE_FIELDS = [
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
    "is_encrypted_port",
    "is_syn_only",
    "log_bytes",
    "log_duration",
    "log_packets",
    "packets",
    "packets_per_sec",
    "proto_icmp",
    "proto_tcp",
    "proto_udp",
    "src_port",
    "tos",
]


class Command(BaseCommand):
    """
    Build the layer-2/day graph from all layer-1 representatives belonging
    to chunks of one day. Features are recovered from sampled_security_data
    using each representative's original_id.
    """
    help = (
        "Build a cosine union-kNN graph from all chunk representatives for a day."
    )
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--day", required=True, help="YYYY-MM-DD")
        parser.add_argument(
            "--threshold", type=float, default=0.995,
            help="Create an edge for every pair whose cosine similarity meets this threshold.",
        )
        parser.add_argument(
            "--degree-cap", type=int, default=0,
            help="Optional maximum degree. 0 (default) preserves all qualifying edges.",
        )
        parser.add_argument(
            "--block-size", type=int, default=512,
            help="Rows per block for exact all-pairs cosine calculation.",
        )
        parser.add_argument(
            "--feature-fields",
            nargs="+",
            default=DEFAULT_FEATURE_FIELDS,
            help="Numeric normalized feature fields used for cosine similarity.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Replace the hierarchy graph for this day if it already exists.",
        )

    @staticmethod
    def _as_object_id_or_string(value):
        text = str(value)
        try:
            return ObjectId(text)
        except (InvalidId, TypeError):
            return text

    @staticmethod
    def _number(value):
        try:
            result = float(value or 0.0)
        except (TypeError, ValueError, OverflowError):
            return 0.0
        return result if np.isfinite(result) else 0.0

    @staticmethod
    def _build_all_pairs_threshold_graph(X, threshold, block_size=512, degree_cap=0):
        """Exact blockwise all-pairs cosine graph.

        Every unordered pair is checked. No kNN pre-filter is used. By default,
        every pair meeting the threshold becomes an edge; an optional degree cap
        can be explicitly requested, but it necessarily removes qualifying edges.
        """
        X = np.asarray(X, dtype=np.float32)
        if X.ndim != 2:
            raise ValueError("X must be a two-dimensional feature matrix.")
        if block_size < 1:
            raise ValueError("block_size must be positive.")
        if degree_cap < 0:
            raise ValueError("degree_cap must be zero (no cap) or positive.")

        n = X.shape[0]
        norms = np.linalg.norm(X, axis=1, keepdims=True)
        X_unit = np.divide(X, norms, out=np.zeros_like(X), where=norms > 1e-12)

        edges = []
        threshold_counts = {
            str(value): 0
            for value in (0.95, 0.99, 0.995, 0.999, 0.9995, 0.9999, 0.99995)
        }
        qualifying_degree = np.zeros(n, dtype=np.int64)
        total_pairs = n * (n - 1) // 2

        # Only upper-triangle pairs are emitted, exactly once.
        for start in range(0, n, block_size):
            stop = min(n, start + block_size)
            similarities = X_unit[start:stop] @ X_unit.T

            for local_row, left in enumerate(range(start, stop)):
                if left + 1 >= n:
                    continue
                row = np.clip(similarities[local_row, left + 1:], -1.0, 1.0)
                for q in threshold_counts:
                    threshold_counts[q] += int(np.count_nonzero(row >= float(q)))

                matching = np.flatnonzero(row >= threshold)
                if matching.size:
                    right_ids = matching + left + 1
                    sims = row[matching]
                    qualifying_degree[left] += int(matching.size)
                    np.add.at(qualifying_degree, right_ids, 1)
                    edges.extend(
                        (int(left), int(right), float(sim))
                        for right, sim in zip(right_ids, sims)
                    )

            print(
                f"[HIERARCHY] Pairwise progress: rows={stop:,}/{n:,}; "
                f"threshold_edges_so_far={len(edges):,}",
                flush=True,
            )

        qualifying_edges_before_cap = len(edges)
        degree_before_cap = qualifying_degree.copy()

        if degree_cap > 0 and edges:
            # Deterministic strongest-first cap. This is optional and lossy:
            # edges are retained only when both endpoints still have capacity.
            edges.sort(key=lambda edge: (-edge[2], edge[0], edge[1]))
            capped = []
            degree = np.zeros(n, dtype=np.int64)
            for left, right, similarity in edges:
                if degree[left] >= degree_cap or degree[right] >= degree_cap:
                    continue
                capped.append((left, right, similarity))
                degree[left] += 1
                degree[right] += 1
            edges = capped
            final_degree = degree
        else:
            final_degree = degree_before_cap

        weights = np.asarray([edge[2] for edge in edges], dtype=np.float64)
        diagnostics = {
            "algorithm": "exact_blockwise_all_pairs_cosine_threshold",
            "total_possible_pairs": int(total_pairs),
            "pairs_checked": int(total_pairs),
            "qualifying_edges_before_degree_cap": int(qualifying_edges_before_cap),
            "edges_removed_by_degree_cap": int(qualifying_edges_before_cap - len(edges)),
            "threshold_edge_counts_all_pairs": threshold_counts,
            "nodes_without_qualifying_neighbors": int(np.count_nonzero(degree_before_cap == 0)),
            "degree_cap": int(degree_cap) if degree_cap > 0 else None,
            "mean_candidate_similarity": float(weights.mean()) if len(weights) else 0.0,
            "candidate_similarity_quantiles": {
                str(q): float(np.quantile(weights, q))
                for q in (0.1, 0.25, 0.5, 0.75, 0.9)
            } if len(weights) else {},
        }
        return edges, diagnostics

    def handle(self, *args, **options):
        day = options["day"]
        try:
            datetime.strptime(day, "%Y-%m-%d")
        except ValueError as exc:
            raise CommandError("--day must be in YYYY-MM-DD format.") from exc

        if options["block_size"] < 1:
            raise CommandError("--block-size must be positive.")
        if not -1 <= options["threshold"] <= 1:
            raise CommandError("--threshold must be in [-1, 1].")
        if options["degree_cap"] < 0:
            raise CommandError("--degree-cap must be zero (no cap) or positive.")
        if not options["feature_fields"]:
            raise CommandError("At least one feature field is required.")

        graph_key = f"hierarchy-day-{day}-layer-2"
        database = get_connection(alias="default")["siem_db"]
        hyper_graphs = database["hyper_graph_metadata"]
        hyper_edges = database["hyper_graph_edges"]
        existing_graph = hyper_graphs.find_one({"source_file": graph_key})
        if existing_graph and not options["force"]:
            raise CommandError(
                f"Hierarchy graph already exists in hyper_graph_metadata: {graph_key}. "
                "Use --force to intentionally rebuild it."
            )

        # Match every chunk key for this day, e.g.:
        # clustered-day-2026-06-21-chunk-0, ...-chunk-19.
        source_pattern = re.compile(
            rf"^clustered-day-{re.escape(day)}-chunk-[0-9]+$"
        )
        load_started = time.perf_counter()
        rep_docs = list(
            GraphRepresentative.objects(
                __raw__={"source_file": {"$regex": source_pattern.pattern}}
            )
            .order_by("source_file", "node_index")
            .as_pymongo()
        )
        if not rep_docs:
            raise CommandError(
                f"No representatives found for day {day}. Expected source_file "
                f"keys matching clustered-day-{day}-chunk-N."
            )
        self.stdout.write(
            f"[HIERARCHY] Loaded {len(rep_docs):,} representatives from "
            f"{len(set(doc.get('source_file') for doc in rep_docs))} chunks "
            f"in {time.perf_counter() - load_started:.2f}s."
        )

        # The representative records carry IDs/labels/scores, not the full
        # feature vector. Recover each original candidate from sampled_security_data.
        original_ids = [str(doc.get("original_id", "")) for doc in rep_docs]
        if any(not value for value in original_ids):
            raise CommandError("At least one representative has no original_id.")

        sampled = database["sampled_security_data"]
        lookup_values = [self._as_object_id_or_string(value) for value in original_ids]

        source_docs_by_id = {}
        lookup_started = time.perf_counter()
        batch_size = 1000
        for start in range(0, len(lookup_values), batch_size):
            batch = lookup_values[start:start + batch_size]
            cursor = sampled.find(
                {"_id": {"$in": batch}},
                {"_id": 1, "label": 1, **{field: 1 for field in options["feature_fields"]}},
            )
            try:
                for doc in cursor:
                    source_docs_by_id[str(doc["_id"])] = doc
            finally:
                cursor.close()

        self.stdout.write(
            f"[HIERARCHY] Retrieved {len(source_docs_by_id):,}/{len(original_ids):,} "
            f"source records in {time.perf_counter() - lookup_started:.2f}s."
        )
        missing = [value for value in original_ids if value not in source_docs_by_id]
        if missing:
            raise CommandError(
                f"Could not find {len(missing)} of {len(original_ids)} representative "
                f"source records in sampled_security_data by _id. Examples: {missing[:5]}"
            )

        feature_fields = list(dict.fromkeys(options["feature_fields"]))
        X = np.asarray(
            [
                [self._number(source_docs_by_id[original_id].get(field, 0.0))
                 for field in feature_fields]
                for original_id in original_ids
            ],
            dtype=np.float32,
        )

        variable_mask = np.nanstd(X, axis=0) > 1e-8
        X = X[:, variable_mask]
        feature_fields = [
            field for field, keep in zip(feature_fields, variable_mask) if keep
        ]
        if X.shape[1] == 0:
            raise CommandError("All selected feature dimensions are constant.")

        self.stdout.write(
            f"[HIERARCHY] day={day}; representatives={len(rep_docs)}; "
            f"feature_count={X.shape[1]}; graph_key={graph_key}"
        )
        similarity_started = time.perf_counter()
        self.stdout.write(
            f"[HIERARCHY] Building exact all-pairs cosine graph: "
            f"nodes={X.shape[0]:,}; features={X.shape[1]}; "
            f"possible_pairs={X.shape[0] * (X.shape[0] - 1) // 2:,}; "
            f"threshold={options['threshold']}; "
            f"degree_cap={options['degree_cap'] or 'disabled'}; "
            f"block_size={options['block_size']}."
        )
        edges, diagnostics = self._build_all_pairs_threshold_graph(
            X,
            threshold=options["threshold"],
            block_size=options["block_size"],
            degree_cap=options["degree_cap"],
        )
        self.stdout.write(
            f"[HIERARCHY] Similarity graph computed in "
            f"{time.perf_counter() - similarity_started:.2f}s; edges={len(edges):,}."
        )

        stats = compute_sparse_graph_stats(len(rep_docs), edges)
        weights = np.asarray([weight for _, _, weight in edges], dtype=np.float64)
        stats.update({
            "mean_edge_similarity": float(weights.mean()) if len(weights) else 0.0,
            "min_edge_similarity": float(weights.min()) if len(weights) else 0.0,
            "max_edge_similarity": float(weights.max()) if len(weights) else 0.0,
            "algorithm": diagnostics["algorithm"],
            "total_possible_pairs": diagnostics["total_possible_pairs"],
            "pairs_checked": diagnostics["pairs_checked"],
            "qualifying_edges_before_degree_cap": diagnostics["qualifying_edges_before_degree_cap"],
            "edges_removed_by_degree_cap": diagnostics["edges_removed_by_degree_cap"],
            "nodes_without_qualifying_neighbors": diagnostics["nodes_without_qualifying_neighbors"],
            "threshold_edge_counts_all_pairs": diagnostics["threshold_edge_counts_all_pairs"],
            "candidate_similarity_quantiles": diagnostics["candidate_similarity_quantiles"],
            "degree_cap": diagnostics["degree_cap"],
            "similarity_threshold": float(options["threshold"]),
            "block_size": int(options["block_size"]),
            "feature_count": int(X.shape[1]),
            "feature_fields": feature_fields,
            "layer": 2,
            "chunk_count": len(set(doc["source_file"] for doc in rep_docs)),
        })

        labels = []
        for rep_doc in rep_docs:
            label = rep_doc.get("label", 0)
            try:
                label = int(label)
            except (TypeError, ValueError, OverflowError):
                label = 0
            labels.append(label if label in (0, 1) else 0)

        node_ids = [str(doc["_id"]) for doc in rep_docs]
        # Keep metadata below MongoDB's BSON document-size limit.
        # Store edges separately, in batches, rather than embedding hundreds of
        # thousands of edge objects in one metadata document.
        if existing_graph:
            hyper_edges.delete_many({"source_file": graph_key})
            hyper_graphs.delete_one({"_id": existing_graph["_id"]})

        graph_doc = {
            "source_file": graph_key,
            "source_day": day,
            "candidate_generation": "hierarchy_layer_2_from_chunk_representatives",
            "is_random": False,
            "graph_path": None,
            "stats": stats,
            "edge_collection": "hyper_graph_edges",
            "edge_count": len(edges),
            "node_ids": node_ids,
            "node_labels": labels,
            "graph_parameters": {
                "similarity": "cosine",
                "edge_selection": "exact_all_pairs_cosine_threshold",
                "pairwise_comparison": "all_unordered_pairs",
                "degree_cap": diagnostics["degree_cap"],
                "similarity_threshold": float(options["threshold"]),
                "weight": "cosine_similarity",
                "feature_fields": feature_fields,
                "layer": 2,
                "source_day": day,
                "source_representative_pattern": f"clustered-day-{day}-chunk-N",
                "block_size": int(options["block_size"]),
            },
            "features": X.tolist() if len(rep_docs) <= 5000 else [],
            "status": "building",
            "created_at": datetime.utcnow(),
        }
        insert_result = hyper_graphs.insert_one(graph_doc)

        batch_size = 5000
        saved_edges = 0
        try:
            for batch_start in range(0, len(edges), batch_size):
                batch = edges[batch_start:batch_start + batch_size]
                documents = [
                    {
                        "source_file": graph_key,
                        "source": int(left),
                        "target": int(right),
                        "weight": float(weight),
                    }
                    for left, right, weight in batch
                ]
                if documents:
                    hyper_edges.insert_many(documents, ordered=False)
                    saved_edges += len(documents)
                self.stdout.write(
                    f"[HIERARCHY] Saved edges: {saved_edges:,}/{len(edges):,}",
                    ending="\\n",
                )
        except Exception:
            hyper_graphs.update_one(
                {"_id": insert_result.inserted_id},
                {"$set": {"status": "failed", "saved_edge_count": saved_edges}},
            )
            raise

        hyper_graphs.update_one(
            {"_id": insert_result.inserted_id},
            {"$set": {
                "status": "complete",
                "saved_edge_count": saved_edges,
                "completed_at": datetime.utcnow(),
            }},
        )

        self.stdout.write(self.style.SUCCESS(
            f"[HIERARCHY] Saved metadata to siem_db.hyper_graph_metadata "
            f"(document_id={insert_result.inserted_id})\\n"
            f"[HIERARCHY] Saved {saved_edges:,} edges to siem_db.hyper_graph_edges\\n"
            f"[HIERARCHY] Completed {graph_key}: nodes={len(rep_docs):,}; "
            f"edges={saved_edges:,}; components={stats.get('num_components', 'n/a')}; "
            f"isolates={stats.get('isolated_nodes', 'n/a')}; "
            f"threshold={options['threshold']}; "
            f"pairs_checked={diagnostics['pairs_checked']:,}; "
            f"qualifying_before_cap={diagnostics['qualifying_edges_before_degree_cap']:,}; "
            f"removed_by_cap={diagnostics['edges_removed_by_degree_cap']:,}; "
            f"degree_cap={diagnostics['degree_cap'] or 'disabled'}"
        ))
