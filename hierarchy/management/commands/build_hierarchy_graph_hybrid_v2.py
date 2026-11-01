import json
import re
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from bson import ObjectId
from bson.errors import InvalidId
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from mongoengine import get_connection

from ingestion.models.graph_representative import GraphRepresentative
from ingestion.services.graph.graph_stats import compute_sparse_graph_stats
from hierarchy.services.similarity.hierarchy_similarity_v2 import (
    NUMERIC_FIELDS,
    CATEGORICAL_FIELDS,
    BEHAVIOR_FLAG_FIELDS,
    BEHAVIOR_CATEGORICAL_FIELDS,
    pair_similarity,
    feature_schema_report,
)


class Command(BaseCommand):
    """
    Experimental layer-2 hybrid graph builder.

    Numeric + TCP flags: sampled_security_data.
    Categorical values: security_data, joined through
    sampled_security_data.original_id -> security_data._id.

    Only approved feature fields are passed to pair_similarity. Labels,
    attack metadata, risk scores, IP addresses and raw port numbers are not
    used in similarity calculation.

    Default: diagnostic JSON/TXT only. --save-graph persists a separate
    graph key ending in -hybrid and never overwrites the cosine graph.
    """
    help = "Diagnose/build the independent hybrid layer-2 graph."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--day", required=True, help="YYYY-MM-DD")
        parser.add_argument("--threshold", type=float, default=0.85)
        parser.add_argument("--progress-rows", type=int, default=100)
        parser.add_argument("--save-graph", action="store_true")
        parser.add_argument("--force", action="store_true")

    @staticmethod
    def _oid(value):
        text = str(value)
        try:
            return ObjectId(text)
        except (InvalidId, TypeError):
            return text

    @staticmethod
    def _json_safe(value):
        if isinstance(value, ObjectId):
            return str(value)
        if isinstance(value, dict):
            return {str(k): Command._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [Command._json_safe(v) for v in value]
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            return float(value)
        return value

    @staticmethod
    def _distribution(values):
        arr = np.asarray(values, dtype=np.float64)
        if not len(arr):
            return {}
        return {
            "count": int(len(arr)),
            "mean": float(arr.mean()),
            "std": float(arr.std()),
            "min": float(arr.min()),
            "max": float(arr.max()),
            "quantiles": {
                str(q): float(np.quantile(arr, q))
                for q in (0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)
            },
        }

    def handle(self, *args, **options):
        day = options["day"]
        try:
            datetime.strptime(day, "%Y-%m-%d")
        except ValueError as exc:
            raise CommandError("--day must use YYYY-MM-DD.") from exc

        threshold = options["threshold"]
        if not 0.0 <= threshold <= 1.0:
            raise CommandError("--threshold must be between 0 and 1.")
        if options["progress_rows"] < 1:
            raise CommandError("--progress-rows must be >= 1.")

        graph_key = f"hierarchy-day-{day}-layer-2-hybrid"
        db = get_connection(alias="default")["siem_db"]
        sampled_col = db["sampled_security_data"]
        raw_col = db["security_data"]
        graph_col = db["hyper_graph_metadata"]
        edge_col = db["hyper_graph_edges"]

        existing = graph_col.find_one({"source_file": graph_key})
        if options["save_graph"] and existing and not options["force"]:
            raise CommandError(
                f"{graph_key} already exists. Use --force to replace only "
                "the hybrid graph."
            )

        source_pattern = rf"^clustered-day-{re.escape(day)}-chunk-[0-9]+$"
        rep_docs = list(
            GraphRepresentative.objects(
                __raw__={"source_file": {"$regex": source_pattern}}
            ).order_by("source_file", "node_index").as_pymongo()
        )
        if not rep_docs:
            raise CommandError(
                f"No layer-1 representatives found for {day}; expected "
                "clustered-day-DAY-chunk-N."
            )

        # Representative.original_id is the _id in sampled_security_data.
        sampled_ids = [str(doc.get("original_id", "")) for doc in rep_docs]
        if any(not value for value in sampled_ids):
            raise CommandError("A representative has an empty original_id.")
        if len(set(sampled_ids)) != len(sampled_ids):
            raise CommandError("Duplicate sampled record IDs among representatives.")

        batch_size = 1000
        sampled_lookup = [self._oid(value) for value in sampled_ids]
        sampled_projection = {
            "_id": 1, "original_id": 1,
            **{field: 1 for field in NUMERIC_FIELDS},
            **{field: 1 for field in BEHAVIOR_FLAG_FIELDS},
            **{field: 1 for field in BEHAVIOR_CATEGORICAL_FIELDS},
        }
        sampled_by_id = {}
        for offset in range(0, len(sampled_lookup), batch_size):
            cursor = sampled_col.find(
                {"_id": {"$in": sampled_lookup[offset:offset + batch_size]}},
                sampled_projection,
            )
            try:
                for doc in cursor:
                    sampled_by_id[str(doc["_id"])] = doc
            finally:
                cursor.close()

        missing_sampled = [value for value in sampled_ids if value not in sampled_by_id]
        if missing_sampled:
            raise CommandError(
                f"{len(missing_sampled)}/{len(sampled_ids)} representative records "
                f"were not found in sampled_security_data by _id. "
                f"Examples: {missing_sampled[:5]}"
            )

        # sampled_security_data.original_id points to security_data._id.
        raw_ids = [
            str(sampled_by_id[sid].get("original_id", ""))
            for sid in sampled_ids
        ]
        if any(not value for value in raw_ids):
            raise CommandError(
                "Some sampled_security_data records have no original_id; "
                "cannot recover categorical fields from security_data."
            )

        raw_lookup = [self._oid(value) for value in raw_ids]
        raw_projection = {
            "_id": 1, **{field: 1 for field in CATEGORICAL_FIELDS}
        }
        raw_by_id = {}
        for offset in range(0, len(raw_lookup), batch_size):
            cursor = raw_col.find(
                {"_id": {"$in": raw_lookup[offset:offset + batch_size]}},
                raw_projection,
            )
            try:
                for doc in cursor:
                    raw_by_id[str(doc["_id"])] = doc
            finally:
                cursor.close()

        missing_raw = [rid for rid in raw_ids if rid not in raw_by_id]
        if missing_raw:
            raise CommandError(
                f"{len(missing_raw)}/{len(raw_ids)} raw records were not found "
                f"in security_data using sampled_security_data.original_id. "
                f"Examples: {missing_raw[:5]}"
            )

        # Build allow-listed feature-only dictionaries. Never merge complete
        # source documents, so labels/risk/attack metadata/IPs cannot leak in.
        records = []
        for sampled_id, raw_id in zip(sampled_ids, raw_ids):
            sample_doc = sampled_by_id[sampled_id]
            raw_doc = raw_by_id[raw_id]
            features = {}
            for field in NUMERIC_FIELDS:
                features[field] = sample_doc.get(field)
            for field in BEHAVIOR_FLAG_FIELDS:
                features[field] = sample_doc.get(field)
            for field in CATEGORICAL_FIELDS:
                features[field] = raw_doc.get(field)
            for field in BEHAVIOR_CATEGORICAL_FIELDS:
                features[field] = sample_doc.get(field)
            records.append(features)

        schema = feature_schema_report(records)
        missing_categories = {
            field: sum(
                1 for record in records
                if record.get(field) is None
                or (isinstance(record.get(field), str)
                    and not record.get(field).strip())
            )
            for field in CATEGORICAL_FIELDS
        }

        n = len(records)
        possible_pairs = n * (n - 1) // 2
        self.stdout.write(
            f"[HYBRID] day={day}; nodes={n:,}; possible_pairs={possible_pairs:,}; "
            f"threshold={threshold:.3f}"
        )
        self.stdout.write(
            "[HYBRID] Sources: numeric/flags=sampled_security_data; "
            "categorical=security_data via sampled.original_id"
        )
        self.stdout.write(
            "[HYBRID] Missing categories: "
            + ", ".join(f"{k}={v}" for k, v in missing_categories.items())
        )

        threshold_grid = (0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 0.995)
        threshold_counts = {str(t): 0 for t in threshold_grid}
        family_values = {
            "numeric": [], "categorical": [], "behavioral": [], "combined": []
        }
        family_pair_counts = {
            "numeric": 0, "categorical": 0, "behavioral": 0, "all_three": 0
        }
        degrees = np.zeros(n, dtype=np.int64)
        graph_edges = [] if options["save_graph"] else None
        top_pairs = []
        pair_count = eligible_count = incomplete_count = edge_count = 0
        started = time.perf_counter()

        for i in range(n):
            for j in range(i + 1, n):
                result = pair_similarity(records[i], records[j])
                pair_count += 1

                for family, key in (
                    ("numeric", "numeric_similarity"),
                    ("categorical", "categorical_similarity"),
                    ("behavioral", "behavioral_similarity"),
                ):
                    value = result[key]
                    if value is not None:
                        family_pair_counts[family] += 1
                        family_values[family].append(value)

                if result["families_compared"] != 3:
                    incomplete_count += 1
                    continue

                eligible_count += 1
                family_pair_counts["all_three"] += 1
                score = result["combined_similarity"]
                family_values["combined"].append(score)

                for t in threshold_grid:
                    if score >= t:
                        threshold_counts[str(t)] += 1

                if score >= threshold:
                    edge_count += 1
                    degrees[i] += 1
                    degrees[j] += 1
                    if graph_edges is not None:
                        graph_edges.append((i, j, float(score)))

                    candidate = (float(score), i, j, result)
                    if len(top_pairs) < 30:
                        top_pairs.append(candidate)
                        top_pairs.sort(key=lambda x: x[0], reverse=True)
                    elif score > top_pairs[-1][0]:
                        top_pairs[-1] = candidate
                        top_pairs.sort(key=lambda x: x[0], reverse=True)

            if (i + 1) % options["progress_rows"] == 0 or i + 1 == n:
                self.stdout.write(
                    f"[HYBRID] progress={i + 1:,}/{n:,}; pairs={pair_count:,}; "
                    f"edges@{threshold:.2f}={edge_count:,}"
                )

        elapsed = time.perf_counter() - started
        distributions = {
            family: self._distribution(values)
            for family, values in family_values.items()
        }

        report = {
            "source_day": day,
            "source_file": graph_key,
            "algorithm": "equal_mean_numeric_categorical_behavioral",
            "data_sources": {
                "numeric_and_behavioral": "siem_db.sampled_security_data",
                "categorical": "siem_db.security_data",
                "join": "sampled_security_data.original_id -> security_data._id",
            },
            "threshold": threshold,
            "node_count": n,
            "total_possible_pairs": pair_count,
            "eligible_pairs_all_three_families": eligible_count,
            "pairs_missing_one_or_more_families": incomplete_count,
            "family_pair_counts": family_pair_counts,
            "missing_raw_records": len(missing_raw),
            "missing_categorical_values": missing_categories,
            "threshold_edge_counts": threshold_counts,
            "similarity_distributions": distributions,
            "nodes_without_qualifying_neighbors": int(np.count_nonzero(degrees == 0)),
            "degree_distribution": self._distribution(degrees),
            "schema_report": schema,
            "elapsed_seconds": elapsed,
            "top_pairs": [
                {
                    "similarity": score,
                    "source_index": i,
                    "target_index": j,
                    "source_representative_id": str(rep_docs[i]["_id"]),
                    "target_representative_id": str(rep_docs[j]["_id"]),
                    "source_sampled_id": sampled_ids[i],
                    "target_sampled_id": sampled_ids[j],
                    "numeric_similarity": result["numeric_similarity"],
                    "categorical_similarity": result["categorical_similarity"],
                    "behavioral_similarity": result["behavioral_similarity"],
                    "features_compared": result["features_compared"],
                }
                for score, i, j, result in top_pairs
            ],
        }

        out_dir = (
            Path(settings.BASE_DIR) / "files" / "evaluation"
            / f"hierarchy-day-{day}" / "hybrid_similarity"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / f"{graph_key}_diagnostic.json"
        txt_path = out_dir / f"{graph_key}_diagnostic.txt"
        with json_path.open("w", encoding="utf-8") as fp:
            json.dump(self._json_safe(report), fp, indent=2, ensure_ascii=False)

        lines = [
            "HYBRID LAYER-2 SIMILARITY DIAGNOSTIC",
            "=" * 48,
            f"Day: {day}",
            f"Nodes: {n:,}",
            f"Possible pairs: {pair_count:,}",
            f"Eligible pairs (all three families): {eligible_count:,}",
            f"Incomplete pairs: {incomplete_count:,}",
            f"Threshold: {threshold:.4f}",
            "Join: sampled_security_data.original_id -> security_data._id",
            "",
            "FAMILY PAIR COUNTS",
            "-" * 24,
        ]
        lines.extend(f"{k}: {v:,}" for k, v in family_pair_counts.items())
        lines.extend(["", "THRESHOLD EDGE COUNTS", "-" * 24])
        lines.extend(f">= {t}: {v:,}" for t, v in threshold_counts.items())
        lines.extend(["", "SIMILARITY DISTRIBUTIONS", "-" * 24])
        lines.extend(f"{k}: {v}" for k, v in distributions.items())
        lines.extend(["", "MISSING CATEGORICAL VALUES", "-" * 28])
        lines.extend(f"{k}: {v:,}/{n:,}" for k, v in missing_categories.items())
        lines.extend([
            "",
            f"Nodes without neighbors: {report['nodes_without_qualifying_neighbors']:,}",
            f"Elapsed: {elapsed:.2f}s",
            "",
            "TOP PAIRS",
            "-" * 24,
        ])
        for pair in report["top_pairs"]:
            lines.append(
                f"{pair['similarity']:.5f} | "
                f"{pair['source_sampled_id']} <-> {pair['target_sampled_id']} | "
                f"N={pair['numeric_similarity']:.3f}, "
                f"C={pair['categorical_similarity']:.3f}, "
                f"B={pair['behavioral_similarity']:.3f}"
            )
        with txt_path.open("w", encoding="utf-8") as fp:
            fp.write("\\n".join(lines) + "\\n")

        self.stdout.write(self.style.SUCCESS(f"[HYBRID] JSON: {json_path}"))
        self.stdout.write(self.style.SUCCESS(f"[HYBRID] TXT: {txt_path}"))

        if not options["save_graph"]:
            self.stdout.write(
                "[HYBRID] Diagnostic-only; graph collections unchanged. "
                "Use --save-graph after reviewing results."
            )
            return

        labels = []
        for rep in rep_docs:
            try:
                label = int(rep.get("label", 0))
            except (TypeError, ValueError, OverflowError):
                label = 0
            labels.append(label if label in (0, 1) else 0)

        final_edges = graph_edges or []
        stats = compute_sparse_graph_stats(n, final_edges)
        weights = np.asarray([edge[2] for edge in final_edges], dtype=np.float64)
        stats.update({
            "similarity_threshold": threshold,
            "algorithm": "equal_mean_numeric_categorical_behavioral",
            "mean_edge_similarity": float(weights.mean()) if len(weights) else 0.0,
            "min_edge_similarity": float(weights.min()) if len(weights) else 0.0,
            "max_edge_similarity": float(weights.max()) if len(weights) else 0.0,
            "threshold_edge_counts": threshold_counts,
            "eligible_pairs_all_three_families": eligible_count,
            "similarity_distributions": distributions,
            "nodes_without_qualifying_neighbors": int(np.count_nonzero(degrees == 0)),
            "layer": 2,
        })

        if existing:
            edge_col.delete_many({"source_file": graph_key})
            graph_col.delete_one({"_id": existing["_id"]})

        graph_doc = {
            "source_file": graph_key,
            "source_day": day,
            "candidate_generation": "layer_2_hybrid_similarity_experiment",
            "is_random": False,
            "graph_path": None,
            "stats": stats,
            "edge_collection": "hyper_graph_edges",
            "edge_count": len(final_edges),
            "node_ids": [str(doc["_id"]) for doc in rep_docs],
            "node_labels": labels,
            "graph_parameters": {
                "similarity": "hybrid_equal_mean",
                "numeric_fields": list(NUMERIC_FIELDS),
                "categorical_fields": list(CATEGORICAL_FIELDS),
                "behavior_flag_fields": list(BEHAVIOR_FLAG_FIELDS),
                "behavior_categorical_fields": list(BEHAVIOR_CATEGORICAL_FIELDS),
                "family_aggregation": "arithmetic_mean_equal_third",
                "similarity_threshold": threshold,
                "data_join": "sampled_security_data.original_id -> security_data._id",
                "layer": 2,
                "source_day": day,
            },
            "features": [],
            "status": "building",
            "created_at": datetime.utcnow(),
        }
        inserted = graph_col.insert_one(graph_doc)
        saved = 0
        try:
            for offset in range(0, len(final_edges), 5000):
                batch = final_edges[offset:offset + 5000]
                docs = [
                    {
                        "source_file": graph_key,
                        "source": int(left),
                        "target": int(right),
                        "weight": float(weight),
                    }
                    for left, right, weight in batch
                ]
                if docs:
                    edge_col.insert_many(docs, ordered=False)
                    saved += len(docs)
            graph_col.update_one(
                {"_id": inserted.inserted_id},
                {"$set": {
                    "status": "complete",
                    "saved_edge_count": saved,
                    "completed_at": datetime.utcnow(),
                }},
            )
        except Exception:
            graph_col.update_one(
                {"_id": inserted.inserted_id},
                {"$set": {"status": "failed", "saved_edge_count": saved}},
            )
            raise

        self.stdout.write(self.style.SUCCESS(
            f"[HYBRID] Saved separate graph {graph_key}: "
            f"nodes={n:,}; edges={saved:,}"
        ))
