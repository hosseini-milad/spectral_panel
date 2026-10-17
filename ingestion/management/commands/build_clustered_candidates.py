from collections import defaultdict
from datetime import datetime
import math
import re

import numpy as np
from bson import ObjectId
from django.core.management.base import BaseCommand, CommandError
from mongoengine import get_connection
from pymongo import InsertOne
from sklearn.cluster import MiniBatchKMeans

from ingestion.management.commands.normalize_parquet_dataset import NUMERIC_FIELDS


METADATA_FIELDS = (
    "original_id", "source_file", "source_path", "source_day", "source_type",
    "type", "row_index", "window_start", "flow_start", "timestamp",
    "attack_category", "attack_type", "label", "label_binary",
)
GENERATION = "time_label_minibatch_medoids_with_tails_v1"


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
    match = re.search(r"nfcapd\.(\d{10})", str(record.get("source_file", "")))
    if match:
        return datetime.strptime(match.group(1), "%Y%m%d%H").strftime("%Y-%m-%dT%H")
    return "unknown"


def _allocate_quotas(capacities, target):
    """Proportional largest-remainder allocation with capacity constraints."""
    total = sum(capacities)
    if target >= total:
        return list(capacities)
    if target <= 0 or not capacities:
        return [0] * len(capacities)

    exact = [target * capacity / total for capacity in capacities]
    quotas = [min(capacities[i], int(math.floor(value))) for i, value in enumerate(exact)]
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
        except (TypeError, ValueError):
            value = 0.0
        values.append(value if math.isfinite(value) else 0.0)
    return values


class Command(BaseCommand):
    help = (
        "Create time/class-stratified clustered candidates, keeping medoids and "
        "within-cluster tail points alongside random candidates."
    )
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--day", required=True)
        parser.add_argument("--count", type=int, default=20_000)
        parser.add_argument("--batch-size", type=int, default=2_000)
        parser.add_argument("--clusters-per-20-candidates", type=int, default=1)
        parser.add_argument("--random-state", type=int, default=42)
        parser.add_argument("--outlier-quantile", type=float, default=0.99)

    def handle(self, *args, **options):
        day = options["day"]
        target = options["count"]
        batch_size = options["batch_size"]
        clusters_per_20 = options["clusters_per_20_candidates"]
        outlier_quantile = options["outlier_quantile"]
        if target < 1 or batch_size < 1 or clusters_per_20 < 1:
            raise CommandError("count, batch-size and clusters-per-20-candidates must be positive.")
        if not 0.5 < outlier_quantile < 1:
            raise CommandError("--outlier-quantile must be between 0.5 and 1.0.")

        database = get_connection(alias="default")["siem_db"]
        normalized = database["normalized_security_data"]
        candidates = database["sampled_security_data"]
        day_filter = {"source_day": day, "normalization_version": 1}
        total = normalized.count_documents(day_filter)
        if total == 0:
            raise CommandError(f"No normalized records found for source_day={day!r}.")
        target = min(target, total)

        numeric_fields = [field for field in NUMERIC_FIELDS if field in normalized.find_one(day_filter, {field: 1})]
        if not numeric_fields:
            raise CommandError("No numeric feature fields found in normalized records.")
        projection = {field: 1 for field in set(numeric_fields) | set(METADATA_FIELDS)}
        projection["_id"] = 1

        records = []
        vectors = []
        groups = defaultdict(list)
        cursor = normalized.find(day_filter, projection).batch_size(10_000)
        try:
            for record in cursor:
                record["label"] = int(record.get("label", record.get("label_binary", 0)) or 0)
                records.append(record)
                vectors.append(_numeric_vector(record, numeric_fields))
                group_key = (_hour_bucket(record), record["label"])
                groups[group_key].append(len(records) - 1)
        finally:
            cursor.close()
        if not records:
            raise CommandError(f"No records could be loaded for {day!r}.")

        matrix = np.asarray(vectors, dtype=np.float32)
        # Constant dimensions do not help clustering and can distort distances.
        active = np.nanstd(matrix, axis=0) > 1e-8
        matrix = matrix[:, active]
        if matrix.shape[1] == 0:
            raise CommandError("All numeric feature dimensions are constant in this day.")

        group_items = sorted(groups.items(), key=lambda item: item[0])
        group_quotas = _allocate_quotas(
            [len(indices) for _, indices in group_items], target
        )
        chosen = []
        group_cluster_count = 0
        small_strata_kept = 0
        detected_outlier_count = 0

        for (group_key, indices), quota in zip(group_items, group_quotas):
            if quota == 0:
                continue
            if quota >= len(indices):
                chosen.extend((index, "all_records_small_stratum", None, False) for index in indices)
                small_strata_kept += 1
                continue

            cluster_count = max(1, quota // 20 * clusters_per_20)
            cluster_count = min(cluster_count, quota, len(indices) - 1)
            group_matrix = matrix[indices]
            model = MiniBatchKMeans(
                n_clusters=cluster_count,
                init="k-means++",
                n_init=1,
                random_state=options["random_state"],
                batch_size=max(256, min(8192, len(indices))),
                max_iter=100,
                reassignment_ratio=0.0,
            )
            assignments = model.fit_predict(group_matrix)
            centers = model.cluster_centers_
            distances = np.linalg.norm(group_matrix - centers[assignments], axis=1)
            sizes = np.bincount(assignments, minlength=cluster_count).tolist()
            cluster_quotas = _allocate_quotas(sizes, quota)

            for cluster_id, cluster_quota in enumerate(cluster_quotas):
                if cluster_quota == 0:
                    continue
                members = np.flatnonzero(assignments == cluster_id)
                cluster_distances = distances[members]
                cutoff = float(np.quantile(cluster_distances, outlier_quantile))
                outlier_mask = cluster_distances > cutoff
                outlier_members = members[outlier_mask]
                core_members = members[~outlier_mask]

                # Every distance-based outlier is retained. The final coreset can
                # exceed its target if a stratum contains more detected outliers
                # than its representative quota.
                for local_index in outlier_members:
                    chosen.append((indices[int(local_index)], "statistical_outlier", cluster_id, True))
                detected_outlier_count += len(outlier_members)

                core_quota = max(0, cluster_quota - len(outlier_members))
                if core_quota and len(core_members):
                    core_order = np.argsort(distances[core_members], kind="stable")
                    sorted_core = core_members[core_order]
                    core_quota = min(core_quota, len(sorted_core))
                    if core_quota == len(sorted_core):
                        positions = np.arange(len(sorted_core))
                    elif core_quota == 1:
                        positions = np.array([0])
                    else:
                        positions = np.rint(
                            np.linspace(0, len(sorted_core) - 1, core_quota)
                        ).astype(int)
                    for rank, position in enumerate(positions):
                        local_index = int(sorted_core[position])
                        record_index = indices[local_index]
                        role = "cluster_medoid" if rank == 0 else "cluster_quantile"
                        chosen.append((record_index, role, cluster_id, False))
            group_cluster_count += cluster_count

        if len(chosen) < target:
            raise CommandError(
                f"Selection produced only {len(chosen):,} rows for a target of {target:,}."
            )

        # Mark the earlier random run explicitly so both methods can be compared.
        candidates.update_many(
            {"source_day": day, "candidate_generation": "uniform_day_sample_v1"},
            {"$set": {"isRandom": True}},
        )
        candidates.delete_many({"source_day": day, "candidate_generation": GENERATION})

        created_at = datetime.utcnow()
        operations = []
        try:
            for index, role, cluster_id, is_tail in chosen:
                record = dict(records[index])
                record.pop("_id", None)
                record["_id"] = ObjectId()
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
            if operations:
                candidates.bulk_write(operations, ordered=False)
        except Exception:
            candidates.delete_many({"source_day": day, "candidate_generation": GENERATION})
            raise

        stored = candidates.count_documents({"source_day": day, "candidate_generation": GENERATION})
        label_counts = {
            str(label): candidates.count_documents({
                "source_day": day,
                "candidate_generation": GENERATION,
                "label": label,
            })
            for label in (0, 1)
        }
        tail_count = candidates.count_documents({
            "source_day": day,
            "candidate_generation": GENERATION,
            "is_outlier_candidate": True,
        })
        self.stdout.write(self.style.SUCCESS(
            f"Stored {stored:,} clustered candidates for {day} beside the prior random run."
        ))
        self.stdout.write(
            f"isRandom=false; method={GENERATION}; day records={total:,}; "
            f"requested target={target:,}; selected={stored:,}; "
            f"time/label strata={len(groups)}; fitted clusters={group_cluster_count:,}; "
            f"within-cluster outlier quantile={outlier_quantile:.3f}; "
            f"robust outliers retained={detected_outlier_count:,}; "
            f"outlier records stored={tail_count:,}; small strata kept whole={small_strata_kept}; "
            f"labels={label_counts}."
        )
