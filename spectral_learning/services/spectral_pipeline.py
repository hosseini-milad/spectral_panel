"""Versioned phase-1 persistence. Old runs/data are retained; publish only on success."""
from datetime import datetime, timezone
import uuid
import platform
from importlib.metadata import version

from bson import BSON
from mongoengine import get_db

from .spectral_inputs import load_inputs
from .spectral_core import analyze_graph
from .spectral_reports import write_graph, write_phase

VERSION = 'hierarchical_spectral_phase1_v1'


def insert_rows(collection, rows, batch_size=1000):
    batch = []
    for row in rows:
        if len(BSON.encode(row)) >= 16 * 1024 * 1024:
            raise ValueError('Spectral record exceeds MongoDB document limit')
        batch.append(row)
        if len(batch) >= batch_size:
            collection.insert_many(batch); batch = []
    if batch:
        collection.insert_many(batch)


def run_spectral(day, *, scope='all', chunk_index=None, hierarchy_run_id=None, requested=8,
                 budget=32, dense_limit=256, higher_levels=2, planning_ratio=.5, force=False, progress=None):
    db = get_db()
    active_key = f'{day}:{scope}:{chunk_index if chunk_index is not None else "all"}'
    previous = db.spectral_analysis_active.find_one({'_id': active_key})
    if previous and not force:
        raise ValueError('A spectral run exists for this selection; use --force to create a new version.')
    inputs, context = load_inputs(day, scope, chunk_index, hierarchy_run_id)
    signatures = {graph.key: graph.signature for graph in inputs}
    run_id = uuid.uuid4().hex
    parameters = dict(scope=scope, chunk_index=chunk_index, hierarchy_run_id=context['hierarchy_run_id'],
                      requested_eigenvectors=requested, max_basis=budget, dense_limit=dense_limit,
                      higher_levels_above_meta=higher_levels, planning_ratio=planning_ratio,
                      operator='symmetric_normalized_laplacian_isolate_diagonal_zero',
                      eigenspace_group_tolerance=1e-7, seed=17,
                      runtime_versions={'python': platform.python_version(), 'numpy': version('numpy'), 'scipy': version('scipy')})
    db.spectral_analysis_runs.insert_one({'_id': run_id, 'status': 'building', 'source_day': day,
                                         'version': VERSION, 'parameters': parameters,
                                         'source_signatures': signatures, 'created_at': datetime.now(timezone.utc)})
    summaries, paths = [], []
    try:
        for number, graph in enumerate(inputs, 1):
            if progress:
                progress(f'[SPECTRAL] GRAPH {number}/{len(inputs)}: {graph.key}; layer={graph.layer}; nodes={len(graph.node_ids)}')
            result = analyze_graph(graph, requested=requested, budget=budget, dense_limit=dense_limit, progress=progress)
            outputs = write_graph(graph, result, run_id)
            summary, arrays = result.summary, result.arrays
            summary['artifacts'] = outputs
            common = dict(run_id=run_id, graph_key=graph.key, layer=graph.layer, source_day=day)
            db.spectral_graphs.insert_one(dict(summary, **common))
            insert_rows(db.spectral_blocks, (dict(row, **common) for row in result.blocks))
            insert_rows(db.spectral_node_encodings, (
                dict(common, node_index=index, node_id=node_id, block_index=int(arrays['block_index'][index]),
                     eigenvectors=arrays['eigenvectors'][index].tolist(), eigenvalues=arrays['eigenvalues'][index].tolist(),
                     basis_global_columns=arrays['basis_global_columns'][index].tolist(),
                     basis_mask=arrays['basis_mask'][index].tolist(), node_spectral=arrays['node_spectral'][index].tolist(),
                     node_spectral_mask=bool(arrays['node_spectral_mask'][index]),
                     node_features=graph.features[index].tolist(), node_feature_mask=graph.feature_mask[index].tolist(),
                     lineage=graph.lineage[index] if graph.lineage else None)
                for index, node_id in enumerate(graph.node_ids)))
            insert_rows(db.spectral_edge_encodings, (
                dict(common, source=int(arrays['edge_index'][0, index]), target=int(arrays['edge_index'][1, index]),
                     weight=float(weight), edge_spectral=arrays['edge_spectral'][index].tolist(),
                     edge_spectral_mask=bool(arrays['edge_spectral_mask'][index]))
                for index, weight in enumerate(arrays['edge_weight'])))
            summaries.append(summary); paths.append(outputs)
        for name in ('spectral_graphs', 'spectral_blocks', 'spectral_node_encodings', 'spectral_edge_encodings'):
            db[name].create_index([('run_id', 1), ('graph_key', 1)])
        # Prevent a phase from silently mixing different versions while running.
        current, _ = load_inputs(day, scope, chunk_index, hierarchy_run_id)
        if {graph.key: graph.signature for graph in current} != signatures:
            raise ValueError('Source graphs changed during spectral analysis; retry after upstream work finishes.')
        phase = write_phase(day, run_id, summaries, context, higher_levels, planning_ratio, parameters=parameters)
        db.spectral_analysis_runs.update_one({'_id': run_id}, {'$set': {
            'status': 'complete', 'completed_at': datetime.now(timezone.utc), 'graph_count': len(inputs),
            'phase_artifacts': phase, 'graph_artifacts': paths, 'source_versions_verified': True}})
        pointer = {'run_id': run_id, 'source_day': day, 'parameters': parameters, 'status': 'complete', 'phase_artifacts': phase}
        if previous:
            updated = db.spectral_analysis_active.update_one({'_id': active_key, 'run_id': previous['run_id']}, {'$set': pointer})
            if updated.modified_count != 1:
                raise ValueError('Concurrent spectral run changed the active pointer; this run was not published.')
        else:
            db.spectral_analysis_active.insert_one(dict(pointer, _id=active_key))
        return {'run_id': run_id, 'graphs': summaries, 'phase': phase}
    except Exception as exc:
        db.spectral_analysis_runs.update_one({'_id': run_id}, {'$set': {'status': 'failed', 'error': str(exc)}})
        raise
