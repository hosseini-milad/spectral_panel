"""Typed, version-pinned adapters for current candidate/component graphs."""
from dataclasses import dataclass
import hashlib
import json
import re

import numpy as np
from mongoengine import get_db

from hierarchy.services.component_hierarchy import source_fingerprints
from ingestion.services.graph.components import load_node_documents

FEATURES = ('bytes', 'packets', 'duration_s', 'bytes_per_packet', 'bytes_per_sec', 'packets_per_sec',
            'iat_mean', 'iat_std', 'iat_cv', 'payload_entropy', 'flag_ack', 'flag_syn', 'flag_fin',
            'flag_psh', 'flag_rst', 'flag_urg', 'is_encrypted_port', 'is_syn_only', 'proto_icmp', 'proto_tcp', 'proto_udp')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, allow_nan=False).encode()).hexdigest()


@dataclass
class GraphInput:
    key: str
    day: str
    layer: int
    chunk: object
    node_type: str
    node_ids: list
    edges: list
    features: np.ndarray
    feature_mask: np.ndarray
    feature_names: tuple
    source: dict
    block_lookup: object = None
    lineage: object = None

    @property
    def signature(self):
        return fingerprint({'key': self.key, 'node_ids': self.node_ids, 'edges': self.edges,
                            'source': self.source, 'features': self.features.tolist(),
                            'feature_mask': self.feature_mask.tolist(),
                            'blocks': sorted((sorted(part), value) for part, value in (self.block_lookup or {}).items())})


def feature_array(documents, component=False):
    values = np.zeros((len(documents), len(FEATURES)))
    mask = np.zeros_like(values, dtype=bool)
    for row, doc in enumerate(documents):
        for column, field in enumerate(FEATURES):
            if component:
                profile = (doc.get('numeric') or {}).get(field)
                behavior = (doc.get('behavior') or {}).get(field)
                value = profile.get('mean') if profile else (behavior.get('prevalence') if behavior else None)
            else:
                value = doc.get(field)
            try:
                value = float(value)
            except (TypeError, ValueError, OverflowError):
                continue
            if np.isfinite(value):
                values[row, column] = value; mask[row, column] = True
    return values, mask


def chunk_input(db, graph, day, expected_source=None):
    key = graph['source_file']
    if graph.get('component_status') not in (None, 'complete'):
        raise ValueError(f'{key}: component storage is not complete')
    if graph.get('status') in ('building', 'failed'):
        raise ValueError(f'{key}: graph is not complete')
    ids = list(graph.get('node_ids') or [])
    parts = list(db.graph_components.find({'source_file': key, 'layer': 1}))
    snapshot = source_fingerprints(graph, parts)
    if expected_source and any(expected_source.get(field) != value for field, value in snapshot.items()):
        raise ValueError(f'{key}: current chunk differs from the selected hierarchy run; rebuild hierarchy or select a consistent source run.')
    docs = load_node_documents(db, ids, 'sampled_security_data')
    if len(docs) != len(ids):
        raise ValueError(f'{key}: missing candidate feature records')
    lookup = {}
    for part in parts:
        indices = part.get('node_indices') or []
        if part.get('node_ids') != [ids[index] for index in indices] or part.get('node_count') != len(indices):
            raise ValueError(f'{key}: invalid persisted component membership')
        members = frozenset(indices)
        if members in lookup:
            raise ValueError(f'{key}: duplicate persisted component')
        lookup[members] = part['component_id']
    values, mask = feature_array([docs[value] for value in ids])
    chunk = int(re.search(r'-chunk-(\d+)$', key).group(1))
    source = {'collection': 'graph_metadata', 'document_id': str(graph['_id']), **snapshot,
              'graph_parameters': graph.get('graph_parameters') or {},
              'time_basis': 'processing_chunk_not_a_time_window'}
    lineage = [{'original_id': str(docs[value].get('original_id', value)), 'source_file': docs[value].get('source_file')} for value in ids]
    return GraphInput(key, day, 1, chunk, 'candidate_flow', ids, list(graph.get('edges') or []),
                      values, mask, FEATURES, source, lookup, lineage)


def hierarchy_input(db, run):
    key = run['source_file']
    nodes = list(db.component_hierarchy_nodes.find({'run_id': run['_id']}).sort('node_index', 1))
    if [row['node_index'] for row in nodes] != list(range(len(nodes))) or len(nodes) != run['component_count']:
        raise ValueError('Hierarchy node snapshot is incomplete or unordered')
    ids = [row['component_id'] for row in nodes]
    edges = [{field: row[field] for field in ('source', 'target', 'weight')}
             for row in db.component_hierarchy_edges.find({'run_id': run['_id']}).sort([('source', 1), ('target', 1)])]
    metas = list(db.meta_components.find({'run_id': run['_id']}))
    if len(metas) != run['meta_component_count']:
        raise ValueError('Hierarchy Meta-component snapshot is incomplete')
    lookup = {}
    for meta in metas:
        if meta['child_component_ids'] != [ids[index] for index in meta['node_indices']]:
            raise ValueError('Hierarchy Meta-component node order is invalid')
        members = frozenset(meta['node_indices'])
        if members in lookup:
            raise ValueError('Duplicate Meta-component partition')
        lookup[members] = meta['meta_component_id']
    features, mask = feature_array(nodes, component=True)
    source = {'collection': 'component_hierarchy_runs', 'hierarchy_run_id': run['_id'],
              'parameters': run.get('parameters'), 'input_digest': run.get('input_digest'),
              'time_basis': 'source_day_partition_no_inferred_temporal_edges'}
    lineage = [{'chunk_index': row['chunk_index'], 'source_file': row['source_file'],
                'component_id': row['component_id'], 'source_graph_revision': row.get('source_graph_revision')}
               for row in nodes]
    return GraphInput(key, run['source_day'], 2, None, 'layer1_component', ids, edges,
                      features, mask, FEATURES, source, lookup, lineage)


def load_inputs(day, scope='all', chunk_index=None, hierarchy_run_id=None):
    db = get_db()
    run = None
    if scope in ('all', 'components'):
        if hierarchy_run_id:
            run = db.component_hierarchy_runs.find_one({'_id': hierarchy_run_id, 'source_day': day, 'status': 'complete'})
        else:
            pointer = db.component_hierarchy_graphs.find_one({'_id': f'hierarchy-components-day-{day}-layer-2', 'status': 'complete'})
            if pointer:
                run = db.component_hierarchy_runs.find_one({'_id': pointer['active_run_id'], 'source_day': day, 'status': 'complete'})
        if not run:
            raise ValueError('No complete component hierarchy run; execute build_hierarchy_graph for the day first.')
    graphs = []
    if scope in ('all', 'chunks'):
        pattern = rf'^clustered-day-{re.escape(day)}-chunk-(\d+)$'
        metadata = list(db.graph_metadata.find({'source_file': {'$regex': pattern}}))
        if chunk_index is not None:
            metadata = [row for row in metadata if int(re.fullmatch(pattern, row['source_file']).group(1)) == chunk_index]
        keys = [row['source_file'] for row in metadata]
        if not keys or len(set(keys)) != len(keys):
            raise ValueError('No matching chunk graphs, or duplicate chunk keys')
        expected = {source['source_file']: source for source in run['sources']} if run else {}
        if run and set(keys) != set(expected):
            raise ValueError('Chunk set differs from the selected daily hierarchy snapshot')
        for row in sorted(metadata, key=lambda item: int(re.fullmatch(pattern, item['source_file']).group(1))):
            graphs.append(chunk_input(db, row, day, expected.get(row['source_file'])))
    if run:
        graphs.append(hierarchy_input(db, run))
    context = {'hierarchy_run_id': run['_id'] if run else None,
               'meta_component_count': run['meta_component_count'] if run else None,
               'raw_record_count': db.security_data.count_documents({'source_day': day})}
    return graphs, context
