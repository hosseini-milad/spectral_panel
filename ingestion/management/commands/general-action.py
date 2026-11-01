"""One resumable layer-1 pipeline for an explicit day/chunk key."""
import re
import time
from datetime import datetime

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from mongoengine import get_db

from ingestion.services.graph.candidate_graph import CANDIDATE_GENERATION
from ingestion.utils.document_paths import document_directory

SOURCE_RE = re.compile(r"^clustered-day-(\d{4}-\d{2}-\d{2})-chunk-(\d+)$")


class Command(BaseCommand):
    help = "Resume one chunk from normalization through graph/components, representatives, all layer-1 evaluations and visualization."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--source-file', required=True, help='clustered-day-YYYY-MM-DD-chunk-N')
        parser.add_argument('--sample-per-day', type=int, default=20000)
        parser.add_argument('--batch-size', type=int, default=2000)
        parser.add_argument('--neighbors', type=int, default=12)
        parser.add_argument('--threshold', type=float, default=0.995)
        parser.add_argument('--degree-cap', type=int, default=20)
        parser.add_argument('--ratio', type=float, default=0.10)
        parser.add_argument('--skip-eigen', action='store_true')

    def handle(self, *args, **options):
        source = options['source_file'].strip()
        match = SOURCE_RE.fullmatch(source)
        if not match:
            raise CommandError('--source-file must be clustered-day-YYYY-MM-DD-chunk-N.')
        day, chunk_text = match.groups()
        try:
            datetime.strptime(day, '%Y-%m-%d')
        except ValueError as exc:
            raise CommandError('Invalid calendar date in --source-file.') from exc
        chunk = int(chunk_text)
        size, batch, ratio = options['sample_per_day'], options['batch_size'], options['ratio']
        if min(size, batch, options['neighbors'], options['degree_cap']) < 1:
            raise CommandError('Chunk size, batch size, neighbors and degree cap must be positive.')
        if not 0 < ratio < 1 or not -1 <= options['threshold'] <= 1:
            raise CommandError('Require 0 < ratio < 1 and -1 <= threshold <= 1.')
        db = get_db()
        raw_count = db.security_data.count_documents({'source_day': day})
        expected = min(size, max(0, raw_count - chunk * size))
        if not expected:
            raise CommandError(f'No raw records for {source}: day_records={raw_count}, offset={chunk * size}. Ingest the requested day first.')
        normalized_query = {'source_day': day, 'normalization_chunk_index': chunk}
        candidate_query = {'source_day': day, 'chunk_index': chunk, 'isRandom': False,
                           'candidate_generation': CANDIDATE_GENERATION}
        target = min(expected, max(1, round(expected * .10)))
        graph_query = {'source_file': source}
        started = time.perf_counter()
        self.stdout.write(f'[PIPELINE] {source}; raw_chunk={expected}; candidates_target={target}; resume enabled')

        def run(number, title, command, **kwargs):
            self.stdout.write(self.style.NOTICE(f'[PIPELINE] {number}/10 {title}'))
            before = time.perf_counter()
            try:
                call_command(command, stdout=self.stdout, stderr=self.stderr, **kwargs)
            except Exception as exc:
                raise CommandError(f'{number}/10 {title} failed after {time.perf_counter() - before:.1f}s. Later stages were not run. Retry the same command after resolving the cause: {exc}') from exc
            self.stdout.write(self.style.SUCCESS(f'[PIPELINE] Completed {number}/10 ({time.perf_counter() - before:.1f}s)'))

        def skip(number, title, detail):
            self.stdout.write(f'[PIPELINE] {number}/10 SKIP {title}: {detail}')

        def require_count(collection, query, count, stage):
            actual = collection.count_documents(query)
            if actual != count:
                raise CommandError(f'{stage}: stored={actual}, expected={count}. Partial/incompatible output; later stages were not run. Inspect this chunk before retrying.')

        normalized_count = db.normalized_security_data.count_documents(normalized_query)
        candidate_count = db.sampled_security_data.count_documents(candidate_query)
        graph_count = db.graph_metadata.count_documents(graph_query)
        if graph_count > 1:
            raise CommandError(f'Multiple graphs found for {source}; inspect duplicate metadata first.')
        if candidate_count and candidate_count != target:
            require_count(db.sampled_security_data, candidate_query, target, 'Candidates')
        if normalized_count == expected:
            # A changed chunk size must not silently select a different raw cohort.
            incompatible = db.normalized_security_data.count_documents({
                **normalized_query, 'normalization_sample_per_day': {'$exists': True, '$nin': [None, size]},
            })
            if incompatible:
                raise CommandError('Existing normalized chunk uses a different --sample-per-day; reuse its original chunk size.')
            skip(1, 'Normalize', f'{normalized_count} records already stored')
        elif candidate_count or graph_count:
            raise CommandError(f'Normalized chunk has {normalized_count}/{expected} records with downstream artifacts present. Refusing to overwrite its upstream data.')
        else:
            run(1, 'Normalize chunk', 'normalize_parquet_dataset', days=day, chunk_index=chunk,
                sample_per_day=size, batch_size=batch)
            require_count(db.normalized_security_data, normalized_query, expected, 'Normalization')

        if candidate_count:
            skip(2, 'Candidates', f'{candidate_count} records in current generation')
        else:
            if graph_count or db.graph_representatives.count_documents(graph_query):
                raise CommandError('Downstream graph/representatives exist without the expected candidate cohort. Refusing to replace their inputs.')
            run(2, 'Build candidates', 'build_clustered_candidates', day=day, chunk_index=chunk, count=expected)
            require_count(db.sampled_security_data, candidate_query, target, 'Candidates')

        ids = [str(doc['_id']) for doc in db.sampled_security_data.find(candidate_query, {'_id': 1}).sort('_id', 1)]
        if graph_count:
            graph = db.graph_metadata.find_one(graph_query)
            skip(3, 'Graph', f"stored parameters={graph.get('graph_parameters', {})}; CLI graph parameters apply only to new graphs")
        else:
            run(3, 'Build graph and components', 'build_candidate_similarity_graph', day=day, chunk_index=chunk,
                neighbors=options['neighbors'], threshold=options['threshold'], degree_cap=options['degree_cap'])
            graph = db.graph_metadata.find_one(graph_query)
        if not graph or graph.get('node_ids') != ids:
            raise CommandError('Graph node ordering differs from the requested candidate cohort; later stages were not run.')

        rep_target = max(1, int(len(ids) * ratio + .5))
        rep_count = db.graph_representatives.count_documents(graph_query)
        if rep_count:
            require_count(db.graph_representatives, graph_query, rep_target, 'Representatives')
            skip(4, 'Representatives', f'{rep_count} records already stored')
        else:
            run(4, 'Select representatives', 'build_day_representatives', day=day, chunk_index=chunk,
                stage='reps', ratio=ratio)
            require_count(db.graph_representatives, graph_query, rep_target, 'Representatives')

        # Always refresh documents, including reports introduced after an old run.
        run(5, 'Persist/evaluate components and render schematics', 'evaluate_graph_components', source_file=source)
        run(6, 'Verify component/representative integrity', 'verify_graph_components', source_file=source)
        run(7, 'Evaluate layer-1 component structure', 'evaluate_layer1_components', source_file=source)
        run(8, 'Evaluate component representative allocation', 'evaluate_layer1_component_allocation', source_file=source)
        run(9, 'Evaluate representatives', 'evaluate_representatives', source_file=source,
            chunk_index=chunk, skip_eigen=options['skip_eigen'])
        run(10, 'Visualize representatives', 'visualize_representatives', source_file=source)
        self.stdout.write(self.style.SUCCESS(f'[PIPELINE] ALL 10 STAGES COMPLETED for {source} in {time.perf_counter() - started:.1f}s'))
        for category in ('component', 'report', 'nominal'):
            self.stdout.write(f'[PIPELINE] {category}: {document_directory(category, source, day=day, chunk=chunk)}')
