"""Versioned neighborhood-objective ablation; reads MongoDB, writes only documents."""
from datetime import date
from pathlib import Path
import uuid

import matplotlib.pyplot as plt
import numpy as np
import torch
from mongoengine import get_db
from threadpoolctl import threadpool_limits

from .autoencoder_inputs import load_raw_chunks, prepare_chunks
from .autoencoder_training import evaluate_chunk, forward_chunk
from .normal_behavior import audit_graph_identities, reference_splits, _signatures, _verify_raw_sources
from .normal_behavior_reports import load_reference_bundle, _sha
from .neighborhood_learning import train_pair, normalized_targets
from .representation_quality import latent_geometry
from .spectral_reports import dump_json, save
from .message_passing_reports import write_csv
from ingestion.utils.document_paths import document_directory


def _evaluate(model, chunk, normalization, target, identity):
    values, mask = normalized_targets(target, normalization)
    width = chunk.values.shape[1]
    with torch.no_grad():
        _, z, _, _ = forward_chunk(model, chunk, chunk.fixed_hidden)
        predicted = model.decode_neighborhood(z).numpy()
    if not np.isfinite(predicted).all():
        raise ValueError('Nonfinite neighborhood predictions')
    squared = (predicted - values) ** 2
    constant = values ** 2  # zero normalized prediction = normal train target mean
    raw_prediction = predicted * normalization['scale'] + normalization['mean']
    result = evaluate_chunk(model, chunk, normalization['feature_baseline'])
    rows = []; node = {}; n = len(chunk.values)
    original_isolates = result['original_isolate']
    for name, section in [('degree', slice(0, 1)), ('neighbor_mean', slice(1, 1 + width)),
                          ('neighbor_std', slice(1 + width, None))]:
        valid = mask[:, section]; count = valid.sum(axis=1)
        node[name + '_mse'] = np.divide(np.where(valid, squared[:, section], 0).sum(axis=1), count,
            out=np.zeros(n), where=count > 0)
        node[name + '_valid'] = count > 0
        node[name + '_target_count'] = count
        for group, chosen in [('all', np.ones(n, dtype=bool)), ('isolated', original_isolates),
                              ('connected', ~original_isolates)]:
            selected = valid & chosen[:, None]; size = int(selected.sum())
            rows.append(dict(**identity, family=name, group=group, targets=size,
                sse=float(squared[:, section][selected].sum()),
                baseline_sse=float(constant[:, section][selected].sum()),
                mse=float(squared[:, section][selected].mean()) if size else None,
                train_constant_baseline_mse=float(constant[:, section][selected].mean()) if size else None))
    feature_rows = []
    for j, name in enumerate(chunk.graph.feature_names):
        for family, offset in [('neighbor_mean', 1), ('neighbor_std', 1 + width)]:
            chosen = mask[:, offset + j]; size = int(chosen.sum())
            feature_rows.append(dict(**identity, family=family, feature=name, targets=size,
                mse=float(squared[chosen, offset + j].mean()) if size else None,
                train_constant_baseline_mse=float(constant[chosen, offset + j].mean()) if size else None))
    primary = dict(**identity, **result['metrics'], **latent_geometry(result['latent']))
    for entry in result['coverage']:
        rows.append(dict(**identity, family='feature', group=entry['group'],
                         targets=entry['target_entries'], mse=entry['feature_mse'],
                         sse=(entry['feature_mse'] or 0) * entry['target_entries'], baseline_sse=None,
                         train_constant_baseline_mse=None))
    arrays = dict(node_ids=np.asarray(chunk.graph.node_ids, dtype=str),
        raw_record_ids=np.asarray([r['original_id'] for r in chunk.graph.lineage], dtype=str),
        component_index=chunk.original.arrays['block_index'], feature_hidden=chunk.fixed_hidden,
        neighborhood_target=target[0], neighborhood_target_valid=mask,
        neighborhood_prediction=raw_prediction, neighborhood_normalized_prediction=predicted,
        latent=result['latent'], feature_mse=result['node_error'], feature_valid=result['node_error_mask'],
        isolated=original_isolates, **node)
    return primary, rows, feature_rows, arrays


def _aggregate(rows):
    output = []
    keys = sorted({(r['day'], r['split'], r['variant'], r['arm'], r['seed'], r['family'], r['group']) for r in rows})
    names = ('day', 'split', 'variant', 'arm', 'seed', 'family', 'group')
    for key in keys:
        group = [r for r in rows if tuple(r[k] for k in names) == key]
        count = sum(r['targets'] for r in group); sse = sum(r['sse'] for r in group)
        baseline = sum(r['baseline_sse'] for r in group) if all(r['baseline_sse'] is not None for r in group) else None
        output.append(dict(zip(names, key), targets=count, mse=sse/count if count else None,
            train_constant_baseline_mse=baseline/count if count and baseline is not None else None,
            improvement_over_constant=1-sse/baseline if baseline is not None and baseline > 0 else None))
    return output


def _plots(folder, aggregate):
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    for ax, family in zip(axes, ['degree', 'neighbor_mean', 'neighbor_std']):
        selected = [r for r in aggregate if r['family'] == family and r['group'] == 'all'
                    and r['split'] in ('test', 'additional_day') and r['mse'] is not None]
        labels = sorted({(r['day'], r['variant']) for r in selected})
        for arm, shift in [('baseline', -.18), ('neighborhood', .18)]:
            means, stds = [], []
            for day, variant in labels:
                x = [r['mse'] for r in selected if (r['day'], r['variant'], r['arm']) == (day, variant, arm)]
                means.append(np.mean(x)); stds.append(np.std(x))
            ax.bar(np.arange(len(labels)) + shift, means, .36, yerr=stds, label=arm)
        ax.set_xticks(np.arange(len(labels)), [f'{d}\n{v}' for d, v in labels], rotation=25)
        ax.set(title=family, ylabel='Train-normalized target MSE'); ax.legend(fontsize=8)
    fig.suptitle('Held-out reconstruction; bars average training seeds, not detection accuracy')
    fig.tight_layout(); save(fig, folder / 'neighborhood_comparison')
    fig, ax = plt.subplots(figsize=(13, 4)); ax.axis('off')
    for x, text in [(0.12, 'Raw allowlisted features\n+ edge-held-out spectral graph'),
                    (.43, 'Preserved graph / spectral encoder\nLatent Z'),
                    (.76, 'Feature + relation decoders\nAuxiliary degree + neighbor mean/std')]:
        ax.text(x, .6, text, ha='center', va='center', transform=ax.transAxes,
                bbox=dict(boxstyle='round,pad=.7', fc='#e5eff6', ec='#40596b'), fontsize=10)
    for a, b in [(.25, .30), (.56, .60)]:
        ax.annotate('', xy=(b, .6), xytext=(a, .6), xycoords='axes fraction', arrowprops=dict(arrowstyle='->'))
    ax.text(.5, .15, 'Full-source neighborhood targets are supervision only, never encoder inputs.\nBaseline: auxiliary gradient stops at Z. New arm: auxiliary gradient reaches encoder.\nSame masks, seeds, epochs and primary validation selection; no alerts or automatic promotion.',
            ha='center', transform=ax.transAxes, fontsize=10)
    save(fig, folder / 'neighborhood_schematic')


def run_neighborhood_experiment(reference_bundle, days=(), *, seeds=(17, 29, 43), epochs=None,
                                auxiliary_weight=.1, progress=None):
    if not np.isfinite(auxiliary_weight) or auxiliary_weight <= 0:
        raise ValueError('auxiliary_weight must be finite and positive')
    seeds = list(seeds); days = list(days)
    if not seeds or len(set(seeds)) != len(seeds) or any(not isinstance(s, int) or not 0 <= s < 2**32 for s in seeds):
        raise ValueError('Provide distinct integer seeds in [0, 2**32)')
    _, scaler, parameters, _, _, saved = load_reference_bundle(reference_bundle)
    normal_day = saved['normal_day']; epochs = parameters['epochs'] if epochs is None else epochs
    if not isinstance(epochs, int) or epochs < 1:
        raise ValueError('epochs must be a positive integer')
    if len(set(days)) != len(days) or normal_day in days:
        raise ValueError('Additional days must be distinct and different from reference')
    for day in days:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError('Use YYYY-MM-DD dates')
    folder = document_directory('autoencoder', layer=1, day=normal_day) / 'neighborhood_learning' / 'runs' / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=False)
    dump_json(folder / 'run_status.json', dict(status='building'))
    previous_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        with threadpool_limits(limits=1), torch.random.fork_rng(devices=[]):
            db = get_db(); seen = set(); lineage = []; graphs = []; source = []; signatures = {}
            for day in [normal_day, *days]:
                if progress:
                    progress(f'[NEIGHBORHOOD] Load and audit {day}')
                raw = sorted(load_raw_chunks(day), key=lambda g: g.chunk); source.extend(raw)
                signatures[day] = _signatures(raw)
                kept, rows, _ = audit_graph_identities(db, raw, seen, 'reference' if day == normal_day else 'additional_day',
                    reject=day == normal_day, origin_field=saved['origin_id_field'], progress=progress)
                if not kept:
                    raise ValueError(f'No independent graphs retained for {day}')
                graphs.extend(kept); lineage.extend(rows)
            lineage_signatures = {r['graph_key']: r['raw_signature'] for r in lineage}
            reference = [g for g in graphs if g.day == normal_day]; splits = reference_splits(reference)
            if signatures[normal_day] != saved['source_signatures'][normal_day] or splits != saved['chunk_splits']:
                raise ValueError('Reference graph signatures or split changed from saved bundle')
            if any(lineage_signatures[g.key] != saved['lineage_signatures'][g.key] for g in reference):
                raise ValueError('Reference raw records/provenance changed from saved bundle')
            write_csv(folder / 'lineage_audit.csv', lineage)
            manifest = dict(version='neighborhood_ablation_v1', run_id=folder.name, status='building', normal_day=normal_day,
                reference_run_id=saved['run_id'], reference_bundle=str(Path(reference_bundle).resolve()),
                reference_checkpoint_sha256=saved['checkpoint_sha256'], reference_arrays_sha256=saved['reference_arrays_sha256'],
                days=days, seeds=seeds, parameters=dict(parameters, epochs=epochs), auxiliary_weight=auxiliary_weight,
                source_signatures=signatures, lineage_signatures=lineage_signatures,
                selection='minimum_primary_validation_loss_for_both_arms',
                training='fresh_paired_initialization_not_finetuning_saved_checkpoints',
                scaler='reuse_verified_reference_feature_scaler; neighborhood_scaler_fitted_on_normal_train_only',
                target_semantics='full_source_log1p_degree_and_unweighted_neighbor_feature_population_mean_std',
                std_validity='at_least_two_observed_neighbors; means_require_one; isolates_have_degree_target_only',
                baseline='same_auxiliary_heads_trained_on_detached_latent; encoder_receives_only_original_losses',
                promotion='none; separate_experimental_checkpoints_not_accepted_by_old_bundle_loader',
                limits=['Moments do not identify a full neighborhood distribution.',
                        'Full-source degree targets may be partly observable from encoder topology.',
                        'No anomaly calibration, alerts, MongoDB writes or automatic model promotion.',
                        'Artificial reference is not an independent temporal normal day; modified copies may evade lineage checks.',
                        'Historical zero filling is not repaired; reference inactive features remain excluded.',
                        'Additional days already inspected are development evidence, not untouched final tests.'])
            dump_json(folder / 'manifest.json', manifest)
            summaries = []; metrics = []; features = []; histories = []; artifacts = []
            for seed in seeds:
                prepared = prepare_chunks(graphs, {g.key: splits.get(g.key, 'additional_day') for g in graphs},
                    scaler, seed=seed, max_pairs=parameters['max_pairs'], progress=progress,
                    required_splits=('train', 'validation', 'calibration', 'test'))
                for variant in ('graph', 'spectral'):
                    pair, targets = train_pair(prepared, scaler, parameters, variant=variant, seed=seed,
                        epochs=epochs, auxiliary_weight=auxiliary_weight, progress=progress)
                    if not all(torch.equal(pair['baseline']['initial'][k], v) for k, v in pair['neighborhood']['initial'].items()):
                        raise ValueError('Paired initialization differs')
                    for arm, item in pair.items():
                        base = folder / f'seed-{seed}' / variant / arm; base.mkdir(parents=True)
                        normalization = dict(item['target_scaler'], feature_baseline=scaler['baseline'])
                        torch.save(dict(version='neighborhood_ablation_checkpoint_v1', variant=variant, arm=arm,
                            seed=seed, state_dict=item['state'], parameters=dict(parameters, epochs=epochs),
                            selected_epoch=item['selected_epoch'], auxiliary_weight=auxiliary_weight,
                            target_scaler={k: v.tolist() for k, v in item['target_scaler'].items()}), base / 'model.pt')
                        np.savez_compressed(base / 'feature_scaler.npz', **scaler)
                        for history in item['history']:
                            histories.append(dict(variant=variant, arm=arm, seed=seed, **history))
                        frozen = {k: v.clone() for k, v in item['model'].state_dict().items()}
                        for chunk in prepared:
                            identity = dict(day=chunk.graph.day, graph_key=chunk.graph.key, split=chunk.split,
                                            variant=variant, arm=arm, seed=seed)
                            summary, rows, feature_rows, arrays = _evaluate(item['model'], chunk, normalization,
                                targets[chunk.graph.key], identity)
                            summary['selected_epoch'] = item['selected_epoch']
                            summaries.append(summary); metrics.extend(rows); features.extend(feature_rows)
                            path = base / chunk.graph.day / f'chunk-{chunk.graph.chunk}.npz'; path.parent.mkdir(exist_ok=True)
                            np.savez_compressed(path, **arrays)
                        if any(not torch.equal(v, frozen[k]) for k, v in item['model'].state_dict().items()):
                            raise ValueError('Model changed during evaluation')
                        artifacts.append(dict(seed=seed, variant=variant, arm=arm,
                            checkpoint=str((base / 'model.pt').relative_to(folder)), checksum=_sha(base / 'model.pt'),
                            scaler_checksum=_sha(base / 'feature_scaler.npz'), selected_epoch=item['selected_epoch']))
            def verify():
                if any(_signatures(load_raw_chunks(day)) != signatures[day] for day in signatures):
                    raise ValueError('Source graph changed during experiment')
                _verify_raw_sources(db, source, lineage_signatures)
                if _sha(Path(reference_bundle) / 'reference_arrays.npz') != saved['reference_arrays_sha256'] or any(
                    _sha(Path(reference_bundle) / f'{v}_model.pt') != sha for v, sha in saved['checkpoint_sha256'].items()):
                    raise ValueError('Reference bundle changed during experiment')
            verify()
            aggregate = _aggregate(metrics)
            for name, rows in [('graph_metrics', summaries), ('neighborhood_metrics', metrics),
                               ('feature_neighborhood_metrics', features), ('aggregate_metrics', aggregate), ('training_history', histories)]:
                write_csv(folder / f'{name}.csv', rows)
            paired = []
            for row in aggregate:
                if row['arm'] != 'neighborhood':
                    continue
                other = next(r for r in aggregate if r['arm'] == 'baseline' and all(
                    r[k] == row[k] for k in ('day', 'split', 'variant', 'seed', 'family', 'group')))
                paired.append(dict(**{k: row[k] for k in ('day', 'split', 'variant', 'seed', 'family', 'group')},
                    targets=row['targets'], baseline_mse=other['mse'], neighborhood_mse=row['mse'],
                    mse_change=row['mse']-other['mse'] if row['mse'] is not None and other['mse'] is not None else None))
            write_csv(folder / 'paired_comparison.csv', paired)
            dump_json(folder / 'representation_contract.json', dict(
                version='neighborhood_representation_contract_v1', unit='candidate_flow', structural_layer=1,
                feature_names=list(graphs[0].feature_names),
                reconstruction_view='edge_holdout_topology_and_fixed_masked_features',
                latent_view='full_source_topology_and_full_active_features',
                neighborhood_targets='full_source_degree_log1p_and_neighbor_population_mean_std_in_reference_feature_space',
                residual_space='normal_train_standardized_neighborhood_targets',
                invalid_residuals='stored_zero_requires_corresponding_valid_flag_false; never_score_as_normal',
                neighborhood_head='unconstrained_normalized_regression; raw_predictions_may_exceed_physical_bounds',
                signal_status='experimental_uncalibrated_residuals; not_alerts_or_attack_probabilities',
                source_event_identity='raw_record_ids_require_canonical_provenance_for_modified_artificial_copies',
                missing_signals=['cross_level_deviation', 'real_event_temporal_context'],
                reference_run_id=saved['run_id']))
            _plots(folder, aggregate)
            (folder / 'summary.txt').write_text(
                'Behavior Representation: paired neighborhood-objective ablation.\n'
                'Compare normal held-out test first; external days are development replay.\n'
                'Lower neighbor MSE must be considered with primary feature/link quality, latent geometry, and seed variation.\n'
                'Means/std are moments, not a full probability distribution. Missing targets are invalid, not normal.\n'
                'No automatic acceptance, alert calibration or MongoDB output.\n', encoding='utf-8')
            verify(); manifest.update(status='complete', artifacts=artifacts, weights_unchanged_during_evaluation=True,
                                      paired_initialization_verified=True, source_unchanged_verified=True)
            dump_json(folder / 'manifest.json', manifest)
            dump_json(folder / 'run_status.json', dict(status='complete'))
    except BaseException as exc:
        dump_json(folder / 'run_status.json', dict(status='failed', error=f'{type(exc).__name__}: {exc}'))
        if progress:
            progress(f'[NEIGHBORHOOD] FAILED; incomplete output: {folder}')
        raise
    finally:
        torch.set_num_threads(previous_threads)
    return dict(directory=str(folder), metrics=str(folder / 'aggregate_metrics.csv'))
