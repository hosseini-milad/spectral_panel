from collections import Counter
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from ingestion.models.graph_metadata import GraphMetadata
from ingestion.models.graph_representative import GraphRepresentative
from ingestion.models.sampled_data import SampledSecurityData

FORBIDDEN = {
    '_id', 'original_id', 'source_file', 'source_day', 'source_path',
    'flow_start', 'timestamp', 'window_start', 'date', 'created_at',
    'label', 'label_binary', 'label_multiclass', 'source_label',
    'attack_category', 'attack_type', 'src_ip', 'dst_ip', 'row_index',
}

class Command(BaseCommand):
    help = 'Read-only audit of representative records before spectral graph construction.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--source-file', required=True)
        parser.add_argument('--expected-representatives', type=int, default=2000)

    def handle(self, *args, **opts):
        key = opts['source_file']
        graph = GraphMetadata.objects(source_file=key).order_by('-created_at').first()
        if graph is None:
            raise CommandError(f'Missing graph_metadata: {key}')
        query = {'source_day': graph.source_day} if graph.source_day else {'source_file': key}
        if graph.source_day:
            if graph.candidate_generation is not None:
                query['candidate_generation'] = graph.candidate_generation
            if graph.is_random is not None:
                query['isRandom'] = graph.is_random
        docs = list(SampledSecurityData.objects(__raw__=query).order_by('id').as_pymongo())
        reps = list(GraphRepresentative.objects(source_file=key).as_pymongo())
        self.stdout.write(f'[AUDIT] Graph node ids={len(graph.node_ids)}, sampled={len(docs)}, representatives={len(reps)}')
        issues = []
        if len(graph.node_ids) != len(docs):
            issues.append('Node count does not match sampled records')
        else:
            mismatches = [i for i, doc in enumerate(docs) if str(doc['_id']) != str(graph.node_ids[i])]
            self.stdout.write(f'[AUDIT] Graph node-order mismatches={len(mismatches)}; sample={mismatches[:10]}')
            if mismatches:
                issues.append('Graph node index / sampled record ID mismatch')
        if len(reps) != opts['expected_representatives']:
            issues.append('Representative count differs from expected count')
        index_counts = Counter(r.get('node_index') for r in reps)
        duplicate_indices = [n for n, count in index_counts.items() if count > 1]
        if duplicate_indices:
            issues.append(f'Duplicate representative indices: {duplicate_indices[:10]}')
        bad_mapping = []
        missing_time = []
        invalid_time = []
        selected_times = []
        for rep in reps:
            idx = rep.get('node_index')
            if not isinstance(idx, int) or not (0 <= idx < len(docs)):
                bad_mapping.append(idx)
                continue
            doc = docs[idx]
            if str(doc['_id']) != str(rep.get('original_id')):
                bad_mapping.append(idx)
            value = doc.get('flow_start')
            if value is None or value == '':
                missing_time.append(idx)
            elif isinstance(value, datetime):
                selected_times.append(value)
            elif isinstance(value, str):
                try:
                    selected_times.append(datetime.fromisoformat(value.replace('Z', '+00:00')))
                except ValueError:
                    invalid_time.append(idx)
            else:
                invalid_time.append(idx)
        self.stdout.write(f'[AUDIT] Invalid representative mappings={len(bad_mapping)}; sample={bad_mapping[:10]}')
        self.stdout.write(f'[AUDIT] flow_start missing={len(missing_time)}, unparsable={len(invalid_time)}, parsed={len(selected_times)}')
        if bad_mapping:
            issues.append('Representative original_id/node_index mismatch')
        if missing_time or invalid_time:
            issues.append('Selected representative records lack valid flow_start')
        fields = (graph.graph_parameters or {}).get('feature_fields', [])
        if not fields:
            fields = (graph.stats or {}).get('feature_fields', [])
        forbidden_present = sorted(FORBIDDEN.intersection(fields))
        self.stdout.write(f'[AUDIT] Feature count={len(fields)}, forbidden fields={forbidden_present}')
        if forbidden_present:
            issues.append(f'Forbidden feature fields in similarity graph: {forbidden_present}')
        if not fields:
            issues.append('Missing persisted feature field list')
        if selected_times:
            try:
                self.stdout.write(f'[AUDIT] flow_start range: {min(selected_times)} -> {max(selected_times)}')
            except TypeError:
                self.stdout.write('[AUDIT] flow_start contains mixed naive/timezone-aware datetimes; normalize timezones')
                issues.append('Mixed naive and timezone-aware flow_start')
        if issues:
            for issue in issues:
                self.stderr.write(self.style.ERROR(f'[AUDIT] FAIL: {issue}'))
            raise CommandError(f'Pre-spectral audit failed ({len(issues)} checks). No data was changed.')
        self.stdout.write(self.style.SUCCESS('[AUDIT] PASS: basic mappings, feature exclusions, and timestamps verified. No data was changed.'))
