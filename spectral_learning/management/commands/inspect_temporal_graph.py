from mongoengine import get_connection
from django.core.management.base import BaseCommand, CommandError

from spectral_learning.services.temporal_graph import GRAPH_COLLECTION


class Command(BaseCommand):
    help = "Display temporal graph size and structural/spectral changes."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("source_file", type=str)
        parser.add_argument(
            "--scale",
            choices=("minute", "hour", "day"),
            help="Optionally show only one temporal scale.",
        )

    def handle(self, *args, **options):
        query = {"source_file": options["source_file"]}
        if options.get("scale"):
            query["scale"] = options["scale"]
        collection = get_connection(alias="default")["siem_db"][GRAPH_COLLECTION]
        snapshots = list(collection.find(query).sort([("scale", 1), ("window_start", 1)]))
        if not snapshots:
            raise CommandError("No graph snapshots found. Build them first with build_temporal_graph.")

        self.stdout.write("scale | window_start | flows | nodes | directed_edges | components | edge_churn | spectral_distance | relative_weight_change | flow_delta")
        for item in snapshots:
            change = item.get("change") or {}
            fmt = lambda key: f"{change[key]:.4f}" if key in change else "-"
            self.stdout.write(
                f"{item['scale']} | {item['window_start']} | {item['flow_count']} | "
                f"{item['node_count']} | {item['edge_count']} | "
                f"{item['spectral']['component_count']} | "
                f"{fmt('edge_jaccard_distance')} | "
                f"{fmt('spectral_histogram_l1_distance')} | "
                f"{fmt('relative_edge_weight_change')} | "
                f"{change.get('flow_count_delta', '-') }"
            )

        comparable = [item for item in snapshots if item.get("change")]
        if comparable:
            largest_spectral = max(
                comparable,
                key=lambda item: item["change"]["spectral_histogram_l1_distance"],
            )
            largest_edge_churn = max(
                comparable,
                key=lambda item: item["change"]["edge_jaccard_distance"],
            )
            self.stdout.write("")
            self.stdout.write(
                "Largest spectral change: "
                f"{largest_spectral['scale']} @ {largest_spectral['window_start']} "
                f"({largest_spectral['change']['spectral_histogram_l1_distance']:.4f})"
            )
            self.stdout.write(
                "Largest edge-set change: "
                f"{largest_edge_churn['scale']} @ {largest_edge_churn['window_start']} "
                f"({largest_edge_churn['change']['edge_jaccard_distance']:.4f})"
            )
