"""Transductive masked-feature probes and controlled interventions, not detection."""
from copy import deepcopy
from dataclasses import replace
import numpy as np
import torch
from torch import nn
from threadpoolctl import threadpool_limits

from spectral_learning.models.eigenvector_gnn import EigenvectorAwareMessagePassing
from .spectral_core import analyze_graph, invariant_features


def relative_change(before, after):
    denominator = np.linalg.norm(before)
    return float(np.linalg.norm(after - before) / denominator) if denominator > 1e-12 else None


def split_features(features, observed, seed=17):
    """Per-column disjoint entries; fit scaling on training entries only."""
    rng = np.random.default_rng(seed)
    train = observed.copy(); validation = np.zeros_like(observed); test = np.zeros_like(observed)
    for col in range(observed.shape[1]):
        rows = rng.permutation(np.flatnonzero(observed[:, col]))
        if len(rows) < 5:
            continue
        count = max(1, int(len(rows) * .1))
        validation[rows[:count], col] = True; test[rows[count:2 * count], col] = True
        train[rows[:2 * count], col] = False
    mean = np.zeros(features.shape[1]); scale = np.ones(features.shape[1])
    for col in range(features.shape[1]):
        values = features[train[:, col], col]
        if len(values):
            mean[col] = values.mean(); scale[col] = max(values.std(), 1e-6)
    target = np.where(observed, (features - mean) / scale, 0).astype('float32')
    if not train.any() or not validation.any() or not test.any():
        raise ValueError('Insufficient observed attributes for disjoint training/validation/test feature entries (need >=5 rows in a field).')
    return target, train, validation, test, mean, scale


def tensors(arrays, features, observed, spectral=True):
    def t(value, dtype=torch.float32):
        return torch.as_tensor(np.array(value, copy=True), dtype=dtype)
    return [t(features), t(observed, torch.bool), t(arrays['node_spectral']) if spectral else torch.zeros((len(features), 3)),
            t(arrays['node_spectral_mask'], torch.bool) if spectral else torch.zeros(len(features), dtype=torch.bool),
            t(arrays['edge_index'], torch.long), t(arrays['edge_weight']),
            t(arrays['edge_spectral']) if spectral else torch.zeros((len(arrays['edge_weight']), 3)),
            t(arrays['edge_spectral_mask'], torch.bool) if spectral else torch.zeros(len(arrays['edge_weight']), dtype=torch.bool)]


class FeatureProbe(nn.Module):
    """Small auxiliary head for this stage; not the phase-4 graph Autoencoder."""
    def __init__(self, input_dim, hidden, layers):
        super().__init__()
        self.encoder = EigenvectorAwareMessagePassing(input_dim, hidden_dim=hidden, layers=layers)
        self.head = nn.Linear(hidden, input_dim)

    def forward(self, args, level):
        z = self.encoder(*args, level=level)
        return self.head(z), z


def fit_probe(arrays, level, *, epochs=30, hidden=32, layers=2, seed=17, spectral=True, progress=None):
    """Validation-selected probe; fixed held-out entries are absent from all training inputs."""
    target, train, val, test, mean, scale = split_features(arrays['node_features'], arrays['node_feature_mask'], seed)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = FeatureProbe(target.shape[1], hidden, layers)
        optimizer = torch.optim.Adam(model.parameters(), lr=.003, weight_decay=1e-4)
        truth = torch.as_tensor(target); val_t = torch.as_tensor(val); test_t = torch.as_tensor(test)
        rng = np.random.default_rng(seed)
        fixed_args = tensors(arrays, target, train, spectral)
        best, best_state, history, selected_epoch = float('inf'), None, [], 0
        for epoch in range(epochs):
            corruption = (rng.random(train.shape) < .2) & train
            if not corruption.any():
                positions = np.argwhere(train); corruption[tuple(positions[rng.integers(len(positions))])] = True
            args = tensors(arrays, target, train & ~corruption, spectral)
            model.train(); optimizer.zero_grad()
            predicted, _ = model(args, level)
            loss = (predicted[corruption] - truth[corruption]).square().mean()
            loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 5); optimizer.step()
            model.eval()
            with torch.no_grad():
                prediction, _ = model(fixed_args, level)
                valid_loss = float((prediction[val_t] - truth[val_t]).square().mean())
            if not np.isfinite([float(loss.detach()), valid_loss]).all():
                raise ValueError('Nonfinite message-passing loss')
            history.append({'epoch': epoch + 1, 'train_masked_mse': float(loss.detach()), 'validation_mse': valid_loss})
            if progress and (epoch == 0 or (epoch + 1) % 5 == 0 or epoch + 1 == epochs):
                progress(f'[MESSAGE PASSING] spectral={spectral}; epoch={epoch + 1}/{epochs}; train={float(loss.detach()):.6g}; validation={valid_loss:.6g}')
            if valid_loss < best:
                best = valid_loss; best_state = deepcopy(model.state_dict()); selected_epoch = epoch + 1
        model.load_state_dict(best_state); model.eval()
        with torch.no_grad():
            predicted, _ = model(fixed_args, level)
            test_mse = float((predicted[test_t] - truth[test_t]).square().mean())
            _, embedding = model(tensors(arrays, target, arrays['node_feature_mask'], spectral), level)
        metrics = dict(validation_mse=best, test_mse=test_mse,
                       test_mean_baseline_mse=float(np.mean(target[test] ** 2)), selected_epoch=selected_epoch,
                       train_entries=int(train.sum()), validation_entries=int(val.sum()), test_entries=int(test.sum()))
    return dict(model=model, embedding=embedding.numpy(), metrics=metrics, history=history,
                mean=mean, scale=scale, train=train, validation=val, test=test, standardized=target)


def infer(probe, arrays, level, spectral=True):
    values = np.where(arrays['node_feature_mask'], (arrays['node_features'] - probe['mean']) / probe['scale'], 0).astype('float32')
    with torch.no_grad():
        return probe['model'](tensors(arrays, values, arrays['node_feature_mask'], spectral), level)[1].numpy()


def permutation_error(probe, arrays, level, seed=17):
    rng = np.random.default_rng(seed); order = rng.permutation(len(arrays['node_features']))
    inverse = np.argsort(order); permuted = dict(arrays)
    for name in ('node_features', 'node_feature_mask', 'node_spectral', 'node_spectral_mask'):
        permuted[name] = arrays[name][order]
    permuted['edge_index'] = inverse[arrays['edge_index']]
    reference = infer(probe, arrays, level)
    return float(np.max(np.abs(infer(probe, permuted, level)[inverse] - reference)))


def eigenspace_invariance_error(result, seed=17):
    """Audit exported signatures under random signs and within-group rotations."""
    rng = np.random.default_rng(seed); maximum = 0.
    for block in result.blocks:
        dim = block['basis_dim']
        if not dim:
            continue
        rows = np.asarray(block['node_indices'])
        vectors = result.arrays['eigenvectors'][rows, :dim].copy()
        groups = block['eigenvalue_groups']
        for group in groups:
            rotation, _ = np.linalg.qr(rng.normal(size=(len(group), len(group))))
            vectors[:, group] = -vectors[:, group] @ rotation
        index = np.full(len(result.arrays['node_ids']), -1, dtype=int); index[rows] = np.arange(len(rows))
        edges = result.arrays['edge_index']; selected = np.flatnonzero(index[edges[0]] >= 0)
        pairs = index[edges[:, selected]].T
        node, edge = invariant_features(vectors, np.asarray(block['selected_values']), groups, pairs)
        maximum = max(maximum, float(np.max(np.abs(node - result.arrays['node_spectral'][rows]))))
        if len(edge):
            maximum = max(maximum, float(np.max(np.abs(edge - result.arrays['edge_spectral'][selected]))))
    return maximum


def perturb_graph(graph, kind, amount, seed):
    rng = np.random.default_rng(seed)
    edges = [dict(edge) for edge in graph.edges]; features = graph.features.copy()
    changed = 0
    if kind == 'edge_weight':
        if edges:
            chosen = rng.choice(len(edges), max(1, int(np.ceil(.1 * len(edges)))), replace=False)
            for i in chosen:
                edges[i]['weight'] *= float(np.exp(rng.uniform(-amount, amount))); changed += 1
    elif kind == 'edge_drop':
        if edges:
            chosen = set(rng.choice(len(edges), max(1, int(np.ceil(amount * len(edges)))), replace=False).tolist())
            edges = [edge for index, edge in enumerate(edges) if index not in chosen]; changed = len(chosen)
    elif kind == 'feature_noise':
        for col in range(features.shape[1]):
            mask = graph.feature_mask[:, col]
            spread = features[mask, col].std() if mask.any() else 0
            features[mask, col] += rng.normal(0, amount * spread, int(mask.sum()))
        changed = int(graph.feature_mask.sum())
    else:
        raise ValueError('Unknown perturbation')
    # Changed topology must not be checked against the old component partition.
    return replace(graph, edges=edges, features=features, block_lookup=None), changed


def evaluate_interventions(graph, result, spectral_probe, plain_probe, *, repeats=3, seed=17, analyze_options=None, progress=None):
    rows = []; arrays = result.arrays
    for kind, amount in [('edge_weight', .05), ('edge_drop', .01), ('feature_noise', .05)]:
        for trial in range(repeats):
            if progress:
                progress(f'[MESSAGE PASSING] {graph.key}: intervention={kind}; trial={trial + 1}/{repeats}')
            changed_graph, changed = perturb_graph(graph, kind, amount, seed + trial)
            if kind == 'feature_noise':
                changed_arrays = dict(arrays, node_features=changed_graph.features)
                summary = result.summary
            else:
                altered = analyze_graph(changed_graph, **(analyze_options or {}))
                changed_arrays, summary = altered.arrays, altered.summary
            common = arrays['node_spectral_mask'] & changed_arrays['node_spectral_mask']
            row = dict(intervention=kind, amount=amount, trial=trial, changed_items=changed,
                       status='observed' if changed else 'not_applicable_no_items',
                       node_signature_relative_change=relative_change(arrays['node_spectral'][common], changed_arrays['node_spectral'][common]) if common.any() else None,
                       comparable_spectral_nodes=int(common.sum()),
                       spectral_embedding_relative_change=relative_change(spectral_probe['embedding'], infer(spectral_probe, changed_arrays, graph.layer)),
                       plain_embedding_relative_change=relative_change(plain_probe['embedding'], infer(plain_probe, changed_arrays, graph.layer, False)),
                       component_count_delta=summary['component_count'] - result.summary['component_count'],
                       encoded_node_count_delta=summary['encoded_node_count'] - result.summary['encoded_node_count'])
            rows.append(row)
    return rows


def pool_blocks(embedding, block_index):
    embedding = np.asarray(embedding, dtype=np.float64)
    count = int(block_index.max()) + 1
    sizes = np.bincount(block_index, minlength=count)
    mean = np.zeros((count, embedding.shape[1])); squared = np.zeros_like(mean)
    np.add.at(mean, block_index, embedding); np.add.at(squared, block_index, embedding ** 2)
    mean /= sizes[:, None]; squared /= sizes[:, None]
    return mean, np.sqrt(np.maximum(squared - mean ** 2, 0)), sizes


def evaluate_message_passing(graph, result, *, epochs=30, hidden=32, layers=2, repeats=3, seed=17, analyze_options=None, progress=None):
    # Keep CPU runs reproducible and avoid BLAS oversubscription; restore caller settings.
    previous_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        with threadpool_limits(limits=1):
            spectral = fit_probe(result.arrays, graph.layer, epochs=epochs, hidden=hidden, layers=layers, seed=seed, progress=progress)
            plain = fit_probe(result.arrays, graph.layer, epochs=epochs, hidden=hidden, layers=layers, seed=seed, spectral=False, progress=progress)
            interventions = evaluate_interventions(graph, result, spectral, plain, repeats=repeats, seed=seed, analyze_options=analyze_options, progress=progress)
            permutation = permutation_error(spectral, result.arrays, graph.layer, seed)
            invariance = eigenspace_invariance_error(result, seed)
            if invariance > 1e-9:
                raise ValueError(f'Eigenspace invariance check failed: {invariance}')
            if permutation > 1e-4:
                raise ValueError(f'Message-passing permutation check failed: {permutation}')
            mean, std, sizes = pool_blocks(spectral['embedding'], result.arrays['block_index'])
            return dict(spectral=spectral, plain=plain, interventions=interventions, permutation_error=permutation,
                        pooled_mean=mean, pooled_std=std, pooled_sizes=sizes, eigenspace_invariance_error=invariance)
    finally:
        torch.set_num_threads(previous_threads)
