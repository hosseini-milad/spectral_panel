import json
import re
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


CHUNK_SUFFIX_RE = re.compile(r"^(?P<base>.+)-chunk-(?P<chunk>\d+)$")


class Command(BaseCommand):
    help = (
        "Evaluate stored graph representatives for one day/chunk and save "
        "chunk-specific JSON, PNG and TXT reports."
    )
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-file",
            required=True,
            help=(
                "Base graph key, e.g. clustered-day-2026-06-24; "
                "the chunk suffix is added automatically."
            ),
        )
        parser.add_argument(
            "--chunk-index",
            type=int,
            default=0,
            help="Chunk index; defaults to 0.",
        )
        parser.add_argument(
            "--skip-eigen",
            action="store_true",
            help="Compute fast metrics only, without eigenvector recomputation.",
        )
        parser.add_argument(
            "--output",
            default=None,
            help="Optional output JSON path (defaults to BASE_DIR/evaluation).",
        )

    @staticmethod
    def _resolve_source_file(source_file, chunk_index):
        if chunk_index < 0:
            raise CommandError("--chunk-index must be >= 0.")

        match = CHUNK_SUFFIX_RE.match(source_file)
        if match:
            supplied_chunk = int(match.group("chunk"))
            if supplied_chunk != chunk_index:
                raise CommandError(
                    f"--source-file already specifies chunk {supplied_chunk}, "
                    f"but --chunk-index={chunk_index} was supplied."
                )
            return source_file

        return f"{source_file}-chunk-{chunk_index}"

    def handle(self, *args, **options):
        requested_source = options["source_file"].strip()
        chunk_index = options["chunk_index"]
        if not requested_source:
            raise CommandError("--source-file cannot be empty.")

        source_file = self._resolve_source_file(requested_source, chunk_index)
        graph = (
            GraphMetadata.objects(source_file=source_file)
            .order_by("-created_at")
            .first()
        )
        if graph is None:
            raise CommandError(
                f"No graph_metadata entry for {source_file!r}. "
                f"Expected source_file={source_file!r} for chunk_index={chunk_index}."
            )

        reps = list(
            GraphRepresentative.objects(source_file=source_file).as_pymongo()
        )
        if not reps:
            raise CommandError(f"No representatives for {source_file!r}")

        self.stdout.write(
            f"[EVAL] source_file={source_file}; chunk_index={chunk_index}; "
            f"graph_nodes={len(graph.node_ids)}; graph_edges={len(graph.edges)}"
        )
        self.stdout.write(f"[EVAL] Loaded {len(reps)} stored representatives")

        try:
            results = evaluate_representatives(
                graph, reps, with_eigen=not options["skip_eigen"]
            )
        except Exception as exc:
            raise CommandError(f"Evaluation failed for {source_file}: {exc}") from exc

        results["source_file"] = source_file
        results["chunk_index"] = chunk_index
        folder = Path(settings.BASE_DIR) / "files"/"evaluation"/options["source_file"]
        folder.mkdir(parents=True, exist_ok=True)

        if options["output"]:
            output = Path(options["output"])
        else:
            output = folder / f"{source_file}_evaluation.json"
        output.parent.mkdir(parents=True, exist_ok=True)

        with output.open("w", encoding="utf-8") as fp:
            json.dump(results, fp, indent=2, ensure_ascii=False)
        self.stdout.write(self.style.SUCCESS(f"[EVAL] JSON saved: {output}"))

        # Each chunk receives its own dashboard and text summary.
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
