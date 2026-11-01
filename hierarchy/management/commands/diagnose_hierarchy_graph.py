"""
Read-only audit for a stored layer-2 hierarchy graph.

Run:
    python manage.py diagnose_hierarchy_graph --day 2026-06-21

Optional:
    --edge-sample 50000
    --batch-size 1000

This command DOES NOT modify graph metadata, edges, representatives, or source records.
"""
import csv
import math
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from bson import ObjectId
from bson.errors import InvalidId
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from mongoengine import get_connection

from ingestion.models.graph_representative import GraphRepresentative


DEFAULT_FEATURES = [
    "bytes", "bytes_per_packet", "bytes_per_sec", "dst_port", "duration_s",
    "flag_ack", "flag_count", "flag_fin", "flag_psh", "flag_rst", "flag_syn",
    "flag_urg", "is_encrypted_port", "is_syn_only", "log_bytes",
    "log_duration", "log_packets", "packets", "packets_per_sec",
    "proto_icmp", "proto_tcp", "proto_udp", "src_port", "tos",
]

FEATURE_GROUPS = {
    "volume_bytes": ["bytes", "log_bytes", "bytes_per_packet", "bytes_per_sec"],
    "packet_volume": ["packets", "log_packets", "packets_per_sec"],
    "duration": ["duration_s", "log_duration"],
    "tcp_flags": ["flag_ack", "flag_fin", "flag_psh", "flag_rst", "flag_syn",
                  "flag_urg", "flag_count", "is_syn_only"],
    "protocol": ["proto_icmp", "proto_tcp", "proto_udp"],
    "ports": ["src_port", "dst_port", "is_encrypted_port"],
    "other": ["tos"],
}
PROVENANCE_FIELDS = [
    "src_ip", "dst_ip", "src_port", "dst_port", "protocol",
    "attack_type", "attack_category",
]


def finite_number(value):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return value if math.isfinite(value) else 0.0


def object_id_or_string(value):
    value = str(value)
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return value


def cosine_rows(a, b):
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom <= 1e-12:
        return 0.0
    return float(np.dot(a, b) / denom)


def write_csv(path, rows, fieldnames):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


class Command(BaseCommand):
    help = "Read-only structural, cross-chunk and feature audit of a stored hierarchy graph."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--day", required=True, help="YYYY-MM-DD")
        parser.add_argument("--edge-sample", type=int, default=50000,
                            help="Maximum cross-chunk edges for detailed behavioral audit.")
        parser.add_argument("--batch-size", type=int, default=1000)

    def handle(self, *args, **opts):
        day = opts["day"]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise CommandError("--day must be YYYY-MM-DD.")
        if opts["edge_sample"] < 1 or opts["batch_size"] < 1:
            raise CommandError("--edge-sample and --batch-size must be positive.")

        started = time.perf_counter()
        graph_key = f"hierarchy-day-{day}-layer-2"
        db = get_connection(alias="default")["siem_db"]
        metadata = db["hyper_graph_metadata"].find_one({"source_file": graph_key})
        if not metadata:
            raise CommandError(f"Hierarchy metadata not found: {graph_key}")
        if metadata.get("status") not in (None, "complete"):
            raise CommandError(f"Graph status is {metadata.get('status')!r}; audit stopped.")

        rep_pattern = rf"^clustered-day-{re.escape(day)}-chunk-\d+$"
        reps = list(
            GraphRepresentative.objects(
                __raw__={"source_file": {"$regex": rep_pattern}}
            ).order_by("source_file", "node_index").as_pymongo()
        )
        if not reps:
            raise CommandError(f"No layer-1 representatives found for {day}.")

        node_ids = [str(x) for x in metadata.get("node_ids", [])]
        rep_ids = [str(x["_id"]) for x in reps]
        if node_ids != rep_ids:
            raise CommandError(
                "Representative ordering/IDs do not match hierarchy metadata node_ids. "
                "Refusing to map edges to chunks because this could produce false results."
            )

        chunks = [str(x.get("source_file", "")).rsplit("-chunk-", 1)[-1] for x in reps]
        chunk_counts = Counter(chunks)
        labels = np.asarray([int(x.get("label", 0) or 0) for x in reps], dtype=np.int8)

        feature_fields = (
            metadata.get("graph_parameters", {}).get("feature_fields")
            or metadata.get("stats", {}).get("feature_fields")
            or DEFAULT_FEATURES
        )
        feature_fields = list(dict.fromkeys(feature_fields))

        sampled = db["sampled_security_data"]
        lookup = [object_id_or_string(x.get("original_id", "")) for x in reps]
        docs_by_id = {}
        for offset in range(0, len(lookup), opts["batch_size"]):
            batch = lookup[offset:offset + opts["batch_size"]]
            projection = {"_id": 1, "label": 1}
            projection.update({f: 1 for f in set(feature_fields + PROVENANCE_FIELDS)})
            for doc in sampled.find({"_id": {"$in": batch}}, projection):
                docs_by_id[str(doc["_id"])] = doc

        missing = [x for x in reps if str(x.get("original_id", "")) not in docs_by_id]
        if missing:
            raise CommandError(
                f"{len(missing)} representative source records are missing. "
                "No partial audit was written."
            )

        X = np.asarray([
            [finite_number(docs_by_id[str(r["original_id"])].get(f, 0.0))
             for f in feature_fields]
            for r in reps
        ], dtype=np.float64)
        valid_mask = np.std(X, axis=0) > 1e-10
        dropped_constant = [f for f, keep in zip(feature_fields, valid_mask) if not keep]
        X = X[:, valid_mask]
        feature_fields = [f for f, keep in zip(feature_fields, valid_mask) if keep]
        if X.shape[1] == 0:
            raise CommandError("All hierarchy feature columns are constant.")

        edges_coll = db[metadata.get("edge_collection", "hyper_graph_edges")]
        edge_cursor = edges_coll.find(
            {"source_file": graph_key},
            {"_id": 0, "source": 1, "target": 1, "weight": 1},
        )
        intra_count = 0
        inter_count = 0
        pair_counts = Counter()
        cross_degree = np.zeros(len(reps), dtype=np.int64)
        intra_degree = np.zeros(len(reps), dtype=np.int64)
        inter_edges = []
        all_edge_rows = []
        edge_weights = []
        edge_count = 0

        for edge in edge_cursor:
            u, v = int(edge["source"]), int(edge["target"])
            if not (0 <= u < len(reps) and 0 <= v < len(reps)):
                raise CommandError(f"Invalid edge endpoint ({u}, {v}) for {len(reps)} nodes.")
            cu, cv = chunks[u], chunks[v]
            weight = finite_number(edge.get("weight", 0))
            edge_count += 1
            edge_weights.append(weight)
            if cu == cv:
                intra_count += 1
                intra_degree[u] += 1
                intra_degree[v] += 1
            else:
                inter_count += 1
                cross_degree[u] += 1
                cross_degree[v] += 1
                key = tuple(sorted((cu, cv), key=lambda z: int(z) if z.isdigit() else z))
                pair_counts[key] += 1
                if len(inter_edges) < opts["edge_sample"]:
                    inter_edges.append((u, v, weight))
            all_edge_rows.append((u, v, weight, cu, cv))
        edge_cursor.close()

        # Chunk-pair density, normalized by all possible cross-chunk pairs.
        chunk_ids = sorted(chunk_counts, key=lambda z: int(z) if z.isdigit() else z)
        connectivity_rows = []
        for i, ci in enumerate(chunk_ids):
            for cj in chunk_ids[i + 1:]:
                possible = chunk_counts[ci] * chunk_counts[cj]
                observed = pair_counts.get((ci, cj), 0)
                connectivity_rows.append({
                    "chunk_a": ci, "chunk_b": cj,
                    "nodes_a": chunk_counts[ci], "nodes_b": chunk_counts[cj],
                    "inter_edges": observed, "possible_pairs": possible,
                    "cross_chunk_density": observed / possible if possible else 0.0,
                })

        # Feature contribution on existing edges. Signed contribution sums to cosine.
        contribution_sum = np.zeros(X.shape[1], dtype=np.float64)
        contribution_abs = np.zeros(X.shape[1], dtype=np.float64)
        ablation_drops = {name: [] for name in FEATURE_GROUPS}
        valid_edge_vectors = 0
        for u, v, _w, _cu, _cv in all_edge_rows:
            a, b = X[u], X[v]
            denom = float(np.linalg.norm(a) * np.linalg.norm(b))
            if denom <= 1e-12:
                continue
            full_cosine = cosine_rows(a, b)
            valid_edge_vectors += 1
            contrib = (a * b) / denom
            contribution_sum += contrib
            contribution_abs += np.abs(contrib)
            for group, fields in FEATURE_GROUPS.items():
                idx = [feature_fields.index(f) for f in fields if f in feature_fields]
                if idx:
                    keep = [j for j in range(X.shape[1]) if j not in idx]
                    reduced_cosine = cosine_rows(a[keep], b[keep]) if keep else 0.0
                    ablation_drops[group].append(full_cosine - reduced_cosine)

        feature_rows = []
        for i, field in enumerate(feature_fields):
            feature_rows.append({
                "feature": field,
                "mean_signed_cosine_contribution": contribution_sum[i] / max(1, valid_edge_vectors),
                "mean_absolute_contribution": contribution_abs[i] / max(1, valid_edge_vectors),
                "constant_removed": False,
            })
        feature_rows.sort(key=lambda r: r["mean_absolute_contribution"], reverse=True)

        group_rows = []
        for group, drops in ablation_drops.items():
            group_rows.append({
                "feature_group": group,
                "edges_evaluated": len(drops),
                "mean_cosine_drop_after_removal": float(np.mean(drops)) if drops else 0.0,
                "median_cosine_drop_after_removal": float(np.median(drops)) if drops else 0.0,
            })

        # Sampled inter-chunk behavioral evidence; encoded IP values are proxies,
        # not proof of real-world identity.
        behavior_rows = []
        for u, v, weight in inter_edges:
            du = docs_by_id[str(reps[u]["original_id"])]
            dv = docs_by_id[str(reps[v]["original_id"])]
            row = {
                "node_u": u, "node_v": v, "chunk_u": chunks[u], "chunk_v": chunks[v],
                "cosine_edge_weight": weight, "label_u": int(labels[u]), "label_v": int(labels[v]),
                "same_label": int(labels[u] == labels[v]),
            }
            for field in PROVENANCE_FIELDS:
                if field in ("attack_type", "attack_category"):
                    a, b = du.get(field), dv.get(field)
                    row[f"same_{field}"] = int(a == b) if a is not None and b is not None else ""
                else:
                    a, b = du.get(field), dv.get(field)
                    row[f"abs_delta_{field}"] = (
                        abs(finite_number(a) - finite_number(b))
                        if a is not None and b is not None else ""
                    )
            behavior_rows.append(row)

        # Integrity checks.
        original_ids = [str(r.get("original_id", "")) for r in reps]
        duplicate_ids = [k for k, n in Counter(original_ids).items() if n > 1]
        zero_vectors = int(np.count_nonzero(np.linalg.norm(X, axis=1) <= 1e-12))
        missing_feature_values = sum(
            1 for r in reps for f in feature_fields
            if docs_by_id[str(r["original_id"])].get(f) is None
        )

        output_dir = Path(settings.BASE_DIR) / "files" / "hierarchy" / "diagnostics" / day
        output_dir.mkdir(parents=True, exist_ok=True)
        write_csv(output_dir / "chunk_connectivity.csv", connectivity_rows,
                  ["chunk_a", "chunk_b", "nodes_a", "nodes_b", "inter_edges",
                   "possible_pairs", "cross_chunk_density"])
        write_csv(output_dir / "feature_contribution.csv", feature_rows,
                  ["feature", "mean_signed_cosine_contribution",
                   "mean_absolute_contribution", "constant_removed"])
        write_csv(output_dir / "feature_group_ablation.csv", group_rows,
                  ["feature_group", "edges_evaluated", "mean_cosine_drop_after_removal",
                   "median_cosine_drop_after_removal"])
        behavior_fields = (
            ["node_u", "node_v", "chunk_u", "chunk_v", "cosine_edge_weight",
             "label_u", "label_v", "same_label"]
            + [f"same_{f}" if f in ("attack_type", "attack_category") else f"abs_delta_{f}"
               for f in PROVENANCE_FIELDS]
        )
        write_csv(output_dir / "cross_chunk_edge_audit_sample.csv", behavior_rows, behavior_fields)

        # Optional visual diagnostics; CSV/TXT remain the primary outputs.
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            matrix = np.zeros((len(chunk_ids), len(chunk_ids)), dtype=np.float64)
            pos = {c: i for i, c in enumerate(chunk_ids)}
            for row in connectivity_rows:
                i, j = pos[row["chunk_a"]], pos[row["chunk_b"]]
                matrix[i, j] = matrix[j, i] = row["cross_chunk_density"]
            fig, ax = plt.subplots(figsize=(max(8, len(chunk_ids) * 0.45),
                                            max(6, len(chunk_ids) * 0.4)))
            im = ax.imshow(matrix, aspect="auto")
            ax.set_xticks(range(len(chunk_ids)), chunk_ids, rotation=90)
            ax.set_yticks(range(len(chunk_ids)), chunk_ids)
            ax.set_title("Cross-chunk edge density")
            fig.colorbar(im, ax=ax, label="Edges / possible node pairs")
            fig.tight_layout()
            fig.savefig(output_dir / "chunk_connectivity_matrix.png", dpi=180)
            plt.close(fig)

            fig, ax = plt.subplots(figsize=(10, 5))
            top = feature_rows[:min(25, len(feature_rows))]
            ax.bar([r["feature"] for r in top], [r["mean_absolute_contribution"] for r in top])
            ax.set_title("Mean absolute feature contribution to cosine on stored edges")
            ax.tick_params(axis="x", rotation=75)
            fig.tight_layout()
            fig.savefig(output_dir / "feature_contribution.png", dpi=180)
            plt.close(fig)
        except Exception as exc:
            self.stderr.write(self.style.WARNING(f"[DIAG] Plot generation skipped: {exc}"))

        weights = np.asarray(edge_weights, dtype=np.float64)
        cross_weights = np.asarray([x[2] for x in inter_edges], dtype=np.float64)
        lines = [
            "HIERARCHY GRAPH DIAGNOSTIC",
            "=" * 72,
            f"Graph: {graph_key}",
            f"Nodes: {len(reps):,} | chunks: {len(chunk_ids)} | edges: {edge_count:,}",
            f"Intra-chunk edges: {intra_count:,} ({intra_count/max(1,edge_count):.2%})",
            f"Inter-chunk edges: {inter_count:,} ({inter_count/max(1,edge_count):.2%})",
            f"Inter-chunk edges sampled for detail: {len(inter_edges):,}",
            f"Mean stored edge weight: {weights.mean():.6f}" if len(weights) else "Mean stored edge weight: n/a",
            f"Mean sampled inter-chunk weight: {cross_weights.mean():.6f}" if len(cross_weights) else "Mean sampled inter-chunk weight: n/a",
            f"Chunks with representatives: {len(chunk_ids)}",
            f"Representative counts by chunk: {dict(sorted(chunk_counts.items(), key=lambda x: int(x[0]) if x[0].isdigit() else x[0]))}",
            f"Nodes with >=1 cross-chunk edge: {int(np.count_nonzero(cross_degree)):,}/{len(reps):,}",
            f"Nodes with no cross-chunk edge: {int(np.count_nonzero(cross_degree == 0)):,}",
            f"Duplicate original_id count: {len(duplicate_ids)}",
            f"Zero feature vectors: {zero_vectors}",
            f"Missing feature values (None): {missing_feature_values}",
            f"Constant features excluded from analysis: {dropped_constant}",
            "",
            "INTERPRETATION NOTES",
            "- Cross-chunk density is normalized by the possible node pairs for each chunk pair.",
            "- Feature contributions are computed on stored edges, not on all possible pairs.",
            "- Group ablation recomputes cosine after removing each group, on stored edges only.",
            "- IP fields in sampled_security_data may be normalized numeric encodings; deltas are not identity proof.",
            "- Label agreement is descriptive only; it is not evidence that an edge is behaviorally valid.",
            "",
            f"Elapsed: {time.perf_counter()-started:.2f}s",
            f"Output directory: {output_dir}",
        ]
        (output_dir / "hierarchy_diagnostic_summary.txt").write_text(
            "\n".join(lines), encoding="utf-8"
        )
        self.stdout.write(self.style.SUCCESS("\n".join(lines)))
