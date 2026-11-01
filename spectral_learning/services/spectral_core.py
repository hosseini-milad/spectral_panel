"""Sparse, disconnected-graph spectral analysis with invariant message descriptors."""
from dataclasses import dataclass
import time
from numbers import Integral

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import LinearOperator, eigsh
from threadpoolctl import threadpool_limits

DIFFUSION_SCALES = np.array([.1, 1., 10.])


@dataclass
class SpectralResult:
    summary: dict
    blocks: list
    arrays: dict


def adjacency(node_count, edges):
    """Require one finite, positive undirected edge per pair; retain all nodes."""
    pairs, weights, seen = [], [], set()
    for edge in edges:
        if not isinstance(edge['source'], Integral) or not isinstance(edge['target'], Integral):
            raise ValueError('Edge indices must be integers')
        left, right, weight = int(edge['source']), int(edge['target']), float(edge.get('weight', 1.))
        if not 0 <= left < node_count or not 0 <= right < node_count:
            raise ValueError(f'Edge outside node_order: {left}, {right}')
        if left == right:
            raise ValueError('Self-loops require a separate operator contract; source graph contains one.')
        if not np.isfinite(weight) or weight <= 0:
            raise ValueError('Spectral phase requires finite positive edge weights.')
        pair = (min(left, right), max(left, right))
        if pair in seen:
            raise ValueError(f'Duplicate undirected edge: {pair}')
        seen.add(pair); pairs.append(pair); weights.append(weight)
    order = sorted(range(len(pairs)), key=lambda index: pairs[index])
    pairs = np.asarray([pairs[index] for index in order], dtype=np.int64).reshape(-1, 2)
    weights = np.asarray([weights[index] for index in order], dtype=np.float64)
    if len(pairs):
        rows = np.r_[pairs[:, 0], pairs[:, 1]]; cols = np.r_[pairs[:, 1], pairs[:, 0]]
        matrix = sparse.csr_matrix((np.r_[weights, weights], (rows, cols)), shape=(node_count, node_count))
    else:
        matrix = sparse.csr_matrix((node_count, node_count), dtype=float)
    return matrix, pairs.T.copy(), weights


def normalized_laplacian(matrix):
    degree = np.asarray(matrix.sum(axis=1)).ravel()
    inv = np.divide(1., np.sqrt(degree), out=np.zeros_like(degree), where=degree > 0)
    lap = sparse.diags((degree > 0).astype(float)) - sparse.diags(inv) @ matrix @ sparse.diags(inv)
    return lap.tocsr(), degree


def eigen_groups(values, tolerance):
    result = []
    for index, value in enumerate(values):
        if not result or abs(value - values[result[-1][-1]]) > tolerance * (1 + abs(value)):
            result.append([index])
        else:
            result[-1].append(index)
    return result


def choose_basis(values, requested, budget, all_known, tolerance):
    groups, selected = eigen_groups(values, tolerance), []
    need_more, limited = False, False
    for group in groups:
        if group[-1] + 1 > budget:
            limited = True; break
        if group[-1] == len(values) - 1 and not all_known:
            need_more = True; break
        selected.append(group)
        if sum(map(len, selected)) >= requested:
            break
    return selected, need_more, limited


def invariant_features(vectors, values, groups, pairs, scales=DIFFUSION_SCALES):
    """Projector-based signatures invariant to signs/rotations WITHIN full groups.

    Returned node heat diagonals and edge diffusion distances use only the
    retained nontrivial eigenspaces. They are not the complete heat kernel.
    """
    node = np.zeros((len(vectors), len(scales)))
    edge = np.zeros((len(pairs), len(scales)))
    for group in groups:
        block = vectors[:, group]
        weight = np.exp(-np.mean(values[group]) * np.asarray(scales))
        node += np.sum(block ** 2, axis=1)[:, None] * weight
        if len(pairs):
            distances = .5 * np.sum((block[pairs[:, 0]] - block[pairs[:, 1]]) ** 2, axis=1)
            edge += distances[:, None] * weight
    return node, edge


def solve_block(lap, degree, *, requested=8, budget=32, dense_limit=256,
                tolerance=1e-8, group_tolerance=1e-7, seed=17):
    n = lap.shape[0]
    if n == 1:
        return np.empty(0), np.empty((1, 0)), [], {
            'solver': 'analytic_isolate', 'spectrum_kind': 'full', 'full_eigenvalues': [0.],
            'computed_positive_values': [], 'basis_dim': 0, 'basis_limited': False,
            'residual_max': 0., 'orthogonality_max': 0., 'kernel_overlap_max': 0.,
            'bounds_ok': True, 'fiedler_value': None, 'near_zero_nontrivial_count': 0,
        }
    kernel = np.sqrt(degree); kernel /= np.linalg.norm(kernel)
    full_values = None
    if n <= dense_limit:
        raw_values, raw_vectors = np.linalg.eigh(lap.toarray())
        trivial = int(np.argmax(np.abs(raw_vectors.T @ kernel)))
        if abs(raw_values[trivial]) > tolerance:
            raise ValueError('Dense solver did not recover the known trivial eigenmode.')
        keep = np.arange(n) != trivial
        values, vectors = raw_values[keep], raw_vectors[:, keep]
        full_values = raw_values.tolist(); all_known = True
        groups, _, limited = choose_basis(values, requested, budget, True, group_tolerance)
        solver = 'dense_connected_block'
    else:
        # Shift the known zero mode above [0,2] so sparse SM solves target
        # nontrivial modes without asking for k + global_component_count modes.
        operator = LinearOperator(lap.shape, matvec=lambda x: lap @ x + 3 * kernel * np.dot(kernel, x), dtype=float)
        count = min(n - 1, max(2, requested + 8))
        rng = np.random.default_rng(seed)
        while True:
            values, vectors = eigsh(operator, k=count, which='SM', tol=tolerance * .1,
                                    maxiter=max(3000, n * 20), v0=rng.normal(size=n))
            order = np.argsort(values); values, vectors = values[order], vectors[:, order]
            all_known = count == n - 1
            groups, more, limited = choose_basis(values, requested, budget, all_known, group_tolerance)
            if not more or limited:
                break
            new_count = min(n - 1, budget + 1, count + 8)
            if new_count <= count:
                limited = True; break
            count = new_count
        if all_known:
            full_values = [0.] + values.tolist()
        solver = 'sparse_deflated_connected_block'
    # Check raw solver results BEFORE any rounding or clipping.
    bounds_ok = bool(np.all(values >= -tolerance) and np.all(values <= 2 + tolerance) and np.isfinite(values).all())
    residual = float(np.max(np.linalg.norm(lap @ vectors - vectors * values, axis=0)))
    orthogonality = float(np.max(np.abs(vectors.T @ vectors - np.eye(len(values)))))
    kernel_overlap = float(np.max(np.abs(vectors.T @ kernel)))
    if not bounds_ok or max(residual, orthogonality, kernel_overlap) > 1e-6:
        raise ValueError(f'Eigenpair validation failed: bounds={bounds_ok}, residual={residual}, orthogonality={orthogonality}, kernel_overlap={kernel_overlap}')
    selected = [index for group in groups for index in group]
    remapped, start = [], 0
    for group in groups:
        remapped.append(list(range(start, start + len(group)))); start += len(group)
    metadata = {
        'solver': solver, 'spectrum_kind': 'full' if full_values is not None else 'partial',
        'full_eigenvalues': full_values, 'computed_positive_values': values.tolist(),
        'basis_dim': len(selected), 'basis_limited': bool(limited),
        'residual_max': residual, 'orthogonality_max': orthogonality,
        'kernel_overlap_max': kernel_overlap, 'bounds_ok': bounds_ok,
        'fiedler_value': float(values[0]),
        'near_zero_nontrivial_count': int(np.sum(values <= tolerance)),
    }
    return values[selected], vectors[:, selected], remapped, metadata


def analyze_graph(graph, *, requested=8, budget=32, dense_limit=256, progress=None):
    began = time.perf_counter()
    n = len(graph.node_ids)
    if not n or len(set(graph.node_ids)) != n:
        raise ValueError('Graph requires a nonempty, unique node_order.')
    matrix, edge_index, edge_weight = adjacency(n, graph.edges)
    lap, degree = normalized_laplacian(matrix)
    count, labels = connected_components(matrix, directed=False)
    parts = sorted([np.flatnonzero(labels == index) for index in range(count)], key=lambda part: (-len(part), int(part[0])))
    lookup = graph.block_lookup
    if lookup is not None and set(lookup) != {frozenset(part.tolist()) for part in parts}:
        raise ValueError(f'{graph.key}: stored component membership differs from graph topology.')
    basis = np.zeros((n, budget)); basis_values = np.zeros((n, budget)); basis_mask = np.zeros((n, budget), dtype=bool)
    global_columns = np.full((n, budget), -1, dtype=np.int64)
    global_values = []
    node_spectral = np.zeros((n, 3)); edge_spectral = np.zeros((len(edge_weight), 3))
    node_valid = np.zeros(n, dtype=bool); edge_valid = np.zeros(len(edge_weight), dtype=bool)
    block_index = np.empty(n, dtype=np.int64)
    for index, part in enumerate(parts):
        block_index[part] = index
    edges_by_block = [[] for _ in parts]
    for index in range(len(edge_weight)):
        edges_by_block[block_index[edge_index[0, index]]].append(index)
    blocks = []
    with threadpool_limits(limits=1):
        for index, part in enumerate(parts):
            start = time.perf_counter()
            if progress and len(part) > dense_limit:
                progress(f'[SPECTRAL] Sparse solve: block={index}; nodes={len(part)}; requested={requested}; basis_budget={budget}')
            sub = lap[part][:, part].tocsr()
            values, vectors, groups, metadata = solve_block(sub, degree[part], requested=requested,
                                                           budget=budget, dense_limit=dense_limit)
            d = len(values)
            offset = len(global_values)
            global_values.extend(values.tolist())
            basis[np.ix_(part, np.arange(d))] = vectors
            basis_values[np.ix_(part, np.arange(d))] = values
            basis_mask[np.ix_(part, np.arange(d))] = True
            global_columns[np.ix_(part, np.arange(d))] = np.arange(offset, offset + d)
            local_index = {int(node): i for i, node in enumerate(part)}
            selected_edges = np.asarray(edges_by_block[index], dtype=np.int64)
            pairs = np.array([[local_index[int(edge_index[0, e])], local_index[int(edge_index[1, e])]]
                              for e in selected_edges], dtype=np.int64).reshape(-1, 2)
            node_features, edge_features = invariant_features(vectors, values, groups, pairs)
            node_spectral[part] = node_features; edge_spectral[selected_edges] = edge_features
            node_valid[part] = d > 0; edge_valid[selected_edges] = d > 0
            blocks.append(dict(metadata, block_index=index, node_indices=part.tolist(), node_count=len(part),
                               basis_column_offset=offset,
                               source_component_id=lookup[frozenset(part.tolist())] if lookup is not None else None,
                               eigenvalue_groups=groups, selected_values=values.tolist(),
                               elapsed_seconds=time.perf_counter() - start))
            if progress and (index % 50 == 0 or index == len(parts) - 1):
                progress(f'[SPECTRAL] {graph.key}: blocks {index + 1}/{len(parts)}; largest={len(parts[0])}')
    full = all(block['spectrum_kind'] == 'full' for block in blocks)
    full_values = [value for block in blocks for value in (block['full_eigenvalues'] or [])]
    histogram = None; entropy = None
    if full:
        hist = np.histogram(full_values, bins=32, range=(-1e-8, 2 + 1e-8))[0].astype(float)
        hist /= hist.sum(); histogram = hist.tolist()
        entropy = float(-np.sum(hist[hist > 0] * np.log(hist[hist > 0])) / np.log(32))
    symmetry = lap - lap.T
    symmetry_error = float(np.max(np.abs(symmetry.data))) if symmetry.nnz else 0.
    if symmetry_error > 1e-10:
        raise ValueError('Normalized Laplacian symmetry validation failed')
    isolates = int(np.sum(degree == 0))
    summary = {
        'graph_key': graph.key, 'layer': graph.layer, 'node_type': graph.node_type,
        'analysis_parameters': {'requested_eigenvectors': requested, 'max_basis': budget,
                                'dense_limit': dense_limit, 'solver_tolerance': 1e-8,
                                'eigenspace_group_tolerance': 1e-7, 'seed': 17, 'linear_algebra_threads': 1},
        'node_count': n, 'edge_count': len(edge_weight), 'component_count': int(count),
        'isolate_count': isolates, 'expected_zero_modes': int(count), 'expected_positive_rank': n - int(count),
        'zero_mode_source': 'topology_with_zero_diagonal_for_isolates',
        'global_lambda2': 0. if count > 1 else (blocks[0]['fiedler_value'] if n > 1 else None),
        'spectrum_kind': 'full' if full else 'mixed_full_and_partial',
        'full_spectrum_node_coverage_percent': 100 * len(full_values) / n,
        'full_spectrum_histogram': histogram, 'full_spectrum_entropy': entropy,
        'encoded_node_count': int(node_valid.sum()), 'encoded_node_percent': 100 * float(node_valid.mean()),
        'encoded_nonisolate_percent': 100 * int(node_valid.sum()) / (n - isolates) if n > isolates else None,
        'basis_limited_blocks': sum(block['basis_limited'] for block in blocks),
        'max_basis_dim_used': max(block['basis_dim'] for block in blocks),
        'total_retained_eigenvectors': len(global_values),
        'basis_layout': 'block_local_slots_with_explicit_global_column_mapping',
        'global_basis_order': 'block_then_within_block_eigenvalue',
        'max_residual': max(block['residual_max'] for block in blocks),
        'max_orthogonality_error': max(block['orthogonality_max'] for block in blocks),
        'max_kernel_overlap': max(block['kernel_overlap_max'] for block in blocks),
        'operator_symmetry_error': symmetry_error,
        'eigenvalue_bounds_pass': all(block['bounds_ok'] for block in blocks),
        'dense_full_matrix_estimate_mib': n * n * 8 / 1024 ** 2,
        'peak_memory_measured': False, 'elapsed_seconds': time.perf_counter() - began,
        'message_passing_executed': False, 'learned_embeddings_generated': False,
        'diffusion_scales': DIFFUSION_SCALES.tolist(),
        'diffusion_semantics': 'truncated_nontrivial_eigenspace_projector_features_not_full_heat_kernel',
        'numerical_checks_pass': symmetry_error <= 1e-10,
        'analysis_status': 'complete_with_basis_limitations' if any(block['basis_limited'] for block in blocks) else 'complete',
    }
    arrays = {'node_ids': np.asarray(graph.node_ids, dtype=str), 'edge_index': edge_index, 'edge_weight': edge_weight,
              'eigenvectors': basis, 'eigenvalues': basis_values, 'basis_mask': basis_mask,
              'basis_global_columns': global_columns, 'global_basis_eigenvalues': np.asarray(global_values),
              'node_spectral': node_spectral, 'edge_spectral': edge_spectral,
              'node_spectral_mask': node_valid, 'edge_spectral_mask': edge_valid,
              'block_index': block_index, 'node_features': graph.features, 'node_feature_mask': graph.feature_mask,
              'feature_names': np.asarray(graph.feature_names, dtype=str)}
    return SpectralResult(summary, blocks, arrays)
