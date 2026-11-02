"""Versioned layer-2 graphs whose nodes are complete layer-1 components."""
import hashlib
import heapq
import json
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone

import networkx as nx
import numpy as np
from bson import BSON
from mongoengine import get_db
from scipy.special import rel_entr

from ingestion.services.graph.components import build_component_graph, load_node_documents

NUMERIC = ('bytes', 'packets', 'duration_s', 'bytes_per_packet', 'bytes_per_sec',
           'packets_per_sec', 'iat_mean', 'iat_std', 'iat_cv', 'payload_entropy',
           'log_bytes', 'log_packets', 'log_duration')
CATEGORICAL = ('protocol', 'src_port_category', 'dst_port_category', 'flow_duration_class')
BEHAVIOR = ('flag_ack', 'flag_syn', 'flag_fin', 'flag_psh', 'flag_rst', 'flag_urg',
            'is_encrypted_port', 'is_syn_only', 'proto_icmp', 'proto_tcp', 'proto_udp')
QUANTILES = np.array([0., .1, .25, .5, .75, .9, 1.])
WEIGHTS = {'numeric': .60, 'categorical': .25, 'behavior': .15}
VERSION = 'component_distribution_mutual_knn_v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, allow_nan=False).encode()).hexdigest()


def finite_values(docs, field):
    values = []
    for doc in docs:
        try:
            value = float(doc[field])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if np.isfinite(value):
            values.append(value)
    return np.asarray(values, dtype=float)


def source_fingerprints(graph, components):
    return {
        'graph_fingerprint': digest({field: graph.get(field) for field in
                                     ('_id', 'source_file', 'component_revision', 'node_ids', 'edges')}),
        'membership_fingerprint': digest(sorted([
            {field: row.get(field) for field in ('component_id', 'graph_revision', 'node_ids', 'node_indices')}
            for row in components], key=lambda row: row['component_id'])),
    }


def load_components(db, day):
    """Read-only audit of every source graph and membership before building."""
    pattern = rf'^clustered-day-{re.escape(day)}-chunk-(\d+)$'
    graphs = list(db.graph_metadata.find({'source_file': {'$regex': pattern}}))
    if not graphs:
        raise ValueError(f'No layer-1 chunk graphs for {day}; run hyper-general-action first.')
    by_chunk = {}
    for graph in graphs:
        index = int(re.fullmatch(pattern, graph['source_file']).group(1))
        if index in by_chunk:
            raise ValueError(f'Duplicate graph metadata for chunk {index}')
        if graph.get('component_status') not in (None, 'complete'):
            raise ValueError(f"Incomplete component storage: {graph['source_file']}")
        if graph.get('status') in ('building', 'failed'):
            raise ValueError(f"Incomplete source graph: {graph['source_file']}")
        by_chunk[index] = graph
    sizes = [value for value in db.normalized_security_data.distinct(
        'normalization_sample_per_day', {'source_day': day}) if value is not None]
    if len(sizes) > 1:
        raise ValueError('Mixed normalization chunk sizes for this day; resolve source partitioning first.')
    raw_count = db.security_data.count_documents({'source_day': day})
    expected = (raw_count + sizes[0] - 1) // sizes[0] if raw_count and sizes else max(by_chunk) + 1
    if set(by_chunk) != set(range(expected)):
        raise ValueError(f'Incomplete day graphs; expected chunks 0..{expected - 1}, found {sorted(by_chunk)}')
    nodes, sources, used_ids, used_originals = [], [], set(), set()
    for chunk, graph in sorted(by_chunk.items()):
        source = graph['source_file']
        if not graph.get('node_ids'):
            raise ValueError(f'Empty source graph: {source}')
        components = list(db.graph_components.find({'source_file': source, 'layer': 1}))
        components.sort(key=lambda row: (row['component_index'], row['component_id']))
        g = build_component_graph(graph.get('node_ids', []), graph.get('edges', []))
        expected_partition = {frozenset(part) for part in nx.connected_components(g)}
        actual = [frozenset(row.get('node_indices', [])) for row in components]
        if set(actual) != expected_partition or len(set(actual)) != len(components):
            raise ValueError(f'Invalid/missing connected-component partition: {source}')
        if sum(len(part) for part in actual) != len(graph['node_ids']):
            raise ValueError(f'Duplicate component membership: {source}')
        source_docs = load_node_documents(db, graph['node_ids'], 'sampled_security_data')
        if len(source_docs) != len(graph['node_ids']):
            raise ValueError(f'Missing sampled member documents in {source}; repair source data first.')
        raw_ids = [str(doc.get('original_id', doc['_id'])) for doc in source_docs.values()]
        raw_docs = load_node_documents(db, raw_ids, 'security_data')
        sources.append({'source_file': source, 'chunk_index': chunk,
                        'graph_id': str(graph['_id']), 'revision': graph.get('component_revision'),
                        'node_count': len(graph['node_ids']), 'component_count': len(components),
                        **source_fingerprints(graph, components)})
        for component in components:
            if (graph.get('component_revision') and component.get('graph_revision')
                    and graph['component_revision'] != component['graph_revision']):
                raise ValueError(f'Stale source component revision in {source}')
            indices, ids = component['node_indices'], component['node_ids']
            if len(ids) != component['node_count'] or ids != [graph['node_ids'][i] for i in indices]:
                raise ValueError(f"Invalid index/ID mapping: {component['component_id']}")
            if component['component_id'] in used_ids:
                raise ValueError('Duplicate component identity')
            used_ids.add(component['component_id'])
            docs = [source_docs[value] for value in ids]
            originals = [str(doc.get('original_id', doc['_id'])) for doc in docs]
            if len(set(originals)) != len(originals) or used_originals.intersection(originals):
                raise ValueError('Overlapping original candidate records across source components')
            used_originals.update(originals)
            numeric = {}
            for field in NUMERIC:
                values = finite_values(docs, field)
                if len(values) < .8 * len(docs):
                    continue
                if np.any(values < -1e-8) or np.any(values > 1 + 1e-8):
                    raise ValueError(f'{source}: {field} must contain normalized values in [0, 1]')
                numeric[field] = {'count': len(values), 'mean': float(values.mean()),
                                  'std': float(values.std()), 'quantiles': np.quantile(values, QUANTILES).tolist()}
            if len(numeric) < 3:
                raise ValueError(f"Component {component['component_id']} has fewer than 3 sufficiently observed numeric fields")
            raw = [raw_docs[value] for value in originals if value in raw_docs]
            categories = {field: dict(Counter(str(doc[field]) for doc in raw
                                              if doc.get(field) not in (None, ''))) for field in CATEGORICAL}
            categories = {field: counts if sum(counts.values()) >= .8 * len(docs) else {}
                          for field, counts in categories.items()}
            behavior = {}
            for field in BEHAVIOR:
                values = finite_values(docs, field)
                if len(values) >= .8 * len(docs):
                    behavior[field] = {'count': len(values), 'present': int(np.sum(values > .5)),
                                       'prevalence': float(np.mean(values > .5))}
            nodes.append({'node_index': len(nodes), 'component_id': component['component_id'],
                          'source_file': source, 'source_day': day, 'chunk_index': chunk,
                          'component_index': component['component_index'], 'node_count': len(ids),
                          'source_component_collection': 'graph_components',
                          'member_node_collection': 'sampled_security_data', 'member_original_collection': 'security_data',
                          'member_node_ids': ids, 'member_node_indices': indices, 'member_original_ids': originals,
                          'source_graph_revision': graph.get('component_revision'),
                          'source_component_revision': component.get('graph_revision'),
                          'representative_count': component.get('representative_count', 0),
                          'numeric': numeric, 'categorical': categories, 'behavior': behavior,
                          'structure': component.get('component_statistics', {}),
                          'missing_raw_count': len(docs) - len(raw)})
    return nodes, sources, {'raw_day_records': raw_count,
                            'trailing_chunk_completeness_verified': bool(raw_count and sizes)}


class Similarity:
    """Vectorized one-to-many component-distribution comparisons; no N x N matrix."""
    def __init__(self, nodes):
        self.nodes = nodes
        n, f, q = len(nodes), len(NUMERIC), len(QUANTILES)
        self.quantiles = np.zeros((n, f, q))
        self.present = np.zeros((n, f), dtype=bool)
        for i, node in enumerate(nodes):
            for j, field in enumerate(NUMERIC):
                if field in node['numeric']:
                    self.present[i, j] = True
                    self.quantiles[i, j] = node['numeric'][field]['quantiles']
        # Common full-day candidate-population scales, not independent component scales.
        self.scales = np.ones(f)
        self.active = np.zeros(f, dtype=bool)
        for j, field in enumerate(NUMERIC):
            valid = np.flatnonzero(self.present[:, j])
            if not len(valid):
                continue
            counts = np.array([nodes[i]['numeric'][field]['count'] for i in valid])
            values = self.quantiles[valid, j].reshape(-1)
            weights = np.repeat(counts / len(QUANTILES), len(QUANTILES))
            order = np.argsort(values, kind='stable')
            cumulative = np.cumsum(weights[order]) / weights.sum()
            low, high = np.interp([.25, .75], cumulative, values[order])
            span = float(values.max() - values.min())
            self.active[j] = bool(np.max(np.ptp(self.quantiles[valid, j], axis=0)) > 1e-10)
            self.scales[j] = max(float(high - low), span * .05, 1e-10)
        self.behavior = np.full((n, len(BEHAVIOR)), np.nan)
        for i, node in enumerate(nodes):
            for j, field in enumerate(BEHAVIOR):
                if field in node['behavior']:
                    self.behavior[i, j] = node['behavior'][field]['prevalence']
        self.categories = []
        self.excluded_categorical_fields = []
        for field in CATEGORICAL:
            vocabulary = sorted({key for node in nodes for key in node['categorical'][field]})
            if len(vocabulary) > 128:
                self.excluded_categorical_fields.append(field)
                continue
            matrix = np.array([[node['categorical'][field].get(key, 0) for key in vocabulary] for node in nodes], dtype=float)
            if not vocabulary:
                continue
            counts = matrix.sum(axis=1)
            matrix = np.divide(matrix, counts[:, None], out=np.zeros_like(matrix), where=counts[:, None] > 0)
            self.categories.append((matrix, counts > 0))

    def compare(self, i, targets):
        targets = np.asarray(targets, dtype=int)
        shared = self.present[targets] & self.present[i]
        observed = shared.sum(axis=1)
        active = shared & self.active
        distances = np.trapezoid(np.abs(self.quantiles[targets] - self.quantiles[i]), QUANTILES, axis=2)
        distances = np.clip(distances / self.scales, 0, 1)
        numeric = 1 - np.divide((distances * active).sum(axis=1), active.sum(axis=1),
                                out=np.zeros(len(targets)), where=active.sum(axis=1) > 0)
        numeric_ok = (observed >= 3) & ((active.sum(axis=1) > 0) | (not np.any(self.active)))
        behavior_shared = np.isfinite(self.behavior[targets]) & np.isfinite(self.behavior[i])
        bd = np.nan_to_num(np.abs(self.behavior[targets] - self.behavior[i]))
        bcount = behavior_shared.sum(axis=1)
        behavior = 1 - np.divide((bd * behavior_shared).sum(axis=1), bcount,
                                 out=np.zeros(len(targets)), where=bcount > 0)
        category_sum, category_count = np.zeros(len(targets)), np.zeros(len(targets))
        for matrix, available in self.categories:
            if not available[i]:
                continue
            mixture = (matrix[targets] + matrix[i]) / 2
            js = .5 * (rel_entr(matrix[targets], mixture).sum(axis=1) + rel_entr(matrix[i], mixture).sum(axis=1))
            category_sum += (1 - np.sqrt(np.clip(js / np.log(2), 0, 1))) * available[targets]
            category_count += available[targets]
        categorical = np.divide(category_sum, category_count, out=np.zeros(len(targets)), where=category_count > 0)
        coverage = .6 * numeric_ok + .25 * (category_count > 0) + .15 * (bcount > 0)
        score = np.divide(.6 * numeric * numeric_ok + .25 * categorical * (category_count > 0)
                          + .15 * behavior * (bcount > 0), coverage,
                          out=np.zeros(len(targets)), where=coverage > 0)
        valid = numeric_ok  # Never connect solely because both inputs lack data.
        return score, valid, {'numeric': numeric, 'categorical': categorical, 'behavior': behavior,
                              'categorical_available': category_count > 0, 'behavior_available': bcount > 0,
                              'available_weight': coverage, 'shared_numeric_fields': observed}


def component_graph(nodes, similarity, threshold=.85, neighbors=8, degree_cap=12, progress=None):
    n = len(nodes)
    nearest = [[] for _ in nodes]
    histogram = np.zeros(100, dtype=int)
    sensitivities = {str(value): 0 for value in (.75, .8, .85, .9, .95)}
    compared = qualifying = 0
    for i in range(n):
        targets = np.arange(i + 1, n)
        scores, valid, _ = similarity.compare(i, targets)
        values = scores[valid]
        compared += len(values)
        histogram += np.histogram(values, bins=np.linspace(0, 1, 101))[0]
        for value in sensitivities:
            sensitivities[value] += int(np.sum(values >= float(value)))
        for j, score in zip(targets[valid & (scores >= threshold)], scores[valid & (scores >= threshold)]):
            qualifying += 1
            for left, right in ((i, int(j)), (int(j), i)):
                item = (float(score), -right)
                if len(nearest[left]) < neighbors:
                    heapq.heappush(nearest[left], item)
                elif item > nearest[left][0]:
                    heapq.heapreplace(nearest[left], item)
        if progress and (i % 100 == 0 or i == n - 1):
            progress(f'Compared rows {i + 1}/{n}; qualifying pairs={qualifying}')
    selections = [{-other for _, other in row} for row in nearest]
    pairs = {(i, j) for i, choices in enumerate(selections) for j in choices if i < j and i in selections[j]}
    # Resolve exact descriptor ties without isolating every node beyond the first k.
    duplicates = defaultdict(list)
    for i, node in enumerate(nodes):
        signature = {
            'numeric': {field: profile['quantiles'] for field, profile in node['numeric'].items()},
            'categorical': {field: {key: count / sum(counts.values()) for key, count in counts.items()}
                            for field, counts in node['categorical'].items()},
            'behavior': {field: profile['prevalence'] for field, profile in node['behavior'].items()},
        }
        duplicates[digest(signature)].append(i)
    ring = set()
    for group in duplicates.values():
        if len(group) > 1:
            ring.update(tuple(sorted((group[i], group[(i + 1) % len(group)]))) for i in range(len(group)))
    graph = nx.Graph()
    graph.add_nodes_from(range(n))
    def add(left, right, score, families, offset, reason):
        if graph.degree(left) < degree_cap and graph.degree(right) < degree_cap:
            graph.add_edge(left, right, weight=float(score),
                           selection_reason=reason,
                           numeric_similarity=float(families['numeric'][offset]),
                           categorical_similarity=(float(families['categorical'][offset]) if families['categorical_available'][offset] else None),
                           behavior_similarity=(float(families['behavior'][offset]) if families['behavior_available'][offset] else None),
                           shared_numeric_fields=int(families['shared_numeric_fields'][offset]),
                           available_weight=float(families['available_weight'][offset]))
    for left, right in sorted(ring):
        score, valid, details = similarity.compare(left, [right])
        if valid[0] and score[0] >= threshold:
            add(left, right, score[0], details, 0, 'duplicate_descriptor_ring')
    candidates = []
    for left, right in sorted(pairs - ring):
        score, valid, details = similarity.compare(left, [right])
        if valid[0]:
            candidates.append((float(score[0]), left, right, details))
    for score, left, right, details in sorted(candidates, key=lambda row: (-row[0], row[1], row[2])):
        add(left, right, score, details, 0, 'mutual_knn')
    return graph, {'possible_pairs': n * (n - 1) // 2, 'comparable_pairs': compared,
                   'threshold_qualifying_pairs': qualifying, 'mutual_knn_pairs': len(pairs),
                   'duplicate_ring_pairs': len(ring), 'histogram_counts': histogram.tolist(),
                   'mutual_pairs_dropped_by_cap': len(pairs - {tuple(sorted(edge)) for edge in graph.edges()}),
                   'retained_ring_edges': sum(data['selection_reason'] == 'duplicate_descriptor_ring' for _, _, data in graph.edges(data=True)),
                   'histogram_bins': np.linspace(0, 1, 101).tolist(), 'threshold_sensitivity': sensitivities}


def meta_components(nodes, graph, similarity, key, threshold):
    result = []
    for index, group in enumerate(sorted((sorted(part) for part in nx.connected_components(graph)), key=lambda part: (-len(part), part[0]))):
        children = [nodes[i] for i in group]
        sub = graph.subgraph(group)
        below = count = 0
        minimum, total = None, 0.
        for offset, left in enumerate(group):
            values, valid, _ = similarity.compare(left, group[offset + 1:])
            values = values[valid]
            if len(values):
                minimum = min(minimum if minimum is not None else 1., float(values.min()))
                total += float(values.sum()); count += len(values); below += int(np.sum(values < threshold))
        numeric = {}
        for field in NUMERIC:
            profiles = [node['numeric'][field] for node in children if field in node['numeric']]
            observations = sum(row['count'] for row in profiles)
            if observations:
                mean = sum(row['count'] * row['mean'] for row in profiles) / observations
                variance = sum(row['count'] * (row['std'] ** 2 + (row['mean'] - mean) ** 2) for row in profiles) / observations
                numeric[field] = {'count': observations, 'mean': mean, 'std': float(np.sqrt(max(0., variance))),
                                  'min': min(row['quantiles'][0] for row in profiles),
                                  'max': max(row['quantiles'][-1] for row in profiles)}
        categories = {}
        for field in CATEGORICAL:
            counts = Counter()
            for node in children:
                counts.update(node['categorical'][field])
            categories[field] = dict(counts)
        behavior = {}
        for field in BEHAVIOR:
            profiles = [node['behavior'][field] for node in children if field in node['behavior']]
            observations = sum(profile['count'] for profile in profiles)
            present = sum(profile['present'] for profile in profiles)
            if observations:
                behavior[field] = {'count': observations, 'present': present, 'prevalence': present / observations}
        child_ids = [node['component_id'] for node in children]
        result.append({'meta_component_id': digest([key, sorted(child_ids)])[:24], 'meta_index': index,
                       'source_file': key, 'child_component_collection': 'graph_components',
                       'node_indices': group, 'child_component_ids': child_ids,
                       'component_count': len(group), 'member_node_count': sum(node['node_count'] for node in children),
                       'source_chunks': sorted({node['chunk_index'] for node in children}),
                       'numeric': numeric, 'categorical': categories, 'behavior': behavior,
                       'internal_edges': sub.number_of_edges(), 'density': nx.density(sub),
                       'bridge_count': sum(1 for _ in nx.bridges(sub)),
                       'pair_similarity_min': minimum, 'pair_similarity_mean': total / count if count else None,
                       'comparable_internal_pairs': count, 'below_threshold_pairs': below,
                       'uncomparable_internal_pairs': len(group) * (len(group) - 1) // 2 - count,
                       'chaining_warning': bool(below), 'singleton': len(group) == 1})
    return result


def build_hierarchy(day, *, force=False, threshold=.85, neighbors=8, degree_cap=12, progress=None, render_reports=True):
    if not 0 <= threshold <= 1 or neighbors < 1 or degree_cap < 2:
        raise ValueError('Require threshold in [0, 1], neighbors >= 1, degree_cap >= 2')
    db = get_db()
    key = f'hierarchy-components-day-{day}-layer-2'
    previous = db.component_hierarchy_graphs.find_one({'_id': key})
    if previous and not force:
        raise ValueError(f'{key} exists; use --force to create a new version (previous runs are retained).')
    nodes, sources, coverage = load_components(db, day)
    similarity = Similarity(nodes)
    graph, diagnostics = component_graph(nodes, similarity, threshold, neighbors, degree_cap, progress)
    if progress:
        progress(f'[META] Grouping {len(nodes)} components and evaluating internal similarities...')
    metas = meta_components(nodes, graph, similarity, key, threshold)
    if sorted(i for meta in metas for i in meta['node_indices']) != list(range(len(nodes))):
        raise ValueError('Meta-component partition is incomplete')
    run_id = uuid.uuid4().hex
    evaluation = {
        'schema_version': VERSION, 'source_file': key, 'source_day': day, 'run_id': run_id,
        'population_scope': 'layer1_graph_candidate_nodes_not_unsampled_raw_flows',
        'node_type': 'layer1_component', 'meta_definition': 'connected_components_in_sparse_component_similarity_graph',
        'parameters': {'threshold': threshold, 'neighbors': neighbors, 'degree_cap': degree_cap,
                       'family_weights': WEIGHTS, 'minimum_shared_numeric_fields': 3,
                       'numeric_method': 'quantile_integral_distance_with_shared_day_candidate_scale',
                       'scale_estimation': 'candidate_count_weighted_quantile_grid_approximation',
                       'categorical_method': 'one_minus_sqrt_JS_divergence',
                       'behavior_method': 'one_minus_mean_prevalence_difference',
                       'edge_policy': 'mutual_knn_with_exact_descriptor_duplicate_ring_and_degree_cap'},
        'chunk_count': len(sources), 'component_count': len(nodes),
        'candidate_node_count': sum(node['node_count'] for node in nodes),
        'components_without_representatives': sum(node['representative_count'] == 0 for node in nodes),
        'edge_count': graph.number_of_edges(), 'density': nx.density(graph),
        'max_degree': max(dict(graph.degree()).values(), default=0),
        'meta_component_count': len(metas), 'singleton_meta_components': sum(meta['singleton'] for meta in metas),
        'cross_chunk_meta_components': sum(len(meta['source_chunks']) > 1 for meta in metas),
        'cross_chunk_edges': sum(nodes[a]['chunk_index'] != nodes[b]['chunk_index'] for a, b in graph.edges()),
        'cross_chunk_component_fraction': sum(meta['component_count'] for meta in metas if len(meta['source_chunks']) > 1) / len(nodes),
        'largest_meta_component_fraction': max(meta['component_count'] for meta in metas) / len(nodes),
        'meta_components_with_unknown_pair_evidence': sum(meta['uncomparable_internal_pairs'] > 0 for meta in metas),
        'missing_raw_member_count': sum(node['missing_raw_count'] for node in nodes),
        'components_with_categorical_data': sum(any(node['categorical'][field] for field in CATEGORICAL) for node in nodes),
        'excluded_high_cardinality_categorical_fields': similarity.excluded_categorical_fields,
        'numeric_scales': dict(zip(NUMERIC, similarity.scales.tolist())),
        'active_numeric_fields': [field for field, active in zip(NUMERIC, similarity.active) if active],
        'integrity': {'all_components_assigned_once': True, 'all_candidate_nodes_traced': True,
                      'degree_cap_respected': all(degree <= degree_cap for _, degree in graph.degree())},
        'sources': sources, 'diagnostics': diagnostics, 'meta_components': metas, **coverage,
        'limitations': ['Threshold and family weights are experimental and require sensitivity analysis.',
                       'Quantile distances approximate distributions; stored signatures are not full empirical distributions.',
                       'Missing categorical families are excluded and remaining family weights renormalized.',
                       'Chunk order is processing order, not a claim of temporal or causal adjacency.',
                       'Connected meta-components may contain weakly similar pairs connected through a chain.'],
    }
    evaluation['warnings'] = []
    if evaluation['components_with_categorical_data'] < len(nodes):
        evaluation['warnings'].append('Some components have insufficient categorical coverage; missing families were excluded, not zero-filled.')
    if not coverage['trailing_chunk_completeness_verified']:
        evaluation['warnings'].append('Trailing day completeness could not be checked against raw count and normalization chunk size.')
    if not np.any(similarity.active):
        evaluation['warnings'].append('No varying numeric fields across component quantile signatures; inspect whether data or scaling is degenerate.')
    if similarity.excluded_categorical_fields:
        evaluation['warnings'].append('Categorical fields with more than 128 distinct values were omitted from similarity to bound memory usage.')
    run = {'_id': run_id, 'source_file': key, 'source_day': day, 'status': 'building',
           'parameters': evaluation['parameters'], 'sources': sources,
           'created_at': datetime.now(timezone.utc), 'input_digest': digest(sources),
           'evaluation_snapshot': {key: value for key, value in evaluation.items() if key != 'meta_components'}}
    db.component_hierarchy_runs.insert_one(run)
    try:
        if progress:
            progress('[META] Writing versioned graph and Meta-components to MongoDB...')
        for collection, rows in [('component_hierarchy_nodes', nodes),
                                 ('component_hierarchy_edges', [dict(source=a, target=b, **data) for a, b, data in graph.edges(data=True)]),
                                 ('meta_components', metas)]:
            for offset in range(0, len(rows), 500):
                batch = [dict(row, run_id=run_id, hierarchy_graph_key=key, source_day=day, layer=2) for row in rows[offset:offset + 500]]
                if any(len(BSON.encode(row)) >= 16 * 1024 * 1024 for row in batch):
                    raise ValueError('A hierarchy record exceeds the MongoDB document limit')
                if batch:
                    db[collection].insert_many(batch)
            db[collection].create_index([('run_id', 1)])
        paths = {}
        if render_reports:
            from hierarchy.services.component_hierarchy_report import write_reports
            if progress:
                progress(f'[META] Rendering static diagrams and metric tables ({len(nodes)} graph nodes); no HTML or lineage pages...')
            paths = write_reports(evaluation, nodes, graph)
        if progress:
            progress('[META] Verifying source versions before publishing the run...')
        for source in sources:
            matches = list(db.graph_metadata.find({'source_file': source['source_file']}))
            current = matches[0] if len(matches) == 1 else None
            components = list(db.graph_components.find({'source_file': source['source_file'], 'layer': 1}))
            if not current or any(source[field] != value for field, value in source_fingerprints(current, components).items()):
                raise ValueError(f"Source graph/components changed during build: {source['source_file']}; retry after upstream work finishes")
        db.component_hierarchy_runs.update_one({'_id': run_id}, {'$set': {
            'status': 'complete', 'completed_at': datetime.now(timezone.utc),
            'paths': paths, 'component_count': len(nodes), 'meta_component_count': len(metas),
            'parameters': evaluation['parameters'], 'integrity': evaluation['integrity']}})
        pointer = {'source_day': day, 'node_type': 'layer1_component', 'active_run_id': run_id,
                   'status': 'complete', 'schema_version': VERSION, 'paths': paths}
        if previous:
            result = db.component_hierarchy_graphs.update_one({'_id': key, 'active_run_id': previous['active_run_id']}, {'$set': pointer})
            if result.modified_count != 1:
                raise ValueError('Another build changed the active run; this run was not published')
        else:
            db.component_hierarchy_graphs.insert_one(dict(pointer, _id=key))
        return evaluation, paths
    except Exception as exc:
        db.component_hierarchy_runs.update_one({'_id': run_id}, {'$set': {'status': 'failed', 'error': str(exc)}})
        raise
