"""Pinned, immutable phase-2 runs. Source graph topology is never rewritten."""
from datetime import datetime, timezone
from importlib.metadata import version
import uuid

from mongoengine import get_db
from .spectral_inputs import load_inputs
from .spectral_core import analyze_graph
from .spectral_pipeline import insert_rows
from .message_passing_evaluation import evaluate_message_passing
from .message_passing_reports import input_audit, graph_report, phase_report


def run_message_passing(day, *, phase1_run_id=None, epochs=30, hidden=32, layers=2, repeats=3, seed=17, force=False, progress=None):
    if not 1 <= epochs <= 1000 or not 4 <= hidden <= 256 or not 1 <= layers <= 6 or not 1 <= repeats <= 20 or not 0 <= seed < 2**32:
        raise ValueError('Require epochs 1..1000, hidden 4..256, layers 1..6, repeats 1..20, seed 0..2^32-1.')
    db = get_db()
    if phase1_run_id is None:
        pointer = db.spectral_analysis_active.find_one({'_id': f'{day}:all:all', 'status': 'complete'})
        phase1_run_id = pointer['run_id'] if pointer else None
    phase1 = db.spectral_analysis_runs.find_one({'_id': phase1_run_id, 'source_day': day, 'status': 'complete'})
    if not phase1:
        raise ValueError('No complete phase-1 run; run spectral_analysis --day DAY first, or select --spectral-run-id.')
    p = phase1['parameters']
    args = dict(scope=p['scope'], chunk_index=p.get('chunk_index'), hierarchy_run_id=p.get('hierarchy_run_id'))
    graphs, _ = load_inputs(day, **args)
    signatures = {g.key: g.signature for g in graphs}
    if signatures != phase1['source_signatures']:
        raise ValueError('Source graph/attributes differ from phase 1. Re-run phase 1 after upstream changes.')
    active_key = f'{day}:{phase1_run_id}'
    previous = db.spectral_message_passing_active.find_one({'_id': active_key})
    if previous and not force:
        raise ValueError('Message-passing run exists; --force creates a new retained version.')
    run_id = uuid.uuid4().hex
    parameters = dict(epochs=epochs, hidden_dim=hidden, layers=layers, perturbation_repeats=repeats, seed=seed,
                      learning_rate=.003, weight_decay=.0001, training_mask_rate=.2, validation_fraction=.1, test_fraction=.1,
                      checkpoint_selection='minimum_validation_masked_entry_mse', training_seeds=1,
                      perturbations={'edge_weight': '10% of edges multiplied by exp(uniform(-.05,.05))',
                                     'edge_drop': 'ceil(1% of edges) removed', 'feature_noise': 'Gaussian 5% observed-column SD'},
                      torch_version=version('torch'), numpy_version=version('numpy'), scipy_version=version('scipy'), device='cpu', threads=1)
    db.spectral_message_passing_runs.insert_one(dict(_id=run_id, status='building', source_day=day, phase1_run_id=phase1_run_id,
                                                    version='eigenvector_aware_mp_probe_v1', parameters=parameters,
                                                    source_signatures=signatures, created_at=datetime.now(timezone.utc)))
    summaries = []
    try:
        audits = input_audit(graphs)
        if progress:
            for row in audits:
                if row['status'] in ('mixed', 'review_required'):
                    progress(f"[INPUT AUDIT] {row['graph_key']}: {row['check']}={row['status']}; {row['detail']}")
        for number, graph in enumerate(graphs, 1):
            if progress:
                progress(f'[MESSAGE PASSING] GRAPH {number}/{len(graphs)}: {graph.key}; epochs={epochs}; two probes + interventions')
            analyze_options = dict(requested=p['requested_eigenvectors'], budget=p['max_basis'], dense_limit=p['dense_limit'])
            result = analyze_graph(graph, **analyze_options)
            evaluated = evaluate_message_passing(graph, result, epochs=epochs, hidden=hidden, layers=layers, repeats=repeats,
                                                seed=seed, analyze_options=analyze_options, progress=progress)
            summary = graph_report(graph, result, evaluated, run_id, phase1_run_id, parameters)
            common = dict(run_id=run_id, phase1_run_id=phase1_run_id, graph_key=graph.key, source_day=day, layer=graph.layer)
            db.spectral_message_passing_graphs.insert_one(dict(summary))
            insert_rows(db.spectral_message_passing_nodes, (
                dict(common, node_index=i, node_id=node_id, embedding=evaluated['spectral']['embedding'][i].tolist(),
                     block_index=int(result.arrays['block_index'][i]), lineage=graph.lineage[i] if graph.lineage else None)
                for i, node_id in enumerate(graph.node_ids)))
            insert_rows(db.spectral_pooled_features, (
                dict(common, block_index=block['block_index'], component_id=block['source_component_id'],
                     node_indices=block['node_indices'], child_count=block['node_count'],
                     mean=evaluated['pooled_mean'][i].tolist(), std=evaluated['pooled_std'][i].tolist(),
                     parent_graph_created=False)
                for i, block in enumerate(result.blocks)))
            summaries.append(summary)
            if progress:
                progress(f"[MESSAGE PASSING] TEST: spectral={summary['spectral_probe']['test_mse']:.6g}; plain={summary['plain_probe']['test_mse']:.6g}")
        current, _ = load_inputs(day, **args)
        if {g.key: g.signature for g in current} != signatures:
            raise ValueError('Source graphs changed during message-passing evaluation; run not published.')
        for name in ('spectral_message_passing_graphs', 'spectral_message_passing_nodes', 'spectral_pooled_features'):
            db[name].create_index([('run_id', 1), ('graph_key', 1)])
        phase = phase_report(day, run_id, phase1_run_id, summaries, audits, parameters)
        db.spectral_message_passing_runs.update_one({'_id': run_id}, {'$set': dict(status='complete', graph_count=len(graphs),
            completed_at=datetime.now(timezone.utc), phase_artifacts=phase, source_versions_verified=True)})
        pointer = dict(run_id=run_id, source_day=day, phase1_run_id=phase1_run_id, status='complete', phase_artifacts=phase)
        if previous:
            updated = db.spectral_message_passing_active.update_one({'_id': active_key, 'run_id': previous['run_id']}, {'$set': pointer})
            if updated.modified_count != 1:
                raise ValueError('Concurrent message-passing run changed active pointer; run not published.')
        else:
            db.spectral_message_passing_active.insert_one(dict(pointer, _id=active_key))
        return dict(run_id=run_id, graphs=summaries, phase=phase)
    except Exception as exc:
        db.spectral_message_passing_runs.update_one({'_id': run_id}, {'$set': dict(status='failed', error=str(exc))})
        raise
