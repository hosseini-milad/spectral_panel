from django.core.management.base import BaseCommand, CommandError

from ingestion.services.graph.candidate_graph import build_clustered_day_graph


class Command(BaseCommand):
    help = (
        "Build a sparse union-kNN cosine-similarity graph from clustered "
        "isRandom=false candidates for one day."
    )
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--day", required=True)
        parser.add_argument("--neighbors", type=int, default=12)
        parser.add_argument("--threshold", type=float, default=0.999)
        parser.add_argument("--degree-cap", type=int)
        parser.add_argument("--workers", type=int, default=-1)

    def handle(self, *args, **options):
        if options["neighbors"] < 1:
            raise CommandError("--neighbors must be positive.")
        if not -1 <= options["threshold"] <= 1:
            raise CommandError("--threshold must be in [-1, 1].")
        try:
            result = build_clustered_day_graph(
                source_day=options["day"],
                k=options["neighbors"],
                threshold=options["threshold"],
                degree_cap=options["degree_cap"],
                workers=options["workers"],
            )
        except Exception as exc:
            raise CommandError(f"Could not build similarity graph: {exc}") from exc

        stats = result
        self.stdout.write(self.style.SUCCESS(
            f"Saved graph {result['graph_key']} to siem_db.graph_metadata."
        ))
        self.stdout.write(
            f"nodes={stats['num_nodes']:,}; edges={stats['num_edges']:,}; "
            f"union_knn_candidates={stats['knn_union_candidates']:,}; "
            f"mutual_knn_candidates={stats['mutual_knn_candidates']:,}; "
            f"density={stats['density']:.6f}; avg_degree={stats['avg_degree']:.3f}; "
            f"max_degree={stats['max_degree']}; isolated_nodes={stats['isolated_nodes']:,}; "
            f"components={stats['num_components']:,}; degree_cap={stats['degree_cap']}; "
            f"nodes_without_qualifying_neighbors={stats['nodes_without_qualifying_neighbors']:,}; "
            f"thresholded_edges_before_cap={stats['thresholded_edges_before_degree_cap']:,}; "
            f"threshold={stats['similarity_threshold']:.5f}; "
            f"union-kNN similarity quantiles={stats['candidate_similarity_quantiles']}; "
            f"edges at candidate thresholds={stats['threshold_edge_counts']}"
        )
