"""Process one normalized day/chunk without requiring a legacy baseline graph.

Normalized records use ``normalization_chunk_index``; candidate records use
``chunk_index``. Each chunk's graph and representatives are keyed independently.
"""
from collections import Counter
import re

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from mongoengine import get_connection

from ingestion.models.graph_metadata import GraphMetadata
from ingestion.models.graph_representative import GraphRepresentative
from ingestion.models.graph_component import GraphComponent
from ingestion.models.sampled_data import SampledSecurityData
from ingestion.pipelines.pooling_pipeline import run_pooling
from ingestion.services.graph.candidate_graph import CANDIDATE_GENERATION


class Command(BaseCommand):
    help = 'Build candidates, cosine graph, or representatives for exactly one day/chunk.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--day', required=True, help='YYYY-MM-DD')
        parser.add_argument(
            '--chunk-index',
            type=int,
            default=None,
            help='Chunk index to process. If omitted, process all chunks for this day that already have graph metadata.',
        )
        parser.add_argument(
            '--stage',
            choices=('sample', 'graph', 'reps'),
            default='reps',
            help='Processing stage (default: reps)',
        )
        parser.add_argument('--ratio', type=float, default=0.10)
        parser.add_argument(
            '--force',
            action='store_true',
            help='Explicitly replace artifacts for THIS day/chunk and stage only',
        )

    def handle(self, *args, **opts):
        day = opts['day']
        chunk_index = opts['chunk_index']
        stage = opts['stage']

        if chunk_index is not None and chunk_index < 0:
            raise CommandError('--chunk-index must be >= 0.')

        # A day-only invocation processes each chunk that already has a graph.
        # This keeps the hierarchy inputs chunk-specific and avoids guessing
        # chunk indexes from candidate counts or legacy day-level graph keys.
        if chunk_index is None:
            db = get_connection(alias='default')['siem_db']
            pattern = re.compile(
                rf'^clustered-day-{re.escape(day)}-chunk-(\d+)$'
            )
            chunk_indexes = sorted({
                int(match.group(1))
                for doc in db['graph_metadata'].find(
                    {'source_file': {'$regex': pattern.pattern}},
                    {'source_file': 1},
                )
                for match in [pattern.fullmatch(doc.get('source_file', ''))]
                if match
            })
            if not chunk_indexes:
                raise CommandError(
                    f'No chunk-specific graphs found for day={day}. '
                    'Build candidate graphs first, or specify --chunk-index explicitly.'
                )

            self.stdout.write(
                f'[DAY] No --chunk-index supplied; found {len(chunk_indexes)} '
                f'graph chunks: {chunk_indexes}'
            )
            started = __import__('time').perf_counter()
            completed = []
            for current_chunk in chunk_indexes:
                self.stdout.write(
                    self.style.NOTICE(
                        f'\\n[DAY] Processing chunk {current_chunk} ({len(completed) + 1}/{len(chunk_indexes)})'
                    )
                )
                try:
                    call_command(
                        'build_day_representatives',
                        day=day,
                        chunk_index=current_chunk,
                        stage=stage,
                        ratio=opts['ratio'],
                        force=opts['force'],
                    )
                except Exception as exc:
                    raise CommandError(
                        f'Failed at chunk_index={current_chunk}; '
                        f'completed chunks={completed}. Cause: {exc}'
                    ) from exc
                completed.append(current_chunk)

            self.stdout.write(self.style.SUCCESS(
                f'[DAY] Completed stage={stage!r} for {len(completed)} chunks '
                f'in {__import__("time").perf_counter() - started:.1f}s: {completed}'
            ))
            return

        key = f'clustered-day-{day}-chunk-{chunk_index}'

        db = get_connection(alias='default')['siem_db']
        candidate_filter = {
            'source_day': day,
            'chunk_index': chunk_index,
            'candidate_generation': CANDIDATE_GENERATION,
            'isRandom': False,
        }
        normalized_filter = {
            'source_day': day,
            'normalization_chunk_index': chunk_index,
        }

        graph = GraphMetadata.objects(source_file=key).first()
        stored_reps = GraphRepresentative.objects(source_file=key).count()
        stored_components = GraphComponent.objects(source_file=key).count()
        candidate_count = db['sampled_security_data'].count_documents(candidate_filter)
        normalized_count = db['normalized_security_data'].count_documents(normalized_filter)

        self.stdout.write(
            f'[DAY] day={day} chunk_index={chunk_index} stage={stage} graph_key={key}'
        )
        self.stdout.write(
            f'[DAY] normalized_records={normalized_count}; candidates={candidate_count}; '
            f'graph={bool(graph)}; components={stored_components}; reps={stored_reps}'
        )

        if stage == 'sample':
            if normalized_count == 0:
                raise CommandError(
                    f'No normalized records found for source_day={day!r}, '
                    f'normalization_chunk_index={chunk_index}.'
                )
            if candidate_count and not opts['force']:
                raise CommandError(
                    'Candidates already exist for this day/chunk; use --force only to intentionally rebuild.'
                )
            if graph or stored_reps or stored_components:
                raise CommandError(
                    'Cannot rebuild candidates while this chunk has graph/representatives. '
                    'Remove downstream artifacts deliberately first.'
                )

            call_command(
                'build_clustered_candidates',
                day=day,
                chunk_index=chunk_index,
                count=normalized_count,
            )
            self.stdout.write(self.style.SUCCESS(
                '[DAY] Candidate sampling finished. Verify candidate count before graph stage.'
            ))
            return

        if stage == 'graph':
            if candidate_count == 0:
                raise CommandError(
                    'No clustered candidates found for this day/chunk; run --stage sample first.'
                )
            if graph and not opts['force']:
                raise CommandError(
                    'Graph already exists for this day/chunk. No replacement performed; '
                    '--force required to rebuild this stage.'
                )
            if stored_reps or stored_components:
                if not opts['force']:
                    raise CommandError(
                        'This chunk already has representatives/components; refusing to '
                        'rebuild its graph because their mappings would become stale. '
                        'Use --force to intentionally remove and rebuild downstream artifacts.'
                    )
                GraphRepresentative.objects(source_file=key).delete()
                GraphComponent.objects(source_file=key).delete()
                self.stdout.write(
                    self.style.WARNING(
                        '[DAY] Removed existing representatives/components before forced graph rebuild.'
                    )
                )

            # The graph command owns its defaults (neighbors, threshold, degree cap,
            # workers, and feature fields); keep this orchestration command in sync
            # with the requested minimal invocation.
            call_command(
                'build_candidate_similarity_graph',
                day=day,
                chunk_index=chunk_index,
            )
            graph = GraphMetadata.objects(source_file=key).first()
            if not graph:
                raise CommandError(
                    f'Graph command completed, but GraphMetadata source_file={key!r} was not found. '
                    'Check that build_candidate_similarity_graph stores the chunk-specific key.'
                )

            self.stdout.write(self.style.SUCCESS(
                f'[DAY] Graph built: nodes={len(graph.node_ids)}, edges={len(graph.edges)}'
            ))
            return

        if not 0 < opts['ratio'] < 1:
            raise CommandError('ratio must lie strictly between 0 and 1')
        if not graph:
            raise CommandError(
                f'Graph not found for source_file={key!r}; run --stage graph first. '
                'A legacy whole-day graph is not used as an implicit baseline.'
            )
        if (stored_reps or stored_components) and not opts['force']:
            raise CommandError(
                'Representatives or components already exist for this day/chunk; '
            'no overwrite performed.'
            )

        docs = list(
            SampledSecurityData.objects(__raw__=candidate_filter)
            .order_by('id')
            .as_pymongo()
        )
        if not docs:
            raise CommandError(
                f'No candidate records found for source_day={day!r}, chunk_index={chunk_index}.'
            )

        ids = [str(doc['_id']) for doc in docs]
        if ids != list(graph.node_ids):
            raise CommandError(
                'Graph node_ids do not match sampled record IDs for this day/chunk in order; '
                'stopping to avoid invalid representatives.'
            )

        # Raw categorical descriptors are fetched from security_data. The sampled
        # normalized documents contain encoded categorical values, which must not
        # be treated as original category labels in component frequency profiles.
        raw_ids = [doc["_id"] for doc in docs]
        raw_projection = {
            "_id": 1,
            "protocol": 1,
            "src_port_category": 1,
            "dst_port_category": 1,
            "flow_duration_class": 1,
        }
        raw_docs = list(
            db["security_data"].find(
                {"_id": {"$in": raw_ids}},
                raw_projection,
            )
        )
        raw_docs_by_id = {str(doc["_id"]): doc for doc in raw_docs}

        labels = {i: int(doc.get('label', 0) or 0) for i, doc in enumerate(docs)}
        if not all(label in (0, 1) for label in labels.values()):
            raise CommandError('Non-binary label found; verify source data.')

        attack_ratio = sum(label == 1 for label in labels.values()) / len(labels)
        self.stdout.write(
            f'[DAY] Starting reps: day={day}; chunk_index={chunk_index}; '
            f'nodes={len(docs)}; edges={len(graph.edges)}; attack_ratio={attack_ratio:.4f}'
        )

        reps = run_pooling(
            source_file=key,
            edges=graph.edges,
            features=graph.features,
            docs=docs,
            feature_fields=(graph.graph_parameters or {}).get("feature_fields", []),
            raw_docs_by_id=raw_docs_by_id,
            ratio=opts['ratio'],
            labels=labels,
            attack_ratio=attack_ratio,
            create_visualization=False,
        )
        component_count = GraphComponent.objects(source_file=key).count()
        stored_rep_count = GraphRepresentative.objects(source_file=key).count()
        if component_count == 0:
            raise CommandError(
                "Pooling returned representatives but no GraphComponent documents were saved."
            )
        if stored_rep_count != len(reps):
            raise CommandError(
                f"Representative persistence mismatch: returned={len(reps)}, "
                f"stored={stored_rep_count}."
            )

        component_ids = set(
            GraphComponent.objects(source_file=key).distinct("component_id")
        )
        orphan_reps = GraphRepresentative.objects(
            source_file=key,
            component_id__nin=list(component_ids),
        ).count()
        if orphan_reps:
            raise CommandError(
                f"Found {orphan_reps} representatives with missing component references."
            )

        labels_out = dict(Counter(int(rep['label']) for rep in reps))
        self.stdout.write(self.style.SUCCESS(
            f'[DAY] SUCCESS day={day}; chunk_index={chunk_index}; '
            f'graph_nodes={len(docs)}; edges={len(graph.edges)}; '
            f'stored_components={GraphComponent.objects(source_file=key).count()}; '
            f'stored_reps={GraphRepresentative.objects(source_file=key).count()}; '
            f'label_counts={labels_out}'
        ))
