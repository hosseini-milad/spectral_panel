"""Evaluate immutable daily snapshots; never rebuild or replace the source graph."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

import networkx as nx
import numpy as np
from mongoengine import get_db

from .component_hierarchy import Similarity, digest, CATEGORICAL
from .hierarchy_metrics import build_metrics_table
from .component_hierarchy_report import write_reports


def snapshot(db, run_id):
    query = {'run_id': run_id}
    nodes = list(db.component_hierarchy_nodes.find(query).sort('node_index', 1))
    edges = list(db.component_hierarchy_edges.find(query).sort([('source', 1), ('target', 1)]))
    metas = list(db.meta_components.find(query).sort('meta_index', 1))
    return nodes, edges, metas


def pair_diagnostics(nodes, threshold, progress=None):
    similarity = Similarity(nodes); histogram = np.zeros(100, dtype=int); compared = qualifying = 0
    for i in range(len(nodes)):
        scores, valid, _ = similarity.compare(i, np.arange(i + 1, len(nodes)))
        scores = scores[valid]; compared += len(scores); qualifying += int(np.sum(scores >= threshold))
        histogram += np.histogram(scores, bins=np.linspace(0, 1, 101))[0]
        if progress and (i % 100 == 0 or i + 1 == len(nodes)):
            progress(f'[HIER-EVAL] Pair diagnostics {i + 1}/{len(nodes)} (legacy snapshot without diagnostics).')
    return dict(possible_pairs=len(nodes) * (len(nodes)-1)//2, comparable_pairs=compared,
                threshold_qualifying_pairs=qualifying, histogram_counts=histogram.tolist(),
                histogram_bins=np.linspace(0, 1, 101).tolist())


def evaluate_hierarchy(day, *, run_id=None, progress=None):
    db = get_db(); key = f'hierarchy-components-day-{day}-layer-2'
    if run_id is None:
        pointer = db.component_hierarchy_graphs.find_one({'_id': key, 'status': 'complete'})
        run_id = pointer['active_run_id'] if pointer else None
    run = db.component_hierarchy_runs.find_one({'_id': run_id, 'source_day': day, 'status': 'complete'})
    if not run or run['source_file'] != key:
        raise ValueError('No complete daily component graph; run build_hierarchy_graph first or select a valid --run-id.')
    nodes, edges, metas = snapshot(db, run_id); initial_digest = digest([nodes, edges, metas])
    if not nodes or [row['node_index'] for row in nodes] != list(range(run['component_count'])):
        raise ValueError('Incomplete or unordered hierarchy node snapshot')
    if len({row['component_id'] for row in nodes}) != len(nodes):
        raise ValueError('Duplicate input component IDs')
    if [row['meta_index'] for row in metas] != list(range(run['meta_component_count'])):
        raise ValueError('Incomplete or unordered Meta-component snapshot')
    graph = nx.Graph(); graph.add_nodes_from(range(len(nodes)))
    for edge in edges:
        a, b, weight = edge['source'], edge['target'], edge['weight']
        if not isinstance(a, int) or not isinstance(b, int) or a == b or not 0 <= a < len(nodes) or not 0 <= b < len(nodes) or graph.has_edge(a, b) or not np.isfinite(weight) or weight <= 0:
            raise ValueError('Invalid/duplicated stored hierarchy edge')
        graph.add_edge(a, b, **{k: v for k, v in edge.items() if k not in {'_id', 'run_id', 'hierarchy_graph_key', 'source_day', 'layer', 'source', 'target'}})
    expected = {frozenset(part) for part in nx.connected_components(graph)}
    flattened = [i for meta in metas for i in meta['node_indices']]
    if sorted(flattened) != list(range(len(nodes))) or {frozenset(meta['node_indices']) for meta in metas} != expected:
        raise ValueError('Stored Meta-components do not partition the graph exactly once')
    for meta in metas:
        indices = meta['node_indices']
        if meta['child_component_ids'] != [nodes[i]['component_id'] for i in indices] or meta['component_count'] != len(indices) or meta['source_chunks'] != sorted({nodes[i]['chunk_index'] for i in indices}) or meta['member_node_count'] != sum(nodes[i]['node_count'] for i in indices):
            raise ValueError('Stored Meta-component references/counts are inconsistent')
    originals = [value for node in nodes for value in node['member_original_ids']]
    if len(originals) != len(set(originals)) or any(node['node_count'] != len(node['member_original_ids']) for node in nodes):
        raise ValueError('Original candidate references overlap or counts are inconsistent')
    evaluation = deepcopy(run.get('evaluation_snapshot') or {})
    origin = 'database_build_snapshot'
    if not evaluation:
        # Old completed runs have a report on the user's machine; only diagnostics
        # and historical coverage context are reused, never authoritative membership.
        path = (run.get('paths') or {}).get('evaluation')
        if path and Path(path).is_file():
            previous = json.loads(Path(path).read_text(encoding='utf-8-sig'))
            if previous.get('run_id') == run_id and previous.get('source_file') == key:
                evaluation = previous; origin = 'legacy_build_report'
    evaluation.pop('metrics_table', None)
    evaluation.update(dict(source_file=key, source_day=day, schema_version=run.get('schema_version', 'component_daily_evaluation_v2'),
        hierarchy_run_id=run_id, temporal_level='day', structural_stage='daily_component_graph',
        node_type='layer1_component', population_scope='layer1_graph_candidate_nodes_not_unsampled_raw_flows',
        meta_definition='connected_components_in_sparse_component_similarity_graph', parameters=run['parameters'], sources=run['sources'],
        chunk_count=len(run['sources']), component_count=len(nodes), candidate_node_count=sum(n['node_count'] for n in nodes),
        components_without_representatives=sum(n.get('representative_count', 0) == 0 for n in nodes),
        edge_count=graph.number_of_edges(), density=nx.density(graph), max_degree=max(dict(graph.degree()).values(), default=0),
        meta_component_count=len(metas), singleton_meta_components=sum(len(m['node_indices']) == 1 for m in metas),
        cross_chunk_meta_components=sum(len(m['source_chunks']) > 1 for m in metas),
        components_with_categorical_data=sum(any(n['categorical'].get(f) for f in CATEGORICAL) for n in nodes),
        missing_raw_member_count=sum(n.get('missing_raw_count', 0) for n in nodes), meta_components=metas,
        integrity=dict(all_components_assigned_once=True, all_candidate_nodes_traced=True,
                       degree_cap_respected=all(d <= run['parameters']['degree_cap'] for _, d in graph.degree()))))
    if not evaluation.get('diagnostics'):
        evaluation['diagnostics'] = pair_diagnostics(nodes, run['parameters']['threshold'], progress); origin = 'recomputed_from_saved_descriptors'
    evaluation['diagnostics_origin'] = origin
    evaluation.setdefault('warnings', [])
    evaluation.setdefault('limitations', ['Connected groups can contain below-threshold pairs linked through chains.',
        'Candidate-node coverage is not coverage of unsampled raw flows.', 'No spectral, rare-behavior or temporal preservation is established by these statistics.'])
    rows = build_metrics_table(evaluation, nodes)
    evaluation['metrics_table'] = rows
    failures = [row['metric'] for row in rows if row['assessment'] == 'FAIL']
    report_id = uuid.uuid4().hex; evaluation['run_id'] = report_id
    evaluation['evaluation_status'] = 'integrity_failed' if failures else 'complete'
    db.component_hierarchy_evaluations.insert_one(dict(_id=report_id, hierarchy_run_id=run_id, source_day=day,
        status='building', snapshot_digest=initial_digest, created_at=datetime.now(timezone.utc)))
    try:
        if progress:
            progress(f'[HIER-EVAL] Source run={run_id}; nodes={len(nodes)}; metas={len(metas)}; rendering reports...')
        # Mongo IDs are metadata, not diagram inputs / JSON lineage fields.
        clean_nodes = [{k: v for k, v in node.items() if k != '_id'} for node in nodes]
        evaluation['meta_components'] = [{k: v for k, v in meta.items() if k != '_id'} for meta in metas]
        paths = write_reports(evaluation, clean_nodes, graph)
        if digest(list(snapshot(db, run_id))) != initial_digest:
            raise ValueError('Stored hierarchy snapshot changed during evaluation; report not published.')
        if failures:
            raise ValueError(f'Hierarchy integrity metrics failed: {failures}; inspect {paths["metrics_csv"]}')
        db.component_hierarchy_evaluations.update_one({'_id': report_id}, {'$set': dict(status='complete', paths=paths,
            metrics_table=evaluation['metrics_table'], completed_at=datetime.now(timezone.utc))})
        db.component_hierarchy_evaluations.create_index([('hierarchy_run_id', 1), ('source_day', 1)])
        return evaluation, paths
    except Exception as exc:
        db.component_hierarchy_evaluations.update_one({'_id': report_id}, {'$set': dict(status='failed', error=str(exc))})
        raise
