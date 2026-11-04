"""Representation diagnostics only: no anomaly threshold or attack-label metric."""
import numpy as np
import torch

from .autoencoder_training import reconstruct
from .message_passing_evaluation import tensors, pool_blocks


def covering_masks(observed, passes=5, seed=17):
    """Disjoint, seeded partitions: each active observed entry is predicted once."""
    observed = np.asarray(observed, dtype=bool)
    if observed.ndim != 2 or not 2 <= passes <= 20:
        raise ValueError('Require a 2-D observation mask and 2..20 mask passes')
    masks = np.zeros((passes, *observed.shape), dtype=bool)
    rng = np.random.default_rng(seed)
    for row in range(len(observed)):
        columns = rng.permutation(np.flatnonzero(observed[row]))
        offset = int(rng.integers(passes))
        for i, column in enumerate(columns):
            masks[(i + offset) % passes, row, column] = True
    return masks


def latent_geometry(z):
    z = np.asarray(z, dtype=float)
    if z.ndim != 2 or not len(z) or not np.isfinite(z).all():
        raise ValueError('Latent matrix must be nonempty, two-dimensional and finite')
    centered = z - z.mean(axis=0)
    eigenvalues = np.maximum(np.linalg.eigvalsh(centered.T @ centered / len(z)), 0)
    total = float(eigenvalues.sum())
    probability = eigenvalues[eigenvalues > 0] / total if total > 1e-12 else np.asarray([])
    return dict(nodes=len(z), latent_dim=z.shape[1], covariance_trace=total,
                effective_rank=float(np.exp(-(probability * np.log(probability)).sum())) if len(probability) else 0.,
                participation_ratio=float(total ** 2 / np.sum(eigenvalues ** 2)) if total > 1e-12 else 0.,
                rank_estimable=len(z) > 1, latent_norm_mean=float(np.linalg.norm(z, axis=1).mean()),
                geometry_semantics='Population covariance eigenvalues; effective rank=exp(entropy); no pass/fail cutoff')


def measured_neighborhood(arrays, values, observed):
    """Measured full-graph descriptors, not predictions or new encoder inputs."""
    values = np.asarray(values, dtype=float)
    observed = np.asarray(observed, dtype=bool)
    n, width = values.shape
    left, right = arrays['edge_index']
    source = np.r_[left, right]; target = np.r_[right, left]
    weights = np.r_[arrays['edge_weight'], arrays['edge_weight']]
    count = np.zeros((n, width), dtype=int)
    total = np.zeros((n, width)); squared = np.zeros((n, width))
    clean = np.where(observed, values, 0)
    np.add.at(count, target, observed[source])
    np.add.at(total, target, clean[source])
    np.add.at(squared, target, clean[source] ** 2)
    mean = np.divide(total, count, out=np.zeros_like(total), where=count > 0)
    variance = np.divide(squared, count, out=np.zeros_like(total), where=count > 0) - mean ** 2
    return dict(degree=np.bincount(target, minlength=n),
                weighted_degree=np.bincount(target, weights=weights, minlength=n),
                neighbor_feature_mean=mean, neighbor_feature_std=np.sqrt(np.maximum(variance, 0)),
                neighbor_feature_valid=count > 0, neighbor_observation_count=count)


def _infer(model, arrays, values, observed):
    with torch.no_grad():
        prediction, z = model(tensors(arrays, values, observed))
    if not torch.isfinite(prediction).all() or not torch.isfinite(z).all():
        raise ValueError('Nonfinite decoder output or latent representation')
    return reconstruct(prediction), z.detach().numpy()


def permutation_check(model, chunk, full_latent, seed=17):
    n = len(chunk.values)
    order = np.random.default_rng(seed).permutation(n)
    inverse = np.empty(n, dtype=int); inverse[order] = np.arange(n)
    arrays = dict(chunk.original.arrays)
    arrays['node_spectral'] = arrays['node_spectral'][order]
    arrays['node_spectral_mask'] = arrays['node_spectral_mask'][order]
    arrays['edge_index'] = inverse[arrays['edge_index']]
    _, z = _infer(model, arrays, chunk.values[order], chunk.mask[order])
    error = float(np.max(np.abs(z[inverse] - full_latent)))
    if error > 1e-4:
        raise ValueError(f'Frozen encoder node-order equivariance failed: {error}')
    return error


def audit_chunk(model, chunk, *, passes=5, seed=17):
    model.eval()
    _, full_z = _infer(model, chunk.original.arrays, chunk.values, chunk.mask)
    _, masked_graph_z = _infer(model, chunk.spectral.arrays, chunk.values, chunk.mask)
    masks = covering_masks(chunk.mask, passes, seed)
    n, width = chunk.values.shape
    target_count = np.zeros((passes, n), dtype=int)
    masked_mse = np.zeros((passes, n), dtype=float)
    sensitivity = np.zeros((passes, n), dtype=float)
    sensitivity_valid = np.zeros((passes, n), dtype=bool)
    squared_error_sum = np.zeros((n, width), dtype=float)
    base_norm = np.linalg.norm(masked_graph_z, axis=1)
    for index, hidden in enumerate(masks):
        if not hidden.any():
            continue
        prediction, z = _infer(model, chunk.spectral.arrays, chunk.values, chunk.mask & ~hidden)
        error = (prediction.astype(float) - chunk.values) ** 2
        target_count[index] = hidden.sum(axis=1)
        sse = np.where(hidden, error, 0)
        squared_error_sum += sse
        np.divide(sse.sum(axis=1), target_count[index], out=masked_mse[index], where=target_count[index] > 0)
        sensitivity_valid[index] = base_norm > 1e-12
        np.divide(np.linalg.norm(z - masked_graph_z, axis=1), base_norm,
                  out=sensitivity[index], where=sensitivity_valid[index])
    coverage = masks.sum(axis=0)
    if not np.array_equal(coverage, chunk.mask.astype(int)):
        raise ValueError('Mask partition lost or duplicated feature targets')
    count = target_count.sum(axis=0)
    error_mean = np.divide(squared_error_sum.sum(axis=1), count,
                           out=np.zeros(n), where=count > 0)
    pass_valid = target_count > 0
    pass_count = pass_valid.sum(axis=0)
    # Variation across different target subsets is a sensitivity diagnostic,
    # not a calibrated predictive uncertainty or confidence interval.
    pass_mean = np.divide(masked_mse.sum(axis=0), pass_count, out=np.zeros(n), where=pass_count > 0)
    pass_variance = np.divide(np.where(pass_valid, (masked_mse-pass_mean) ** 2, 0).sum(axis=0),
                              pass_count, out=np.zeros(n), where=pass_count > 0)
    feature_count = coverage.sum(axis=0)
    feature_mse = np.divide(squared_error_sum.sum(axis=0), feature_count,
                            out=np.zeros(width), where=feature_count > 0)
    comparable_count = sensitivity_valid.sum(axis=0)
    mean_sensitivity = np.divide(sensitivity.sum(axis=0), comparable_count,
                                 out=np.zeros(n), where=comparable_count > 0)
    component_mean, component_std, size = pool_blocks(full_z, chunk.original.arrays['block_index'])
    pooled_mean = np.average(component_mean, axis=0, weights=size)
    pooled_variance = np.average(component_std ** 2 + (component_mean-pooled_mean) ** 2, axis=0, weights=size)
    if int(size.sum()) != n or not np.allclose(pooled_mean, full_z.astype(float).mean(axis=0), rtol=1e-8, atol=1e-8) or not np.allclose(pooled_variance, full_z.astype(float).var(axis=0), rtol=1e-8, atol=1e-8):
        raise ValueError('Component pooling failed candidate-mass or moment conservation')
    permutation_error = permutation_check(model, chunk, full_z, seed)
    summary = dict(**latent_geometry(full_z), components=len(size),
        observed_active_entries=int(chunk.mask.sum()), predicted_entries=int(coverage.sum()),
        nodes_without_feature_targets=int((count == 0).sum()),
        covering_reconstruction_mse=float(squared_error_sum.sum() / coverage.sum()) if coverage.sum() else None,
        mask_relative_latent_change_mean=float(sensitivity[sensitivity_valid].mean()) if sensitivity_valid.any() else None,
        topology_holdout_relative_change=float(np.linalg.norm(full_z-masked_graph_z) / np.linalg.norm(full_z)) if np.linalg.norm(full_z) > 1e-12 else None,
        permutation_max_absolute_error=permutation_error, pooling_moments_verified=True,
        spectral_numeric_checks=bool(chunk.original.summary['numerical_checks_pass']))
    arrays = dict(latent=full_z, mask_target_count=target_count, mask_reconstruction_mse=masked_mse,
        mask_error_valid=pass_valid, covering_reconstruction_mse=error_mean, feature_error_valid=count > 0,
        mask_subset_mse_std=np.sqrt(pass_variance), observed_active_count=count,
        feature_target_coverage=coverage, feature_squared_error_sum=squared_error_sum,
        mask_relative_latent_change=sensitivity, mask_latent_change_valid=sensitivity_valid,
        mean_mask_relative_latent_change=mean_sensitivity, component_latent_mean=component_mean,
        component_latent_std=component_std, component_size=size)
    features = [dict(feature=name, targets=int(feature_count[i]),
                     mse=float(feature_mse[i]) if feature_count[i] else None)
                for i, name in enumerate(chunk.graph.feature_names)]
    return summary, arrays, features
