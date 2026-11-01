import re
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


SOURCE_RE = re.compile(
    r"^clustered-day-(\d{4}-\d{2}-\d{2})-chunk-(\d+)$"
)


class Command(BaseCommand):
    """
    Run the complete one-chunk pipeline in order:
      1. Normalize the requested 20,000-record chunk
      2. Select 2,000 clustered candidates
      3. Build the cosine similarity graph
      4. Select graph representatives
      5. Evaluate representatives
      6. Visualize the representative graph

    Stops immediately if any stage raises an error.
    """
    help = (
        "Run normalization, candidate selection, graph construction, "
        "representative selection, evaluation, and visualization for one chunk."
    )
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-file",
            required=True,
            help=(
                "Full chunk key, e.g. "
                "clustered-day-2026-06-21-chunk-2"
            ),
        )
        parser.add_argument(
            "--sample-per-day",
            type=int,
            default=20000,
            help="Number of normalized records in this chunk (default: 20000).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=2000,
            help="Normalization batch size (default: 2000).",
        )
        parser.add_argument("--neighbors", type=int, default=12)
        parser.add_argument("--threshold", type=float, default=0.995)
        parser.add_argument("--degree-cap", type=int, default=20)
        parser.add_argument("--ratio", type=float, default=0.10)
        parser.add_argument(
            "--skip-eigen",
            action="store_true",
            help="Skip eigenvector recomputation during evaluation.",
        )

    def handle(self, *args, **options):
        source_file = options["source_file"].strip()
        match = SOURCE_RE.fullmatch(source_file)
        if not match:
            raise CommandError(
                "--source-file must have the form "
                "'clustered-day-YYYY-MM-DD-chunk-N', for example "
                "'clustered-day-2026-06-21-chunk-2'."
            )

        day, chunk_index_text = match.groups()
        chunk_index = int(chunk_index_text)
        sample_per_day = options["sample_per_day"]
        batch_size = options["batch_size"]
        ratio = options["ratio"]

        if sample_per_day < 1:
            raise CommandError("--sample-per-day must be positive.")
        if batch_size < 1:
            raise CommandError("--batch-size must be positive.")
        if not 0 < ratio < 1:
            raise CommandError("--ratio must be strictly between 0 and 1.")
        if options["neighbors"] < 1:
            raise CommandError("--neighbors must be positive.")
        if not -1 <= options["threshold"] <= 1:
            raise CommandError("--threshold must be in [-1, 1].")
        if options["degree_cap"] < 1:
            raise CommandError("--degree-cap must be positive.")

        # The evaluation command historically accepts the day-level key plus
        # --chunk-index, while graph metadata and visualization use the full key.
        day_source_file = f"clustered-day-{day}"

        stages = [
            (
                "1/6 Normalize parquet chunk",
                "normalize_parquet_dataset",
                {
                    # normalize_parquet_dataset expects --days as a string
                    # and parses/splits it internally (e.g. "2026-06-21").
                    "days": day,
                    "chunk_index": chunk_index,
                    "sample_per_day": sample_per_day,
                    "batch_size": batch_size,
                },
            ),
            (
                "2/6 Build clustered candidates",
                "build_clustered_candidates",
                {
                    "day": day,
                    "chunk_index": chunk_index,
                },
            ),
            (
                "3/6 Build cosine similarity graph",
                "build_candidate_similarity_graph",
                {
                    "day": day,
                    "chunk_index": chunk_index,
                    "neighbors": options["neighbors"],
                    "threshold": options["threshold"],
                    "degree_cap": options["degree_cap"],
                },
            ),
            (
                "4/6 Select representatives",
                "build_day_representatives",
                {
                    "day": day,
                    "chunk_index": chunk_index,
                    "stage": "reps",
                    "ratio": ratio,
                },
            ),
        ]

        started = time.perf_counter()
        self.stdout.write(self.style.NOTICE(
            f"[PIPELINE] source_file={source_file}; day={day}; "
            f"chunk_index={chunk_index}"
        ))

        for title, command_name, kwargs in stages:
            stage_started = time.perf_counter()
            self.stdout.write(self.style.NOTICE(f"\n[PIPELINE] {title}"))
            try:
                call_command(command_name, **kwargs)
            except Exception as exc:
                elapsed = time.perf_counter() - stage_started
                raise CommandError(
                    f"{title} failed after {elapsed:.1f}s. "
                    f"Pipeline stopped; later stages were not run. "
                    f"Cause: {exc}"
                ) from exc
            self.stdout.write(self.style.SUCCESS(
                f"[PIPELINE] Completed: {title} "
                f"({time.perf_counter() - stage_started:.1f}s)"
            ))

        # Evaluation uses the day-level source key plus the explicit chunk index.
        evaluation_kwargs = {
            "source_file": day_source_file,
            "chunk_index": chunk_index,
        }
        if options["skip_eigen"]:
            evaluation_kwargs["skip_eigen"] = True

        final_stages = [
            (
                "5/6 Evaluate representatives",
                "evaluate_representatives",
                evaluation_kwargs,
            ),
            (
                "6/6 Visualize representatives",
                "visualize_representatives",
                {"source_file": source_file},
            ),
        ]

        for title, command_name, kwargs in final_stages:
            stage_started = time.perf_counter()
            self.stdout.write(self.style.NOTICE(f"\n[PIPELINE] {title}"))
            try:
                call_command(command_name, **kwargs)
            except Exception as exc:
                elapsed = time.perf_counter() - stage_started
                raise CommandError(
                    f"{title} failed after {elapsed:.1f}s. "
                    f"Previous stages completed, but the pipeline stopped. "
                    f"Cause: {exc}"
                ) from exc
            self.stdout.write(self.style.SUCCESS(
                f"[PIPELINE] Completed: {title} "
                f"({time.perf_counter() - stage_started:.1f}s)"
            ))

        self.stdout.write(self.style.SUCCESS(
            f"\n[PIPELINE] ALL SIX STAGES COMPLETED for {source_file} "
            f"in {time.perf_counter() - started:.1f}s."
        ))
