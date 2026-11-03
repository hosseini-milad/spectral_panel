"""Normal-reference training and frozen cross-day evaluation, never attack claims."""
from datetime import date
from dataclasses import replace
from hashlib import sha256
import math
import uuid

import numpy as np
import networkx as nx
import torch
from bson import json_util
from mongoengine import get_db
from threadpoolctl import threadpool_limits

from ingestion.services.graph.components import load_node_documents
from ingestion.utils.document_paths import document_directory
from .autoencoder_inputs import load_raw_chunks, fit_scaler, prepare_chunks
from .autoencoder_training import train_shared, evaluate_chunk
from .spectral_reports import dump_json


def reference_splits(graphs):
    graphs = sorted(graphs, key=lambda g: g.chunk)
    if len(graphs) < 4:
        raise ValueError('Normal day needs at least 4 L1 chunk graphs: train, validation, calibration, test. Run hyper-general-action first.')
    train = min(len(graphs) - 3, max(1, int(.6 * len(graphs))))
    validation = min(len(graphs) - train - 2, max(1, int(.15 * len(graphs))))
    calibration = max(1, (len(graphs) - train - validation) // 2)
    return {g.key: ('train' if i < train else 'validation' if i < train + validation
                    else 'calibration' if i < train + validation + calibration else 'test')
            for i, g in enumerate(graphs)}


def calibration_threshold(values, alpha):
    values = np.asarray(values, dtype=float)
    if not 0 < alpha < 1 or values.ndim != 1 or not len(values) or not np.isfinite(values).all():
        raise ValueError('Calibration requires finite valid normal scores and 0 < alpha < 1.')
    rank = math.ceil((len(values) + 1) * (1 - alpha))
    if rank > len(values):
        raise ValueError(f'Only {len(values)} calibration nodes; need at least {math.ceil(1 / alpha) - 1} for alpha={alpha}.')
    return float(np.sort(values)[rank - 1])


def tail_probabilities(calibration, values):
    calibration = np.sort(np.asarray(calibration, dtype=float))
    return (1 + len(calibration) - np.searchsorted(calibration, values, side='left')) / (len(calibration) + 1)


def _field(doc, field):
    value = doc
    for part in field.split('.'):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def record_identity(doc, origin_field='artificial_day.original_id'):
    """ID aliases plus exact event-content fingerprint (not a near-duplicate test)."""
    ids = {str(doc['_id'])}
    for field in (origin_field, 'original_id'):
        value = _field(doc, field)
        if value is not None:
            ids.add(str(value))
    excluded = {'_id', 'source_day', 'source_file', 'original_id', 'artificial_day',
                'is_artificial_day', 'is_synthetic_normal', 'label', 'ingested_at',
                'created_at', 'updated_at', origin_field.split('.')[0]}
    payload = {key: value for key, value in doc.items() if key not in excluded}
    # Event timestamps and network endpoints remain in this hash. IDs/day/labels do not.
    digest = sha256(json_util.dumps(payload, sort_keys=True).encode()).hexdigest()
    return {'id:' + value for value in ids} | {'event:' + digest}


def _raw_signature(docs, ids):
    return sha256(json_util.dumps([docs[value] for value in ids], sort_keys=True).encode()).hexdigest()


def induced_independent_graph(graph, keep):
    """Remove reference copies and incident edges; recompute connected membership."""
    indices = np.flatnonzero(keep).tolist()
    remap = {old: new for new, old in enumerate(indices)}
    edges = [dict(edge, source=remap[edge['source']], target=remap[edge['target']])
             for edge in graph.edges if edge['source'] in remap and edge['target'] in remap]
    network = nx.Graph(); network.add_nodes_from(range(len(indices)))
    network.add_edges_from((e['source'], e['target']) for e in edges)
    original_component = {}
    for members, component_id in (graph.block_lookup or {}).items():
        for index in members:
            original_component[index] = (members, component_id)
    lookup = {}
    for part in nx.connected_components(network):
        original_members = frozenset(indices[i] for i in part)
        previous = original_component.get(min(original_members))
        digest = sha256('|'.join(sorted(str(graph.node_ids[indices[i]]) for i in part)).encode()).hexdigest()[:12]
        component_id = previous[1] if previous and original_members == previous[0] else f'{previous[1] if previous else graph.key}-induced-{digest}'
        lookup[frozenset(part)] = component_id
    return replace(graph, node_ids=[graph.node_ids[i] for i in indices], edges=edges,
                   features=graph.features[indices].copy(), feature_mask=graph.feature_mask[indices].copy(),
                   lineage=[graph.lineage[i] for i in indices], block_lookup=lookup,
                   source=dict(graph.source, normal_reference_filter='remove_reference_nodes_and_incident_edges',
                               original_graph_signature=graph.signature, removed_reference_nodes=int((~keep).sum())))


def audit_graph_identities(db, graphs, seen, group, *, reject, origin_field, progress=None):
    kept, rows, labels = [], [], {}
    for graph in graphs:
        if progress:
            progress(f'[NORMAL] Lineage audit: {graph.key}; nodes={len(graph.node_ids)}')
        ids = [str(row['original_id']) for row in graph.lineage]
        docs = load_node_documents(db, ids, 'security_data')
        if len(docs) != len(set(ids)):
            raise ValueError(f'{graph.key}: missing raw records for lineage audit')
        tokens, overlap, repeated, local = set(), 0, 0, set()
        keep = []
        graph_labels = []
        for value in ids:
            doc = docs[value]
            identity = record_identity(doc, origin_field)
            overlap += bool(identity & seen)
            repeated += bool(identity & local)
            keep.append(not bool(identity & seen or identity & local))
            local.update(identity); tokens.update(identity)
            label = doc.get('label')
            graph_labels.append(int(label) if label in (0, 1) else None)
        duplicate = bool(overlap or repeated)
        excluded = not any(keep)
        rows.append(dict(day=graph.day, graph_key=graph.key, group=group,
                         nodes=len(ids), overlap_nodes=overlap, within_chunk_duplicates=repeated,
                         removed_nodes=len(keep)-sum(keep), retained_nodes=sum(keep),
                         artificial_nodes=sum(bool(docs[value].get('is_artificial_day')) for value in ids),
                         excluded=excluded, raw_signature=_raw_signature(docs, ids),
                         policy='reject_reference_duplicates_or_induce_independent_evaluation_graph'))
        if duplicate and reject:
            raise ValueError(f'{graph.key}: repeated raw IDs/content across normal-reference splits or inside a chunk; fix source duplication before training.')
        if not excluded:
            kept.append(induced_independent_graph(graph, np.asarray(keep)) if duplicate else graph)
            labels[graph.key] = [label for label, include in zip(graph_labels, keep) if include]
        # Evaluation chunks are compared only against the full reference population.
        if reject:
            seen.update(tokens)
    return kept, rows, labels


def _signatures(graphs):
    return {g.key: g.signature for g in graphs}


def _verify_raw_sources(db, graphs, expected):
    for graph in graphs:
        ids = [str(row['original_id']) for row in graph.lineage]
        docs = load_node_documents(db, ids, 'security_data')
        if len(docs) != len(set(ids)) or _raw_signature(docs, ids) != expected[graph.key]:
            raise ValueError('Raw source records or lineage changed during evaluation/reporting')


def _valid_scores(model, prepared, split):
    values = [model['results'][c.graph.key]['node_error'][model['results'][c.graph.key]['node_error_mask']]
              for c in prepared if c.split == split]
    return np.concatenate(values) if values else np.asarray([])


def run_normal_behavior(normal_day, evaluate_days, *, epochs=60, hidden=64, latent=16,
                        layers=2, max_pairs=2048, alpha=.01, seed=17,
                        origin_field='artificial_day.original_id', reference_bundle=None, progress=None):
    for day in [normal_day, *evaluate_days]:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError('Use YYYY-MM-DD dates')
    if normal_day in evaluate_days or len(set(evaluate_days)) != len(evaluate_days):
        raise ValueError('Evaluation days must be distinct and different from the normal day.')
    if not evaluate_days:
        raise ValueError('Provide at least one independent evaluation day.')
    if not 0 < alpha < 1 or not 1 <= epochs <= 1000 or not 2 <= latent < 21 or not latent < hidden <= 256 or not 1 <= layers <= 6 or not 1 <= max_pairs <= 8192 or not 0 <= seed < 2**32:
        raise ValueError('Invalid alpha, epochs, dimensions, layers, relation-pair budget or seed.')
    if not origin_field or origin_field.startswith('$'):
        raise ValueError('Invalid origin ID field')
    db = get_db()
    run_id = uuid.uuid4().hex
    folder = document_directory('autoencoder', layer=1, day=normal_day) / 'normal_behavior' / 'runs' / run_id
    folder.mkdir(parents=True, exist_ok=False)
    status = dict(run_id=run_id, status='building', normal_day=normal_day)
    dump_json(folder / 'run_status.json', status)
    try:
        if progress:
            progress(f'[NORMAL] Loading reference L1 graphs and raw features: {normal_day}')
        reference = sorted(load_raw_chunks(normal_day), key=lambda g: g.chunk)
        signatures = {normal_day: _signatures(reference)}
        seen = set()
        reference, audit, reference_labels = audit_graph_identities(
            db, reference, seen, 'normal_reference', reject=True, origin_field=origin_field, progress=progress)
        if any(label == 1 for values in reference_labels.values() for label in values):
            raise ValueError('Normal-reference candidate records include label=1, contrary to the declared normal population; review day 20 before training.')
        splits = reference_splits(reference)
        evaluation, all_labels = {}, dict(reference_labels)
        source_graphs = list(reference)
        for day in evaluate_days:
            if progress:
                progress(f'[NORMAL] Loading independent evaluation graphs: {day}')
            graphs = sorted(load_raw_chunks(day), key=lambda g: g.chunk)
            source_graphs.extend(graphs)
            signatures[day] = _signatures(graphs)
            kept, rows, labels = audit_graph_identities(db, graphs, seen, 'external_test', reject=False, origin_field=origin_field, progress=progress)
            audit.extend(rows); all_labels.update(labels); evaluation[day] = kept
            if progress:
                progress(f'[NORMAL] {day}: independent chunks={len(kept)}/{len(graphs)}; reference-copy nodes removed={sum(r["removed_nodes"] for r in rows)}')
        from .message_passing_reports import write_csv
        write_csv(folder / 'lineage_audit.csv', audit)
        if progress and sum(row['overlap_nodes'] for row in audit if row['group'] == 'external_test') == 0:
            progress('[NORMAL] WARNING: no exact ID/content matches found. This does not prove independence if copied events were modified or original provenance was discarded.')
        if any(not graphs for graphs in evaluation.values()):
            raise ValueError('An evaluation day has no independent nodes after lineage exclusion; see lineage_audit.csv. Supply an independent day.')
        lineage_signatures = {row['graph_key']: row['raw_signature'] for row in audit}

        if reference_bundle:
            from .normal_behavior_reports import load_reference_bundle
            models, scaler, parameters, calibration, thresholds, saved = load_reference_bundle(reference_bundle)
            if saved['normal_day'] != normal_day or saved['source_signatures'][normal_day] != signatures[normal_day]:
                raise ValueError('Frozen reference day/signatures differ from the current source.')
            if saved['origin_id_field'] != origin_field or saved['chunk_splits'] != splits:
                raise ValueError('Frozen lineage field or normal-reference split differs; use the saved reference settings.')
            if any(saved['lineage_signatures'][g.key] != lineage_signatures[g.key] for g in reference):
                raise ValueError('Frozen normal-reference raw records or lineage differ from the current source.')
            seed, max_pairs, alpha = parameters['seed'], parameters['max_pairs'], saved['alpha']
            prepared = prepare_chunks(reference, splits, scaler, seed=seed, max_pairs=max_pairs,
                                      required_splits=('train', 'validation', 'calibration', 'test'), progress=progress)
            for model in models.values():
                model['results'] = {c.graph.key: evaluate_chunk(model['model'], c, scaler['baseline']) for c in prepared}
        else:
            scaler, _ = fit_scaler(reference, splits)
            parameters = dict(epochs=epochs, hidden_dim=hidden, latent_dim=latent, layers=layers,
                              max_pairs=max_pairs, seed=seed, feature_mask_rate=.2,
                              structure_weight=.1, weight_weight=.05)
            prepared = prepare_chunks(reference, splits, scaler, seed=seed, max_pairs=max_pairs,
                                      required_splits=('train', 'validation', 'calibration', 'test'), progress=progress)
            models = train_shared(prepared, scaler, epochs=epochs, hidden=hidden, latent=latent,
                                  layers=layers, seed=seed, progress=progress)
            calibration = {variant: _valid_scores(model, prepared, 'calibration') for variant, model in models.items()}
            thresholds = {variant: calibration_threshold(values, alpha) for variant, values in calibration.items()}
        if progress:
            progress(f'[NORMAL] Frozen reference thresholds: {thresholds}; external days will not update weights/scaler/thresholds')
        # No optimizer, scaler fitting, threshold fitting or checkpoint selection on external days.
        frozen = {variant: {key: value.detach().clone() for key, value in model['model'].state_dict().items()}
                  for variant, model in models.items()}
        for day, graphs in evaluation.items():
            external = prepare_chunks(graphs, {g.key: 'external_test' for g in graphs}, scaler,
                                      seed=seed, max_pairs=max_pairs, required_splits=('external_test',), progress=progress)
            prepared.extend(external)
            for model in models.values():
                model['results'].update({c.graph.key: evaluate_chunk(model['model'], c, scaler['baseline']) for c in external})
        for variant, model in models.items():
            if any(not torch.equal(value, frozen[variant][key]) for key, value in model['model'].state_dict().items()):
                raise ValueError('Model weights changed during frozen evaluation')
        for day, signature in signatures.items():
            if _signatures(load_raw_chunks(day)) != signature:
                raise ValueError('Source changed during normal-reference evaluation')
        _verify_raw_sources(db, source_graphs, lineage_signatures)
        from .normal_behavior_reports import write_normal_reports
        manifest = dict(version='normal_behavior_v1', run_id=run_id, normal_day=normal_day,
                        evaluate_days=evaluate_days, alpha=alpha, thresholds=thresholds,
                        parameters=parameters, source_signatures=signatures,
                        lineage_signatures=lineage_signatures,
                        chunk_splits=splits, origin_id_field=origin_field,
                        fixed_model_verified=True, reference_basis='user_declared_label_normal_mixed_day_artificial_reference',
                        reference_bundle=str(reference_bundle) if reference_bundle else None,
                        limits=['Candidate-node reconstruction deviations are not attack probabilities.',
                                'Chunks are processing partitions, not fixed time windows; coverage is only available chunks.',
                                'Calibration and test chunks are separate. Candidate dependence prevents a distribution-free false-alarm guarantee.',
                                'External-day alert rates are not false-positive rates unless the evaluated population is known normal.',
                                'Reference is an artificial mixture of normal-labelled source days, not an independent temporal day.',
                                'Lineage checks use raw ID aliases and exact event-content hashes; modified copies without provenance may escape detection.',
                                'Evaluation removes overlapping nodes and incident edges; spectra/components are recomputed on the induced graph. Preprocessing can still depend on the original candidate population.',
                                'Upstream sampling/graph construction may use labels or risk policies; no end-to-end label-free claim.',
                                'Inactive/unseen reference features are excluded from model targets and audited separately.',
                                'Neighborhood-reconstruction training objective has not been added; this is the preserved model baseline.'])
        with threadpool_limits(limits=1):
            if progress:
                progress(f'[NORMAL] Writing reports, score arrays and PNG/SVG schematics: {folder}')
            paths = write_normal_reports(folder, manifest, prepared, models, scaler, calibration, all_labels, audit)
        for day, signature in signatures.items():
            if _signatures(load_raw_chunks(day)) != signature:
                raise ValueError('Source changed during reporting; outputs are not complete')
        _verify_raw_sources(db, source_graphs, lineage_signatures)
        manifest.update(status='complete', paths=paths)
        dump_json(folder / 'manifest.json', manifest)
        dump_json(folder / 'run_status.json', dict(status, status='complete'))
        return dict(run_id=run_id, paths=paths)
    except Exception as exc:
        dump_json(folder / 'run_status.json', dict(status, status='failed', error=str(exc)))
        if progress:
            progress(f'[NORMAL] FAILED; diagnostic directory: {folder}')
        raise


def run_normal_behavior_cpu(*args, **kwargs):
    previous = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        with threadpool_limits(limits=1):
            return run_normal_behavior(*args, **kwargs)
    finally:
        torch.set_num_threads(previous)
