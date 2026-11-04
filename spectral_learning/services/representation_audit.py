"""Versioned, frozen-model behavior representation audit; no scoring stage."""
from datetime import date
from pathlib import Path
import uuid

import numpy as np
import torch
from mongoengine import get_db
from threadpoolctl import threadpool_limits

from ingestion.utils.document_paths import document_directory
from .autoencoder_inputs import load_raw_chunks, prepare_chunks, FEATURES
from .normal_behavior import audit_graph_identities, reference_splits, _signatures, _verify_raw_sources
from .normal_behavior_reports import load_reference_bundle
from .representation_quality import audit_chunk, covering_masks, measured_neighborhood
from .message_passing_reports import write_csv
from .spectral_reports import dump_json, save
import matplotlib.pyplot as plt


def _write_figures(folder, quality, masks):
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    variants = sorted({r['model'] for r in quality})
    for variant in variants:
        rows = [r for r in quality if r['model'] == variant]
        axes[0].plot(range(len(rows)), [r['effective_rank'] for r in rows], marker='.', label=variant)
        axes[1].plot(range(len(rows)), [r['mask_relative_latent_change_mean'] if r['mask_relative_latent_change_mean'] is not None else np.nan for r in rows], marker='.', label=variant)
        subset = [r for r in masks if r['model'] == variant and r['mse'] is not None]
        axes[2].scatter([r['targets'] for r in subset], [r['mse'] for r in subset], s=8, alpha=.4, label=variant)
    axes[0].set(title='Full-view latent covariance effective rank', xlabel='Audit graph order (not time)', ylabel='Effective rank')
    axes[1].set(title='Feature-mask sensitivity on fixed masked topology', xlabel='Audit graph order (not time)', ylabel='Relative latent L2 change')
    axes[2].set(title='Disjoint-mask reconstruction diagnostics', xlabel='Masked target entries', ylabel='Transformed-space MSE')
    for ax in axes:
        ax.legend(fontsize=8)
    fig.suptitle('Behavior representation audit: no anomaly decisions or label-based selection')
    fig.tight_layout(); save(fig, folder / 'representation_quality')
    fig, ax = plt.subplots(figsize=(14, 5)); ax.axis('off')
    stages = [('Pinned graphs / raw lineage\nSaved scaler + frozen checkpoints', .12),
              ('Spectral-aware encoder\nFull-view Z + component pooling', .38),
              ('Covering feature masks\nFixed topology, same masks per model', .65),
              ('Coverage / geometry / stability\nVersioned ML output contract', .90)]
    for text, x in stages:
        ax.text(x, .6, text, ha='center', va='center', transform=ax.transAxes, fontsize=9,
                bbox=dict(boxstyle='round,pad=.6', fc='#e5eff6', ec='#40596b'))
    for (_, a), (_, b) in zip(stages, stages[1:]):
        ax.annotate('', xy=(b-.12, .6), xytext=(a+.12, .6), xycoords='axes fraction', arrowprops=dict(arrowstyle='->'))
    ax.text(.5, .18, 'No training, threshold fitting, signal fusion or attack classification\nMask-subset variation is a sensitivity measurement, not calibrated predictive uncertainty',
            ha='center', transform=ax.transAxes, fontsize=11)
    ax.set_title('Current phase: ML core and behavior representation', fontsize=15)
    save(fig, folder / 'representation_audit_schematic')


def run_representation_audit(reference_bundle, days=(), *, mask_passes=5, progress=None):
    if not 2 <= mask_passes <= 20:
        raise ValueError('Require 2..20 disjoint covering mask passes')
    models, scaler, parameters, _, _, saved = load_reference_bundle(reference_bundle)
    normal_day = saved['normal_day']
    days = list(days)
    if normal_day in days or len(set(days)) != len(days):
        raise ValueError('Additional days must be distinct and different from the reference day; reference is always included')
    for day in [normal_day, *days]:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError('Use YYYY-MM-DD dates')
    folder = document_directory('autoencoder', layer=1, day=normal_day) / 'representation_audit' / 'runs' / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=False)
    dump_json(folder / 'run_status.json', dict(status='building'))
    frozen = {name: {key: value.detach().clone() for key, value in item['model'].state_dict().items()}
              for name, item in models.items()}
    try:
        db = get_db(); seen = set(); lineage = []; source_graphs = []; signatures = {}; audited = {}
        for day in [normal_day, *days]:
            if progress:
                progress(f'[REPRESENTATION] Load pinned source: {day}')
            graphs = sorted(load_raw_chunks(day), key=lambda g: g.chunk)
            signatures[day] = _signatures(graphs); source_graphs.extend(graphs)
            kept, rows, _ = audit_graph_identities(db, graphs, seen, 'reference' if day == normal_day else 'additional_day',
                reject=day == normal_day, origin_field=saved['origin_id_field'], progress=progress)
            audited[day] = kept; lineage.extend(rows)
        write_csv(folder / 'lineage_audit.csv', lineage)
        if any(not graphs for graphs in audited.values()):
            raise ValueError('No independent retained nodes for an audit day; inspect lineage_audit.csv')
        lineage_signatures = {row['graph_key']: row['raw_signature'] for row in lineage}
        if signatures[normal_day] != saved['source_signatures'][normal_day]:
            raise ValueError('Reference graph signatures differ from the saved model source')
        splits = reference_splits(audited[normal_day])
        if splits != saved['chunk_splits'] or any(lineage_signatures[g.key] != saved['lineage_signatures'][g.key] for g in audited[normal_day]):
            raise ValueError('Reference split, raw records or provenance differs from the saved model')
        quality, masks, features, coverage = [], [], [], []
        artifact_rows = []
        previous_threads = torch.get_num_threads()
        try:
            torch.set_num_threads(1)
            with threadpool_limits(limits=1):
                for day, graphs in audited.items():
                    for index, graph in enumerate(graphs):
                        if progress:
                            progress(f'[REPRESENTATION] {day}: graph {index+1}/{len(graphs)}; nodes={len(graph.node_ids)}; covering passes={mask_passes}')
                        split = splits[graph.key] if day == normal_day else 'additional_day'
                        chunk = prepare_chunks([graph], {graph.key: split}, scaler,
                            seed=parameters['seed']+index, max_pairs=parameters['max_pairs'], required_splits=())[0]
                        output = folder / day / f'chunk-{int(graph.chunk)}'
                        output.mkdir(parents=True, exist_ok=False)
                        mask_seed = parameters['seed']+30000+index
                        np.savez_compressed(output / 'inputs.npz', node_ids=np.asarray(graph.node_ids, dtype=str),
                            original_ids=np.asarray([r['original_id'] for r in graph.lineage], dtype=str),
                            feature_names=np.asarray(FEATURES), raw_features=graph.features,
                            transformed_features=chunk.values,
                            raw_observed_mask=graph.feature_mask, observed_active_mask=chunk.mask,
                            feature_masks=covering_masks(chunk.mask, mask_passes, mask_seed),
                            full_edge_index=chunk.original.arrays['edge_index'], full_edge_weight=chunk.original.arrays['edge_weight'],
                            masked_edge_index=chunk.spectral.arrays['edge_index'],
                            masked_edge_weight=chunk.spectral.arrays['edge_weight'],
                            full_node_spectral=chunk.original.arrays['node_spectral'],
                            full_edge_spectral=chunk.original.arrays['edge_spectral'],
                            full_edge_spectral_mask=chunk.original.arrays['edge_spectral_mask'],
                            masked_node_spectral=chunk.spectral.arrays['node_spectral'],
                            masked_node_spectral_mask=chunk.spectral.arrays['node_spectral_mask'],
                            masked_edge_spectral=chunk.spectral.arrays['edge_spectral'],
                            masked_edge_spectral_mask=chunk.spectral.arrays['edge_spectral_mask'],
                            full_node_spectral_mask=chunk.original.arrays['node_spectral_mask'],
                            component_index=chunk.original.arrays['block_index'],
                            component_ids=np.asarray([b['source_component_id'] for b in chunk.original.blocks], dtype=str))
                        np.savez_compressed(output / 'measured_neighborhood.npz',
                            **measured_neighborhood(chunk.original.arrays, chunk.values, chunk.mask))
                        for variant, item in models.items():
                            summary, arrays, rows = audit_chunk(item['model'], chunk, passes=mask_passes,
                                                               seed=mask_seed)
                            common = dict(day=day, graph_key=graph.key, split=split, model=variant)
                            quality.append(dict(common, **summary))
                            features.extend(dict(common, **row) for row in rows)
                            for part in range(mask_passes):
                                targets = int(arrays['mask_target_count'][part].sum())
                                sse = float((arrays['mask_reconstruction_mse'][part] * arrays['mask_target_count'][part]).sum())
                                masks.append(dict(common, mask_pass=part+1, targets=targets,
                                                  mse=sse/targets if targets else None))
                            np.savez_compressed(output / f'{variant}_representation.npz', **arrays)
                            artifact_rows.append(dict(common, mask_seed=mask_seed,
                                topology_holdout_seed=parameters['seed']+index,
                                path=str(output / f'{variant}_representation.npz')))
                        coverage.append(dict(day=day, graph_key=graph.key, nodes=len(graph.node_ids),
                            observed_entries=int(graph.feature_mask.sum()), active_observed_entries=int(chunk.mask.sum()),
                            nodes_without_active_features=int((~chunk.mask.any(axis=1)).sum()),
                            observed_inactive_entries=int((graph.feature_mask & ~scaler['active'][None, :]).sum()),
                            full_graph_isolates=sum(b['node_count']==1 for b in chunk.original.blocks),
                            complete_raw_day_coverage='not_inferred'))
        finally:
            torch.set_num_threads(previous_threads)
        for name, item in models.items():
            if any(not torch.equal(value, frozen[name][key]) for key, value in item['model'].state_dict().items()):
                raise ValueError('Frozen model weights changed during representation audit')
        for day, signature in signatures.items():
            if _signatures(load_raw_chunks(day)) != signature:
                raise ValueError('Source graph/features changed during representation audit')
        _verify_raw_sources(db, source_graphs, lineage_signatures)
        write_csv(folder / 'graph_representation_quality.csv', quality)
        write_csv(folder / 'covering_mask_metrics.csv', masks)
        write_csv(folder / 'feature_reconstruction.csv', features)
        write_csv(folder / 'coverage.csv', coverage)
        contract = dict(version='behavior_representation_contract_v1', unit='candidate_flow', structural_layer=1,
            trained_model_scope='shared_normal_reference_L1', latent_dimension=parameters['latent_dim'],
            feature_names=list(FEATURES), reference_bundle=str(Path(reference_bundle).resolve()),
            raw_pointer_semantics='original_ids point to security_data rows; canonical original-event identity requires preserved source provenance',
            model_checkpoint_sha256=saved['checkpoint_sha256'], scaler_reference_sha256=saved['reference_arrays_sha256'],
            latent_view='full_source_topology_and_full_active_observed_features',
            mask_sensitivity_view='same_edge_holdout_topology_with_vs_without_feature_masks',
            topology_change_view='full_vs_edge_holdout_topology_without_feature_corruption',
            pooling_view='candidate_count_weighted_L1_component_mean_and_std_not_trained_L2_encoder',
            named_feature_weights=dict(status='not_estimated', values=None),
            measured_neighborhood='full_graph_degree_and_unweighted_observed_active_neighbor_feature_moments_in_transformed_space; measured_not_predicted',
            uncertainty=dict(status='not_calibrated', mask_subset_variation='sensitivity_only'),
            cross_level_training='not_implemented_by_this_audit', neighborhood_objective='not_added',
            temporal_semantics='processing_chunks_not_time_windows; reference_day_is_artificial_mixture',
            validity_semantics='Finite observed active values; historical zero filling cannot be reversed',
            decisions='No anomaly score, alert, class decision, threshold fit or model update')
        dump_json(folder / 'representation_contract.json', contract)
        _write_figures(folder, quality, masks)
        # Recheck after report I/O too; no stale-source audit is called complete.
        for day, signature in signatures.items():
            if _signatures(load_raw_chunks(day)) != signature:
                raise ValueError('Source changed during report writing')
        _verify_raw_sources(db, source_graphs, lineage_signatures)
        manifest = dict(version='behavior_representation_audit_v1', status='complete', normal_day=normal_day,
            model_acceptance='not_decided_by_this_audit',
            reference_parameters=parameters,
            additional_days=days, reference_run_id=saved['run_id'], mask_passes=mask_passes,
            mask_policy='seeded_disjoint_partitions_each_active_observed_feature_once; approximately 1/passes per view',
            weights_unchanged_verified=True, source_signatures=signatures, lineage_signatures=lineage_signatures,
            artifacts=artifact_rows, contract=contract,
            limits=['No attack detection quality or operational readiness claimed.',
                    'Mask subsets differ in targets; MSE variation is not predictive uncertainty.',
                    'Geometry metrics have no arbitrary promotion cutoff; homogeneous graphs can legitimately have low rank.',
                    'Only source ID/content matches are removed; modified copies with missing provenance may remain.',
                    'Eigenbasis invariance is covered by existing core tests, not independently repeated on every graph in this audit.',
                    'This audits one saved training seed; training-seed stability requires separate reference runs.'])
        dump_json(folder / 'manifest.json', manifest)
        text = ['Behavior representation audit — no scoring/detection',
                f'Reference: {normal_day} / {saved["run_id"]}', f'Additional days: {days}',
                f'Model weights unchanged; {mask_passes} disjoint covering feature masks.',
                'All active observed target entries are predicted exactly once.',
                'Effective rank and mask sensitivity are diagnostics, not anomaly probabilities.', *manifest['limits']]
        (folder / 'representation_summary.txt').write_text('\n'.join(text)+'\n', encoding='utf-8')
        dump_json(folder / 'run_status.json', dict(status='complete'))
        return dict(directory=str(folder), manifest=str(folder / 'manifest.json'),
                    quality=str(folder / 'graph_representation_quality.csv'), contract=str(folder / 'representation_contract.json'),
                    schematic=str(folder / 'representation_audit_schematic.png'), overview=str(folder / 'representation_quality.png'))
    except Exception as exc:
        dump_json(folder / 'run_status.json', dict(status='failed', error=str(exc)))
        if progress:
            progress(f'[REPRESENTATION] FAILED; diagnostics: {folder}')
        raise
