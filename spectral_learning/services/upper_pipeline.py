"""Analyze actual layers above L2, using immutable source MP and hierarchy snapshots."""
from datetime import datetime, timezone
import uuid
import platform
from importlib.metadata import version
import numpy as np
from mongoengine import get_db

from .spectral_inputs import load_inputs, fingerprint
from .spectral_core import analyze_graph
from .spectral_pipeline import insert_rows
from .spectral_reports import write_graph
from .message_passing_evaluation import evaluate_message_passing, pool_blocks
from .message_passing_reports import graph_report
from .upper_graph import initial_moments, build_upper_graph
from .upper_reports import write_upper_graph, write_upper_phase


def load_source(day, source_run_id=None):
    db = get_db()
    if source_run_id is None:
        spectral = db.spectral_analysis_active.find_one({'_id': f'{day}:all:all', 'status': 'complete'})
        pointer = db.spectral_message_passing_active.find_one({'_id': f'{day}:{spectral["run_id"]}', 'status': 'complete'}) if spectral else None
        source_run_id = pointer['run_id'] if pointer else None
    run = db.spectral_message_passing_runs.find_one({'_id': source_run_id, 'source_day': day, 'status': 'complete'})
    if not run:
        raise ValueError('No complete source message-passing run; execute spectral_message_passing first or select --source-run-id.')
    phase1 = db.spectral_analysis_runs.find_one({'_id': run['phase1_run_id'], 'status': 'complete'})
    if not phase1:
        raise ValueError('Source spectral run is not complete')
    p = phase1['parameters']
    graphs, _ = load_inputs(day, p['scope'], p.get('chunk_index'), p.get('hierarchy_run_id'))
    signatures = {g.key: g.signature for g in graphs}
    if signatures != run['source_signatures'] or signatures != phase1['source_signatures']:
        raise ValueError('Source graphs changed since the selected spectral/message-passing run.')
    candidates = [g for g in graphs if g.layer == 2]
    if len(candidates) != 1:
        raise ValueError('The selected source run must contain exactly one daily L2 component graph.')
    graph = candidates[0]
    rows = list(db.spectral_message_passing_nodes.find({'run_id': source_run_id, 'graph_key': graph.key}).sort('node_index', 1))
    if [row['node_index'] for row in rows] != list(range(len(graph.node_ids))) or [row['node_id'] for row in rows] != graph.node_ids:
        raise ValueError('Source learned embedding snapshot is incomplete or misordered')
    embedding = np.asarray([row['embedding'] for row in rows], dtype=float)
    if embedding.ndim != 2 or not np.isfinite(embedding).all() or embedding.shape[1] != run['parameters']['hidden_dim']:
        raise ValueError('Invalid source learned embedding dimensions/values')
    digest = fingerprint(dict(graph_signature=graph.signature, embedding=embedding.tolist()))
    return graph, embedding, run, phase1, digest


def pooled_signatures(result):
    arrays = result.arrays; values = arrays['node_spectral']; valid = arrays['node_spectral_mask']
    means, stds, counts = [], [], []
    for block in result.blocks:
        indices = np.asarray(block['node_indices']); selected = values[indices[valid[indices]]]
        means.append(selected.mean(axis=0) if len(selected) else np.zeros(3))
        stds.append(selected.std(axis=0) if len(selected) else np.zeros(3)); counts.append(len(selected))
    return np.asarray(means), np.asarray(stds), np.asarray(counts)


def run_upper(day, *, source_run_id=None, levels=1, neighbors=8, threshold=.85, bandwidth=1.,
              epochs=60, hidden=32, layers=2, repeats=3, seed=17, force=False, progress=None):
    if not 1 <= levels <= 3 or not 1 <= neighbors <= 128 or not 0 < threshold <= 1 or not np.isfinite(bandwidth) or bandwidth <= 0:
        raise ValueError('Require levels 1..3, neighbors 1..128, threshold (0,1], finite positive bandwidth.')
    if not 1 <= epochs <= 1000 or not 4 <= hidden <= 256 or not 1 <= layers <= 6 or not 1 <= repeats <= 20 or not 0 <= seed < 2**32:
        raise ValueError('Invalid message-passing training parameters')
    db = get_db()
    child, child_embedding, source_run, phase1, source_digest = load_source(day, source_run_id)
    source_run_id = source_run['_id']; active_key = f'{day}:{source_run_id}'
    previous = db.upper_spectral_active.find_one({'_id': active_key})
    if previous and not force:
        raise ValueError('Upper analysis exists; --force creates a retained new version.')
    run_id = uuid.uuid4().hex
    spectral_options = dict(requested=phase1['parameters']['requested_eigenvectors'], budget=phase1['parameters']['max_basis'], dense_limit=phase1['parameters']['dense_limit'])
    parameters = dict(levels=levels, neighbors=neighbors, threshold=threshold, bandwidth=bandwidth,
                      epochs=epochs, hidden_dim=hidden, layers=layers, perturbation_repeats=repeats, seed=seed,
                      learning_rate=.003, weight_decay=.0001, training_mask_rate=.2, training_seeds=1,
                      validation_fraction=.1, test_fraction=.1, source_phase1_run=phase1['_id'],
                      checkpoint_selection='minimum_validation_masked_entry_mse',
                      spectral_options=spectral_options, edge_origin='new_raw_moment_similarity_not_quotient',
                      child_embeddings_used_for_edges=False, child_embeddings_used_as_targets=False,
                      runtime_versions={'python': platform.python_version(), 'torch': version('torch'), 'numpy': version('numpy'), 'scipy': version('scipy')})
    db.upper_spectral_runs.insert_one(dict(_id=run_id, source_day=day, source_message_passing_run=source_run_id,
        status='building', version='upper_moment_similarity_spectral_mp_v1', source_digest=source_digest, parameters=parameters, created_at=datetime.now(timezone.utc)))
    records = []
    try:
        source_audit = list(source_run.get('input_audit') or [])
        # Older source runs stored the audit only in phase artifacts; rederive from pinned inputs.
        if not source_audit:
            from .message_passing_reports import input_audit
            p = phase1['parameters']; inputs, _ = load_inputs(day, p['scope'], p.get('chunk_index'), p.get('hierarchy_run_id'))
            source_audit = input_audit(inputs)
        if progress:
            for row in source_audit:
                if row['status'] in ('mixed', 'review_required'):
                    progress(f"[UPPER INPUT AUDIT] {row['graph_key']}: {row['status']}; {row['detail']}")
        state = initial_moments(child)
        child_result = analyze_graph(child, **spectral_options)
        for offset in range(levels):
            if progress:
                progress(f'[UPPER] Building L{child.layer + 1} from {len(child_result.blocks)} existing memberships; source nodes={len(child.node_ids)}')
            inherited_embedding = pool_blocks(child_embedding, child_result.arrays['block_index'])
            inherited_spectral = pooled_signatures(child_result)
            graph, state, audit = build_upper_graph(child, child_result, state, run_id=run_id, neighbors=neighbors,
                                                    threshold=threshold, bandwidth=bandwidth, progress=progress)
            result = analyze_graph(graph, progress=progress, **spectral_options)
            for block in result.blocks:
                block['source_component_id'] = f'{graph.key}:group:{block["block_index"]}'
            graph.block_lookup = {frozenset(block['node_indices']): block['source_component_id'] for block in result.blocks}
            paths = write_graph(graph, result, run_id); result.summary['artifacts'] = paths
            construction = write_upper_graph(graph, state, audit, result, inherited_embedding, inherited_spectral, run_id)
            if len(graph.node_ids) >= 5 and any(graph.feature_mask[:, col].sum() >= 5 for col in range(graph.features.shape[1])):
                evaluated = evaluate_message_passing(graph, result, epochs=epochs, hidden=hidden, layers=layers, repeats=repeats,
                                                    seed=seed, analyze_options=spectral_options, progress=progress)
                message = graph_report(graph, result, evaluated, run_id, run_id, parameters, source_spectral_collection='upper_spectral_runs')
                child_embedding = evaluated['spectral']['embedding']
                status = 'trained_and_evaluated'
            else:
                message = None; child_embedding = np.empty((len(graph.node_ids), 0)); status = 'not_run_insufficient_validation_test_entries'
                if progress:
                    progress(f'[UPPER] L{graph.layer}: spectral complete; MP not trained (fewer than 5 comparable nodes).')
            record = dict(layer=graph.layer, graph_key=graph.key, spectral=result.summary,
                          message_passing=message, message_passing_status=status, aggregation_audit=audit, construction=construction)
            records.append(record)
            common = dict(run_id=run_id, source_day=day, graph_key=graph.key, layer=graph.layer)
            db.upper_spectral_graphs.insert_one(dict(common, source=graph.source, source_signature=graph.signature, **{'record': record}))
            insert_rows(db.upper_spectral_nodes, (dict(common, node_index=i, node_id=node_id, features=graph.features[i].tolist(),
                feature_mask=graph.feature_mask[i].tolist(), moment_mean=state.mean[i].tolist(), moment_variance=state.variance[i].tolist(),
                moment_count=state.count[i].tolist(), original_component_mass=float(state.mass[i]), lineage=graph.lineage[i],
                eigenvectors=result.arrays['eigenvectors'][i].tolist(), eigenvalues=result.arrays['eigenvalues'][i].tolist(),
                basis_mask=result.arrays['basis_mask'][i].tolist(), basis_global_columns=result.arrays['basis_global_columns'][i].tolist(),
                node_spectral=result.arrays['node_spectral'][i].tolist(), node_spectral_mask=bool(result.arrays['node_spectral_mask'][i]),
                embedding=child_embedding[i].tolist() if message else None,
                inherited_embedding_mean=inherited_embedding[0][i].tolist(), inherited_embedding_std=inherited_embedding[1][i].tolist(),
                inherited_spectral_mean=inherited_spectral[0][i].tolist(), inherited_spectral_valid_count=int(inherited_spectral[2][i]))
                for i, node_id in enumerate(graph.node_ids)))
            insert_rows(db.upper_spectral_edges, (dict(common, **edge, edge_spectral=result.arrays['edge_spectral'][i].tolist(),
                edge_spectral_mask=bool(result.arrays['edge_spectral_mask'][i])) for i, edge in enumerate(graph.edges)))
            insert_rows(db.upper_spectral_components, (dict(common, **block) for block in result.blocks))
            if progress:
                progress(f'[UPPER] L{graph.layer}: nodes={len(graph.node_ids)}; edges={len(graph.edges)}; groups={len(result.blocks)}; reports={construction["directory"]}')
            child, child_result = graph, result
        *_, current_digest = load_source(day, source_run_id)
        if current_digest != source_digest:
            raise ValueError('Source embeddings changed during upper analysis; run not published.')
        phase = write_upper_phase(day, run_id, source_run_id, records, parameters, source_audit)
        for name in ('upper_spectral_graphs', 'upper_spectral_nodes', 'upper_spectral_edges', 'upper_spectral_components'):
            db[name].create_index([('run_id', 1), ('graph_key', 1)])
        db.upper_spectral_runs.update_one({'_id': run_id}, {'$set': dict(status='complete', completed_at=datetime.now(timezone.utc),
            source_versions_verified=True, phase_artifacts=phase)})
        pointer = dict(run_id=run_id, source_day=day, source_message_passing_run=source_run_id, status='complete', phase_artifacts=phase)
        if previous:
            changed = db.upper_spectral_active.update_one({'_id': active_key, 'run_id': previous['run_id']}, {'$set': pointer})
            if changed.modified_count != 1:
                raise ValueError('Concurrent run changed active upper-analysis pointer.')
        else:
            db.upper_spectral_active.insert_one(dict(pointer, _id=active_key))
        return dict(run_id=run_id, levels=records, phase=phase)
    except Exception as exc:
        db.upper_spectral_runs.update_one({'_id': run_id}, {'$set': dict(status='failed', error=str(exc))})
        raise
