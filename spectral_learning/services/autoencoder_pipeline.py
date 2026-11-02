"""Versioned shared L1 autoencoder training; model arrays live in document bundles."""
from datetime import datetime, timezone
from importlib.metadata import version
import platform
import uuid
from pathlib import Path
import json
import numpy as np
from mongoengine import get_db

from ingestion.utils.document_paths import document_directory
from .autoencoder_inputs import load_raw_chunks, chunk_splits, fit_scaler, prepare_chunks
from .autoencoder_training import train_shared
from .autoencoder_reports import write_run
from .message_passing_reports import input_audit
from .spectral_reports import dump_json


def run_autoencoder(day, *, epochs=60, hidden=64, latent=16, layers=2, max_pairs=2048,
                    structure_weight=.1, weight_weight=.05, seed=17, force=False, progress=None):
    if not 1 <= epochs <= 1000 or not 2 <= latent < 21 or not latent < hidden <= 256 or not 1 <= layers <= 6 or not 1 <= max_pairs <= 8192 or not 0 <= seed < 2**32:
        raise ValueError('Require epochs 1..1000, latent 2..20, latent < hidden <=256, layers 1..6, max-pairs 1..8192, seed 0..2^32-1.')
    if not np.isfinite([structure_weight, weight_weight]).all() or min(structure_weight, weight_weight) < 0 or max(structure_weight, weight_weight) > 10:
        raise ValueError('Loss weights must be finite and in [0,10].')
    db = get_db(); key = f'{day}:layer1'
    previous = db.autoencoder_active.find_one({'_id': key})
    if previous and not force:
        raise ValueError('An Autoencoder run exists; --force creates a new retained version.')
    graphs = load_raw_chunks(day); splits = chunk_splits(graphs)
    signatures = {graph.key: graph.signature for graph in graphs}
    scaler, audit = fit_scaler(graphs, splits)
    source_audit = input_audit(graphs)
    source_audit += [dict(graph_key='all', check='upstream_candidate_selection', status='review_required', detail='Existing selection code uses time/label strata and risk-aware policies; this run is not proof of an end-to-end label-free detector.'),
                     dict(graph_key='all', check='legacy_raw_validity', status='review_required', detail='Historical raw ingestion can replace missing/invalid values with zero; original per-value validity cannot be recovered.')]
    parameters = dict(epochs=epochs, hidden_dim=hidden, latent_dim=latent, layers=layers, max_relation_pairs=max_pairs,
        structure_loss_weight=structure_weight, weight_loss_weight=weight_weight, seed=seed, training_seeds=1,
        optimizer='Adam', learning_rate=.001, weight_decay=.0001, gradient_clip_norm=5,
        feature_mask_rate=.2, mask_at_least_one_observed_feature_per_valid_node=True, edge_holdout_fraction=.1, training_graph_weighting='one_optimizer_step_per_training_chunk_per_epoch',
        feature_loss='mean_of_available_continuous_Huber_and_binary_BCE_families',
        validation_selection='feature_target_count_weighted_total_objective',
        edge_negative_policy='sampled_absent_pairs_within_original_connected_blocks',
        spectral_input='recomputed_on_graph_without_hidden_positive_targets',
        spectral_options=dict(requested_eigenvectors=8, max_basis=32, dense_limit=256),
        variants=['feature', 'graph', 'spectral'], scaler_fit='training_chunks_only_raw_log1p_view',
        runtime_versions={'python': platform.python_version(), 'torch': version('torch'), 'numpy': version('numpy'), 'scipy': version('scipy')}, device='cpu', threads=1)
    run_id = uuid.uuid4().hex
    folder = document_directory('autoencoder', layer=1, day=day) / 'runs' / run_id
    folder.mkdir(parents=True, exist_ok=False)
    db.autoencoder_runs.insert_one(dict(_id=run_id, source_day=day, layer=1, status='building',
        version='shared_l1_autoencoder_v1', source_signatures=signatures, parameters=parameters,
        chunk_splits=splits, created_at=datetime.now(timezone.utc), report_directory=str(folder)))
    dump_json(folder / 'run_status.json', dict(run_id=run_id, status='building'))
    try:
        if progress:
            progress(f'[AUTOENCODER] run={run_id}; graphs={len(graphs)}; active features={int(scaler["active"].sum())}; shared encoder per variant')
            for split in ('train', 'validation', 'test'):
                progress(f'[AUTOENCODER] {split}: {[g.chunk for g in graphs if splits[g.key] == split]}')
            for row in source_audit:
                if row['status'] in ('mixed', 'review_required'):
                    progress(f'[INPUT AUDIT] {row["check"]}: {row["status"]}; {row["detail"]}')
        prepared = prepare_chunks(graphs, splits, scaler, seed=seed, max_pairs=max_pairs, progress=progress)
        models = train_shared(prepared, scaler, epochs=epochs, hidden=hidden, latent=latent, layers=layers, seed=seed,
                              structure_weight=structure_weight, weight_weight=weight_weight, progress=progress)
        if {g.key: g.signature for g in load_raw_chunks(day)} != signatures:
            raise ValueError('Source graphs or raw attributes changed during training; run not published.')
        if progress:
            progress('[AUTOENCODER] Writing checkpoints, arrays, metrics and schematics...')
        paths = write_run(day, run_id, prepared, scaler, audit, models, parameters, source_audit)
        if {g.key: g.signature for g in load_raw_chunks(day)} != signatures:
            raise ValueError('Source graphs or raw attributes changed during reporting; run not published.')
        manifest = Path(paths['manifest'])
        data = json.loads(manifest.read_text(encoding='utf-8')); data.update(status='complete', source_versions_verified=True)
        dump_json(manifest, data)
        db.autoencoder_runs.update_one({'_id': run_id}, {'$set': dict(status='complete', paths=paths, source_versions_verified=True,
            metrics=data['metrics'], completed_at=datetime.now(timezone.utc))})
        pointer = dict(run_id=run_id, source_day=day, layer=1, status='complete', paths=paths)
        if previous:
            changed = db.autoencoder_active.update_one({'_id': key, 'run_id': previous['run_id']}, {'$set': pointer})
            if changed.modified_count != 1:
                raise ValueError('Concurrent Autoencoder run changed active pointer.')
        else:
            db.autoencoder_active.insert_one(dict(pointer, _id=key))
        dump_json(folder / 'run_status.json', dict(run_id=run_id, status='complete', source_versions_verified=True))
        return dict(run_id=run_id, paths=paths, metrics=data['metrics'])
    except Exception as exc:
        db.autoencoder_runs.update_one({'_id': run_id}, {'$set': dict(status='failed', error=str(exc))})
        dump_json(folder / 'run_status.json', dict(run_id=run_id, status='failed', error=str(exc)))
        manifest = folder / 'manifest.json'
        if manifest.exists():
            data = json.loads(manifest.read_text(encoding='utf-8')); data.update(status='failed', source_versions_verified=False)
            dump_json(manifest, data)
        raise
