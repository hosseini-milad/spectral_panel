"""Standalone model/data/statistics bundles and schematics for shared L1 AEs."""
from pathlib import Path
import json
import numpy as np
import torch
import networkx as nx
import matplotlib.pyplot as plt
from sklearn.metrics import roc_auc_score, average_precision_score

from ingestion.utils.document_paths import document_directory
from .spectral_reports import dump_json, save
from .message_passing_reports import write_csv
from .autoencoder_inputs import FEATURES, BINARY, log_values


def architecture(path, title='Layer-1 shared masked graph Autoencoder: experimental design'):
    fig, ax = plt.subplots(figsize=(16, 7)); ax.axis('off')
    boxes = [(.11, .73, 'L1 chunk graphs\nRaw feature view + masks\nMasked edges + recomputed spectra'),
             (.39, .73, 'ONE encoder shared across chunks\nFeature / graph / spectral variants\nTraining-only fitted scaling'),
             (.65, .73, 'Latent Z per candidate node\nDefault dimension 16\nComponent mean + SD handoff')]
    for x, y, label in boxes:
        ax.text(x, y, label, ha='center', va='center', transform=ax.transAxes, fontsize=10,
                bbox=dict(boxstyle='round,pad=.6', fc='#e1eef9', ec='#466477'))
    for a, b in zip(boxes, boxes[1:]):
        ax.annotate('', xy=(b[0]-.12, .73), xytext=(a[0]+.12, .73), xycoords='axes fraction', arrowprops=dict(arrowstyle='->', lw=2))
    for y, label in [(.84, 'Feature decoder\nContinuous + binary heads'), (.56, 'Symmetric pair decoder\nEdge presence + weight')]:
        ax.text(.91, y, label, ha='center', va='center', transform=ax.transAxes, fontsize=10,
                bbox=dict(boxstyle='round,pad=.6', fc='#e1f0e4', ec='#466477'))
        ax.annotate('', xy=(.80, y), xytext=(.76, .73), xycoords='axes fraction', arrowprops=dict(arrowstyle='->'))
    ax.text(.5, .32, 'Disjoint processing-chunk splits: train / validation / test (NOT a timestamp-based split)\nValidation selects checkpoint; held-out chunk results evaluated afterward\nIsolates: attribute reconstruction only, no invented spectral or relation targets', ha='center', transform=ax.transAxes, fontsize=12)
    ax.text(.5, .09, 'Reconstruction residuals are diagnostics, not calibrated anomaly probabilities.\nNo full spectral decoder, cross-day detector, weekly encoder or Ridge is trained here.', ha='center', transform=ax.transAxes, fontsize=11)
    ax.set_title(title, fontsize=16, pad=20); save(fig, path)


def graph_bundle(chunk, models, run_id):
    graph = chunk.graph
    folder = document_directory('autoencoder', graph.key, layer=1, day=graph.day, chunk=graph.chunk) / 'runs' / run_id
    folder.mkdir(parents=True, exist_ok=True)
    component_ids = [b['source_component_id'] for b in chunk.original.blocks]
    np.savez_compressed(folder / 'inputs.npz', node_ids=np.asarray(graph.node_ids, dtype=str),
        original_ids=np.asarray([row['original_id'] for row in graph.lineage], dtype=str), feature_names=np.asarray(FEATURES),
        raw_features=graph.features, raw_observed_mask=graph.feature_mask, targets=chunk.values,
        model_observed_mask=chunk.mask, evaluation_hidden_mask=chunk.fixed_hidden,
        original_edge_index=chunk.original.arrays['edge_index'], original_edge_weight=chunk.original.arrays['edge_weight'],
        input_edge_index=chunk.spectral.arrays['edge_index'], input_edge_weight=chunk.spectral.arrays['edge_weight'],
        inference_node_spectral=chunk.original.arrays['node_spectral'], inference_node_spectral_mask=chunk.original.arrays['node_spectral_mask'],
        inference_edge_spectral=chunk.original.arrays['edge_spectral'], inference_edge_spectral_mask=chunk.original.arrays['edge_spectral_mask'],
        node_spectral=chunk.spectral.arrays['node_spectral'], node_spectral_mask=chunk.spectral.arrays['node_spectral_mask'],
        edge_spectral=chunk.spectral.arrays['edge_spectral'], edge_spectral_mask=chunk.spectral.arrays['edge_spectral_mask'],
        relation_pairs=chunk.pairs, relation_presence_targets=chunk.pair_labels, hidden_positive_weight_targets=chunk.positive_weights,
        component_index=chunk.original.arrays['block_index'], component_ids=np.asarray(component_ids, dtype=str))
    metrics, features, coverage, components = [], [], [], []
    for variant, model in models.items():
        result = model['results'][graph.key]
        metrics.append(dict(model=variant, graph_key=graph.key, split=chunk.split, **result['metrics']))
        features.extend(dict(model=variant, graph_key=graph.key, split=chunk.split, **row) for row in result['feature_metrics'])
        coverage.extend(dict(model=variant, graph_key=graph.key, split=chunk.split, **row) for row in result['coverage'])
        np.savez_compressed(folder / f'{variant}_outputs.npz', latent=result['latent'], reconstruction=result['reconstruction'],
            masked_feature_mse=result['node_error'], error_valid=result['node_error_mask'], original_isolate=result['original_isolate'],
            relation_probability=result['pair_probability'], predicted_relation_weight=result['pair_weights'],
            component_latent_mean=result['pooled_mean'], component_latent_std=result['pooled_std'], component_size=result['pooled_size'],
            component_masked_mse=result['component_mse'], component_error_valid=result['component_target_count'] > 0,
            component_max_node_mse=result['component_max_node_mse'], component_target_count=result['component_target_count'])
        for i, component_id in enumerate(component_ids):
            components.append(dict(model=variant, component_id=component_id, split=chunk.split, nodes=int(result['pooled_size'][i]),
                target_entries=int(result['component_target_count'][i]),
                feature_mse=float(result['component_mse'][i]) if result['component_target_count'][i] else None,
                max_node_mse=float(result['component_max_node_mse'][i]) if result['component_target_count'][i] else None))
    write_csv(folder / 'metrics.csv', metrics); write_csv(folder / 'feature_metrics.csv', features); write_csv(folder / 'coverage_metrics.csv', coverage)
    write_csv(folder / 'component_metrics.csv', components)
    dump_json(folder / 'lineage.json', dict(graph_key=graph.key, split=chunk.split, node_ids=graph.node_ids, lineage=graph.lineage,
        components=[dict(component_id=b['source_component_id'], node_indices=b['node_indices']) for b in chunk.original.blocks]))
    fig, axes = plt.subplots(2, 2, figsize=(15, 11))
    for variant, model in models.items():
        result = model['results'][graph.key]; valid = result['node_error_mask']
        axes[0, 0].hist(result['node_error'][valid], bins=40, histtype='step', label=variant)
    axes[0, 0].set(title='Masked feature reconstruction residuals (not anomaly scores)', xlabel='Per-node MSE', ylabel='Nodes'); axes[0, 0].legend()
    axes[0, 1].bar([r['model'] for r in metrics], [r['feature_mse'] if r['feature_mse'] is not None else 0 for r in metrics])
    axes[0, 1].set(title=f'{chunk.split} chunk: reconstruction MSE', ylabel='Standardized continuous / binary probability error')
    selected = models['spectral']['results'][graph.key]
    latent = selected['latent']; centered = latent - latent.mean(axis=0)
    u, singular, _ = np.linalg.svd(centered, full_matrices=False)
    coordinates = np.zeros((len(latent), 2)); dimensions = min(2, len(singular)); coordinates[:, :dimensions] = u[:, :dimensions] * singular[:dimensions]
    color = selected['node_error']; limit = float(np.quantile(color[selected['node_error_mask']], .99)) if selected['node_error_mask'].any() else 1
    image = axes[1, 0].scatter(coordinates[:, 0], coordinates[:, 1], c=color, s=5, cmap='viridis', vmin=0, vmax=max(limit, 1e-8))
    axes[1, 0].set(title='PCA display of full-view latent Z; color = masked residual\nColor scale capped at p99; not attack labels', xlabel='PC1', ylabel='PC2'); fig.colorbar(image, ax=axes[1, 0])
    network = nx.Graph(); network.add_nodes_from(range(len(graph.node_ids)))
    network.add_edges_from(chunk.spectral.arrays['edge_index'].T.tolist())
    shown = sorted(network, key=lambda i: (-network.degree(i), i))[:150]; sub = network.subgraph(shown)
    pos = nx.spring_layout(sub, seed=17, iterations=30)
    nx.draw_networkx_edges(sub, pos, ax=axes[1, 1], alpha=.2, width=.5)
    nx.draw_networkx_nodes(sub, pos, ax=axes[1, 1], node_size=15, node_color=[color[i] for i in sub], cmap='viridis', vmin=0, vmax=max(limit, 1e-8))
    axes[1, 1].set_title(f'Masked input topology: {len(shown)}/{len(graph.node_ids)} nodes shown\nInduced view can omit connecting paths'); axes[1, 1].axis('off')
    fig.suptitle(f'{graph.key} | shared L1 Autoencoder | split={chunk.split}'); fig.tight_layout(rect=(0, 0, 1, .95)); save(fig, folder / 'autoencoder_overview')
    return dict(directory=str(folder), inputs=str(folder / 'inputs.npz'), metrics=str(folder / 'metrics.csv'),
                schematic=str(folder / 'autoencoder_overview.png'), lineage=str(folder / 'lineage.json'))


def aggregate(models, prepared):
    rows = []
    for variant, model in models.items():
        for split in ('train', 'validation', 'test'):
            chunks = [c for c in prepared if c.split == split]
            results = [model['results'][c.graph.key] for c in chunks]
            count = sum(r['metrics']['target_entries'] for r in results)
            mse = sum(r['metrics']['feature_mse'] * r['metrics']['target_entries'] for r in results if r['metrics']['target_entries']) / count
            baseline = sum(r['metrics']['mean_baseline_mse'] * r['metrics']['target_entries'] for r in results if r['metrics']['target_entries']) / count
            labels = np.concatenate([c.pair_labels for c in chunks]); probabilities = np.concatenate([r['pair_probability'] for r in results])
            both = len(np.unique(labels)) == 2
            rows.append(dict(model=variant, split=split, chunks=len(chunks), nodes=sum(len(c.graph.node_ids) for c in chunks),
                feature_targets=count, feature_mse=mse, mean_baseline_mse=baseline,
                improvement_vs_mean_percent=100 * (1-mse/baseline) if baseline > 1e-12 else None,
                relation_roc_auc=float(roc_auc_score(labels, probabilities)) if both else None,
                relation_average_precision=float(average_precision_score(labels, probabilities)) if both else None,
                relation_positive_fraction=float(labels.mean()) if len(labels) else None))
    return rows


def write_run(day, run_id, prepared, scaler, audit, models, parameters, source_audit):
    folder = document_directory('autoencoder', layer=1, day=day) / 'runs' / run_id
    folder.mkdir(parents=True, exist_ok=True)
    paths = {c.graph.key: graph_bundle(c, models, run_id) for c in prepared}
    history = [dict(model=variant, **row) for variant, model in models.items() for row in model['history']]
    metrics = aggregate(models, prepared)
    write_csv(folder / 'metrics.csv', metrics); write_csv(folder / 'training_history.csv', history); write_csv(folder / 'feature_audit.csv', audit)
    write_csv(folder / 'input_audit.csv', source_audit)
    for variant, model in models.items():
        torch.save(dict(version='shared_l1_autoencoder_v1', state_dict=model['state'], variant=variant, parameters=parameters,
                        feature_names=list(FEATURES), scaler={key: value.tolist() for key, value in scaler.items()},
                        selected_epoch=model['selected_epoch'], checkpoint_selection='validation_only', source_day=day), folder / f'{variant}_model.pt')
    quality = []
    for chunk in prepared:
        average = np.where(BINARY, scaler['baseline'], scaler['mean'])
        changed_constant = chunk.graph.feature_mask & ~scaler['active'][None, :] & (scaler['train_observation_count'][None, :] > 0) & (np.abs(log_values(chunk.graph.features)-average) > 1e-6)
        unseen = chunk.graph.feature_mask & (scaler['train_observation_count'][None, :] == 0)
        quality.append(dict(graph_key=chunk.graph.key, split=chunk.split, changed_constant_feature_entries=int(changed_constant.sum()), unseen_training_feature_entries=int(unseen.sum())))
    write_csv(folder / 'constant_feature_shift_audit.csv', quality)
    manifest = dict(version='shared_l1_autoencoder_v1', run_id=run_id, source_day=day, temporal_level='processing_chunks_of_day',
        structural_layer=1, parameters=parameters, feature_names=list(FEATURES), active_features=[name for i, name in enumerate(FEATURES) if scaler['active'][i]],
        scaler={key: value.tolist() for key, value in scaler.items()}, metrics=metrics, input_audit=source_audit,
        models={variant: dict(parameter_count=sum(p.numel() for p in m['model'].parameters()), selected_epoch=m['selected_epoch'], validation_loss=m['best_validation_loss'], best_at_final_epoch=m['best_at_final_epoch'], checkpoint=str(folder / f'{variant}_model.pt')) for variant, m in models.items()},
        chunks=[dict(graph_key=c.graph.key, chunk_index=c.graph.chunk, split=c.split, nodes=len(c.graph.node_ids),
                     source_signature=c.graph.signature, source=c.graph.source, spectral_numeric_checks=c.spectral.summary['numerical_checks_pass'],
                     hidden_positive_edges=len(c.positive_weights), sampled_negative_pairs=int((c.pair_labels == 0).sum()), paths=paths[c.graph.key]) for c in prepared],
        reconstruction_space='log1p_then_train_standardized_continuous_and_binary_probabilities',
        split_semantics='held_out_processing_chunks_not_timestamp_split_or_unseen_day_test',
        embedding_semantics='shared_model_full_observed_features_and_full_source_topology_after_masked_evaluation',
        residual_semantics='fixed_hidden_feature_reconstruction_error_not_calibrated_attack_score',
        labels_used_by_autoencoder=False, reference_population='mixed_candidates_no_clean_normal_reference_assumed',
        source_versions_verified=True, anomaly_detection_accuracy=None,
        limitations=['Upstream graph construction and candidate selection can depend on full features and label/risk policies; this does not establish end-to-end label-free detection.',
                     'Legacy raw ingestion can zero-fill missing values; the historical per-value validity cannot be recovered here.',
                     'Spectral inputs are recomputed after hiding target edges; feature prediction is still conditional on an existing feature-derived graph.',
                     'Nonedges are absent similarity edges, not verified unrelated behavior or benign examples.',
                     'Constant/unobserved training columns are excluded from trained targets; separate shift audit is exported.',
                     'One training seed and one day; no temporal, cross-day, weekly or attack-detection claim.'])
    dump_json(folder / 'manifest.json', manifest)
    lines = ['Shared layer-1 Autoencoder: ' + day, 'Run: ' + run_id, manifest['split_semantics'],
             'Model | Split | Feature MSE | Mean baseline MSE | Relation ROC-AUC']
    lines += [f"{r['model']} | {r['split']} | {r['feature_mse']:.6g} | {r['mean_baseline_mse']:.6g} | {r['relation_roc_auc']}" for r in metrics]
    lines += ['', 'Limitations:', *manifest['limitations']]
    (folder / 'evaluation.txt').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    architecture(folder / 'architecture', f'{day}: shared layer-1 Autoencoder architecture (executed training run)')
    # The membership table needs a taller canvas for days with many chunks.
    fig, axes = plt.subplots(1, 3, figsize=(17, max(6, .27 * (len(prepared) + 1) + 2)))
    for variant, model in models.items():
        axes[0].plot([r['epoch'] for r in model['history']], [r['validation_loss'] for r in model['history']], label=variant)
    axes[0].set(title='Validation objective; checkpoint selected without test', xlabel='Epoch', ylabel='Huber/BCE + weighted structure loss'); axes[0].legend()
    test = [r for r in metrics if r['split']=='test']
    axes[1].bar([r['model'] for r in test], [r['feature_mse'] for r in test]); axes[1].axhline(test[0]['mean_baseline_mse'], color='red', label='Train-mean baseline')
    axes[1].set(title='Held-out processing chunks: masked feature MSE', ylabel='Feature MSE'); axes[1].legend()
    axes[2].axis('off'); rows = [[c.graph.chunk, c.split, len(c.graph.node_ids), len(c.positive_weights)] for c in prepared]
    table=axes[2].table(cellText=rows,colLabels=['Chunk','Split','Nodes','Hidden edges'],loc='center');table.auto_set_font_size(False);table.set_fontsize(8);table.scale(1,1.3)
    axes[2].set_title('Shared-model dataset membership')
    fig.suptitle(day + ' | L1 masked graph Autoencoder evaluation | not anomaly detection');fig.tight_layout();save(fig,folder/'evaluation_overview')
    return dict(directory=str(folder), manifest=str(folder/'manifest.json'), metrics=str(folder/'metrics.csv'),
                text=str(folder/'evaluation.txt'), schematic=str(folder/'architecture.png'), overview=str(folder/'evaluation_overview.png'))
