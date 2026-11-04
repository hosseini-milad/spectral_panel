"""Exact-membership pooled behavior on existing components/Meta-components.

No new encoder, hierarchy reconstruction, signal fusion or attack decision.
"""
from pathlib import Path
import json
import math
import uuid
from collections import defaultdict

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from mongoengine import get_db
from pymongo import UpdateOne

from ingestion.utils.document_paths import document_directory
from hierarchy.services.component_hierarchy import source_fingerprints
from .autoencoder_inputs import load_raw_chunks
from .behavior_signal_inputs import CHANNELS, validate_observation
from .normal_behavior import _signatures, calibration_threshold, tail_probabilities
from .normal_behavior_reports import _sha
from .spectral_inputs import fingerprint, hierarchy_input
from .spectral_reports import dump_json, save
from .message_passing_reports import write_csv

VERSION = 'hierarchical_behavior_v1'
FAMILIES = ('representation', 'member_behavior', 'structure')


def size_stratum(size, child_count, kind):
    size_bin = 'one' if size == 1 else '2_to_10' if size <= 10 else '11_plus'
    return size_bin + (':single_child' if child_count == 1 else ':multiple_children') if kind == 'meta_component' else size_bin


def pooled_moments(means, variances, counts):
    means = np.asarray(means); variances = np.asarray(variances); counts = np.asarray(counts)
    if (means.shape != variances.shape or means.ndim != 2 or len(counts) != len(means)
            or np.any(counts <= 0) or not np.isfinite(means).all() or not np.isfinite(variances).all()):
        raise ValueError('Invalid pooling inputs')
    mean = np.average(means, axis=0, weights=counts)
    variance = np.average(variances + (means-mean)**2, axis=0, weights=counts)
    return mean, np.maximum(variance, 0), int(counts.sum())


def load_hierarchy(db, day):
    key = f'hierarchy-components-day-{day}-layer-2'
    pointer = db.component_hierarchy_graphs.find_one({'_id': key, 'status': 'complete'})
    if not pointer:
        raise ValueError(f'{day}: missing hierarchy; run build_hierarchy_graph --day {day}')
    run = db.component_hierarchy_runs.find_one({'_id': pointer['active_run_id'], 'source_day': day, 'status': 'complete'})
    if not run:
        raise ValueError(f'{day}: hierarchy run incomplete')
    graph = hierarchy_input(db, run)
    if len(set(graph.node_ids)) != len(graph.node_ids):
        raise ValueError('Duplicate component identity in hierarchy')
    nodes = list(db.component_hierarchy_nodes.find({'run_id': run['_id']}).sort('node_index', 1))
    metas = sorted(db.meta_components.find({'run_id': run['_id']}), key=lambda m: m['meta_component_id'])
    edges = sorted(db.component_hierarchy_edges.find({'run_id': run['_id']}), key=lambda e: (e['source'], e['target']))
    for source in run['sources']:
        metadata = list(db.graph_metadata.find({'source_file': source['source_file']}))
        if len(metadata) != 1:
            raise ValueError('Missing/ambiguous hierarchy source graph')
        components = list(db.graph_components.find({'source_file': source['source_file'], 'layer': 1}))
        actual = source_fingerprints(metadata[0], components)
        if any(source.get(k) != v for k, v in actual.items()):
            raise ValueError('Hierarchy is stale relative to component sources; rebuild matching hierarchy')
    if len({m['meta_component_id'] for m in metas}) != len(metas):
        raise ValueError('Duplicate Meta-component identity')
    network = nx.Graph(); network.add_nodes_from(range(len(nodes)))
    for edge in edges:
        if edge['source'] == edge['target'] or not (0 <= edge['source'] < len(nodes) and 0 <= edge['target'] < len(nodes)):
            raise ValueError('Invalid hierarchy edge')
        network.add_edge(edge['source'], edge['target'])
    for meta in metas:
        if (len(set(meta['node_indices'])) != len(meta['node_indices'])
                or len(set(meta['child_component_ids'])) != len(meta['child_component_ids'])):
            raise ValueError('Duplicate child membership inside Meta-component')
        sub = network.subgraph(meta['node_indices'])
        if (meta['component_count'] != len(meta['node_indices'])
                or meta['member_node_count'] != sum(nodes[i]['node_count'] for i in meta['node_indices'])
                or meta['internal_edges'] != sub.number_of_edges()
                or not np.isclose(meta['density'], nx.density(sub))):
            raise ValueError('Meta-component structure or mass differs from membership')
    partition = [frozenset(m['node_indices']) for m in metas]
    if (len(partition) != len(set(partition)) or any(not p for p in partition)
            or sum(map(len, partition)) != len(nodes)
            or set(partition) != {frozenset(c) for c in nx.connected_components(network)}):
        raise ValueError('Invalid Meta-component partition')
    digest = fingerprint(dict(run=run, nodes=nodes, metas=metas, edges=edges))
    return dict(day=day, run_id=run['_id'], nodes=nodes, metas=metas, graph=graph,
                network=network, digest=digest)


def describe(members, *, kind, size, children, structure):
    z = np.asarray([r['z'] for r in members], dtype=float)
    if z.ndim != 2 or not np.isfinite(z).all():
        raise ValueError('Invalid group latent vectors')
    mean, variance = z.mean(0), z.var(0)
    representation = np.r_[mean, np.sqrt(variance)]
    representation_mask = np.r_[np.ones(z.shape[1], dtype=bool), np.full(z.shape[1], size > 1)]
    behavior, observed, detail = [], [], {}
    for channel in CHANNELS:
        values = np.asarray([r['residuals'][channel] for r in members if r['residuals'][channel] is not None])
        count = len(values); valid = count > 0
        behavior.extend([float(values.mean()) if valid else 0., float(np.quantile(values, .9)) if valid else 0., count/size])
        observed.extend([valid, valid, True])
        exceed = sum(r['exceeds'][channel] is True for r in members)
        calibrated_count = sum(r['exceeds'][channel] is not None for r in members)
        detail[channel] = dict(observed_members=count, calibrated_members=calibrated_count,
            raw_mean=float(values.mean()) if valid else None, raw_p90=float(np.quantile(values, .9)) if valid else None,
            tail_exceeding_members=exceed, tail_exceeding_fraction=exceed/calibrated_count if calibrated_count else None)
    # Tail exceedances are explanatory only: never fit upper baselines on scores
    # that were themselves calibrated using the same normal calibration split.
    structure_values = [np.log1p(size), np.log1p(children), float(np.mean([r['isolated'] for r in members]))]
    structure_mask = [True, True, True]
    for name in ('internal_edges', 'density', 'bridge_count'):
        value = structure.get(name)
        valid = value is not None and np.isfinite(value) and value >= 0
        structure_values.append(float(value) if valid and name == 'density' else float(np.log1p(value)) if valid else 0.)
        structure_mask.append(valid)
    return dict(representation=(representation, representation_mask),
        member_behavior=(np.asarray(behavior), np.asarray(observed)),
        structure=(np.asarray(structure_values), np.asarray(structure_mask))), mean, variance, detail


def build_groups(snapshot, observations, normal_day):
    day = snapshot['day']; groups = []; by_component = {}; memberships = []; used = set()
    if len({n['component_id'] for n in snapshot['nodes']}) != len(snapshot['nodes']):
        raise ValueError('Duplicate component identity')
    for node in snapshot['nodes']:
        ids = list(map(str, node['member_node_ids'])); originals = list(map(str, node['member_original_ids']))
        if len(set(ids)) != len(ids) or len(ids) != node['node_count'] or used.intersection(ids):
            raise ValueError('Duplicate or inconsistent component membership')
        if any(value not in observations for value in ids):
            raise ValueError('Hierarchy contains candidates missing from signal export; filtered/partial membership is not silently accepted')
        members = [observations[value] for value in ids]
        if ([m['raw_id'] for m in members] != originals or any(m['component_id'] != node['component_id']
                or m['graph_key'] != node['source_file'] for m in members)):
            raise ValueError('Hierarchy component and signal candidate/raw membership differ')
        used.update(ids)
        group = _group(day, 'component', node['component_id'], members, 1, node.get('structure') or {}, normal_day)
        group['source_graph_key'] = node['source_file']; groups.append(group); by_component[node['component_id']] = group
        memberships.extend(dict(parent_type='component', parent_id=node['component_id'], child_type='candidate_flow',
                                child_id=m['observation_id'], source_node_id=value) for value, m in zip(ids, members))
    if used != set(observations):
        raise ValueError('Hierarchy does not cover every signal candidate exactly')
    for meta in snapshot['metas']:
        children = [by_component[cid] for cid in meta['child_component_ids']]
        members = [m for child in children for m in child['_members']]
        if len(children) != meta['component_count'] or len(members) != meta['member_node_count']:
            raise ValueError('Meta-component mass/count mismatch')
        group = _group(day, 'meta_component', meta['meta_component_id'], members, len(children), meta, normal_day)
        mean, variance, mass = pooled_moments([c['_mean'] for c in children], [c['_variance'] for c in children], [c['candidate_count'] for c in children])
        if mass != group['candidate_count'] or not np.allclose(mean, group['_mean'], atol=1e-6) or not np.allclose(variance, group['_variance'], atol=1e-6):
            raise ValueError('Pooling mass/moments not conserved')
        group['pooling_verified'] = True; groups.append(group)
        memberships.extend(dict(parent_type='meta_component', parent_id=meta['meta_component_id'], child_type='component',
                                child_id=child['entity_id'], source_node_id=None) for child in children)
    return groups, memberships


def _group(day, kind, entity_id, members, children, structure, normal_day):
    roles = sorted({r['split'] for r in members})
    if day == normal_day:
        split = roles[0] if len(roles) == 1 else 'mixed_reference_splits'
        if any(r not in ('train', 'validation', 'calibration', 'test') for r in roles):
            raise ValueError('Invalid normal reference split')
    else:
        if roles != ['additional_day']:
            raise ValueError('External hierarchy includes reference-role candidates')
        split = 'additional_day'
    descriptors, mean, variance, detail = describe(members, kind=kind, size=len(members), children=children, structure=structure)
    return dict(day=day, entity_type=kind, entity_id=entity_id, split=split, member_splits=roles,
        candidate_count=len(members), child_component_count=children, stratum=size_stratum(len(members), children, kind),
        descriptor=descriptors, member_signals=detail, pooling_verified=kind == 'component',
        _members=members, _mean=mean, _variance=variance)


def reference_models(groups, alpha, min_train=5):
    if not 0 < alpha < 1 or min_train < 2:
        raise ValueError('Require 0<alpha<1 and min_train>=2')
    output = {}
    for kind, stratum in sorted({(g['entity_type'], g['stratum']) for g in groups}):
        for family in FAMILIES:
            train = [g for g in groups if (g['entity_type'], g['stratum'], g['split']) == (kind, stratum, 'train')]
            cal = [g for g in groups if (g['entity_type'], g['stratum'], g['split']) == (kind, stratum, 'calibration')]
            key = '|'.join([kind, stratum, family])
            state = dict(status='uncalibrated', reason='insufficient_matching_normal_train_groups', train_groups=len(train),
                         calibration_groups=0, alpha=alpha, threshold=None)
            if len(train) >= min_train:
                values = np.stack([g['descriptor'][family][0] for g in train])
                mask = np.stack([g['descriptor'][family][1] for g in train])
                active = mask.sum(0) >= min_train
                center = np.zeros(values.shape[1]); scale = np.ones(values.shape[1])
                for col in np.flatnonzero(active):
                    x = values[mask[:, col], col]; center[col] = np.median(x)
                    scale[col] = np.quantile(x, .75) - np.quantile(x, .25)
                    if scale[col] < 1e-3:
                        scale[col] = 1.
                state.update(center=center.tolist(), scale=scale.tolist(), active=active.tolist())
                scores = [distance(g, family, state) for g in cal]
                scores = np.sort([x for x in scores if x is not None]); state['values'] = scores.tolist()
                state['calibration_groups'] = len(scores)
                state['reason'] = 'insufficient_matching_normal_calibration_groups'
                if len(scores) >= math.ceil(1/alpha)-1 and len(scores):
                    state.update(status='calibrated', reason=None, threshold=calibration_threshold(scores, alpha))
            output[key] = state
    return output


def distance(group, family, state):
    if 'active' not in state:
        return None
    values, mask = group['descriptor'][family]; chosen = mask & np.asarray(state['active'], dtype=bool)
    if not chosen.any():
        return None
    z = (values[chosen] - np.asarray(state['center'])[chosen]) / np.asarray(state['scale'])[chosen]
    result = float(np.mean(z**2))
    if not np.isfinite(result):
        raise ValueError('Nonfinite group reference distance')
    return result


def score_group(group, states, reference_id):
    output = {}
    for family in FAMILIES:
        key = '|'.join([group['entity_type'], group['stratum'], family]); state = states[key]
        excluded = group['split'] == 'mixed_reference_splits'
        value = distance(group, family, state)
        valid = not excluded and value is not None and state['status'] == 'calibrated'
        contributions = []
        if value is not None:
            vector, mask = group['descriptor'][family]
            columns = np.flatnonzero(mask & np.asarray(state['active'], dtype=bool))
            differences = ((vector[columns] - np.asarray(state['center'])[columns]) / np.asarray(state['scale'])[columns])**2
            for offset in np.argsort(-differences)[:3]:
                contributions.append(dict(descriptor_index=int(columns[offset]), squared_standardized_difference=float(differences[offset])))
        output[family] = dict(status='valid' if valid else 'excluded' if excluded else 'uncalibrated',
            reason='mixed_normal_train_calibration_test_membership' if excluded else None if valid else state['reason'] or 'no_matching_observed_descriptor_dimensions',
            reference_id=reference_id, reference_group=key, distance=value,
            normal_train_groups=state['train_groups'], normal_calibration_groups=state['calibration_groups'],
            top_descriptor_differences=contributions,
            threshold=state['threshold'] if valid else None,
            tail_probability=float(tail_probabilities(state['values'], [value])[0]) if valid else None,
            exceeds_tail=bool(value > state['threshold']) if valid else None)
    return output


def find_signal_bundle(run_id, normal_day='2026-06-20'):
    from datetime import date
    if len(run_id)!=64 or any(c not in '0123456789abcdef' for c in run_id):
        raise ValueError('Signal run ID must be a 64-character lowercase hash')
    if date.fromisoformat(normal_day).isoformat()!=normal_day:
        raise ValueError('Use YYYY-MM-DD for normal day')
    root=document_directory('autoencoder',layer=1,day=normal_day)/'signal_inputs'/'runs'
    found=[]
    for path in sorted(root.glob('*/manifest.json')):
        status=path.parent/'run_status.json'
        try:
            item=json.loads(path.read_text()); state=json.loads(status.read_text())
        except (OSError,ValueError):
            continue
        if item.get('_id')==run_id and item.get('status')=='complete' and state.get('status')=='complete':
            found.append((path.parent,item))
    if not found:
        raise ValueError('No completed local signal export matches this run ID; use --signal-bundle with its exact folder')
    if len({item['payload_sha256'] for _,item in found})!=1:
        raise ValueError('Conflicting signal payloads for the same run ID')
    return found[0][0]


def read_signal_bundle(folder):
    folder = Path(folder); manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    if (manifest.get('schema_version') != 'behavior_signal_inputs_v1' or manifest.get('status') != 'complete'
            or json.loads((folder/'run_status.json').read_text())['status'] != 'complete'):
        raise ValueError('Require a completed behavior signal input bundle')
    if fingerprint(manifest['identity']) != manifest['_id'] or _sha(folder/'observations.jsonl') != manifest['payload_sha256']:
        raise ValueError('Parent signal identity/payload checksum mismatch')
    by_day = defaultdict(dict); count = 0; ids = set(); normal_days = set()
    with (folder/'observations.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line); validate_observation(row)
            if fingerprint({k: v for k, v in row.items() if k != 'content_sha256'}) != row['content_sha256']:
                raise ValueError('Signal observation checksum mismatch')
            if (row['run_id'] != manifest['_id'] or row['model_id'] != manifest['identity']['checkpoint']
                    or row['calibration_id'] != manifest['calibration_id'] or row['_id'] in ids):
                raise ValueError('Inconsistent/duplicate signal observation identity')
            entity = row['entity']; day = entity['source_day']; node = entity['node_id']
            if node in by_day[day] or not entity['component_id']:
                raise ValueError('Duplicate candidate or missing component identity')
            if row['split'] != 'additional_day':
                normal_days.add(day)
            if row['source_signature'] != manifest['identity']['source_signatures'][day][entity['graph_key']]:
                raise ValueError('Signal graph provenance mismatch')
            by_day[day][node] = dict(z=row['representation']['vector'], split=row['split'],
                observation_id=row['_id'], raw_id=row['raw_source']['record_id'], component_id=entity['component_id'],
                graph_key=entity['graph_key'], isolated=row['isolated'],
                residuals={k: row['signals'][k]['residual'] for k in CHANNELS},
                exceeds={k: row['signals'][k]['exceeds_tail'] for k in CHANNELS})
            ids.add(row['_id']); count += 1
    if count != manifest['observation_count'] or len(normal_days) != 1:
        raise ValueError('Parent count or normal reference day is invalid')
    return manifest, by_day, normal_days.pop()


def _write_jsonl(path, rows):
    count = 0
    with Path(path).open('w', encoding='utf-8') as stream:
        for row in rows:
            row['content_sha256'] = fingerprint(row)
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False)+'\n'); count += 1
    return count


def persist_hierarchy(db, run, files):
    runs = db.behavior_hierarchy_runs
    existing = runs.find_one({'_id': run['_id']})
    if existing and existing.get('files') != run['files']:
        raise ValueError('Existing hierarchical run payload differs')
    runs.update_one({'_id': run['_id']}, {'$setOnInsert': run}, upsert=True)
    runs.update_one({'_id': run['_id']}, {'$set': {'status': 'building'}})
    try:
        for name, path in files.items():
            expected_file = run['files'][name]
            if _sha(path) != expected_file['sha256']:
                raise ValueError('Hierarchy export checksum changed')
            collection = db[name]; collection.create_index([('run_id', 1)])
            expected = {}; batch = []
            with Path(path).open(encoding='utf-8') as stream:
                for line in stream:
                    row = json.loads(line)
                    if row['run_id'] != run['_id'] or row['_id'] in expected:
                        raise ValueError('Wrong run or duplicate hierarchical record')
                    expected[row['_id']] = row['content_sha256']
                    batch.append(UpdateOne({'_id': row['_id']}, {'$setOnInsert': row}, upsert=True))
                    if len(batch) == 500:
                        collection.bulk_write(batch, ordered=False); batch = []
                if batch:
                    collection.bulk_write(batch, ordered=False)
            if collection.count_documents({'run_id': run['_id']}) != expected_file['count']:
                raise ValueError('Persisted hierarchy record count differs')
            for row in collection.find({'run_id': run['_id']}):
                if expected.get(row['_id']) != row.get('content_sha256') or fingerprint({k:v for k,v in row.items() if k!='content_sha256'}) != row['content_sha256']:
                    raise ValueError('Existing hierarchical evidence content conflict')
        runs.update_one({'_id': run['_id']}, {'$set': {'status':'complete'}})
    except Exception as exc:
        runs.update_one({'_id': run['_id']}, {'$set': {'status':'failed', 'error':str(exc)}})
        raise


def _figures(folder, coverage, groups):
    fig, axes = plt.subplots(1, 2, figsize=(13, 4))
    for ax, kind in zip(axes, ('component', 'meta_component')):
        rows = [r for r in coverage if r['entity_type']==kind and r['split'] in ('test', 'additional_day')]
        names = [f"{r['day']}\n{r['family']}" for r in rows]
        values = [r['tail_fraction'] if r['tail_fraction'] is not None else 0 for r in rows]
        ax.bar(range(len(rows)), values)
        ax.set_xticks(range(len(rows)), names, rotation=45, ha='right', fontsize=8)
        ax.set(title=kind, ylabel='Tail fraction among calibrated groups')
        for i, r in enumerate(rows):
            if not r['valid']:
                ax.text(i, 0, 'N/A', rotation=90, ha='center', fontsize=8)
    fig.suptitle('Group deviations from normal reference; not attack detection accuracy')
    fig.tight_layout(); save(fig, folder/'hierarchy_deviations')
    fig, ax = plt.subplots(figsize=(14, 5)); ax.axis('off')
    boxes = [(0.12, .67, 'Pinned node evidence\nFull latent + raw residuals'),
             (.43, .67, 'Exact L1 components\nMean/std + member behavior'),
             (.77, .67, 'Existing L2 Meta-components\nMass-preserving pooling'),
             (.43, .28, 'Normal train: robust reference\nNormal calibration: tail cutoffs'),
             (.77, .28, 'Versioned group evidence\nNo final fusion or alerts')]
    for x,y,text in boxes:
        ax.text(x,y,text,ha='center',va='center',transform=ax.transAxes,fontsize=10,
                bbox=dict(boxstyle='round,pad=.7',fc='#e5eff6',ec='#40596b'))
    for a,b in [((.25,.67),(.30,.67)),((.57,.67),(.62,.67)),((.43,.54),(.43,.40)),
                ((.77,.54),(.77,.40)),((.58,.28),(.62,.28))]:
        ax.annotate('',xy=b,xytext=a,xycoords='axes fraction',arrowprops=dict(arrowstyle='->'))
    ax.text(.5,.03,'Size strata kept separate; mixed-reference-split Meta-components excluded from fitting/calibration.\nNo new upper encoder or new Layer-3 similarity graph is claimed.',ha='center',transform=ax.transAxes,fontsize=10)
    save(fig,folder/'hierarchy_behavior_schematic')


def run_hierarchy_behavior(signal_bundle, *, alpha=.01, min_train=5, write=False, progress=None):
    if not 0 < alpha < 1 or min_train < 2:
        raise ValueError('Require 0<alpha<1 and min_train>=2')
    source = Path(signal_bundle).resolve()
    parent, observations, normal_day = read_signal_bundle(source)
    parent_manifest_sha = _sha(source/'manifest.json')
    folder = document_directory('autoencoder',layer=2,day=normal_day)/'hierarchical_behavior'/'runs'/uuid.uuid4().hex
    folder.mkdir(parents=True); dump_json(folder/'run_status.json',dict(status='building'))
    try:
        db = get_db(); snapshots = {}; groups = []; memberships = []
        for day in sorted(observations):
            if progress:
                progress(f'[HIERARCHY BEHAVIOR] Verify source and membership {day}')
            raw = load_raw_chunks(day)
            if _signatures(raw) != parent['identity']['source_signatures'][day]:
                raise ValueError('Current raw graph differs from pinned node signals')
            from .normal_behavior import _verify_raw_sources
            _verify_raw_sources(db,raw,parent['identity']['lineage_signatures'])
            snapshot = load_hierarchy(db,day); snapshots[day]=snapshot
            day_groups, day_memberships = build_groups(snapshot,observations[day],normal_day)
            groups.extend(day_groups)
            memberships.extend(dict(day=day, hierarchy_run_id=snapshot['run_id'], **r) for r in day_memberships)
        identity = dict(version=VERSION,parent_run_id=parent['_id'],parent_payload_sha256=parent['payload_sha256'],
            hierarchy={day:dict(run_id=s['run_id'],digest=s['digest']) for day,s in snapshots.items()},
            alpha=alpha,min_train=min_train,reference_policy='train_median_iqr_masked_distance_size_strata_v1')
        run_id=fingerprint(identity); reference_id=fingerprint(dict(identity=identity,role='group_reference'))
        states=reference_models(groups,alpha,min_train)
        records=[]; descriptor_rows=[]; coverage={}; group_ids={}
        for g in groups:
            entity_id=fingerprint(dict(run_id=run_id,day=g['day'],kind=g['entity_type'],id=g['entity_id']))
            group_ids[(g['day'],g['entity_type'],g['entity_id'])]=entity_id
            signals=score_group(g,states,reference_id)
            record=dict(_id=entity_id,run_id=run_id,schema_version=VERSION,parent_signal_run_id=parent['_id'],
                entity=dict(type=g['entity_type'],id=g['entity_id'],day=g['day'],hierarchy_run_id=snapshots[g['day']]['run_id'],
                    source_structural_layer=1 if g['entity_type']=='component' else 2),
                split=g['split'],member_splits=g['member_splits'],candidate_count=g['candidate_count'],
                child_component_count=g['child_component_count'],comparison_stratum=g['stratum'],
                representation=dict(mean=g['_mean'].tolist(),std=np.sqrt(g['_variance']).tolist(),
                    pooling='candidate_weighted_population_moments_not_trained_upper_encoder',verified=g['pooling_verified']),
                member_signals=g['member_signals'],signals=signals,
                temporal_context=dict(status='not_computed'),fusion=dict(status='not_computed',score=None,alert=None),
                quality=dict(operational_ready=False,reference_split_mixed=g['split']=='mixed_reference_splits',
                    upstream_graph_construction_not_proven_split_independent=True,canonical_event_identity='not_verified'))
            records.append(record)
            for family,(values,mask) in g['descriptor'].items():
                descriptor_rows.append(dict(group_observation_id=entity_id,family=family,values=values.tolist(),observed=mask.tolist()))
            for family,signal in signals.items():
                key=(g['day'],g['split'],g['entity_type'],family)
                counts=coverage.setdefault(key,dict(groups=0,valid=0,uncalibrated=0,excluded=0,tail_exceedances=0))
                counts['groups']+=1; counts[signal['status']]+=1; counts['tail_exceedances']+=signal['exceeds_tail'] is True
        def member_records():
            for m in memberships:
                parent_id=group_ids[(m['day'],m['parent_type'],m['parent_id'])]
                child_id=m['child_id'] if m['child_type']=='candidate_flow' else group_ids[(m['day'],'component',m['child_id'])]
                yield dict(_id=fingerprint(dict(parent=parent_id,child=child_id)),run_id=run_id,
                    parent_group_observation_id=parent_id,child_observation_id=child_id,
                    child_type=m['child_type'],source_node_id=m['source_node_id'],hierarchy_run_id=m['hierarchy_run_id'])
        files={}
        for name,filename,rows in [('behavior_group_observations','group_observations.jsonl',records),
                                  ('behavior_hierarchy_memberships','memberships.jsonl',member_records())]:
            path=folder/filename; count=_write_jsonl(path,rows); files[name]=dict(count=count,sha256=_sha(path),path=filename)
        dump_json(folder/'group_descriptors.json',descriptor_rows)
        dump_json(folder/'reference_models.json',dict(reference_id=reference_id,models=states))
        report=[dict(day=k[0],split=k[1],entity_type=k[2],family=k[3],**v,
            tail_fraction=v['tail_exceedances']/v['valid'] if v['valid'] else None) for k,v in sorted(coverage.items())]
        write_csv(folder/'group_coverage.csv',report)
        statistics=[dict(day=g['day'],entity_type=g['entity_type'],entity_id=g['entity_id'],split=g['split'],
            candidate_count=g['candidate_count'],child_component_count=g['child_component_count'],stratum=g['stratum']) for g in groups]
        write_csv(folder/'group_statistics.csv',statistics)
        samples=[]
        for kind in ('component','meta_component'):
            for role in ('train','calibration','test','mixed_reference_splits','additional_day'):
                samples.extend([r for r in records if r['entity']['type']==kind and r['split']==role][:2])
        dump_json(folder/'group_samples.json',samples)
        reference_coverage=[]
        for key,state in states.items():
            kind,stratum,family=key.split('|')
            reference_coverage.append(dict(entity_type=kind,stratum=stratum,family=family,status=state['status'],
                reason=state['reason'],train_groups=state['train_groups'],calibration_groups=state['calibration_groups'],
                minimum_calibration_groups=math.ceil(1/alpha)-1,threshold=state['threshold']))
        write_csv(folder/'reference_coverage.csv',reference_coverage)
        scores=[dict(day=r['entity']['day'],entity_type=r['entity']['type'],entity_id=r['entity']['id'],split=r['split'],
            candidate_count=r['candidate_count'],stratum=r['comparison_stratum'],family=family,status=signal['status'],
            distance=signal['distance'],threshold=signal['threshold'],tail_probability=signal['tail_probability'],
            exceeds_tail=signal['exceeds_tail']) for r in records for family,signal in r['signals'].items()]
        write_csv(folder/'group_scores.csv',scores)
        contract=dict(version=VERSION,reference_id=reference_id,normal_day=normal_day,
            methods='pooled_existing_node_latents_raw_member_residuals_and_observed_structure; no_new_encoder',
            representation_features='latent_mean_then_latent_population_std',
            member_behavior_features=[f'{c}_{s}' for c in CHANNELS for s in ('raw_mean','raw_p90','valid_fraction')],
            structure_features=['log1p_candidates','log1p_child_components','isolated_fraction','log1p_internal_edges','density','log1p_bridges'],
            reference='per_entity_type_and_size_stratum_train_only_median_iqr; near_constant_scale_set_to_one',
            calibration='normal_calibration_groups_only; mixed_reference_split_groups_excluded',
            score='mean_squared_train_robust_standardized_distance_over_observed_active_dimensions_not_attack_probability',
            inherited_tail_exceedances='explanation_only_not_upper_reference_inputs',
            upstream_limit='full_day_hierarchy_construction_can_depend_on_all_reference_splits; no_end_to_end_independence_claim',
            limitations=['Artificial normal reference and canonical event identity limitations remain.',
                         'Candidate/child count and membership are preserved; grouping is not balanced artificially.',
                         'No new Layer-3 graph, trained upper encoder, temporal signal, Ridge, fusion or final alert.',
                         'Sparse size strata explicitly remain uncalibrated; no silent cross-size fallback.'],
            consumption='require_complete_parent_run_and_valid_signal; never_convert_null_to_zero')
        dump_json(folder/'signal_contract.json',contract);_figures(folder,report,groups)
        def verify():
            if _sha(source/'manifest.json')!=parent_manifest_sha or _sha(source/'observations.jsonl')!=parent['payload_sha256']:
                raise ValueError('Parent signal export changed during hierarchy analysis')
            for day,snapshot in snapshots.items():
                if load_hierarchy(db,day)['digest']!=snapshot['digest']:
                    raise ValueError('Hierarchy snapshot changed during analysis')
                raw=load_raw_chunks(day)
                if _signatures(raw)!=parent['identity']['source_signatures'][day]:
                    raise ValueError('Raw graph changed during analysis')
                _verify_raw_sources(db,raw,parent['identity']['lineage_signatures'])
        verify()
        run=dict(_id=run_id,schema_version=VERSION,identity=identity,parent_signal_run_id=parent['_id'],
            reference_id=reference_id,files=files,contract=contract,operational_ready=False,
            reference_models=states,
            artifact_sha256={name:_sha(folder/name) for name in ('reference_models.json','signal_contract.json','group_descriptors.json')})
        if write:
            persist_hierarchy(db,run,{name:folder/v['path'] for name,v in files.items()})
        dump_json(folder/'manifest.json',dict(run,status='complete',mongo_written=write,
            component_count=sum(g['entity_type']=='component' for g in groups),
            meta_component_count=sum(g['entity_type']=='meta_component' for g in groups),
            source_verified=True,pooling_verified=True,
            calibrated_reference_models=sum(s['status']=='calibrated' for s in states.values()),
            uncalibrated_reference_models=sum(s['status']!='calibrated' for s in states.values())))
        dump_json(folder/'run_status.json',dict(status='complete',run_id=run_id,mongo_written=write))
    except BaseException as exc:
        dump_json(folder/'run_status.json',dict(status='failed',error=f'{type(exc).__name__}: {exc}'))
        if progress:
            progress(f'[HIERARCHY BEHAVIOR] Failed/incomplete: {folder}')
        raise
    return dict(directory=str(folder),run_id=run_id,mongo_written=write)
