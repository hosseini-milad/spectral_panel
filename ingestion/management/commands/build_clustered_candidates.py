from collections import defaultdict
from datetime import datetime
import math
import re
import tempfile
import time
from pathlib import Path

import numpy as np
from bson import ObjectId
from django.core.management.base import BaseCommand, CommandError
from mongoengine import get_connection
from pymongo import InsertOne
from sklearn.cluster import MiniBatchKMeans

from ingestion.management.commands.normalize_parquet_dataset import NUMERIC_FIELDS


METADATA_FIELDS = (
    "original_id", "source_file", "flow_file", "source_path", "source_day", "source_type",
    "type", "row_index", "window_start", "flow_start", "timestamp",
    "attack_category", "attack_type", "label", "label_binary",
    "risk_score", "threat_score", "threat_intel_score", "anomaly_score", "risk",
)
RISK_FIELDS = ("threat_intel_score", "risk_score", "threat_score", "anomaly_score", "risk")
# New generation because the selection policy is now risk/novelty-aware.
GENERATION = "time_label_minibatch_medoids_risk_novelty_v3"


def _hour_bucket(record):
    for field in ("flow_start", "timestamp", "window_start"):
        value = record.get(field)
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%dT%H")
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime(
                    "%Y-%m-%dT%H"
                )
            except ValueError:
                pass
    # Prefer the original flow-file name when explicit timestamps are absent.
    # Example: nfcapd.202606212040 -> hour bucket 2026-06-21T20.
    for field in ("flow_file", "source_file", "source_path"):
        match = re.search(r"nfcapd.*?(\d{10})", str(record.get(field, "")))
        if match:
            return datetime.strptime(match.group(1), "%Y%m%d%H").strftime("%Y-%m-%dT%H")
    return "unknown"


def _allocate_quotas(capacities, target):
    """Proportional largest-remainder allocation, respecting each capacity."""
    total = sum(capacities)
    if target >= total:
        return list(capacities)
    if target <= 0 or not capacities:
        return [0] * len(capacities)

    exact = [target * capacity / total for capacity in capacities]
    quotas = [min(capacities[i], int(math.floor(exact[i]))) for i in range(len(capacities))]
    left = target - sum(quotas)
    order = sorted(
        range(len(capacities)),
        key=lambda i: (exact[i] - quotas[i], capacities[i]),
        reverse=True,
    )
    while left:
        progressed = False
        for index in order:
            if quotas[index] < capacities[index]:
                quotas[index] += 1
                left -= 1
                progressed = True
                if left == 0:
                    break
        if not progressed:
            break
    return quotas


def _numeric_vector(record, fields):
    values = []
    for field in fields:
        try:
            value = float(record.get(field, 0) or 0)
        except (TypeError, ValueError, OverflowError):
            value = 0.0
        values.append(value if math.isfinite(value) else 0.0)
    return values


def _label01(record):
    value = record.get("label")
    if value is None:
        value = record.get("label_binary", 0)
    try:
        value = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return 0
    return value if value in (0, 1) else 0


def _risk_value(record, risk_field):
    """Return the configured risk score, safely treating missing values as zero."""
    if not risk_field:
        return 0.0
    try:
        value = float(record.get(risk_field, 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return value if math.isfinite(value) else 0.0


class Command(BaseCommand):
    help = (
        "Reduce one normalized day/chunk to 10% graph-based clustered candidates. "
        "This stage does not build the cosine similarity graph or compute eigenvectors."
    )
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--day", required=True, help="Source day, YYYY-MM-DD")
        parser.add_argument("--chunk-index", type=int, required=True)
        parser.add_argument("--count", type=int, default=20_000,
                            help="Maximum number of normalized input records to process")
        parser.add_argument("--ratio", type=float, default=0.10,
                            help="Fraction of input records to retain; default 0.10")
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--clusters-per-20-candidates", type=int, default=1)
        parser.add_argument("--random-state", type=int, default=42)
        parser.add_argument("--outlier-quantile", type=float, default=0.99)
        parser.add_argument("--force", action="store_true",
                            help="Replace this day's/chunk's candidates from this generation")

    def handle(self, *args, **options):
        started = time.monotonic()
        day = options["day"]
        chunk_index = options["chunk_index"]
        input_limit = options["count"]
        ratio = options["ratio"]
        batch_size = options["batch_size"]
        clusters_per_20 = options["clusters_per_20_candidates"]
        outlier_quantile = options["outlier_quantile"]

        if chunk_index < 0:
            raise CommandError("--chunk-index must be >= 0.")
        if input_limit < 1 or batch_size < 1 or clusters_per_20 < 1:
            raise CommandError("count, batch-size and clusters-per-20-candidates must be positive.")
        if not 0 < ratio < 1:
            raise CommandError("--ratio must be greater than 0 and less than 1.")
        if not 0.5 < outlier_quantile < 1:
            raise CommandError("--outlier-quantile must be between 0.5 and 1.0.")

        database = get_connection(alias="default")["siem_db"]
        normalized = database["normalized_security_data"]
        candidates = database["sampled_security_data"]

        # Source normalized records use normalization_chunk_index.
        chunk_filter = {
            "source_day": day,
            "normalization_chunk_index": chunk_index,
        }
        available = normalized.count_documents(chunk_filter)
        if available == 0:
            raise CommandError(
                f"No normalized records found for source_day={day!r}, "
                f"normalization_chunk_index={chunk_index}."
            )

        input_count = min(available, input_limit)
        target = min(input_count, max(1, int(round(input_count * ratio))))
        candidate_filter = {
            "source_day": day,
            "chunk_index": chunk_index,
            "candidate_generation": GENERATION,
        }
        existing = candidates.count_documents(candidate_filter)
        if existing and not options["force"]:
            raise CommandError(
                f"{existing} candidates already exist for day={day}, chunk_index={chunk_index}. "
                "Use --force to replace only this generation for this chunk."
            )

        sample_record = normalized.find_one(chunk_filter)
        if sample_record is None:
            raise CommandError("Chunk count was positive but no normalized sample record was found.")
        numeric_fields = [field for field in NUMERIC_FIELDS if field in sample_record]
        if not numeric_fields:
            raise CommandError("No numeric feature fields found in normalized records.")
        risk_field = next((field for field in RISK_FIELDS if field in sample_record), None)
        if risk_field:
            print(f"[CANDIDATES] Risk-aware selection field: {risk_field}", flush=True)
        else:
            print(
                "[CANDIDATES] WARNING: no recognized risk score field found; "
                "selection will use feature-space novelty only.", flush=True
            )

        projection = {field: 1 for field in set(numeric_fields) | set(METADATA_FIELDS)}
        projection["_id"] = 1
        sort_field = "_id"

        # Disk-backed matrix bounds RAM use; this reads only this day/chunk.
        workdir = tempfile.TemporaryDirectory(prefix="clustered_candidates_")
        workpath = Path(workdir.name)
        matrix = np.memmap(
            workpath / "vectors.dat", dtype=np.float32, mode="w+",
            shape=(input_count, len(numeric_fields)),
        )
        ids = np.memmap(
            workpath / "objectids.dat", dtype="S24", mode="w+",
            shape=(input_count,),
        )
        groups = defaultdict(list)
        risk_values = np.zeros(input_count, dtype=np.float64)
        loaded = 0
        print(
            f"[CANDIDATES] source_day={day}; chunk_index={chunk_index}; "
            f"available={available:,}; input_limit={input_count:,}; target={target:,} "
            f"({ratio:.1%})",
            flush=True,
        )
        print("[CANDIDATES] Reading this chunk only...", flush=True)
        cursor = normalized.find(
            chunk_filter, projection, no_cursor_timeout=True
        ).sort(sort_field, 1).limit(input_count).batch_size(2_000)
        try:
            for record in cursor:
                label = _label01(record)
                matrix[loaded, :] = _numeric_vector(record, numeric_fields)
                ids[loaded] = str(record["_id"]).encode("ascii")
                groups[(_hour_bucket(record), label)].append(loaded)
                risk_values[loaded] = _risk_value(record, risk_field)
                loaded += 1
                if loaded % 5_000 == 0 or loaded == input_count:
                    print(f"[CANDIDATES] Read {loaded:,}/{input_count:,}", flush=True)
        finally:
            cursor.close()

        if loaded != input_count:
            matrix._mmap.close()
            ids._mmap.close()
            del matrix, ids
            workdir.cleanup()
            raise CommandError(f"Expected {input_count} input records, read {loaded}.")

        matrix.flush()
        ids.flush()

        # Remove constant dimensions before clustering.
        sums = np.zeros(matrix.shape[1], dtype=np.float64)
        sums_sq = np.zeros(matrix.shape[1], dtype=np.float64)
        for start_idx in range(0, loaded, 5_000):
            block = np.asarray(matrix[start_idx:start_idx + 5_000], dtype=np.float64)
            sums += block.sum(axis=0)
            sums_sq += np.square(block).sum(axis=0)
        variances = np.maximum(sums_sq / loaded - np.square(sums / loaded), 0.0)
        active = np.sqrt(variances) > 1e-8
        if not np.any(active):
            matrix._mmap.close()
            ids._mmap.close()
            del matrix, ids
            workdir.cleanup()
            raise CommandError("All numeric feature dimensions are constant in this chunk.")

        group_items = sorted(groups.items(), key=lambda item: item[0])
        group_quotas = _allocate_quotas([len(indices) for _, indices in group_items], target)
        chosen = []
        fitted_clusters = 0
        small_strata_kept = 0

        print(
            f"[CANDIDATES] Clustering {len(group_items)} time/label strata; "
            f"active_features={int(active.sum())}/{len(active)}...",
            flush=True,
        )
        for group_number, ((group_key, indices), quota) in enumerate(
            zip(group_items, group_quotas), start=1
        ):
            if quota <= 0:
                continue
            if quota >= len(indices):
                chosen.extend(
                    (index, "all_records_small_stratum", None, False)
                    for index in indices
                )
                small_strata_kept += 1
                continue

            # One cluster per ~20 requested representatives within each stratum.
            cluster_count = max(1, quota // 20 * clusters_per_20)
            cluster_count = min(cluster_count, quota, len(indices) - 1)
            group_matrix = np.asarray(matrix[indices], dtype=np.float32)[:, active]
            model = MiniBatchKMeans(
                n_clusters=cluster_count,
                init="k-means++",
                n_init=1,
                random_state=options["random_state"],
                batch_size=max(256, min(2_048, len(indices))),
                max_iter=50,
                reassignment_ratio=0.0,
            )
            assignments = model.fit_predict(group_matrix)
            centers = model.cluster_centers_
            distances = np.linalg.norm(group_matrix - centers[assignments], axis=1)
            cluster_sizes = np.bincount(assignments, minlength=cluster_count).tolist()
            cluster_quotas = _allocate_quotas(cluster_sizes, quota)

            for cluster_id, cluster_quota in enumerate(cluster_quotas):
                if cluster_quota <= 0:
                    continue
                members = np.flatnonzero(assignments == cluster_id)
                cluster_distances = distances[members]
                cutoff = float(np.quantile(cluster_distances, outlier_quantile))
                core_members = members[cluster_distances <= cutoff]

                # Reserve part of each cluster quota for novelty/risk candidates.
                # This avoids the old failure mode where quota=1 or 2 could
                # systematically select only centroid-near records.
                risk_in_cluster = risk_values[np.asarray(indices, dtype=np.int64)[members]]
                distance_rank = np.zeros(len(members), dtype=np.float64)
                risk_rank = np.zeros(len(members), dtype=np.float64)
                if len(members) > 1 and np.ptp(cluster_distances) > 1e-12:
                    order = np.argsort(cluster_distances, kind="stable")
                    distance_rank[order] = np.linspace(0.0, 1.0, len(members))
                if len(members) > 1 and np.ptp(risk_in_cluster) > 1e-12:
                    order = np.argsort(risk_in_cluster, kind="stable")
                    risk_rank[order] = np.linspace(0.0, 1.0, len(members))
                priority = np.maximum(distance_rank, risk_rank)
                priority_order = np.argsort(priority, kind="stable")[::-1]
                novelty_budget = min(
                    cluster_quota,
                    max(1, cluster_quota // 4) if cluster_quota > 1 else 1,
                )
                selected_local = [int(members[pos]) for pos in priority_order[:novelty_budget]]
                used_local = set(selected_local)
                core_budget = cluster_quota - len(selected_local)

                remaining_core = [int(x) for x in core_members if int(x) not in used_local]
                remaining_core.sort(key=lambda x: (float(distances[x]), x))
                if core_budget and remaining_core:
                    if core_budget >= len(remaining_core):
                        positions = np.arange(len(remaining_core))
                    elif core_budget == 1:
                        positions = np.array([0])
                    else:
                        positions = np.rint(
                            np.linspace(0, len(remaining_core) - 1, core_budget)
                        ).astype(int)
                    selected_local.extend(remaining_core[int(pos)] for pos in positions)
                    used_local = set(selected_local)

                if len(selected_local) < cluster_quota:
                    leftovers = [int(x) for x in members if int(x) not in used_local]
                    leftovers.sort(key=lambda x: (float(distances[x]), x))
                    selected_local.extend(leftovers[:cluster_quota - len(selected_local)])

                for rank, local_index in enumerate(selected_local[:cluster_quota]):
                    global_index = indices[local_index]
                    local_pos = int(np.where(members == local_index)[0][0])
                    is_novel = bool(
                        distances[local_index] > cutoff
                        or distance_rank[local_pos] >= 0.90
                        or risk_rank[local_pos] >= 0.90
                    )
                    role = "high_risk_or_novelty" if is_novel else (
                        "cluster_medoid" if rank == 0 else "cluster_quantile"
                    )
                    chosen.append((global_index, role, cluster_id, is_novel))
            fitted_clusters += cluster_count

            if group_number % 10 == 0 or group_number == len(group_items):
                print(
                    f"[CANDIDATES] Processed strata {group_number}/{len(group_items)}; "
                    f"selected_so_far={len(chosen):,}",
                    flush=True,
                )

        # Deduplicate defensively and top up only if a rounding/empty cluster
        # caused a shortfall. Top-up is deterministic, not random.
        deduplicated = []
        seen_indices = set()
        for item in chosen:
            if item[0] not in seen_indices:
                deduplicated.append(item)
                seen_indices.add(item[0])
        chosen = deduplicated

        if len(chosen) < target:
            remaining_indices = [i for i in range(input_count) if i not in seen_indices]
            # Deterministic fill: choose points farthest from their nearest
            # selected point in feature space would be expensive; use stable
            # spread across input order as a safe final quota correction.
            needed = target - len(chosen)
            if needed == 1:
                positions = [len(remaining_indices) // 2]
            else:
                positions = np.rint(
                    np.linspace(0, len(remaining_indices) - 1, needed)
                ).astype(int).tolist()
            for pos in positions:
                idx = remaining_indices[pos]
                chosen.append((idx, "quota_fill_deterministic", None, False))
                seen_indices.add(idx)

        if len(chosen) > target:
            chosen = chosen[:target]
        if len(chosen) != target:
            matrix._mmap.close()
            ids._mmap.close()
            del matrix, ids
            workdir.cleanup()
            raise CommandError(
                f"Selection produced {len(chosen):,} unique records; expected exactly {target:,}."
            )

        print(
            f"[CANDIDATES] Selection complete: {len(chosen):,}/{target:,}. "
            "Preparing batched writes...",
            flush=True,
        )

        # Only replace this exact day/chunk/generation, never other chunks/days.
        if options["force"]:
            candidates.delete_many(candidate_filter)

        created_at = datetime.utcnow()
        output_ids = [ObjectId(ids[index].decode("ascii")) for index, *_ in chosen]
        record_by_id = {}
        for offset in range(0, len(output_ids), 500):
            batch_ids = output_ids[offset:offset + 500]
            cursor = normalized.find(
                {"_id": {"$in": batch_ids}, **chunk_filter},
                projection,
            )
            try:
                for record in cursor:
                    record_by_id[record["_id"]] = record
            finally:
                cursor.close()

        missing = [oid for oid in output_ids if oid not in record_by_id]
        if missing:
            matrix._mmap.close()
            ids._mmap.close()
            del matrix, ids
            workdir.cleanup()
            raise CommandError(
                f"{len(missing)} selected source records could not be reloaded from this chunk."
            )

        operations = []
        try:
            for number, (index, role, cluster_id, is_tail) in enumerate(chosen, start=1):
                original_oid = ObjectId(ids[index].decode("ascii"))
                record = dict(record_by_id[original_oid])
                record.pop("_id", None)
                record["_id"] = ObjectId()
                record["source_day"] = day
                record["chunk_index"] = chunk_index
                record["normalization_chunk_index"] = chunk_index
                record["isRandom"] = False
                record["candidate_generation"] = GENERATION
                record["candidate_sampled_at"] = created_at
                record["selection_role"] = role
                record["cluster_id"] = cluster_id
                record["is_outlier_candidate"] = is_tail
                operations.append(InsertOne(record))

                if len(operations) >= batch_size:
                    candidates.bulk_write(operations, ordered=False)
                    operations.clear()
                if number % 500 == 0 or number == target:
                    print(f"[CANDIDATES] Stored {number:,}/{target:,}", flush=True)

            if operations:
                candidates.bulk_write(operations, ordered=False)
        except Exception:
            candidates.delete_many(candidate_filter)
            raise
        finally:
            matrix.flush()
            ids.flush()
            matrix._mmap.close()
            ids._mmap.close()
            del matrix, ids
            workdir.cleanup()

        stored = candidates.count_documents(candidate_filter)
        if stored != target:
            raise CommandError(
                f"Stored {stored:,} candidate records; expected exactly {target:,}."
            )

        label_counts = {}
        for label in (0, 1):
            label_counts[str(label)] = candidates.count_documents({
                **candidate_filter,
                "$or": [{"label": label}, {"label_binary": label}],
            })

        self.stdout.write(self.style.SUCCESS(
            f"[CANDIDATES] SUCCESS day={day}; chunk_index={chunk_index}; "
            f"input={input_count:,}; stored={stored:,}; ratio={stored/input_count:.1%}; "
            f"strata={len(groups)}; clusters={fitted_clusters}; "
            f"small_strata_kept={small_strata_kept}; labels={label_counts}; "
            f"elapsed={time.monotonic()-started:.1f}s"
        ))
