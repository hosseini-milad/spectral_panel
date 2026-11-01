"""Rebuild an explicitly new similarity graph on existing connected-block units.

This is not quotient-edge preservation: connected components have no cross edges.
Raw attribute moments carry original component mass through every higher level.
"""
from dataclasses import dataclass
import numpy as np
from threadpoolctl import threadpool_limits

from .spectral_inputs import GraphInput


@dataclass
class MomentState:
    mean: np.ndarray
    variance: np.ndarray
    count: np.ndarray
    mass: np.ndarray
    names: tuple


def initial_moments(graph):
    return MomentState(graph.features.copy(), np.zeros_like(graph.features), graph.feature_mask.astype(float),
                       np.ones(len(graph.node_ids)), tuple(graph.feature_names))


def aggregate_moments(state, blocks):
    means, variances, counts, masses = [], [], [], []
    for block in blocks:
        indices = np.asarray(block['node_indices'])
        count = state.count[indices].sum(axis=0)
        mean = np.divide((state.mean[indices] * state.count[indices]).sum(axis=0), count,
                         out=np.zeros_like(count), where=count > 0)
        # Centered mixture formula avoids cancellation in E[x^2] - E[x]^2.
        variance = np.divide(((state.variance[indices] + (state.mean[indices] - mean) ** 2) * state.count[indices]).sum(axis=0),
                             count, out=np.zeros_like(count), where=count > 0)
        means.append(mean); variances.append(variance); counts.append(count); masses.append(state.mass[indices].sum())
    return MomentState(np.asarray(means), np.asarray(variances), np.asarray(counts), np.asarray(masses), state.names)


def global_moments(state):
    return aggregate_moments(state, [{'node_indices': list(range(len(state.mass)))}])


def partition_audit(child, state, parent, blocks):
    flattened = [i for block in blocks for i in block['node_indices']]
    if sorted(flattened) != list(range(len(child.node_ids))):
        raise ValueError('Higher-layer partition must assign every child exactly once.')
    before, after = global_moments(state), global_moments(parent)
    mean_error = float(np.max(np.abs(before.mean - after.mean)))
    variance_error = float(np.max(np.abs(before.variance - after.variance)))
    if not np.allclose(before.mean, after.mean, rtol=1e-10, atol=1e-10) or not np.allclose(before.variance, after.variance, rtol=1e-10, atol=1e-10):
        raise ValueError('Higher-layer aggregation failed moment conservation.')
    block_for = np.empty(len(flattened), dtype=int)
    for index, block in enumerate(blocks):
        block_for[block['node_indices']] = index
    cross_edges = sum(block_for[edge['source']] != block_for[edge['target']] for edge in child.edges)
    if cross_edges:
        raise ValueError('Source blocks are not connected components: unexpected cross-block edges.')
    residual = np.sum(state.count * (state.mean - parent.mean[block_for]) ** 2, axis=0)
    total = np.sum(state.count * (state.variance + (state.mean - before.mean[0]) ** 2), axis=0)
    ratios = np.divide(residual, total, out=np.zeros_like(residual), where=total > 1e-15)
    return dict(child_node_count=len(flattened), parent_node_count=len(blocks), partition_exactly_once=True,
                original_component_mass_before=float(state.mass.sum()), original_component_mass_after=float(parent.mass.sum()),
                observed_attribute_counts_preserved=bool(np.allclose(state.count.sum(axis=0), parent.count.sum(axis=0))),
                global_mean_max_absolute_error=mean_error, global_variance_max_absolute_error=variance_error,
                child_mean_reconstruction_variance_fraction=ratios.tolist(),
                child_mean_reconstruction_semantics='Per-attribute loss from replacing child means by group means / total original-component variance; not a spectral preservation score.',
                quotient_cross_edges=int(cross_edges), edge_origin='new_attribute_similarity_not_source_quotient',
                spectral_preservation=None)


def descriptor_edges(values, observed, *, neighbors=8, threshold=.85, bandwidth=1., minimum_shared=3, batch_size=128, progress=None):
    """Exact mutual kNN over masked standardized RBF distances; bounded B x N memory.

    Constant fields carry no distance but remain available for shared-field coverage.
    Equal descriptors get a deterministic ring, preventing tie-induced star graphs.
    """
    n, width = values.shape
    if n == 0 or values.shape != observed.shape or not np.isfinite(values[observed]).all():
        raise ValueError('Invalid higher-layer descriptors')
    if not 1 <= neighbors <= 128 or not 0 < threshold <= 1 or not np.isfinite(bandwidth) or bandwidth <= 0 or minimum_shared < 1:
        raise ValueError('Invalid similarity graph parameters')
    mean = np.zeros(width); scale = np.ones(width)
    for col in range(width):
        entries = values[observed[:, col], col]
        if len(entries):
            mean[col] = entries.mean(); scale[col] = max(entries.std(), 1e-6)
    x = np.where(observed, (values - mean) / scale, 0.)
    m = observed.astype(float); x2 = x * x
    selected = []; scores = {}; duplicate_groups = {}
    for i in range(n):
        duplicate_groups.setdefault((observed[i].tobytes(), values[i][observed[i]].tobytes()), []).append(i)
    with threadpool_limits(limits=1):
        for start in range(0, n, batch_size):
            stop = min(n, start + batch_size)
            shared = m[start:stop] @ m.T
            distance = x2[start:stop] @ m.T + m[start:stop] @ x2.T - 2 * x[start:stop] @ x.T
            distance = np.divide(np.maximum(distance, 0), shared, out=np.full_like(distance, np.inf), where=shared >= minimum_shared)
            similarity = np.exp(-distance / (2 * bandwidth ** 2))
            for row, i in enumerate(range(start, stop)):
                similarity[row, i] = 0
                eligible = np.flatnonzero(similarity[row] >= threshold)
                order = eligible[np.lexsort((eligible, -similarity[row, eligible]))][:neighbors]
                selected.append(set(order.tolist()))
                for j in order:
                    scores[(i, int(j))] = float(similarity[row, j])
            if progress:
                progress(f'[UPPER GRAPH] descriptor comparisons {stop}/{n}; neighbors={neighbors}')
    pairs = {}; degree = np.zeros(n, dtype=int)
    def add(i, j, weight):
        pair = tuple(sorted((i, j)))
        if i != j and pair not in pairs and degree[i] < neighbors and degree[j] < neighbors:
            pairs[pair] = weight; degree[i] += 1; degree[j] += 1
    for group in duplicate_groups.values():
        if len(group) > 1 and observed[group[0]].sum() >= minimum_shared:
            for i, j in zip(group, group[1:] + group[:1]):
                add(i, j, 1.)
    candidates = [(scores[(i, j)], i, j) for i in range(n) for j in selected[i] if i < j and i in selected[j]]
    for weight, i, j in sorted(candidates, key=lambda row: (-row[0], row[1], row[2])):
        add(i, j, weight)
    return [dict(source=i, target=j, weight=weight) for (i, j), weight in sorted(pairs.items())], dict(
        method='masked_standardized_rbf_mutual_knn_duplicate_ring', neighbors=neighbors, degree_cap=neighbors,
        threshold=threshold, bandwidth=bandwidth, minimum_shared_fields=minimum_shared,
        descriptor_mean=mean.tolist(), descriptor_scale=scale.tolist(), max_degree=int(degree.max()),
        original_source_edge_preservation='not_claimed_new_similarity_relations', zero_eligible_nodes=int(sum(not row for row in selected)))


def build_upper_graph(child, child_result, state, *, run_id, neighbors=8, threshold=.85, bandwidth=1., progress=None):
    blocks = child_result.blocks
    parent = aggregate_moments(state, blocks)
    audit = partition_audit(child, state, parent, blocks)
    descriptor = np.column_stack([parent.mean, np.sqrt(parent.variance)])
    observed = np.column_stack([parent.count > 0, parent.count > 0])
    edges, policy = descriptor_edges(descriptor, observed, neighbors=neighbors, threshold=threshold, bandwidth=bandwidth, minimum_shared=6, progress=progress)
    ids = [block.get('source_component_id') or f'{child.key}:group:{block["block_index"]}' for block in blocks]
    # Size is an input/target, never an edge descriptor. Learned coordinates never define edges.
    features = np.column_stack([descriptor, np.log1p(parent.mass)])
    mask = np.column_stack([observed, np.ones(len(blocks), dtype=bool)])
    names = tuple(f'{name}_mean' for name in state.names) + tuple(f'{name}_std' for name in state.names) + ('log_original_component_count',)
    lineage = []
    for block in blocks:
        chunks = set()
        for index in block['node_indices']:
            row = (child.lineage or [{} for _ in child.node_ids])[index] or {}
            chunks.update(row.get('source_chunks', []))
            if row.get('chunk_index') is not None:
                chunks.add(row['chunk_index'])
        lineage.append(dict(source_graph_key=child.key, child_node_indices=block['node_indices'],
                            child_node_ids=[child.node_ids[i] for i in block['node_indices']],
                            source_chunks=sorted(chunks), original_component_count=int(parent.mass[block['block_index']])))
    key = f'hierarchy-meta-day-{child.day}-layer-{child.layer + 1}'
    source = dict(collection='upper_spectral_graphs', upper_run_id=run_id, parent_source_signature=child.signature,
                  source_graph_key=child.key, graph_parameters=policy, descriptor_feature_names=list(names[:-1]),
                  time_basis='same_day_structural_level_not_a_time_window',
                  aggregation='original_layer1_component_mass_weighted_moments_not_raw_flow_weighted',
                  edge_origin='new_similarity_graph_not_quotient', learned_embeddings_used_for_edges=False)
    return GraphInput(key, child.day, child.layer + 1, None, 'meta_component' if child.layer == 2 else 'higher_meta_component',
                      ids, edges, features, mask, names, source, lineage=lineage), parent, audit
