"""Raw allowlisted feature views and masked graph topology, independent of labels."""
from dataclasses import dataclass, replace
import math
import numpy as np
from mongoengine import get_db

from ingestion.services.graph.components import load_node_documents
from .spectral_inputs import load_inputs, feature_array, FEATURES, fingerprint
from .spectral_core import analyze_graph

BINARY = np.asarray([name.startswith('flag_') or name.startswith('proto_') or name in {'is_encrypted_port', 'is_syn_only'} for name in FEATURES])


def load_raw_chunks(day):
    graphs, _ = load_inputs(day, scope='chunks'); db = get_db()
    originals_seen = set()
    for graph in graphs:
        ids = [row['original_id'] for row in graph.lineage]
        if len(set(ids)) != len(ids) or originals_seen.intersection(ids):
            raise ValueError('Raw candidate IDs overlap across selected chunks')
        originals_seen.update(ids)
        docs = load_node_documents(db, ids, 'security_data')
        if len(docs) != len(ids):
            raise ValueError(f'{graph.key}: missing original raw records; no normalized-data fallback is used.')
        ordered = [dict(docs[value]) for value in ids]
        for doc in ordered:
            protocol = str(doc.get('protocol', '')).lower()
            if protocol in {'tcp', 'udp', 'icmp'}:
                for label in ('tcp', 'udp', 'icmp'):
                    doc.setdefault('proto_' + label, int(protocol == label))
        values, mask = feature_array(ordered)
        mask &= np.where(BINARY[None, :], (values == 0) | (values == 1), values >= 0)
        values[~mask] = 0
        graph.features = values; graph.feature_mask = mask
        graph.source = dict(graph.source, autoencoder_feature_view='raw_allowlist_v1',
            raw_feature_digest=fingerprint(dict(original_ids=ids, features=values.tolist(), mask=mask.tolist())),
            validity_semantics='finite_present_nonnegative_or_binary_not_proof_of_original_measurement_validity')
    return graphs


def chunk_splits(graphs):
    if len(graphs) < 3:
        raise ValueError('Require at least 3 chunk graphs for disjoint train/validation/test chunk sets.')
    train = max(1, int(.6 * len(graphs))); validation = max(1, int(.2 * len(graphs)))
    return {g.key: ('train' if i < train else 'validation' if i < train + validation else 'test') for i, g in enumerate(graphs)}


def log_values(values):
    output = values.copy()
    output[:, ~BINARY] = np.log1p(output[:, ~BINARY])
    return output


def fit_scaler(graphs, splits):
    means = np.zeros(len(FEATURES)); scales = np.ones(len(FEATURES)); active = np.zeros(len(FEATURES), dtype=bool)
    observed_counts = np.zeros(len(FEATURES), dtype=int); baseline = np.zeros(len(FEATURES)); audit = []
    for col, name in enumerate(FEATURES):
        values = np.concatenate([log_values(g.features)[g.feature_mask[:, col], col] for g in graphs if splits[g.key] == 'train'])
        observed_counts[col] = len(values)
        average = float(values.mean()) if len(values) else 0.
        std = float(values.std()) if len(values) else 0.
        active[col] = len(values) >= 2 and std > 1e-6
        if not BINARY[col]:
            means[col] = average; scales[col] = max(std, 1e-6)
        baseline[col] = average if BINARY[col] else 0.
        audit.append(dict(feature=name, family='binary' if BINARY[col] else 'log_continuous', train_observations=len(values),
                          train_mean_transformed=average, train_std_transformed=std, trained=bool(active[col])))
    if not active.any():
        raise ValueError('No varying observed raw training feature is available.')
    return dict(mean=means, scale=scales, active=active, binary=BINARY.copy(), baseline=baseline,
                train_observation_count=observed_counts), audit


def transform(graph, scaler):
    values = (log_values(graph.features) - scaler['mean']) / scaler['scale']
    values[~graph.feature_mask] = 0
    if not np.isfinite(values).all():
        raise ValueError('Nonfinite transformed feature values')
    return values.astype('float32'), graph.feature_mask & scaler['active'][None, :]


def feature_corruption(mask, rng, rate=.2):
    selected = (rng.random(mask.shape) < rate) & mask
    for row in np.flatnonzero(mask.any(axis=1) & ~selected.any(axis=1)):
        columns = np.flatnonzero(mask[row]); selected[row, rng.choice(columns)] = True
    return selected


def masked_topology(graph, original, seed=17, max_pairs=2048):
    rng = np.random.default_rng(seed); edges = list(graph.edges)
    chosen = rng.choice(len(edges), min(max_pairs, max(1, int(math.ceil(.1 * len(edges))))), replace=False) if edges else np.array([], dtype=int)
    chosen_set = set(chosen.tolist())
    positive = [(edges[i]['source'], edges[i]['target']) for i in chosen]
    weights = np.asarray([edges[i].get('weight', 1.) for i in chosen], dtype='float32')
    if len(weights) and (np.any(weights <= 0) or np.any(weights > 1)):
        raise ValueError('The layer-1 decoder expects positive similarity weights <=1.')
    existing = {tuple(sorted((edge['source'], edge['target']))) for edge in edges}
    eligible = [np.asarray(block['node_indices']) for block in original.blocks if block['node_count'] > 2]
    negative = set(); attempts = 0
    # Nonedges only within original connected blocks: no trivial cross-block negatives.
    while eligible and len(negative) < len(positive) and attempts < max(100, 50 * len(positive)):
        members = eligible[int(rng.integers(len(eligible)))]; a, b = sorted(rng.choice(members, 2, replace=False).tolist())
        if (a, b) not in existing:
            negative.add((a, b))
        attempts += 1
    pairs = np.asarray(positive + sorted(negative), dtype=np.int64).reshape(-1, 2).T
    labels = np.r_[np.ones(len(positive)), np.zeros(len(negative))].astype('float32')
    kept = [edge for index, edge in enumerate(edges) if index not in chosen_set]
    masked = replace(graph, edges=kept, block_lookup=None)
    return masked, pairs, labels, weights


@dataclass
class PreparedChunk:
    graph: object
    split: str
    original: object
    spectral: object
    values: np.ndarray
    mask: np.ndarray
    fixed_hidden: np.ndarray
    pairs: np.ndarray
    pair_labels: np.ndarray
    positive_weights: np.ndarray


def prepare_chunks(graphs, splits, scaler, *, seed=17, max_pairs=2048, progress=None,
                   required_splits=('train', 'validation', 'test')):
    prepared = []
    for i, graph in enumerate(graphs):
        if progress:
            progress(f'[AUTOENCODER] Prepare {i + 1}/{len(graphs)}: {graph.key}; split={splits[graph.key]}')
        original = analyze_graph(graph)
        masked, pairs, labels, weights = masked_topology(graph, original, seed + i, max_pairs)
        spectral = analyze_graph(masked)
        values, mask = transform(graph, scaler)
        fixed_hidden = feature_corruption(mask, np.random.default_rng(seed + 1000 + i))
        prepared.append(PreparedChunk(graph, splits[graph.key], original, spectral, values, mask,
                                      fixed_hidden, pairs, labels, weights))
    for split in required_splits:
        if not any(chunk.mask.any() for chunk in prepared if chunk.split == split):
            raise ValueError(f'No observed active features in {split} chunk set')
    return prepared
