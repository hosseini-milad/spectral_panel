"""One encoder per variant shared across training chunks; validation-only selection."""
from copy import deepcopy
import numpy as np
import torch
from torch.nn import functional as F
from threadpoolctl import threadpool_limits
from sklearn.metrics import roc_auc_score, average_precision_score

from spectral_learning.models.layer1_autoencoder import Layer1Autoencoder
from .message_passing_evaluation import tensors, pool_blocks
from .autoencoder_inputs import BINARY, feature_corruption

VARIANTS = ('feature', 'graph', 'spectral')


def forward_chunk(model, chunk, hidden):
    inputs = tensors(chunk.spectral.arrays, chunk.values, chunk.mask & ~hidden)
    prediction, latent = model(inputs)
    pairs = torch.as_tensor(chunk.pairs, dtype=torch.long)
    logits, weights = model.decode_pairs(latent, pairs)
    return prediction, latent, logits, weights


def losses(chunk, prediction, logits, weights, hidden, structure_weight=.1, weight_weight=.05):
    truth = torch.as_tensor(chunk.values)
    continuous = torch.as_tensor(hidden & ~BINARY[None, :]); binary = torch.as_tensor(hidden & BINARY[None, :])
    feature_losses = []
    if continuous.any():
        feature_losses.append(F.smooth_l1_loss(prediction[continuous], truth[continuous]))
    if binary.any():
        feature_losses.append(F.binary_cross_entropy_with_logits(prediction[binary], truth[binary]))
    feature = sum(feature_losses) / len(feature_losses) if feature_losses else prediction.sum() * 0
    count_positive = len(chunk.positive_weights)
    link = None
    if count_positive and len(chunk.pair_labels) > count_positive:
        pos = F.binary_cross_entropy_with_logits(logits[:count_positive], torch.ones_like(logits[:count_positive]))
        neg = F.binary_cross_entropy_with_logits(logits[count_positive:], torch.zeros_like(logits[count_positive:]))
        link = (pos + neg) / 2
    weight = F.mse_loss(weights[:count_positive], torch.as_tensor(chunk.positive_weights)) if count_positive else None
    total = feature + (structure_weight * link if link is not None else 0) + (weight_weight * weight if weight is not None else 0)
    return total, feature, link, weight


def reconstruct(prediction):
    values = prediction.detach().numpy().copy()
    values[:, BINARY] = torch.sigmoid(prediction[:, BINARY]).detach().numpy()
    return values


def evaluate_chunk(model, chunk, baseline):
    model.eval()
    with torch.no_grad():
        prediction, _, logits, weights = forward_chunk(model, chunk, chunk.fixed_hidden)
        reconstruction = reconstruct(prediction)
        errors = (reconstruction - chunk.values) ** 2
        chosen = chunk.fixed_hidden
        base_errors = (chunk.values - baseline[None, :]) ** 2
        count = chosen.sum(axis=1)
        node_error = np.divide((errors * chosen).sum(axis=1), count, out=np.zeros(len(count)), where=count > 0)
        _, latent = model(tensors(chunk.original.arrays, chunk.values, chunk.mask))
    pos = len(chunk.positive_weights)
    pair_probability = torch.sigmoid(logits).numpy()
    two_classes = pos > 0 and len(chunk.pair_labels) > pos
    metrics = dict(feature_mse=float(errors[chosen].mean()) if chosen.any() else None,
                   mean_baseline_mse=float(base_errors[chosen].mean()) if chosen.any() else None,
                   target_entries=int(chosen.sum()), node_count=len(count), nodes_with_error=int((count > 0).sum()),
                   edge_positive_targets=pos, edge_negative_targets=len(chunk.pair_labels)-pos,
                   edge_roc_auc=float(roc_auc_score(chunk.pair_labels, pair_probability)) if two_classes else None,
                   edge_average_precision=float(average_precision_score(chunk.pair_labels, pair_probability)) if two_classes else None,
                   weight_mse=float(np.mean((weights[:pos].numpy() - chunk.positive_weights) ** 2)) if pos else None)
    feature_metrics = []
    for col, name in enumerate(chunk.graph.feature_names):
        selected = chosen[:, col]
        feature_metrics.append(dict(feature=name, target_entries=int(selected.sum()),
            feature_mse=float(errors[selected, col].mean()) if selected.any() else None,
            mean_baseline_mse=float(base_errors[selected, col].mean()) if selected.any() else None))
    original_isolate = np.zeros(len(count), dtype=bool)
    for block in chunk.original.blocks:
        if block['node_count'] == 1:
            original_isolate[block['node_indices']] = True
    coverage = []
    for group, rows in [('connected', ~original_isolate), ('isolated', original_isolate)]:
        selected = chosen & rows[:, None]
        coverage.append(dict(group=group, node_count=int(rows.sum()), target_entries=int(selected.sum()),
                             feature_mse=float(errors[selected].mean()) if selected.any() else None))
    component_index = chunk.original.arrays['block_index']
    mean, std, size = pool_blocks(latent.numpy(), component_index)
    component_targets = np.bincount(component_index, weights=count, minlength=len(size))
    component_sse = np.bincount(component_index, weights=(errors * chosen).sum(axis=1), minlength=len(size))
    component_mse = np.divide(component_sse, component_targets, out=np.zeros(len(size)), where=component_targets > 0)
    component_max = np.zeros(len(size)); np.maximum.at(component_max, component_index, node_error)
    return dict(metrics=metrics, feature_metrics=feature_metrics, coverage=coverage, reconstruction=reconstruction,
                latent=latent.numpy(), node_error=node_error, node_error_mask=count > 0,
                original_isolate=original_isolate, pair_probability=pair_probability, pair_weights=weights.numpy(),
                pooled_mean=mean, pooled_std=std, pooled_size=size, component_mse=component_mse,
                component_max_node_mse=component_max, component_target_count=component_targets.astype(int))


def train_shared(prepared, scaler, *, epochs=60, hidden=64, latent=16, layers=2, seed=17,
                 structure_weight=.1, weight_weight=.05, progress=None):
    models = {}; previous_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        with threadpool_limits(limits=1), torch.random.fork_rng(devices=[]):
            training = [c for c in prepared if c.split == 'train']
            validation = [c for c in prepared if c.split == 'validation']
            for variant in VARIANTS:
                torch.manual_seed(seed)
                model = Layer1Autoencoder(len(scaler['mean']), hidden, latent, layers, variant)
                optimizer = torch.optim.Adam(model.parameters(), lr=.001, weight_decay=1e-4)
                rng = np.random.default_rng(seed + 2000)
                best, selected, state, history = float('inf'), None, None, []
                for epoch in range(epochs):
                    train_total = targets = 0
                    model.train()
                    for index in rng.permutation(len(training)):
                        chunk = training[index]; hidden_entries = feature_corruption(chunk.mask, rng)
                        optimizer.zero_grad()
                        prediction, _, logits, weights = forward_chunk(model, chunk, hidden_entries)
                        total, _, _, _ = losses(chunk, prediction, logits, weights, hidden_entries, structure_weight, weight_weight)
                        if not torch.isfinite(total):
                            raise ValueError('Nonfinite autoencoder training loss')
                        total.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 5); optimizer.step()
                        count = int(hidden_entries.sum()); train_total += float(total.detach()) * count; targets += count
                    model.eval(); valid_total = valid_targets = 0
                    with torch.no_grad():
                        for chunk in validation:
                            prediction, _, logits, weights = forward_chunk(model, chunk, chunk.fixed_hidden)
                            total, _, _, _ = losses(chunk, prediction, logits, weights, chunk.fixed_hidden, structure_weight, weight_weight)
                            count = int(chunk.fixed_hidden.sum()); valid_total += float(total) * count; valid_targets += count
                    value = valid_total / valid_targets
                    if not np.isfinite(value):
                        raise ValueError('Nonfinite autoencoder validation loss')
                    history.append(dict(epoch=epoch+1, train_loss=train_total / max(targets, 1), validation_loss=value))
                    if value < best:
                        best = value; selected = epoch+1; state = deepcopy(model.state_dict())
                    if progress and (epoch == 0 or (epoch+1) % 5 == 0 or epoch+1 == epochs):
                        progress(f'[AUTOENCODER] {variant}: epoch={epoch+1}/{epochs}; train={history[-1]["train_loss"]:.6g}; validation={value:.6g}')
                model.load_state_dict(state); model.eval()
                models[variant] = dict(model=model, state=state, history=history, selected_epoch=selected,
                    best_validation_loss=best, best_at_final_epoch=selected == epochs,
                    results={c.graph.key: evaluate_chunk(model, c, scaler['baseline']) for c in prepared})
    finally:
        torch.set_num_threads(previous_threads)
    return models
