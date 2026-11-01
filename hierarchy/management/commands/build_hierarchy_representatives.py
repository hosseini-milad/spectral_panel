import time
from collections import Counter
from datetime import datetime

import networkx as nx
from bson import ObjectId
from bson.errors import InvalidId
from django.core.management.base import BaseCommand, CommandError
from mongoengine import get_connection

from ingestion.models.graph_representative import GraphRepresentative
from ingestion.services.pooling.centrality import build_graph, compute_centralities
from ingestion.services.pooling.representative import select_representatives
from ingestion.services.pooling.scoring import compute_score


class Command(BaseCommand):
    """
    Select layer-2 representatives using the same eigenvector-based pooling
    selection method used by layer 1, then save them to hyper_representatives.

    Input graph:
        siem_db.hyper_graph_metadata
        siem_db.hyper_graph_edges

    Output:
        siem_db.hyper_representatives
    """
    help = "Select hierarchy graph representatives using eigenvector centrality."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-file",
            required=True,
            help="Hierarchy graph key, e.g. hierarchy-day-2026-06-21-layer-2",
        )
        parser.add_argument(
            "--ratio",
            type=float,
            default=0.10,
            help="Fraction of graph nodes to retain (default: 0.10).",
        )
        parser.add_argument(
            "--count",
            type=int,
            default=None,
            help="Explicit representative count; overrides --ratio.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Replace existing representatives for this source_file.",
        )

    @staticmethod
    def _object_id(value):
        try:
            return ObjectId(str(value))
        except (InvalidId, TypeError):
            return None

    @staticmethod
    def _label01(value):
        try:
            value = int(value)
        except (TypeError, ValueError, OverflowError):
            return 0
        return value if value in (0, 1) else 0

    def handle(self, *args, **options):
        started = time.perf_counter()
        source_file = options["source_file"].strip()
        ratio = options["ratio"]
        requested_count = options["count"]

        if requested_count is None and not 0 < ratio < 1:
            raise CommandError("--ratio must be strictly between 0 and 1.")
        if requested_count is not None and requested_count < 1:
            raise CommandError("--count must be positive.")

        database = get_connection(alias="default")["siem_db"]
        metadata_collection = database["hyper_graph_metadata"]
        edge_collection = database["hyper_graph_edges"]
        output_collection = database["hyper_representatives"]

        graph_doc = metadata_collection.find_one(
            {"source_file": source_file, "status": "complete"}
        )
        if graph_doc is None:
            any_graph = metadata_collection.find_one({"source_file": source_file})
            if any_graph is None:
                raise CommandError(f"Hierarchy graph not found: {source_file}")
            raise CommandError(
                f"Hierarchy graph {source_file} is not complete "
                f"(status={any_graph.get('status', 'missing')!r})."
            )

        existing_count = output_collection.count_documents(
            {"source_file": source_file}
        )
        if existing_count and not options["force"]:
            raise CommandError(
                f"{existing_count} representatives already exist for {source_file}. "
                "Use --force to replace this graph's representatives."
            )

        node_ids = [str(value) for value in graph_doc.get("node_ids", [])]
        if not node_ids:
            raise CommandError("Graph metadata contains no node_ids.")

        node_count = len(node_ids)
        target_count = (
            min(int(requested_count), node_count)
            if requested_count is not None
            else min(node_count, max(1, int(node_count * ratio + 0.5)))
        )

        self.stdout.write(
            f"[HYPER-REPS] source_file={source_file}; nodes={node_count:,}; "
            f"target_representatives={target_count:,}; ratio={target_count / node_count:.4f}"
        )

        # Build graph from the separately stored edge collection.
        graph_started = time.perf_counter()
        G = nx.Graph()
        G.add_nodes_from(range(node_count))
        edge_cursor = edge_collection.find(
            {"source_file": source_file},
            {"_id": 0, "source": 1, "target": 1, "weight": 1},
        ).batch_size(10000)

        edge_count = 0
        try:
            for edge in edge_cursor:
                left = int(edge["source"])
                right = int(edge["target"])
                weight = float(edge.get("weight", 1.0))
                if left < 0 or right < 0 or left >= node_count or right >= node_count:
                    raise CommandError(
                        f"Invalid edge endpoint ({left}, {right}) for {node_count} nodes."
                    )
                G.add_edge(left, right, weight=weight)
                edge_count += 1
        finally:
            edge_cursor.close()

        if edge_count != int(graph_doc.get("edge_count", edge_count)):
            raise CommandError(
                f"Edge count mismatch: metadata={graph_doc.get('edge_count')}, "
                f"loaded={edge_count}. Refusing representative selection."
            )

        self.stdout.write(
            f"[HYPER-REPS] Graph loaded: nodes={G.number_of_nodes():,}; "
            f"edges={G.number_of_edges():,}; components={nx.number_connected_components(G):,}; "
            f"isolates={sum(1 for n in G if G.degree(n) == 0):,}; "
            f"elapsed={time.perf_counter() - graph_started:.2f}s"
        )

        # Preserve node order: node index i always refers to node_ids[i].
        raw_labels = graph_doc.get("node_labels", [])
        labels = {
            index: self._label01(raw_labels[index]) if index < len(raw_labels) else 0
            for index in range(node_count)
        }

        # Resolve parent layer-1 representative records for lineage and label
        # verification. In this graph, node_ids point to GraphRepresentative._id.
        parent_ids = []
        parent_id_by_node = {}
        for index, value in enumerate(node_ids):
            oid = self._object_id(value)
            if oid is not None:
                parent_ids.append(oid)
                parent_id_by_node[index] = oid

        parent_by_id = {}
        lookup_started = time.perf_counter()
        for offset in range(0, len(parent_ids), 1000):
            batch = parent_ids[offset:offset + 1000]
            for parent in GraphRepresentative.objects(
                __raw__={"_id": {"$in": batch}}
            ).as_pymongo():
                parent_by_id[str(parent["_id"])] = parent

        missing_parent = [
            node_ids[index]
            for index in range(node_count)
            if node_ids[index] not in parent_by_id
        ]
        if missing_parent:
            raise CommandError(
                f"Could not resolve {len(missing_parent)} parent representatives "
                f"from ingestion.graph_representatives. Examples: {missing_parent[:5]}"
            )

        # Use the saved layer-1 representative label as authoritative where present.
        for index, value in enumerate(node_ids):
            parent = parent_by_id[value]
            labels[index] = self._label01(parent.get("label", labels[index]))

        attack_ratio = (
            sum(value == 1 for value in labels.values()) / max(1, len(labels))
        )
        self.stdout.write(
            f"[HYPER-REPS] Parent lineage resolved in "
            f"{time.perf_counter() - lookup_started:.2f}s; "
            f"normal={sum(v == 0 for v in labels.values())}; "
            f"attack={sum(v == 1 for v in labels.values())}; "
            f"attack_ratio={attack_ratio:.4f}"
        )

        # Same layer-1 centrality/scoring/selection functions; no ingestion code
        # is changed. Anomaly scores are unavailable at this graph layer, so
        # the selector receives an empty anomaly-score mapping and still uses
        # eigenvector, degree, component rarity, class balance, and graph distance.
        centrality_started = time.perf_counter()
        centralities = compute_centralities(G)
        self.stdout.write(
            f"[HYPER-REPS] Centralities computed in "
            f"{time.perf_counter() - centrality_started:.2f}s"
        )

        anomaly_scores = {}
        scores = compute_score(centralities, anomaly_scores)
        if not scores:
            raise CommandError("Scoring returned no node scores.")

        selection_started = time.perf_counter()
        selected_nodes = select_representatives(
            score=scores,
            G=G,
            k=target_count,
            labels=labels,
            attack_ratio=attack_ratio,
            eigenvector_scores=centralities.get("eigenvector", {}),
            anomaly_scores=anomaly_scores,
        )
        selected_nodes = list(dict.fromkeys(int(node) for node in selected_nodes))
        if len(selected_nodes) != target_count:
            raise CommandError(
                f"Selection returned {len(selected_nodes)} representatives; "
                f"expected {target_count}. Nothing was saved."
            )
        self.stdout.write(
            f"[HYPER-REPS] Selected {len(selected_nodes):,} representatives in "
            f"{time.perf_counter() - selection_started:.2f}s"
        )

        # Precompute component IDs once, rather than scanning all components
        # separately for each selected representative.
        component_id_by_node = {}
        for component_index, component in enumerate(nx.connected_components(G)):
            for component_node in component:
                component_id_by_node[component_node] = component_index

        # Prepare all output first. Only replace existing records after selection
        # and lineage checks have completed successfully.
        documents = []
        for node_index in selected_nodes:
            parent_id_text = node_ids[node_index]
            parent = parent_by_id[parent_id_text]
            label = labels[node_index]
            documents.append({
                "source_file": source_file,
                "source_day": graph_doc.get("source_day"),
                "layer": 2,
                "node_index": node_index,
                # ID of the layer-1 GraphRepresentative document represented by
                # this layer-2 node; used as the next layer's parent reference.
                "original_id": parent_id_text,
                "parent_source_file": parent.get("source_file"),
                "parent_node_index": parent.get("node_index"),
                "parent_original_id": str(parent.get("original_id", "")),
                "label": label,
                "attention": float(scores.get(node_index, 0.0)),
                "centrality": float(
                    centralities.get("eigenvector", {}).get(node_index, 0.0)
                ),
                "degree": int(G.degree(node_index)),
                "component_id": int(component_id_by_node.get(node_index, -1)),
                "selection_method": "layer1_eigenvector_based_select_representatives",
                "selection_parameters": {
                    "ratio": float(target_count / node_count),
                    "target_count": int(target_count),
                    "attack_ratio": float(attack_ratio),
                    "anomaly_scores_available": False,
                    "centrality_method": "component_weighted_eigenvector",
                },
                "created_at": datetime.utcnow(),
            })

        if options["force"]:
            output_collection.delete_many({"source_file": source_file})

        batch_size = 1000
        saved = 0
        for offset in range(0, len(documents), batch_size):
            batch = documents[offset:offset + batch_size]
            output_collection.insert_many(batch, ordered=True)
            saved += len(batch)
            self.stdout.write(
                f"[HYPER-REPS] Saved {saved:,}/{len(documents):,}"
            )

        counts = Counter(doc["label"] for doc in documents)
        self.stdout.write(self.style.SUCCESS(
            f"[HYPER-REPS] SUCCESS source_file={source_file}; "
            f"saved={saved}; normal={counts.get(0, 0)}; attack={counts.get(1, 0)}; "
            f"collection=siem_db.hyper_representatives; "
            f"total_elapsed={time.perf_counter() - started:.2f}s"
        ))
