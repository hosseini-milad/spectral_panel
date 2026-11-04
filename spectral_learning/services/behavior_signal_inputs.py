"""Frozen, source-verified signal handoff. No training, fusion or alert decision."""
from datetime import datetime, timezone
from pathlib import Path
import json
import math
import uuid

import numpy as np
import torch
from mongoengine import get_db
from pymongo import UpdateOne
from threadpoolctl import threadpool_limits

from ingestion.utils.document_paths import document_directory
from .autoencoder_inputs import load_raw_chunks, prepare_chunks
from .normal_behavior import (audit_graph_identities, reference_splits, _signatures,
                              _verify_raw_sources, calibration_threshold, tail_probabilities)
from .normal_behavior_reports import load_reference_bundle, _sha
from .neighborhood_learning import NeighborhoodAutoencoder, neighborhood_targets
from .neighborhood_experiment import _evaluate
from .spectral_inputs import fingerprint
from .spectral_reports import dump_json
from .message_passing_reports import write_csv

CHANNELS = ('feature', 'degree', 'neighbor_mean', 'neighbor_std')
VERSION = 'behavior_signal_inputs_v1'


def fit_calibration(evidence, alpha):
    """Separate connected/isolate calibration; no fitting from test/external data."""
    if not 0 < alpha < 1:
        raise ValueError('Require 0 < alpha < 1')
    result = {}
    for channel in CHANNELS:
        for group in ('connected', 'isolated'):
            values = []
            for split, arrays in evidence:
                if split != 'calibration':
                    continue
                chosen = arrays[channel + '_valid'] & (arrays['isolated'] == (group == 'isolated'))
                values.extend(arrays[channel + '_mse'][chosen].tolist())
            x = np.sort(np.asarray(values, dtype=float))
            if not np.isfinite(x).all():
                raise ValueError('Nonfinite calibration residuals')
            key = channel + ':' + group
            minimum = math.ceil(1 / alpha) - 1
            calibrated = len(x) >= minimum and len(x) > 0
            result[key] = dict(status='calibrated' if calibrated else 'unavailable',
                reason=None if calibrated else 'insufficient_normal_calibration_targets',
                n=len(x), minimum_count=minimum, alpha=alpha,
                threshold=calibration_threshold(x, alpha) if calibrated else None, values=x)
    return result


def channel_value(channel, arrays, i, calibration, calibration_id):
    group = 'isolated' if arrays['isolated'][i] else 'connected'
    count = int(arrays['feature_hidden'][i].sum()) if channel == 'feature' else int(arrays[channel + '_target_count'][i])
    if not arrays[channel + '_valid'][i]:
        return dict(status='unavailable', reason='no_observed_targets', target_count=count,
                    residual=None, tail_probability=None, threshold=None, exceeds_tail=None,
                    calibration_id=None, calibration_group=group)
    value = float(arrays[channel + '_mse'][i])
    if not np.isfinite(value) or value < 0:
        raise ValueError('Nonfinite or negative valid signal residual')
    state = calibration[channel + ':' + group]
    valid = state['status'] == 'calibrated'
    return dict(status='valid' if valid else 'uncalibrated', reason=state['reason'], target_count=count,
        residual=value, residual_unit='reference_transformed_feature_mse' if channel == 'feature' else 'normal_train_standardized_target_mse',
        tail_probability=float(tail_probabilities(state['values'], [value])[0]) if valid else None,
        threshold=state['threshold'], exceeds_tail=value > state['threshold'] if valid else None,
        calibration_id=calibration_id if valid else None, calibration_group=group,
        interpretation='upper_tail_deviation_not_attack_probability')


def validate_observation(row):
    """Fail closed on contradictions before exporting a fusion input."""
    if row['schema_version'] != VERSION or not row['entity']['node_id'] or not row['raw_source']['record_id']:
        raise ValueError('Invalid observation identity')
    if row['fusion'] != dict(status='not_computed', score=None, alert=None):
        raise ValueError('Signal inputs must not contain fusion/alert decisions')
    if not np.isfinite(row['representation']['vector']).all():
        raise ValueError('Nonfinite latent representation')
    for name, signal in row['signals'].items():
        if signal['status'] == 'valid':
            if (signal['target_count'] <= 0 or signal['calibration_id'] != row['calibration_id']
                    or signal['residual'] is None or not np.isfinite(signal['residual']) or signal['residual'] < 0
                    or signal['tail_probability'] is None or not 0 < signal['tail_probability'] <= 1
                    or signal['threshold'] is None or not np.isfinite(signal['threshold'])
                    or signal['exceeds_tail'] != (signal['residual'] > signal['threshold'])):
                raise ValueError('Invalid calibrated signal')
        elif signal['status'] in ('unavailable', 'uncalibrated', 'not_computed'):
            if any(signal.get(k) is not None for k in ['tail_probability', 'threshold', 'exceeds_tail']):
                raise ValueError('Missing/uncalibrated signal has a decision')
            if signal['status'] != 'uncalibrated' and signal['residual'] is not None:
                raise ValueError('Unavailable signal must have null residual')
        else:
            raise ValueError('Unknown signal status')
    if row['isolated'] and any(row['signals'][k]['status'] != 'unavailable' for k in ['neighbor_mean', 'neighbor_std']):
        raise ValueError('Isolates cannot have neighbor-moment evidence')


def persist_inputs(db, run, jsonl):
    """Idempotent inserts. Consumers must join to a complete parent run."""
    if _sha(jsonl) != run['payload_sha256']:
        raise ValueError('Signal payload checksum mismatch before persistence')
    runs = db.behavior_analysis_runs; observations = db.behavior_observations
    observations.create_index([('run_id', 1), ('entity.graph_key', 1)])
    existing = runs.find_one({'_id': run['_id']})
    if existing and existing.get('payload_sha256') != run['payload_sha256']:
        raise ValueError('Existing signal run has a different payload checksum')
    runs.update_one({'_id': run['_id']}, {'$setOnInsert': dict(run, status='building')}, upsert=True)
    runs.update_one({'_id': run['_id']}, {'$set': dict(status='building')})
    try:
        batch = []; expected = {}
        with Path(jsonl).open(encoding='utf-8') as stream:
            for line in stream:
                row = json.loads(line); validate_observation(row)
                if row['run_id'] != run['_id'] or row['_id'] in expected:
                    raise ValueError('Wrong run or duplicate observation identity')
                expected[row['_id']] = row['content_sha256']
                batch.append(UpdateOne({'_id': row['_id']}, {'$setOnInsert': row}, upsert=True))
                if len(batch) == 500:
                    observations.bulk_write(batch, ordered=False); batch = []
            if batch:
                observations.bulk_write(batch, ordered=False)
        if observations.count_documents({'run_id': run['_id']}) != run['observation_count']:
            raise ValueError('Persisted observation count differs from completed export')
        for row in observations.find({'run_id': run['_id']}):
            digest = fingerprint({k: v for k, v in row.items() if k != 'content_sha256'})
            if expected.get(row['_id']) != row.get('content_sha256') or digest != row.get('content_sha256'):
                raise ValueError('Persisted observation content conflict; existing evidence was not overwritten')
        runs.update_one({'_id': run['_id']}, {'$set': dict(status='complete')})
    except Exception as exc:
        runs.update_one({'_id': run['_id']}, {'$set': dict(status='failed', error=str(exc))})
        raise


def build_behavior_signal_inputs(experiment_bundle, *, seed=17, alpha=.01,
                                 reference_bundle=None, write=False, progress=None, normal_day_roles=None):
    if not 0 < alpha < 1:
        raise ValueError('Require 0 < alpha < 1')
    roles = dict(normal_day_roles or {})
    from datetime import date
    for day, role in roles.items():
        if date.fromisoformat(day).isoformat() != day or role not in ('normal_group_train', 'normal_group_calibration', 'normal_group_test'):
            raise ValueError('Invalid normal group day/role')
    source_folder = Path(experiment_bundle).resolve()
    manifest_path = source_folder / 'manifest.json'; status_path = source_folder / 'run_status.json'
    experiment_manifest_sha = _sha(manifest_path)
    experiment = json.loads(manifest_path.read_text(encoding='utf-8'))
    if (experiment.get('version') != 'neighborhood_ablation_v1' or experiment.get('status') != 'complete'
            or json.loads(status_path.read_text())['status'] != 'complete'):
        raise ValueError('Require a complete neighborhood experiment bundle')
    if not all(experiment.get(k) for k in ('paired_initialization_verified', 'weights_unchanged_during_evaluation', 'source_unchanged_verified')):
        raise ValueError('Experiment verification flags are incomplete')
    selected = [r for r in experiment['artifacts'] if (r['seed'], r['variant'], r['arm']) == (seed, 'spectral', 'neighborhood')]
    if len(selected) != 1:
        raise ValueError('Require exactly one spectral/neighborhood checkpoint for the requested seed')
    artifact = selected[0]; checkpoint_path = (source_folder / artifact['checkpoint']).resolve()
    if not checkpoint_path.is_relative_to(source_folder):
        raise ValueError('Checkpoint path escapes bundle')
    scaler_path = checkpoint_path.parent / 'feature_scaler.npz'
    if _sha(checkpoint_path) != artifact['checksum'] or _sha(scaler_path) != artifact['scaler_checksum']:
        raise ValueError('Experimental checkpoint/scaler checksum mismatch')
    reference = Path(reference_bundle or experiment['reference_bundle']).resolve()
    _, scaler, parameters, _, _, saved = load_reference_bundle(reference)
    reference_manifest_sha = _sha(reference / 'manifest.json')
    historical_days = set(saved['source_signatures']) | set(experiment['source_signatures'])
    if set(roles) & historical_days:
        raise ValueError('New normal days must not reuse a historical training/evaluation day')
    if saved['run_id'] != experiment['reference_run_id'] or saved['checkpoint_sha256'] != experiment['reference_checkpoint_sha256'] or saved['reference_arrays_sha256'] != experiment['reference_arrays_sha256']:
        raise ValueError('Normal reference differs from the experiment')
    with np.load(scaler_path, allow_pickle=False) as arrays:
        if set(arrays.files) != set(scaler) or any(not np.array_equal(arrays[k], scaler[k]) for k in scaler):
            raise ValueError('Experimental feature scaler differs from pinned reference')
    checkpoint = torch.load(checkpoint_path, map_location='cpu', weights_only=True)
    if checkpoint.get('version') != 'neighborhood_ablation_checkpoint_v1' or (checkpoint['variant'], checkpoint['arm'], checkpoint['seed']) != ('spectral', 'neighborhood', seed):
        raise ValueError('Experimental checkpoint metadata mismatch')
    if checkpoint['parameters'] != experiment['parameters'] or checkpoint['selected_epoch'] != artifact['selected_epoch']:
        raise ValueError('Checkpoint architecture/selection differs from manifest')
    model = NeighborhoodAutoencoder(len(scaler['mean']), parameters['hidden_dim'], parameters['latent_dim'], parameters['layers'], 'spectral')
    model.load_state_dict(checkpoint['state_dict']); model.eval()
    normalization = {k: np.asarray(v, dtype=bool if k == 'active' else np.int64 if k == 'training_target_count' else np.float32)
                     for k, v in checkpoint['target_scaler'].items()}
    width = 1 + 2 * len(scaler['mean'])
    if any(normalization[k].shape != (width,) for k in ['mean', 'scale', 'active']) or not np.isfinite(normalization['mean']).all() or not np.isfinite(normalization['scale']).all() or np.any(normalization['scale'] <= 0):
        raise ValueError('Invalid neighborhood normalization')
    normalization['feature_baseline'] = scaler['baseline']
    # IDs depend on immutable inputs/policy, never on labels or observed deviations.
    identity = dict(version=VERSION, experiment_run_id=experiment['run_id'], checkpoint=artifact['checksum'],
        feature_scaler=artifact['scaler_checksum'], seed=seed, alpha=alpha,
        calibration_policy='normal_calibration_only_connected_isolated_v1',
        source_signatures=experiment['source_signatures'], lineage_signatures=experiment['lineage_signatures'])
    if roles:
        identity['normal_group_day_roles'] = roles
        identity['calibration_policy'] += '_whole_day_group_roles_v1'
    run_id = fingerprint(identity); calibration_id = fingerprint(dict(run_id=run_id, role='calibration'))
    folder = document_directory('autoencoder', layer=1, day=saved['normal_day']) / 'signal_inputs' / 'runs' / uuid.uuid4().hex
    folder.mkdir(parents=True); dump_json(folder / 'run_status.json', dict(status='building', run_id=run_id))
    previous_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        with torch.random.fork_rng(devices=[]), threadpool_limits(limits=1):
            db = get_db(); graphs = []; source = []; lineage = []; seen = set()
            for day in [saved['normal_day'], *experiment['days']]:
                if progress:
                    progress(f'[SIGNAL INPUTS] Verify source {day}')
                raw = sorted(load_raw_chunks(day), key=lambda g: g.chunk); source.extend(raw)
                if _signatures(raw) != experiment['source_signatures'][day]:
                    raise ValueError('Source graph changed since neighborhood experiment')
                retained, rows, _ = audit_graph_identities(db, raw, seen,
                    'reference' if day == saved['normal_day'] else 'additional_day',
                    reject=day == saved['normal_day'], origin_field=saved['origin_id_field'], progress=progress)
                graphs.extend(retained); lineage.extend(rows)
            signatures = {r['graph_key']: r['raw_signature'] for r in lineage}
            if signatures != experiment['lineage_signatures']:
                raise ValueError('Raw source/provenance changed since experiment')
            if roles:
                # Protect every previously used candidate, including historical
                # evaluation days not emitted by the current experiment.
                from .normal_behavior import record_identity
                from ingestion.services.graph.components import load_node_documents
                protected = list(source); protected_signatures = {}
                for day in sorted(historical_days - set(experiment['source_signatures'])):
                    history = sorted(load_raw_chunks(day), key=lambda g: g.chunk)
                    if not history:
                        raise ValueError(f'Missing historical source {day}; cannot audit unseen data')
                    protected.extend(history)
                    protected_signatures[day] = _signatures(history)
                for graph in protected:
                    ids = [str(r['original_id']) for r in graph.lineage]
                    docs = load_node_documents(db, ids, 'security_data')
                    if len(docs) != len(ids):
                        raise ValueError('Missing historical raw records for unseen-data audit')
                    for doc in docs.values():
                        seen.update(record_identity(doc, saved['origin_id_field']))
                history_rows = []
                for day in sorted(protected_signatures):
                    history = [g for g in protected if g.day == day]
                    _, rows, _ = audit_graph_identities(db, history, set(), 'historical_protected',
                        reject=False, origin_field=saved['origin_id_field'], progress=progress)
                    history_rows.extend(rows)
                for day, role in sorted(roles.items()):
                    if progress:
                        progress(f'[SIGNAL INPUTS] New normal day {day}: {role}')
                    raw = sorted(load_raw_chunks(day), key=lambda g: g.chunk)
                    if not raw:
                        raise ValueError(f'No graphs for new normal day {day}')
                    retained, rows, labels = audit_graph_identities(db, raw, seen, role,
                        reject=True, origin_field=saved['origin_id_field'], progress=progress)
                    if any(label != 0 for values in labels.values() for label in values):
                        raise ValueError(f'{day}: all new normal reference candidates must have raw label=0')
                    graphs.extend(retained); source.extend(raw); lineage.extend(rows)
                identity['source_signatures'] = dict(experiment['source_signatures'],
                    **{day: _signatures([g for g in source if g.day == day]) for day in roles})
                identity['lineage_signatures'] = {r['graph_key']: r['raw_signature'] for r in lineage}
                identity['protected_historical_signatures'] = protected_signatures
                identity['protected_historical_lineage'] = {r['graph_key']: r['raw_signature'] for r in history_rows}
                run_id = fingerprint(identity); calibration_id = fingerprint(dict(run_id=run_id, role='calibration'))
                dump_json(folder / 'run_status.json', dict(status='building', run_id=run_id))
                signatures = identity['lineage_signatures']
            split = reference_splits([g for g in graphs if g.day == saved['normal_day']])
            if split != saved['chunk_splits']:
                raise ValueError('Reference splits changed')
            chunks = prepare_chunks(graphs, {g.key: split.get(g.key, roles.get(g.day, 'additional_day')) for g in graphs},
                scaler, seed=seed, max_pairs=parameters['max_pairs'], progress=progress,
                required_splits=('train', 'validation', 'calibration', 'test'))
            frozen = {k: v.clone() for k, v in model.state_dict().items()}
            def infer(chunk):
                _, _, _, arrays = _evaluate(model, chunk, normalization, neighborhood_targets(chunk), {})
                return arrays
            calibration = fit_calibration([(c.split, infer(c)) for c in chunks if c.split == 'calibration'], alpha)
            dump_json(folder / 'calibration.json', {k: {n: v for n, v in state.items() if n != 'values'} for k, state in calibration.items()})
            np.savez_compressed(folder / 'calibration_arrays.npz', **{k.replace(':', '_'): v['values'] for k, v in calibration.items()})
            summaries = {}; samples = {}; observation_count = 0
            temporary = folder / 'observations.jsonl.tmp'
            with temporary.open('w', encoding='utf-8') as stream:
                for chunk in chunks:
                    if progress:
                        progress(f'[SIGNAL INPUTS] Frozen inference {chunk.graph.key}')
                    arrays = infer(chunk)
                    for i, node_id in enumerate(arrays['node_ids']):
                        signals = {name: channel_value(name, arrays, i, calibration, calibration_id) for name in CHANNELS}
                        for name in ['cross_level_structure', 'temporal_context']:
                            signals[name] = dict(status='not_computed', reason='not_implemented', residual=None,
                                                 tail_probability=None, threshold=None, exceeds_tail=None)
                        block = chunk.original.blocks[int(arrays['component_index'][i])]
                        entity = dict(type='candidate_flow', structural_layer=1, node_id=str(node_id),
                            graph_key=chunk.graph.key, chunk_index=chunk.graph.chunk, source_day=chunk.graph.day,
                            component_id=block.get('source_component_id'), local_component_index=int(arrays['component_index'][i]),
                            meta_component_id=None)
                        row = dict(_id=fingerprint(dict(run_id=run_id, graph=chunk.graph.key, node=str(node_id))),
                            schema_version=VERSION, run_id=run_id, entity=entity, split=chunk.split,
                            raw_source=dict(collection='security_data', record_id=str(arrays['raw_record_ids'][i]),
                                canonical_event_id=None, canonical_origin_status='not_verified',
                                event_time=None, event_time_status='not_loaded_no_temporal_signal'),
                            source_signature=identity['source_signatures'][chunk.graph.day][chunk.graph.key],
                            raw_lineage_signature=signatures[chunk.graph.key],
                            inference_graph_signature=chunk.graph.signature, model_id=artifact['checksum'],
                            reference_run_id=saved['run_id'], calibration_id=calibration_id,
                            representation=dict(view='full_topology_full_active_features', vector=arrays['latent'][i].tolist()),
                            residual_view='edge_holdout_topology_fixed_masked_features', isolated=bool(arrays['isolated'][i]),
                            signals=signals, fusion=dict(status='not_computed', score=None, alert=None),
                            quality=dict(contract_valid=True, release_status='experimental', operational_ready=False,
                                calibration_diagnostic_in_sample=chunk.split == 'calibration',
                                missing_signal_families=['cross_level_structure', 'temporal_context']))
                        validate_observation(row)
                        row['content_sha256'] = fingerprint(row)
                        stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n'); observation_count += 1
                        sample_key = (chunk.graph.day, chunk.split, row['isolated'])
                        if len(samples.setdefault(sample_key, [])) < 2:
                            samples[sample_key].append(row)
                        for name in CHANNELS:
                            signal = signals[name]; key = (chunk.graph.day, chunk.split, name, signal['calibration_group'])
                            counts = summaries.setdefault(key, dict(nodes=0, valid=0, unavailable=0, uncalibrated=0, tail_exceedances=0))
                            counts['nodes'] += 1; counts[signal['status']] += 1
                            counts['tail_exceedances'] += signal['exceeds_tail'] is True
            temporary.rename(folder / 'observations.jsonl')
            if any(not torch.equal(v, frozen[k]) for k, v in model.state_dict().items()):
                raise ValueError('Model changed during frozen signal replay')
            def verify():
                for day in identity['source_signatures']:
                    if _signatures(load_raw_chunks(day)) != identity['source_signatures'][day]:
                        raise ValueError('Source graph changed during export')
                _verify_raw_sources(db, source, signatures)
                if roles:
                    for day, expected in protected_signatures.items():
                        if _signatures(load_raw_chunks(day)) != expected:
                            raise ValueError('Historical protected graph changed during export')
                    _verify_raw_sources(db, [g for g in protected if g.day in protected_signatures], identity['protected_historical_lineage'])
                if (_sha(manifest_path) != experiment_manifest_sha
                        or _sha(reference / 'manifest.json') != reference_manifest_sha
                        or _sha(reference / 'reference_arrays.npz') != saved['reference_arrays_sha256']):
                    raise ValueError('Pinned experiment/reference metadata changed during export')
                if _sha(checkpoint_path) != artifact['checksum'] or _sha(scaler_path) != artifact['scaler_checksum']:
                    raise ValueError('Checkpoint/scaler changed during export')
            verify()
            report = [dict(day=k[0], split=k[1], signal=k[2], calibration_group=k[3], **v,
                tail_exceedance_fraction=v['tail_exceedances']/v['valid'] if v['valid'] else None,
                interpretation='normal_heldout_tail_fraction' if k[1] in ('test', 'normal_group_test') else 'diagnostic_not_false_positive_rate') for k, v in sorted(summaries.items())]
            write_csv(folder / 'signal_coverage.csv', report); write_csv(folder / 'lineage_audit.csv', lineage)
            dump_json(folder / 'input_samples.json', [r for group in samples.values() for r in group])
            contract = dict(version=VERSION, unit='candidate_flow_L1', available_signals=list(CHANNELS),
                validity='status_valid_requires_observed_targets_and_sufficient_matching_normal_calibration',
                tail_probability='(1 + calibration_values_greater_or_equal_to_residual)/(n+1); ties_conservative',
                exceeds_tail='strict_residual_greater_than_calibration_order_statistic; diagnostic_not_alert',
                missing_values='null_with_explicit_status; never_zero_or_normal',
                tail_direction='smaller_tail_probability_means_larger_deviation; not_attack_probability',
                familywise_limit='per_signal_alpha_is_not_a_fused_or_familywise_false_alarm_rate',
                reference_basis='user_declared_normal_label_artificial_mixture; upstream_sampling_may_use_labels',
                calibration_limit='artificial_reference_and_dependent_nodes_do_not_guarantee_operational_false_alarm_rate',
                fusion='not_computed_no_ridge_no_final_score_no_alerts',
                provenance='source_hashes_verified; canonical_original_event_identity_not_verified',
                collections=dict(runs='behavior_analysis_runs', observations='behavior_observations'),
                consumption='require_parent_run_status_complete_and_signal_status_valid; retain_split_and_quality_flags',
                immutable_identity=identity)
            dump_json(folder / 'signal_contract.json', contract)
            run = dict(_id=run_id, schema_version=VERSION, identity=identity, calibration_id=calibration_id,
                observation_count=observation_count, payload_sha256=_sha(folder / 'observations.jsonl'),
                calibration_sha256=_sha(folder / 'calibration_arrays.npz'), source_verified=True,
                model_frozen_verified=True, contract=contract, fusion_status='not_computed', operational_ready=False)
            dump_json(folder / 'manifest.json', dict(run, status='complete', mongo_write_requested=write))
            verify()
            if write:
                persist_inputs(db, run, folder / 'observations.jsonl')
            dump_json(folder / 'run_status.json', dict(status='complete', run_id=run_id, mongo_written=write,
                completed_at=datetime.now(timezone.utc).isoformat()))
    except BaseException as exc:
        dump_json(folder / 'run_status.json', dict(status='failed', run_id=run_id, error=f'{type(exc).__name__}: {exc}'))
        if progress:
            progress(f'[SIGNAL INPUTS] Failed/incomplete export: {folder}')
        raise
    finally:
        torch.set_num_threads(previous_threads)
    return dict(directory=str(folder), run_id=run_id, observations=observation_count, mongo_written=write)
