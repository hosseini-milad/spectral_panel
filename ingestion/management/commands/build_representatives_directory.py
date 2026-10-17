from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from ingestion.models.graph_metadata import GraphMetadata
from ingestion.models.graph_representative import GraphRepresentative
from ingestion.models.sampled_data import SampledSecurityData
from ingestion.pipelines.pooling_pipeline import run_pooling


class Command(BaseCommand):
    help = (
        "Build eigenvector-aware representatives directly from existing "
        "graphs stored in graph_metadata."
    )
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument(
            "--representative-ratio",
            type=float,
            default=0.15,
        )

    def handle(self, *args, **options):
        representative_ratio = options["representative_ratio"]

        if not 0 < representative_ratio < 1:
            raise CommandError(
                "representative-ratio must be in (0, 1)."
            )

        graphs = list(
            GraphMetadata.objects
            .order_by("created_at")
        )

        if not graphs:
            raise CommandError(
                "No graphs found in graph_metadata. "
                "Build the graph before extracting representatives."
            )

        self.stdout.write(
            f"Found {len(graphs)} graph(s) in graph_metadata."
        )

        for graph in graphs:

            source_file = graph.source_file

            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"Processing graph: {source_file}"
                )
            )

            # --------------------------------------------------
            # 1. بررسی Graph
            # --------------------------------------------------

            if not graph.edges:
                raise CommandError(
                    f"No edges found for graph {source_file}."
                )

            # --------------------------------------------------
            # 2. پیدا کردن sampled documents
            #
            # برای graphهای روزانه، source_file گراف ممکن است
            # clustered-day-YYYY-MM-DD باشد، بنابراین ابتدا
            # source_day را بررسی می‌کنیم.
            # --------------------------------------------------

            if graph.source_day:
                sampled_query = {
                    "source_day": graph.source_day
                }

                if graph.candidate_generation is not None:
                    sampled_query["candidate_generation"] = (
                        graph.candidate_generation
                    )

                if graph.is_random is not None:
                    sampled_query["isRandom"] = graph.is_random

                sampled_docs = list(
                    SampledSecurityData.objects(
                        __raw__=sampled_query
                    )
                    .order_by("id")
                    .as_pymongo()
                )

            else:
                sampled_docs = list(
                    SampledSecurityData.objects(
                        source_file=source_file
                    )
                    .order_by("id")
                    .as_pymongo()
                )

            if not sampled_docs:
                raise CommandError(
                    f"No sampled records found for graph {source_file}."
                )

            # --------------------------------------------------
            # 3. اطمینان از تطابق تعداد Nodeها
            # --------------------------------------------------

            graph_node_count = len(graph.node_ids)

            if graph_node_count != len(sampled_docs):
                raise CommandError(
                    f"Node/document mismatch for {source_file}: "
                    f"graph_nodes={graph_node_count}, "
                    f"sampled_docs={len(sampled_docs)}."
                )

            # --------------------------------------------------
            # 4. Labelها از sampled data
            # --------------------------------------------------

            labels = {
                index: int(doc.get("label", 0) or 0)
                for index, doc in enumerate(sampled_docs)
            }

            attack_count = sum(
                label == 1
                for label in labels.values()
            )

            attack_ratio = (
                attack_count / len(labels)
                if labels
                else 0.0
            )

            # --------------------------------------------------
            # 5. اجرای Pooling روی گراف موجود
            #
            # اینجا graph دوباره ساخته نمی‌شود.
            # edges مستقیماً از graph_metadata خوانده شده‌اند.
            # --------------------------------------------------

            try:
                representatives = run_pooling(
                    source_file=source_file,
                    edges=graph.edges,
                    features=graph.features,
                    docs=sampled_docs,
                    ratio=representative_ratio,
                    labels=labels,
                    attack_ratio=attack_ratio,
                    create_visualization=False,
                )

            except Exception as exc:
                raise CommandError(
                    f"Representative extraction failed for "
                    f"{source_file}: {exc}"
                ) from exc

            # --------------------------------------------------
            # 6. آمار خروجی
            # --------------------------------------------------

            representative_labels = Counter(
                item["label"]
                for item in representatives
            )

            stored_count = GraphRepresentative.objects(
                source_file=source_file
            ).count()

            self.stdout.write(
                f"{source_file}: "
                f"graph_nodes={len(sampled_docs)}, "
                f"graph_edges={len(graph.edges)}, "
                f"representatives={stored_count}, "
                f"representative_labels="
                f"{dict(representative_labels)}"
            )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully extracted representatives from "
                f"{len(graphs)} existing graph(s). "
                f"No sampling or graph reconstruction was performed."
            )
        )