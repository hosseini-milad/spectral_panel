from django.core.management.base import BaseCommand, CommandError

from ingestion.services.graph.candidate_graph import build_clustered_day_graph


DEFAULT_FEATURE_FIELDS = [
    "bytes",
    "bytes_per_packet",
    "bytes_per_sec",
    "dst_port",
    "duration_s",
    "flag_ack",
    "flag_count",
    "flag_fin",
    "flag_psh",
    "flag_rst",
    "flag_syn",
    "flag_urg",
    "is_encrypted_port",
    "is_syn_only",
    "log_bytes",
    "log_duration",
    "log_packets",
    "packets",
    "packets_per_sec",
    "proto_icmp",
    "proto_tcp",
    "proto_udp",
    "src_port",
    "tos",
    "threat_intel_score",
]


class Command(BaseCommand):
    help = (
        "Build a sparse union-kNN cosine-similarity graph from clustered "
        "candidates for one day and chunk."
    )
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--day", required=True)
        parser.add_argument("--chunk-index", type=int, required=True)
        parser.add_argument("--neighbors", type=int, default=12)
        parser.add_argument(
            "--threshold",
            type=float,
            default=0.95,
            help=(
                "Minimum cosine similarity for an edge. Default 0.95 is an "
                "initial experimental value; validate it against graph diagnostics."
            ),
        )
        parser.add_argument("--degree-cap", type=int, default=20)
        parser.add_argument("--workers", type=int, default=-1)
        parser.add_argument(
            "--feature-fields",
            nargs="+",
            default=DEFAULT_FEATURE_FIELDS,
            help=(
                "Optional list of numeric feature fields. If omitted, the "
                "project's standard 25 fields are used."
            ),
        )

    def handle(self, *args, **options):
        if options["chunk_index"] < 0:
            raise CommandError("--chunk-index must be >= 0.")
        if options["neighbors"] < 1:
            raise CommandError("--neighbors must be positive.")
        if not -1 <= options["threshold"] <= 1:
            raise CommandError("--threshold must be in [-1, 1].")
        if options["degree_cap"] < 1:
            raise CommandError("--degree-cap must be positive.")
        if not options["feature_fields"]:
            raise CommandError("At least one --feature-fields value is required.")

        self.stdout.write(
            f"[GRAPH] day={options['day']}; chunk_index={options['chunk_index']}; "
            f"k={options['neighbors']}; threshold={options['threshold']}; "
            f"degree_cap={options['degree_cap']}; workers={options['workers']}"
        )
        self.stdout.write(
            "[GRAPH] Using candidate generation configured in "
            "ingestion.services.graph.candidate_graph.CANDIDATE_GENERATION."
        )

        try:
            result = build_clustered_day_graph(
                source_day=options["day"],
                chunk_index=options["chunk_index"],
                feature_fields=options["feature_fields"],
                k=options["neighbors"],
                threshold=options["threshold"],
                degree_cap=options["degree_cap"],
                workers=options["workers"],
            )
        except Exception as exc:
            raise CommandError(
                f"Could not build similarity graph for day={options['day']!r}, "
                f"chunk_index={options['chunk_index']}: {exc}"
            ) from exc

        if result is None:
            raise CommandError(
                "No candidate records found for the requested day/chunk. "
                "Check source_day, chunk_index, candidate_generation, and isRandom."
            )

        stats = result
        self.stdout.write(self.style.SUCCESS(
            f"Saved graph {result['graph_key']} to siem_db.graph_metadata."
        ))
        self.stdout.write(
            f"day={options['day']}; chunk_index={options['chunk_index']}; "
            f"nodes={stats['num_nodes']:,}; edges={stats['num_edges']:,}; "
            f"union_knn_candidates={stats['knn_union_candidates']:,}; "
            f"mutual_knn_candidates={stats['mutual_knn_candidates']:,}; "
            f"density={stats['density']:.6f}; avg_degree={stats['avg_degree']:.3f}; "
            f"max_degree={stats['max_degree']}; isolated_nodes={stats['isolated_nodes']:,}; "
            f"components={stats['num_components']:,}; degree_cap={stats['degree_cap']}; "
            f"nodes_without_qualifying_neighbors={stats['nodes_without_qualifying_neighbors']:,}; "
            f"thresholded_edges_before_cap={stats['thresholded_edges_before_degree_cap']:,}; "
            f"threshold={stats['similarity_threshold']:.5f}; "
            f"feature_count={stats['feature_count']}; "
            f"union-kNN similarity quantiles={stats['candidate_similarity_quantiles']}; "
            f"edges at candidate thresholds={stats['threshold_edge_counts']}"
        )
