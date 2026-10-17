from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from ingestion.models.graph_metadata import GraphMetadata
from ingestion.models.graph_representative import GraphRepresentative
from ingestion.models.normalized_data import NormalizedSecurityData
from ingestion.models.sampled_data import SampledSecurityData
from ingestion.pipelines.graph_pipeline import run_graph_pipeline
from ingestion.pipelines.model_input_pipeline import prepare_model_input
from ingestion.pipelines.pooling_pipeline import run_pooling
from ingestion.pipelines.sampling_pipeline import run_sampling
from ingestion.services.reporting.ingest_report import create_ingest_report
from spectral_learning.services.temporal_dataset import (
    build_hierarchical_temporal_dataset,
)
from spectral_learning.services.temporal_graph import build_temporal_graph
from spectral_learning.services.spectral_report import create_spectral_report


class Command(BaseCommand):
    help = (
        "Rebuild sampled data, graph representatives, and spectral-learning "
        "inputs from existing normalized data."
    )
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("source_file", type=str)
        parser.add_argument("--sample-ratio", type=float, default=0.1)
        parser.add_argument("--representative-ratio", type=float, default=0.15)

    def handle(self, *args, **options):
        source_file = options["source_file"]
        sample_ratio = options["sample_ratio"]
        representative_ratio = options["representative_ratio"]
        if not 0 < sample_ratio <= 1:
            raise CommandError("sample-ratio must be in (0, 1].")
        if not 0 < representative_ratio < 1:
            raise CommandError("representative-ratio must be in (0, 1).")

        normalized = list(
            NormalizedSecurityData.objects(source_file=source_file).as_pymongo()
        )
        if not normalized:
            raise CommandError(
                f"No normalized records found for source_file={source_file!r}. "
                "Normalize the source first."
            )

        missing_labels = sum(record.get("label") not in (0, 1) for record in normalized)
        if missing_labels:
            raise CommandError(
                f"Found {missing_labels} normalized records without binary label 0/1."
            )

        try:
            sampled_count = run_sampling(source_file, sample_ratio)
            graph_stats = run_graph_pipeline(source_file)
            if graph_stats is None:
                raise ValueError("Graph construction returned no result.")

            graph = GraphMetadata.objects(source_file=source_file).first()
            sampled = list(
                SampledSecurityData.objects(source_file=source_file)
                .order_by("id")
                .as_pymongo()
            )
            representatives = run_pooling(
                source_file=source_file,
                edges=graph.edges,
                features=graph.features,
                docs=sampled,
                ratio=representative_ratio,
            )
            model_input = prepare_model_input(source_file)
            temporal_dataset = build_hierarchical_temporal_dataset(source_file)
            temporal_graph = build_temporal_graph(source_file)
            report = create_ingest_report(source_file)
            spectral_report = create_spectral_report(source_file)
        except Exception as exc:
            raise CommandError(f"Downstream rebuild failed: {exc}") from exc

        normalized_labels = Counter(record["label"] for record in normalized)
        representative_labels = Counter(item["label"] for item in representatives)
        expected_attack_count = int(
            len(representatives)
            * normalized_labels[1]
            / sum(normalized_labels.values())
            + 0.5
        )

        self.stdout.write(self.style.SUCCESS("Downstream rebuild completed."))
        self.stdout.write(f"source_file: {source_file}")
        self.stdout.write(f"normalized records (unchanged): {len(normalized)}")
        self.stdout.write(f"sampled records: {sampled_count}")
        self.stdout.write(
            f"sampled labels: {dict(Counter(item.get('label') for item in sampled))}"
        )
        self.stdout.write(f"graph nodes/edges: {graph_stats}")
        self.stdout.write(f"representative count: {len(representatives)}")
        self.stdout.write(f"representative labels: {dict(representative_labels)}")
        self.stdout.write(
            "expected attack representatives from normalized prior: "
            f"{expected_attack_count}"
        )
        self.stdout.write(f"model input: {model_input}")
        self.stdout.write(f"temporal dataset: {temporal_dataset}")
        self.stdout.write(f"temporal graph: {temporal_graph}")
        self.stdout.write(f"ingestion report: {report}")
        self.stdout.write(f"spectral report: {spectral_report}")
        self.stdout.write(
            "database representatives after rebuild: "
            f"{GraphRepresentative.objects(source_file=source_file).count()}"
        )
