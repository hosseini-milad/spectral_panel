"""Frozen-model scores, calibrated reference diagnostics and PNG/SVG evidence."""
from pathlib import Path
import hashlib
import json

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import torch
from sklearn.metrics import roc_auc_score, average_precision_score

from .autoencoder_inputs import FEATURES, BINARY, log_values
from .autoencoder_training import VARIANTS
from ..models.layer1_autoencoder import Layer1Autoencoder
from .normal_behavior import tail_probabilities
from .spectral_reports import dump_json, save
from .message_passing_reports import write_csv, input_audit


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_reference_bundle(directory):
    folder = Path(directory)
    if json.loads((folder / 'run_status.json').read_text())['status'] != 'complete':
        raise ValueError('Frozen reference bundle is not complete')
    manifest = json.loads((folder / 'manifest.json').read_text())
    if manifest['version'] != 'normal_behavior_v1' or manifest.get('status') != 'complete':
        raise ValueError('Unsupported or incomplete normal-reference manifest')
    parameters = manifest['parameters']
    models = {}
    for variant in VARIANTS:
        path = folder / f'{variant}_model.pt'
        if _sha(path) != manifest['checkpoint_sha256'][variant]:
            raise ValueError('Frozen checkpoint checksum mismatch')
        checkpoint = torch.load(path, map_location='cpu', weights_only=True)
        if checkpoint['feature_names'] != list(FEATURES):
            raise ValueError('Frozen feature schema differs')
        model = Layer1Autoencoder(len(FEATURES), parameters['hidden_dim'], parameters['latent_dim'],
                                  parameters['layers'], variant)
        model.load_state_dict(checkpoint['state_dict']); model.eval()
        models[variant] = dict(model=model, state=checkpoint['state_dict'], history=checkpoint['history'],
                               selected_epoch=checkpoint['selected_epoch'], results={})
    if _sha(folder / 'reference_arrays.npz') != manifest['reference_arrays_sha256']:
        raise ValueError('Frozen calibration/scaler checksum mismatch')
    with np.load(folder / 'reference_arrays.npz', allow_pickle=False) as arrays:
        scaler = {key.removeprefix('scaler_'): arrays[key].copy() for key in arrays.files if key.startswith('scaler_')}
        calibration = {variant: arrays['calibration_' + variant].copy() for variant in VARIANTS}
    return models, scaler, parameters, calibration, manifest['thresholds'], manifest


def component_dispersion(z, assignment):
    assignment = np.asarray(assignment, dtype=int)
    count = np.bincount(assignment)
    centers = np.zeros((len(count), z.shape[1]))
    np.add.at(centers, assignment, z)
    centers /= count[:, None]
    squared = ((z - centers[assignment]) ** 2).sum(axis=1)
    return np.sqrt(np.bincount(assignment, weights=squared) / count)


def permutation_dispersion(z, assignment, seed=17, repeats=20):
    observed = component_dispersion(z, assignment)
    rng = np.random.default_rng(seed)
    shuffled = np.asarray([component_dispersion(z[rng.permutation(len(z))], assignment) for _ in range(repeats)])
    return observed, shuffled.mean(axis=0), shuffled.std(axis=0)


def cosine_tie_audit(vectors, k=10, max_queries=512):
    """Bounded query sample against all component means, with self excluded."""
    vectors = np.asarray(vectors, dtype=float)
    norm = np.linalg.norm(vectors, axis=1)
    valid = norm > 1e-12
    unit = vectors[valid] / norm[valid, None]
    n = len(unit)
    if n < 2:
        return dict(components=len(vectors), zero_norm_components=int((~valid).sum()),
                    sampled_queries=0, k=0, boundary_tie_fraction=None,
                    mean_candidates_at_knn_boundary=None, tolerance=1e-10)
    k = min(k, n-1)
    queries = np.linspace(0, n-1, min(n, max_queries), dtype=int)
    ties = []
    for start in range(0, len(queries), 64):
        indices = queries[start:start+64]
        distance = np.clip(1 - unit[indices] @ unit.T, 0, 2)
        distance[np.arange(len(indices)), indices] = np.inf
        for row in distance:
            boundary = np.partition(row, k-1)[k-1]
            ties.append(int(np.isclose(row, boundary, atol=1e-10, rtol=0).sum()))
    return dict(components=len(vectors), zero_norm_components=int((~valid).sum()),
                sampled_queries=len(queries), k=k, boundary_tie_fraction=float(np.mean(np.asarray(ties) > 1)),
                mean_candidates_at_knn_boundary=float(np.mean(ties)), tolerance=1e-10)


def _architecture(folder, normal_day):
    fig, ax = plt.subplots(figsize=(15, 6)); ax.axis('off')
    labels = [(0.12, .75, f'Normal reference {normal_day}\nDisjoint processing chunks'),
              (.42, .88, 'TRAIN: fit scaler + masked AE\nFeature / graph / spectral'),
              (.42, .63, 'VALIDATION: select checkpoint\nNo threshold tuning'),
              (.73, .88, 'CALIBRATION: fixed normal scores\nFreeze threshold and calibration array'),
              (.73, .58, 'NORMAL TEST: held-out false alerts\nNever used for training/calibration'),
              (.50, .23, 'INDEPENDENT DAYS: same weights, scaler, threshold\nExclude reference duplicates; no optimizer or refitting\nDeviation alerts are not attack probabilities')]
    for x, y, label in labels:
        ax.text(x, y, label, transform=ax.transAxes, ha='center', va='center', fontsize=10,
                bbox=dict(boxstyle='round,pad=.6', fc='#e6eff8', ec='#47647a'))
    for start, end in [((.23,.75),(.29,.88)), ((.23,.75),(.29,.63)),
                        ((.55,.88),(.59,.88)), ((.73,.77),(.73,.69)), ((.73,.47),(.62,.32))]:
        ax.annotate('', xy=end, xytext=start, xycoords='axes fraction', arrowprops=dict(arrowstyle='->'))
    ax.set_title('Normal-behavior learning and frozen cross-day evaluation', fontsize=15)
    save(fig, folder / 'normal_behavior_schematic')


def write_normal_reports(folder, manifest, prepared, models, scaler, calibration, labels, audit):
    folder = Path(folder)
    checkpoints = {}
    for variant, model in models.items():
        path = folder / f'{variant}_model.pt'
        torch.save(dict(state_dict=model['model'].state_dict(), history=model['history'],
                        selected_epoch=model['selected_epoch'], feature_names=list(FEATURES),
                        parameters=manifest['parameters'], normal_day=manifest['normal_day']), path)
        checkpoints[variant] = _sha(path)
    np.savez_compressed(folder / 'reference_arrays.npz',
                        **{'scaler_' + key: value for key, value in scaler.items()},
                        **{'calibration_' + key: value for key, value in calibration.items()})
    manifest['checkpoint_sha256'] = checkpoints
    manifest['reference_arrays_sha256'] = _sha(folder / 'reference_arrays.npz')
    all_rows, summary, shift_rows, dispersion_rows = [], [], [], []
    history = [dict(model=variant, **row) for variant, model in models.items() for row in model['history']]
    write_csv(folder / 'training_history.csv', history)
    train_z = np.concatenate([models['spectral']['results'][c.graph.key]['latent'] for c in prepared if c.split == 'train'])
    # One PCA basis fitted ONLY to normal training embeddings, reused across days.
    sample = train_z[np.linspace(0, len(train_z) - 1, min(10000, len(train_z)), dtype=int)]
    center = sample.mean(axis=0)
    _, _, axes = np.linalg.svd(sample - center, full_matrices=False)
    axes = axes[:2].T
    np.savez_compressed(folder / 'display_pca.npz', center=center, axes=axes)
    groups = {}
    component_rows = []
    for chunk in prepared:
        graph = chunk.graph
        day_folder = folder / graph.day
        day_folder.mkdir(exist_ok=True)
        transformed = log_values(graph.features)
        average = np.where(BINARY, scaler['baseline'], scaler['mean'])
        changed = graph.feature_mask & ~scaler['active'][None, :] & (scaler['train_observation_count'][None, :] > 0) & (np.abs(transformed - average) > 1e-6)
        unseen = graph.feature_mask & (scaler['train_observation_count'][None, :] == 0)
        shift_rows.append(dict(day=graph.day, graph_key=graph.key, split=chunk.split,
                               changed_constant_entries=int(changed.sum()), unseen_feature_entries=int(unseen.sum())))
        for variant, model in models.items():
            result = model['results'][graph.key]
            valid = result['node_error_mask']; score = result['node_error']
            threshold = manifest['thresholds'][variant]
            alerts = valid & (score > threshold)
            probabilities = tail_probabilities(calibration[variant], score)
            groups.setdefault((graph.day, chunk.split, variant), []).append((chunk, result, alerts))
            for i, node_id in enumerate(graph.node_ids):
                all_rows.append(dict(day=graph.day, graph_key=graph.key, split=chunk.split, model=variant,
                    node_id=str(node_id), raw_record_id=str(graph.lineage[i]['original_id']),
                    score=float(score[i]) if valid[i] else None, valid=bool(valid[i]),
                    threshold=threshold, alert=bool(alerts[i]) if valid[i] else None,
                    normal_tail_rank=float(probabilities[i]) if valid[i] else None,
                    raw_label=labels[graph.key][i]))
            for block in chunk.original.blocks:
                indices = np.asarray(block['node_indices'], dtype=int)
                evaluated = indices[valid[indices]]
                component_rows.append(dict(day=graph.day, graph_key=graph.key, split=chunk.split,
                    model=variant, component_id=str(block['source_component_id']), nodes=len(indices),
                    scored_nodes=len(evaluated), alert_nodes=int(alerts[evaluated].sum()),
                    alert_fraction=float(alerts[evaluated].mean()) if len(evaluated) else None,
                    mean_score=float(score[evaluated].mean()) if len(evaluated) else None))
            np.savez_compressed(day_folder / f'chunk-{graph.chunk}_{variant}.npz',
                node_ids=np.asarray(graph.node_ids, dtype=str), original_ids=np.asarray([r['original_id'] for r in graph.lineage], dtype=str),
                score=score, valid=valid, alert=alerts, threshold=threshold, normal_tail_rank=probabilities,
                latent=result['latent'], reconstruction=result['reconstruction'], targets=chunk.values,
                evaluation_hidden_mask=chunk.fixed_hidden, component_index=chunk.original.arrays['block_index'])
        result = models['spectral']['results'][graph.key]
        observed, random_mean, random_sd = permutation_dispersion(
            result['latent'], chunk.original.arrays['block_index'], seed=manifest['parameters']['seed'])
        for i, block in enumerate(chunk.original.blocks):
            dispersion_rows.append(dict(day=graph.day, graph_key=graph.key, component_id=str(block['source_component_id']),
                nodes=block['node_count'], observed_rms=float(observed[i]), shuffled_mean_rms=float(random_mean[i]),
                shuffled_std_rms=float(random_sd[i]), permutations=20,
                diagnostic='L1 within-component dispersion; not L2 Meta-component dispersion'))

    for (day, split, variant), chunks in groups.items():
        scores = np.concatenate([r['node_error'][r['node_error_mask']] for _, r, _ in chunks])
        alerts = np.concatenate([a[r['node_error_mask']] for _, r, a in chunks])
        target_count = sum(r['metrics']['target_entries'] for _, r, _ in chunks)
        mse = sum(r['metrics']['feature_mse'] * r['metrics']['target_entries'] for _, r, _ in chunks if r['metrics']['target_entries']) / target_count
        baseline = sum(r['metrics']['mean_baseline_mse'] * r['metrics']['target_entries'] for _, r, _ in chunks if r['metrics']['target_entries']) / target_count
        relation_truth = np.concatenate([c.pair_labels for c, _, _ in chunks])
        relation_score = np.concatenate([r['pair_probability'] for _, r, _ in chunks])
        both = len(np.unique(relation_truth)) == 2
        raw_labels = np.concatenate([np.asarray(labels[c.graph.key], dtype=object)[r['node_error_mask']] for c, r, _ in chunks])
        benign = raw_labels == 0; tagged = raw_labels == 1
        row = dict(day=day, split=split, model=variant, chunks=len(chunks), scored_nodes=len(scores),
            alert_nodes=int(alerts.sum()), alert_fraction=float(alerts.mean()) if len(alerts) else None,
            heldout_normal_false_alert_fraction=float(alerts.mean()) if split == 'test' and day == manifest['normal_day'] and len(alerts) else None,
            raw_label0_nodes=int(benign.sum()), raw_label0_alert_fraction=float(alerts[benign].mean()) if benign.any() else None,
            raw_label1_nodes=int(tagged.sum()), raw_label1_alert_fraction=float(alerts[tagged].mean()) if tagged.any() else None,
            threshold=manifest['thresholds'][variant], feature_mse=mse,
            mean_baseline_mse=baseline, improvement_vs_mean_percent=100 * (1-mse/baseline) if baseline > 1e-12 else None,
            relation_roc_auc=float(roc_auc_score(relation_truth, relation_score)) if both else None,
            relation_average_precision=float(average_precision_score(relation_truth, relation_score)) if both else None)
        summary.append(row)
    write_csv(folder / 'node_scores.csv', all_rows)
    write_csv(folder / 'evaluation_metrics.csv', summary)
    write_csv(folder / 'component_scores.csv', component_rows)
    write_csv(folder / 'feature_shift_audit.csv', shift_rows)
    write_csv(folder / 'dispersion_permutation.csv', dispersion_rows)
    write_csv(folder / 'lineage_audit.csv', audit)
    write_csv(folder / 'input_audit.csv', input_audit([c.graph for c in prepared]))
    coverage = []
    for day in [manifest['normal_day'], *manifest['evaluate_days']]:
        rows = [row for row in audit if row['day'] == day]
        coverage.append(dict(day=day, available_chunks=len(rows), evaluated_chunks=sum(not r['excluded'] for r in rows),
                             candidate_nodes_before_filter=sum(r['nodes'] for r in rows),
                             candidate_nodes_after_filter=sum(r['retained_nodes'] for r in rows),
                             removed_nodes=sum(r['removed_nodes'] for r in rows),
                             coverage_basis='available L1 candidate graphs; full raw-day coverage unknown'))
    write_csv(folder / 'coverage.csv', coverage)
    manifest['coverage'] = coverage
    ties = []
    for day in [manifest['normal_day'], *manifest['evaluate_days']]:
        means = np.concatenate([models['spectral']['results'][c.graph.key]['pooled_mean']
                                for c in prepared if c.graph.day == day])
        ties.append(dict(day=day, model='spectral', **cosine_tie_audit(means)))
    write_csv(folder / 'latent_distance_ties.csv', ties)
    manifest['latent_distance_ties'] = ties
    manifest['metrics'] = summary
    manifest['dispersion_null'] = '20 seeded within-chunk permutations of node latent vectors; preserves component sizes, not a training objective or Meta-component evaluation'
    manifest['reference_label_counts'] = {str(label): sum(value == label for key, values in labels.items()
                                                         if any(c.graph.key == key and c.graph.day == manifest['normal_day'] for c in prepared)
                                                         for value in values) for label in (0, 1, None)}
    manifest['reference_split_semantics'] = 'disjoint processing chunks: train / validation / calibration / test; not a time split'
    _architecture(folder, manifest['normal_day'])
    fig, plot = plt.subplots(1, 2, figsize=(14, 5))
    for variant, model in models.items():
        plot[0].plot([r['epoch'] for r in model['history']], [r['validation_loss'] for r in model['history']], label=variant)
    plot[0].set(title='Normal-reference validation objective', xlabel='Epoch', ylabel='Masked training objective'); plot[0].legend()
    shown = [r for r in summary if r['split'] in ('test', 'external_test') and r['model'] == 'spectral']
    plot[1].bar([r['day'] for r in shown], [r['alert_fraction'] for r in shown])
    plot[1].axhline(manifest['alpha'], color='red', linestyle='--', label='Nominal calibration tail')
    plot[1].set(title='Frozen spectral model: candidate alert fraction', ylabel='Fraction (external days are not assumed normal)'); plot[1].legend()
    fig.tight_layout(); save(fig, folder / 'evaluation_overview')
    for day in [manifest['normal_day'], *manifest['evaluate_days']]:
        chunks = [c for c in prepared if c.graph.day == day]
        fig, plot = plt.subplots(2, 2, figsize=(14, 11))
        for variant in VARIANTS:
            scores = np.concatenate([models[variant]['results'][c.graph.key]['node_error'][models[variant]['results'][c.graph.key]['node_error_mask']] for c in chunks])
            plot[0, 0].hist(scores, bins=40, histtype='step', label=variant)
        plot[0, 0].axvline(manifest['thresholds']['spectral'], color='red', linestyle='--', label='Fixed spectral threshold')
        plot[0, 0].set(title='Reconstruction scores; reference day includes all splits', xlabel='Masked MSE'); plot[0, 0].legend()
        for chunk in chunks:
            result = models['spectral']['results'][chunk.graph.key]
            indices = np.linspace(0, len(result['latent'])-1, min(1000, len(result['latent'])), dtype=int)
            xy = (result['latent'][indices] - center) @ axes
            plot[0, 1].scatter(xy[:, 0], xy[:, 1], c=result['node_error'][indices], s=5, alpha=.5, cmap='viridis')
        plot[0, 1].set(title='Frozen spectral latent: normal-train PCA basis\nUp to 1,000 nodes per chunk; colors = score', xlabel='Reference PC1', ylabel='Reference PC2')
        example = max(chunks, key=lambda c: len(c.graph.edges))
        network = nx.Graph(); network.add_nodes_from(range(len(example.graph.node_ids)))
        network.add_edges_from((e['source'], e['target']) for e in example.graph.edges)
        indices = sorted(network, key=lambda i: (-network.degree(i), i))[:120]
        sub = network.subgraph(indices)
        values = models['spectral']['results'][example.graph.key]['node_error']
        nx.draw_networkx(sub, pos=nx.spring_layout(sub, seed=17, iterations=30), ax=plot[1, 0],
                         node_color=[values[i] for i in sub], cmap='viridis', node_size=15, with_labels=False,
                         width=.4, edge_color='#aaaaaa')
        plot[1, 0].set_title(f'Example chunk {example.graph.chunk}: induced schematic\n{len(sub)}/{len(network)} nodes; paths may be omitted'); plot[1, 0].axis('off')
        component = [r for r in dispersion_rows if r['day'] == day and r['nodes'] > 1]
        plot[1, 1].scatter([r['shuffled_mean_rms'] for r in component], [r['observed_rms'] for r in component], s=8, alpha=.5)
        plot[1, 1].set(title='L1 component spread vs permutation reference\nSingletons excluded; not L2 Meta-component spread', xlabel='Shuffled mean RMS', ylabel='Observed RMS')
        fig.suptitle(day + ': normal-behavior diagnostics; deviations are not attack labels')
        fig.tight_layout(); save(fig, folder / day / 'behavior_schematic')
    lines = ['Normal behavior reference: ' + manifest['normal_day'], 'Frozen weights/scaler/thresholds across days.',
             'Day | Split | Model | Scored nodes | Alerts | Alert fraction | Feature MSE']
    lines += [f"{r['day']} | {r['split']} | {r['model']} | {r['scored_nodes']} | {r['alert_nodes']} | {r['alert_fraction']} | {r['feature_mse']}" for r in summary]
    lines += ['', 'Reference label counts: ' + str(manifest['reference_label_counts']),
              'Raw label0/label1 fractions are conditional on existing tags; not verified attack accuracy.',
              '', *manifest['limits']]
    (folder / 'evaluation.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return dict(directory=str(folder), manifest=str(folder / 'manifest.json'),
                metrics=str(folder / 'evaluation_metrics.csv'), scores=str(folder / 'node_scores.csv'),
                schematic=str(folder / 'normal_behavior_schematic.png'), overview=str(folder / 'evaluation_overview.png'),
                text=str(folder / 'evaluation.txt'))
