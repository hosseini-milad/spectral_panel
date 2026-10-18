import json
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ingestion.models.graph_metadata import GraphMetadata
from ingestion.models.graph_representative import GraphRepresentative
from ingestion.services.pooling.evaluation import evaluate_representatives
from ingestion.services.pooling.evaluation_visualization import (
    save_evaluation_dashboard,
    save_evaluation_summary_text,
)


class Command(BaseCommand):
    help = "Evaluate stored graph representatives and save JSON, PNG and TXT reports."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--source-file", required=True)
        parser.add_argument(
            "--skip-eigen",
            action="store_true",
            help="Compute fast metrics only, without eigenvector recomputation",
        )
        parser.add_argument(
            "--output",
            default=None,
            help="Optional output JSON path (defaults to BASE_DIR/evaluation)",
        )

    def handle(self, *args, **options):
        source_file = options["source_file"]
        graph = (
            GraphMetadata.objects(source_file=source_file)
            .order_by("-created_at")
            .first()
        )
        if graph is None:
            raise CommandError(f"No graph_metadata entry for {source_file}")

        reps = list(
            GraphRepresentative.objects(source_file=source_file).as_pymongo()
        )
        if not reps:
            raise CommandError(f"No representatives for {source_file}")

        self.stdout.write(f"[EVAL] Loaded {len(reps)} stored representatives")
        try:
            results = evaluate_representatives(
                graph, reps, with_eigen=not options["skip_eigen"]
            )
        except Exception as exc:
            raise CommandError(f"Evaluation failed: {exc}") from exc

        results["source_file"] = source_file
        folder = Path(settings.BASE_DIR) / "evaluation"
        folder.mkdir(parents=True, exist_ok=True)
        output = Path(options["output"]) if options["output"] else folder / f"{source_file}_evaluation.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as fp:
            json.dump(results, fp, indent=2, ensure_ascii=False)
        self.stdout.write(self.style.SUCCESS(f"[EVAL] JSON saved: {output}"))

        # Visual and plain-text summaries are always saved in BASE_DIR/evaluation.
        dashboard = folder / f"{source_file}_evaluation_dashboard.png"
        summary = folder / f"{source_file}_evaluation_summary.txt"
        try:
            save_evaluation_dashboard(results, str(dashboard))
            self.stdout.write(self.style.SUCCESS(f"[EVAL] Dashboard saved: {dashboard}"))
            save_evaluation_summary_text(results, str(summary))
            self.stdout.write(self.style.SUCCESS(f"[EVAL] Summary saved: {summary}"))
        except Exception as exc:
            raise CommandError(
                f"JSON saved successfully, but dashboard/summary generation failed: {exc}"
            ) from exc

        self.stdout.write(json.dumps(results, indent=2, ensure_ascii=False))
