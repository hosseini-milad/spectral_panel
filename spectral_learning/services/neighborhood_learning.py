"""Controlled auxiliary neighborhood reconstruction; no attack labels or thresholds."""
from copy import deepcopy
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from ..models.layer1_autoencoder import Layer1Autoencoder
from .autoencoder_inputs import feature_corruption
from .autoencoder_training import forward_chunk, losses
from .representation_quality import measured_neighborhood


class NeighborhoodAutoencoder(Layer1Autoencoder):
    """Preserves all existing decoders; auxiliary heads receive only latent Z."""
    def __init__(self, input_dim, hidden_dim=64, latent_dim=16, layers=2, variant='spectral'):
        super().__init__(input_dim, hidden_dim, latent_dim, layers, variant)
        self.neighborhood_decoder = nn.Sequential(nn.Linear(latent_dim, hidden_dim), nn.GELU(),
                                                  nn.Linear(hidden_dim, 1 + 2 * input_dim))

    def decode_neighborhood(self, latent, detach=False):
        return self.neighborhood_decoder(latent.detach() if detach else latent)


def neighborhood_targets(chunk):
    """Full-source targets; encoder still sees held-out topology/corrupted features.

    Moments are unweighted population moments in the train-scaled feature space,
    not a full distribution model. Std requires two observed neighbors.
    """
    measured = measured_neighborhood(chunk.original.arrays, chunk.values, chunk.mask)
    values = np.column_stack([np.log1p(measured['degree']), measured['neighbor_feature_mean'],
                              measured['neighbor_feature_std']]).astype('float32')
    mask = np.column_stack([np.ones(len(values), dtype=bool), measured['neighbor_feature_valid'],
                            measured['neighbor_observation_count'] >= 2])
    return values, mask


def fit_target_scaler(chunks, targets):
    """Only normal train chunks fit head normalization and constant baselines."""
    training = [targets[c.graph.key] for c in chunks if c.split == 'train']
    if not training:
        raise ValueError('No train chunks for neighborhood targets')
    values = np.concatenate([x for x, _ in training]); mask = np.concatenate([m for _, m in training])
    count = mask.sum(axis=0)
    mean = np.divide(np.where(mask, values, 0).sum(axis=0), count,
                     out=np.zeros(values.shape[1]), where=count > 0)
    variance = np.divide(np.where(mask, (values - mean) ** 2, 0).sum(axis=0), count,
                         out=np.zeros_like(mean), where=count > 0)
    # Constant reference targets retain a usable scale; no division by tiny std.
    scale = np.sqrt(variance); scale[scale < 1e-3] = 1.
    return dict(mean=mean.astype('float32'), scale=scale.astype('float32'), active=count > 0,
                training_target_count=count)


def normalized_targets(target, scaler):
    values, mask = target
    return ((values - scaler['mean']) / scaler['scale']).astype('float32'), mask & scaler['active']


def neighborhood_loss(prediction, values, mask):
    """Equal weight for available families; absent targets never count as zero."""
    width = (prediction.shape[1] - 1) // 2
    parts = []
    for section in [slice(0, 1), slice(1, 1 + width), slice(1 + width, None)]:
        selected = torch.as_tensor(mask[:, section])
        if selected.any():
            parts.append(F.smooth_l1_loss(prediction[:, section][selected],
                                         torch.as_tensor(values[:, section])[selected]))
    return sum(parts) / len(parts) if parts else prediction.sum() * 0


def train_pair(chunks, scaler, parameters, *, variant, seed, epochs, auxiliary_weight, progress=None):
    """Two fresh identical cores, same masks/order/budget and primary validation rule.

    Baseline head is trained on detached Z as a diagnostic probe. It cannot change
    the baseline encoder; separate clipping prevents its gradients changing core
    clipping. The augmented arm permits auxiliary gradients into the core.
    """
    targets = {c.graph.key: neighborhood_targets(c) for c in chunks}
    normalization = fit_target_scaler(chunks, targets)
    normalized = {key: normalized_targets(value, normalization) for key, value in targets.items()}
    training = [c for c in chunks if c.split == 'train']
    validation = [c for c in chunks if c.split == 'validation']
    if not training or not validation:
        raise ValueError('Require normal train and validation chunks')
    output = {}
    for arm in ('baseline', 'neighborhood'):
        torch.manual_seed(seed)
        model = NeighborhoodAutoencoder(len(scaler['mean']), parameters['hidden_dim'],
            parameters['latent_dim'], parameters['layers'], variant)
        initial = deepcopy(model.state_dict())
        core = [p for name, p in model.named_parameters() if not name.startswith('neighborhood_decoder.')]
        heads = list(model.neighborhood_decoder.parameters())
        optimizer = torch.optim.Adam(model.parameters(), lr=.001, weight_decay=1e-4)
        rng = np.random.default_rng(seed + 2000)
        best, state, selected, history = float('inf'), None, None, []
        for epoch in range(epochs):
            model.train(); train_sum = aux_sum = target_count = 0
            for index in rng.permutation(len(training)):
                chunk = training[index]; hidden = feature_corruption(chunk.mask, rng)
                optimizer.zero_grad()
                prediction, z, logits, weights = forward_chunk(model, chunk, hidden)
                base, *_ = losses(chunk, prediction, logits, weights, hidden,
                    parameters.get('structure_weight', .1), parameters.get('weight_weight', .05))
                values, mask = normalized[chunk.graph.key]
                aux = neighborhood_loss(model.decode_neighborhood(z, detach=arm == 'baseline'), values, mask)
                total = base + auxiliary_weight * aux
                if not torch.isfinite(total):
                    raise ValueError('Nonfinite neighborhood training loss')
                total.backward()
                torch.nn.utils.clip_grad_norm_(core, 5); torch.nn.utils.clip_grad_norm_(heads, 5)
                optimizer.step()
                n = int(hidden.sum()); train_sum += float(base.detach()) * n
                aux_sum += float(aux.detach()) * n; target_count += n
            model.eval(); validation_sum = validation_count = 0
            with torch.no_grad():
                for chunk in validation:
                    prediction, _, logits, weights = forward_chunk(model, chunk, chunk.fixed_hidden)
                    base, *_ = losses(chunk, prediction, logits, weights, chunk.fixed_hidden,
                        parameters.get('structure_weight', .1), parameters.get('weight_weight', .05))
                    n = int(chunk.fixed_hidden.sum()); validation_sum += float(base) * n; validation_count += n
            if not target_count or not validation_count:
                raise ValueError('No feature targets for training/validation')
            value = validation_sum / validation_count
            if not np.isfinite(value):
                raise ValueError('Nonfinite primary validation loss')
            history.append(dict(epoch=epoch + 1, train_primary_loss=train_sum / target_count,
                train_neighborhood_loss=aux_sum / target_count, validation_primary_loss=value))
            if value < best:
                best, state, selected = value, deepcopy(model.state_dict()), epoch + 1
            if progress and (epoch == 0 or (epoch + 1) % 5 == 0 or epoch + 1 == epochs):
                progress(f'[NEIGHBORHOOD] {variant}/{arm} seed={seed} epoch={epoch+1}/{epochs} primary_val={value:.6g}')
        model.load_state_dict(state); model.eval()
        output[arm] = dict(model=model, history=history, selected_epoch=selected,
                           state=state, initial=initial, target_scaler=normalization)
    return output, targets
