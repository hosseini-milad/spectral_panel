
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ingestion.models.graph_metadata import GraphMetadata
from ingestion.models.graph_representative import GraphRepresentative
from ingestion.services.pooling.visualization import (
    save_representative_graph,
)


class Command(BaseCommand):
    help = "Visualize an existing graph and its saved representatives."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-file",
            required=True,
            help="Graph source_file, e.g. clustered-day-2026-06-21",
        )

    def handle(self, *args, **options):
        source_file = options["source_file"]

        self.stdout.write("Loading graph metadata...")

        graph = GraphMetadata.objects(
            source_file=source_file
        ).first()

        if graph is None:
            raise CommandError(
                f"Graph not found: {source_file}"
            )

        if not graph.edges:
            raise CommandError(
                f"No edges found for graph: {source_file}"
            )

        self.stdout.write("Loading saved representatives...")

        representatives = [
            {
                "node_index": item.node_index,
                "label": item.label,
                "original_id": item.original_id,
                "centrality": item.centrality,
                "score": item.attention,
            }
            for item in GraphRepresentative.objects(
                source_file=source_file
            ).only(
                "node_index",
                "label",
                "original_id",
                "centrality",
                "attention",
            )
        ]

        if not representatives:
            raise CommandError(
                f"No representatives found for: {source_file}"
            )

        output_dir = os.path.join(
            str(settings.BASE_DIR),
            "files",
            "nominal",
        )
        os.makedirs(output_dir, exist_ok=True)

        output_path = os.path.join(
            output_dir,
            f"{source_file}_representatives.png",
        )

        self.stdout.write(
            f"Graph nodes: {len(graph.node_ids)}"
        )
        self.stdout.write(
            f"Graph edges: {len(graph.edges)}"
        )
        self.stdout.write(
            f"Representatives: {len(representatives)}"
        )
        self.stdout.write("Rendering graph; please wait...")

        save_representative_graph(
        edges=graph.edges,
        representatives=representatives,
        path=output_path,
        all_nodes=range(len(graph.node_ids)),
    )

        self.stdout.write(
            self.style.SUCCESS(
                f"Visualization saved to: {output_path}"
            )
        )
