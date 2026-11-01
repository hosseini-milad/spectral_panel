import math
import re
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from mongoengine import get_connection

from ingestion.models.graph_metadata import GraphMetadata
from ingestion.models.graph_representative import GraphRepresentative

DAY_SOURCE_RE = re.compile(r"^clustered-day-(\d{4}-\d{2}-\d{2})$")


class Command(BaseCommand):
    """
    Resume-safe day pipeline.

    Each stage is checked independently. Existing complete outputs are reused;
    missing downstream stages are run without repeating earlier successful work.
    """
    help = "Resume processing all chunks for a day, skipping completed stages."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--source-file", required=True)
        parser.add_argument("--sample-per-day", type=int, default=20000)
        parser.add_argument("--batch-size", type=int, default=2000)
        parser.add_argument("--neighbors", type=int, default=12)
        parser.add_argument("--threshold", type=float, default=0.995)
        parser.add_argument("--degree-cap", type=int, default=20)
        parser.add_argument("--ratio", type=float, default=0.10)
        parser.add_argument("--start-chunk", type=int, default=0)
        parser.add_argument("--max-chunks", type=int, default=None)
        parser.add_argument("--skip-eigen", action="store_true")

    def handle(self, *args, **options):
        match = DAY_SOURCE_RE.fullmatch(options["source_file"].strip())
        if not match:
            raise CommandError(
                "--source-file must be like clustered-day-2026-06-22 "
                "(without -chunk-N)."
            )

        day = match.group(1)
        chunk_size = options["sample_per_day"]
        batch_size = options["batch_size"]
        ratio = options["ratio"]
        start_chunk = options["start_chunk"]
        max_chunks = options["max_chunks"]

        if chunk_size < 1 or batch_size < 1:
            raise CommandError("--sample-per-day and --batch-size must be positive.")
        if start_chunk < 0:
            raise CommandError("--start-chunk cannot be negative.")
        if max_chunks is not None and max_chunks < 1:
            raise CommandError("--max-chunks must be positive.")
        if not 0 < ratio < 1:
            raise CommandError("--ratio must be strictly between 0 and 1.")
        if options["neighbors"] < 1:
            raise CommandError("--neighbors must be positive.")
        if not -1 <= options["threshold"] <= 1:
            raise CommandError("--threshold must be in [-1, 1].")
        if options["degree_cap"] < 1:
            raise CommandError("--degree-cap must be positive.")

        db = get_connection(alias="default")["siem_db"]
        day_total = db["security_data"].count_documents({"source_day": day})
        if not day_total:
            raise CommandError(f"No raw records found for source_day={day!r}.")

        total_chunks = math.ceil(day_total / chunk_size)
        if start_chunk >= total_chunks:
            raise CommandError(
                f"start-chunk={start_chunk} is outside valid range 0..{total_chunks - 1}."
            )
        end_chunk = total_chunks - 1
        if max_chunks is not None:
            end_chunk = min(end_chunk, start_chunk + max_chunks - 1)
        planned = end_chunk - start_chunk + 1

        self.stdout.write(self.style.NOTICE(
            f"[HYPER] day={day}; raw_records={day_total:,}; chunk_size={chunk_size:,}; "
            f"total_chunks={total_chunks}; run={start_chunk}..{end_chunk}"
        ))

        started = time.perf_counter()
        completed_chunks = []
        failed_chunk = None

        for pos, chunk_index in enumerate(range(start_chunk, end_chunk + 1), 1):
            chunk_source = f"clustered-day-{day}-chunk-{chunk_index}"
            offset = chunk_index * chunk_size
            expected_raw = min(chunk_size, max(0, day_total - offset))
            expected_candidates = max(1, int(expected_raw * 0.10 + 0.5))
            chunk_started = time.perf_counter()

            self.stdout.write(self.style.NOTICE(
                f"\n[HYPER] CHUNK {pos}/{planned}: {chunk_source}; "
                f"expected_raw={expected_raw:,}; expected_candidates~={expected_candidates:,}"
            ))

            try:
                # Check normalized records using the normalization-specific chunk field.
                normalized_count = db["normalized_security_data"].count_documents({
                    "source_day": day,
                    "normalization_chunk_index": chunk_index,
                })

                # Candidate presence is checked without hard-coding candidate_generation.
                # This avoids misclassifying valid existing v1/v2 candidates as missing.
                candidate_filter = {
                    "source_day": day,
                    "chunk_index": chunk_index,
                    "isRandom": False,
                }
                candidate_count = db["sampled_security_data"].count_documents(candidate_filter)

                if candidate_count >= expected_candidates:
                    self.stdout.write(self.style.WARNING(
                        f"[HYPER] SKIP normalize: {candidate_count:,} candidates already exist "
                        "for this chunk; avoid overwriting its upstream cohort."
                    ))
                elif normalized_count >= expected_raw:
                    self.stdout.write(self.style.WARNING(
                        f"[HYPER] SKIP normalize: normalized records already exist "
                        f"({normalized_count:,}/{expected_raw:,})."
                    ))
                else:
                    if candidate_count:
                        raise CommandError(
                            f"Only {candidate_count} candidates exist; expected about "
                            f"{expected_candidates}. Candidate command may refuse to overwrite "
                            "partial output. Inspect/remove only this chunk's partial candidates "
                            "before retrying."
                        )
                    self.stdout.write(self.style.NOTICE(
                        f"[HYPER] Run normalization: existing normalized records "
                        f"{normalized_count:,}/{expected_raw:,}."
                    ))
                    call_command(
                        "normalize_parquet_dataset",
                        days=day,
                        chunk_index=chunk_index,
                        sample_per_day=chunk_size,
                        batch_size=batch_size,
                    )

                # Recount after normalization / resume check.
                candidate_count = db["sampled_security_data"].count_documents(candidate_filter)
                if candidate_count < expected_candidates:
                    if candidate_count:
                        raise CommandError(
                            f"Candidate cohort is partial ({candidate_count}/{expected_candidates}); "
                            "refusing to continue with a potentially inconsistent graph."
                        )
                    self.stdout.write(self.style.NOTICE("[HYPER] Build clustered candidates"))
                    call_command(
                        "build_clustered_candidates",
                        day=day,
                        chunk_index=chunk_index,
                    )
                    candidate_count = db["sampled_security_data"].count_documents(candidate_filter)

                if candidate_count < expected_candidates:
                    raise CommandError(
                        f"Candidate generation finished but only {candidate_count} candidates "
                        f"were found; expected about {expected_candidates}."
                    )
                self.stdout.write(self.style.SUCCESS(
                    f"[HYPER] Candidates ready: {candidate_count:,}"
                ))

                # Graph stage: preserve existing graph metadata if present.
                graph = GraphMetadata.objects(source_file=chunk_source).first()
                if graph is None:
                    self.stdout.write(self.style.NOTICE("[HYPER] Build cosine similarity graph"))
                    call_command(
                        "build_candidate_similarity_graph",
                        day=day,
                        chunk_index=chunk_index,
                        neighbors=options["neighbors"],
                        threshold=options["threshold"],
                        degree_cap=options["degree_cap"],
                    )
                    graph = GraphMetadata.objects(source_file=chunk_source).first()
                else:
                    self.stdout.write(self.style.WARNING(
                        f"[HYPER] SKIP graph: already stored "
                        f"(nodes={len(graph.node_ids or [])}, edges={len(graph.edges or [])})."
                    ))

                if graph is None or not graph.node_ids:
                    raise CommandError("Graph metadata missing or graph has no nodes after graph stage.")

                # Representative stage: only run if the stored count is below target.
                expected_reps = max(1, int(len(graph.node_ids) * ratio + 0.5))
                rep_count = GraphRepresentative.objects(source_file=chunk_source).count()
                if rep_count >= expected_reps:
                    self.stdout.write(self.style.WARNING(
                        f"[HYPER] SKIP representatives: {rep_count}/{expected_reps} already stored."
                    ))
                else:
                    if rep_count:
                        raise CommandError(
                            f"Partial representative output ({rep_count}/{expected_reps}); "
                            "inspect this chunk before rebuilding to avoid duplicate/stale records."
                        )
                    self.stdout.write(self.style.NOTICE("[HYPER] Select representatives"))
                    call_command(
                        "build_day_representatives",
                        day=day,
                        chunk_index=chunk_index,
                        stage="reps",
                        ratio=ratio,
                    )
                    rep_count = GraphRepresentative.objects(source_file=chunk_source).count()
                    if rep_count < expected_reps:
                        raise CommandError(
                            f"Representative stage ended with {rep_count}; expected {expected_reps}."
                        )

                # Reports are reproducible outputs; rerun them even when DB stages exist.
                call_command("evaluate_graph_components", source_file=chunk_source)
                eval_kwargs = {
                    "source_file": f"clustered-day-{day}",
                    "chunk_index": chunk_index,
                }
                if options["skip_eigen"]:
                    eval_kwargs["skip_eigen"] = True
                self.stdout.write(self.style.NOTICE("[HYPER] Evaluate representatives"))
                call_command("evaluate_representatives", **eval_kwargs)

                self.stdout.write(self.style.NOTICE("[HYPER] Visualize representatives"))
                call_command("visualize_representatives", source_file=chunk_source)

                completed_chunks.append(chunk_index)
                self.stdout.write(self.style.SUCCESS(
                    f"[HYPER] COMPLETED {chunk_source} in "
                    f"{time.perf_counter() - chunk_started:.1f}s"
                ))

            except Exception as exc:
                failed_chunk = chunk_index
                self.stderr.write(self.style.ERROR(
                    f"[HYPER] FAILED chunk={chunk_index}: {exc}"
                ))
                break

        elapsed = time.perf_counter() - started
        if failed_chunk is not None:
            self.stderr.write(self.style.WARNING(
                f"[HYPER] Stopped at chunk {failed_chunk}; "
                f"completed this run={completed_chunks or 'none'}."
            ))
            raise CommandError(
                f"Hyper pipeline stopped at chunk {failed_chunk}; "
                f"{len(completed_chunks)}/{planned} chunks completed in {elapsed:.1f}s."
            )

        self.stdout.write(self.style.SUCCESS(
            f"\n[HYPER] ALL REQUESTED CHUNKS FINISHED; day={day}; "
            f"range={start_chunk}..{end_chunk}; completed={len(completed_chunks)}; "
            f"elapsed={elapsed:.1f}s."
        ))
