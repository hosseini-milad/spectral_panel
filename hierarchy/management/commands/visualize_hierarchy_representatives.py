from ingestion.utils.document_paths import document_directory
import os
import re
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from mongoengine import get_connection

from hierarchy.services.visualization import save_hierarchy_representative_graph


DAY_FROM_SOURCE = re.compile(r"(\d{4}-\d{2}-\d{2})")


class Command(BaseCommand):
    help = (
        "Visualize a hierarchy graph with class-colored nodes and highlighted "
        "hyper representatives."
    )
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-file",
            required=True,
            help="Hierarchy graph key, e.g. hierarchy-day-2026-06-21-layer-2",
        )

    @staticmethod
    def _label01(value):
        try:
            label = int(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return label if label in (0, 1) else None

    def handle(self, *args, **options):
        started = time.perf_counter()
        source_file = options["source_file"].strip()
        db = get_connection(alias="default")["siem_db"]

        graph = db["hyper_graph_metadata"].find_one(
            {"source_file": source_file, "status": "complete"},
            {"_id": 0, "source_file": 1, "source_day": 1, "node_ids": 1, "node_labels": 1, "edge_count": 1},
        )
        if graph is None:
            any_graph = db["hyper_graph_metadata"].find_one({"source_file": source_file})
            if any_graph is None:
                raise CommandError(f"Hierarchy graph not found: {source_file}")
            raise CommandError(
                f"Hierarchy graph {source_file} is not complete "
                f"(status={any_graph.get('status', 'missing')!r})."
            )

        reps = list(db["hyper_representatives"].find(
            {"source_file": source_file},
            {"_id": 0, "node_index": 1, "label": 1, "original_id": 1, "attention": 1, "centrality": 1},
        ))
        if not reps:
            raise CommandError(f"No hyper_representatives found for: {source_file}")

        edge_cursor = db["hyper_graph_edges"].find(
            {"source_file": source_file},
            {"_id": 0, "source": 1, "target": 1, "weight": 1},
        ).batch_size(10000)
        edges = list(edge_cursor)
        edge_cursor.close()
        if not edges:
            raise CommandError(f"No hyper_graph_edges found for: {source_file}")

        node_ids = list(graph.get("node_ids") or [])
        if not node_ids:
            raise CommandError(f"No node_ids found for hierarchy graph: {source_file}")

        raw_labels = list(graph.get("node_labels") or [])
        node_labels = {}
        for index in range(len(node_ids)):
            if index < len(raw_labels):
                label = self._label01(raw_labels[index])
                if label is not None:
                    node_labels[index] = label

        normal_count = sum(label == 0 for label in node_labels.values())
        attack_count = sum(label == 1 for label in node_labels.values())

        self.stdout.write(f"[HIER-VIS] Graph nodes: {len(node_ids)}")
        self.stdout.write(f"[HIER-VIS] Graph edges: {len(edges)}")
        self.stdout.write(f"[HIER-VIS] Representatives: {len(reps)}")
        self.stdout.write(
            f"[HIER-VIS] Node labels loaded: normal={normal_count}; attack={attack_count}"
        )

        day = graph.get("source_day")
        if not day:
            m = DAY_FROM_SOURCE.search(source_file)
            day = m.group(1) if m else "unknown-day"

        output_dir = document_directory("hierarchy", source_file, layer=2, day=day)
        os.makedirs(output_dir, exist_ok=True)
        full_path = os.path.join(output_dir, f"{source_file}_full.png")
        reps_path = os.path.join(output_dir, f"{source_file}_representatives.png")

        self.stdout.write("[HIER-VIS] Rendering hierarchy visualization...")
        save_hierarchy_representative_graph(
            edges=edges,
            representatives=reps,
            full_path=full_path,
            reps_only_path=reps_path,
            all_nodes=range(len(node_ids)),
            node_labels=node_labels,
            title_prefix=source_file,
        )
        self.stdout.write(self.style.SUCCESS(
            f"[HIER-VIS] Saved full graph to: {full_path}"
        ))
        self.stdout.write(self.style.SUCCESS(
            f"[HIER-VIS] Saved representatives-only graph to: {reps_path}"
        ))
        self.stdout.write(self.style.SUCCESS(
            f"[HIER-VIS] Total elapsed: {time.perf_counter() - started:.1f}s"
        ))
