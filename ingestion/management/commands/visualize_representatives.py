from ingestion.utils.document_paths import document_directory
import os
import re

from bson import ObjectId
from bson.errors import InvalidId
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from mongoengine import get_connection

from ingestion.models.graph_metadata import GraphMetadata
from ingestion.models.graph_representative import GraphRepresentative
from ingestion.services.pooling.visualization import save_representative_graph


class Command(BaseCommand):
    help = (
        "Visualize an existing graph with class-colored nodes and saved "
        "representatives."
    )
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-file",
            required=True,
            help=(
                "Exact graph source_file, e.g. "
                "clustered-day-2026-06-21-chunk-0"
            ),
        )

    @staticmethod
    def _label01(value):
        try:
            label = int(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return label if label in (0, 1) else None

    @staticmethod
    def _date_folder(graph, source_file):
        # Prefer the explicit date stored in graph metadata.
        source_day = getattr(graph, "source_day", None)
        if source_day:
            value = str(source_day)
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                return value

        # Fallback for keys such as clustered-day-2026-06-21-chunk-0.
        match = re.search(r"\d{4}-\d{2}-\d{2}", source_file)
        if match:
            return match.group(0)

        raise CommandError(
            f"Could not determine YYYY-MM-DD date for graph: {source_file}"
        )

    def handle(self, *args, **options):
        source_file = options["source_file"]
        self.stdout.write(f"Loading graph metadata: {source_file}")

        graph = GraphMetadata.objects(source_file=source_file).first()
        if graph is None:
            raise CommandError(f"Graph not found: {source_file}")
        if not graph.node_ids:
            raise CommandError(f"No node_ids found for graph: {source_file}")

        self.stdout.write("Loading saved representatives...")
        representatives = [
            {
                "node_index": item.node_index,
                "label": item.label,
                "original_id": item.original_id,
                "centrality": item.centrality,
                "score": item.attention,
            }
            for item in GraphRepresentative.objects(source_file=source_file).only(
                "node_index",
                "label",
                "original_id",
                "centrality",
                "attention",
            )
        ]
        if not representatives:
            raise CommandError(f"No representatives found for: {source_file}")

        # node_index corresponds to the order of graph.node_ids.
        mongo_ids = []
        for value in graph.node_ids:
            value = str(value)
            try:
                mongo_ids.append(ObjectId(value))
            except (InvalidId, TypeError):
                mongo_ids.append(value)

        database = get_connection(alias="default")["siem_db"]
        sampled = database["sampled_security_data"]
        label_by_id = {}

        cursor = sampled.find(
            {"_id": {"$in": mongo_ids}},
            {"_id": 1, "label": 1},
        )
        try:
            for document in cursor:
                label = self._label01(document.get("label"))
                if label is not None:
                    label_by_id[str(document["_id"])] = label
        finally:
            cursor.close()

        node_labels = {}
        missing_ids = []
        for index, node_id in enumerate(graph.node_ids):
            label = label_by_id.get(str(node_id))
            if label is None:
                missing_ids.append(str(node_id))
            else:
                node_labels[index] = label

        if missing_ids:
            examples = ", ".join(missing_ids[:5])
            raise CommandError(
                f"Could not retrieve binary labels for {len(missing_ids)} of "
                f"{len(graph.node_ids)} graph nodes from sampled_security_data. "
                f"Example IDs: {examples}. No image was generated to avoid "
                "misleading colors."
            )

        normal_count = sum(label == 0 for label in node_labels.values())
        attack_count = sum(label == 1 for label in node_labels.values())
        self.stdout.write(f"Graph nodes: {len(graph.node_ids)}")
        self.stdout.write(f"Graph edges: {len(graph.edges)}")
        self.stdout.write(f"Representatives: {len(representatives)}")
        self.stdout.write(
            f"Node labels loaded: normal={normal_count}; attack={attack_count}"
        )

        # Keep the previous output root and place each graph image in its
        # source-day subfolder: files/nominal/YYYY-MM-DD/.
        date_folder = self._date_folder(graph, source_file) 
        output_dir = document_directory("nominal", source_file, day=date_folder)
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(
            output_dir, f"{source_file}_representatives.png"
        )

        self.stdout.write("Rendering full graph; please wait...")
        save_representative_graph(
            edges=graph.edges,
            representatives=representatives,
            path=output_path,
            all_nodes=range(len(graph.node_ids)),
            node_labels=node_labels,
        )
        self.stdout.write(
            self.style.SUCCESS(f"Visualization saved to: {output_path}")
        )
