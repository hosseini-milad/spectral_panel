"""Offline, exact-membership views of existing L1 embeddings; no training or DB writes."""
import csv
import json
from pathlib import Path

import numpy as np
from .spectral_reports import dump_json, save
import matplotlib.pyplot as plt


def build_meta_view(manifest_path, lineage_path, output, top=12, neighbors=10):
    manifest_path, lineage_path, output = map(Path, (manifest_path, lineage_path, output))
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    lineage = json.loads(lineage_path.read_text(encoding='utf-8-sig'))
    day, run = manifest['source_day'], manifest['run_id']
    if manifest.get('status') != 'complete' or top < 1:
        raise ValueError('A complete Autoencoder run and a positive top count are required.')
    nodes, metas = lineage['nodes'], lineage['meta_components']
    if not nodes or not metas or any(n['source_day'] != day for n in nodes):
        raise ValueError('Hierarchy lineage is empty or belongs to a different day.')
    component_rows, seen_candidates = {}, set()
    for chunk in manifest['chunks']:
        # Prefer paths relative to the run layout: Windows exports can be copied to Linux.
        day_root = manifest_path.parent.parent.parent.parent
        local = day_root / f"chunk-{chunk['chunk_index']}" / chunk['graph_key'] / 'runs' / run
        folder = local if (local / 'inputs.npz').is_file() else Path(chunk['paths']['directory'])
        with np.load(folder / 'inputs.npz', allow_pickle=False) as inputs, np.load(folder / 'spectral_outputs.npz', allow_pickle=False) as encoded:
            ids = inputs['node_ids'].astype(str)
            indices = inputs['component_index']
            components = inputs['component_ids'].astype(str)
            z = encoded['latent'].astype(float)
            if len(ids) != chunk['nodes'] or z.ndim != 2 or len(z) != len(ids) or not np.isfinite(z).all():
                raise ValueError('Invalid embedding shape, node count or non-finite values.')
            if len(set(ids)) != len(ids) or seen_candidates.intersection(ids):
                raise ValueError('Duplicate candidate membership across chunks.')
            seen_candidates.update(ids)
            if indices.shape != (len(ids),) or not np.issubdtype(indices.dtype, np.integer) or np.any(indices < 0) or np.any(indices >= len(components)):
                raise ValueError('Invalid component index array.')
            for i, component in enumerate(components):
                key = (chunk['graph_key'], component)
                select = indices == i
                if key in component_rows or not select.any():
                    raise ValueError('Duplicate or empty component in encoder export.')
                values = z[select]
                component_rows[key] = dict(ids=set(ids[select]), mean=values.mean(0),
                    variance=values.var(0), size=len(values), chunk=int(chunk['chunk_index']))
    ordered, used = [], set()
    for node in nodes:
        key = (node['source_file'], node['component_id'])
        if key not in component_rows or key in used:
            raise ValueError('Hierarchy and encoder components do not match exactly.')
        row = component_rows[key]
        if row['ids'] != set(map(str, node['member_node_ids'])) or len(node['member_node_ids']) != row['size'] or row['size'] != node['node_count'] or row['chunk'] != node['chunk_index']:
            raise ValueError('Hierarchy candidate membership differs from encoder export.')
        used.add(key); ordered.append(row)
    if used != set(component_rows):
        raise ValueError('Hierarchy does not cover every encoded component; regenerate matching reports.')
    component_mean = np.stack([r['mean'] for r in ordered])
    chunks = sorted({r['chunk'] for r in ordered})
    counts = np.zeros((len(metas), len(chunks)), dtype=int)
    assignment = np.full(len(nodes), -1, dtype=int)
    means, stds, sizes, rows = [], [], [], []
    meta_ids = [m['meta_component_id'] for m in metas]
    if len(set(meta_ids)) != len(meta_ids):
        raise ValueError('Duplicate Meta-component IDs.')
    for m, meta in enumerate(metas):
        members = np.asarray(meta['node_indices'], dtype=int)
        if not len(members) or np.any(members < 0) or np.any(members >= len(nodes)) or len(set(members)) != len(members) or np.any(assignment[members] != -1):
            raise ValueError('Invalid or duplicate hierarchy membership.')
        assignment[members] = m
        weight = np.array([ordered[i]['size'] for i in members])
        mean = np.average(component_mean[members], axis=0, weights=weight)
        # Law of total variance: includes within-component and between-component spread.
        variance = np.average(np.stack([ordered[i]['variance'] for i in members]) + (component_mean[members]-mean)**2, axis=0, weights=weight)
        means.append(mean); stds.append(np.sqrt(np.maximum(variance, 0))); sizes.append(int(weight.sum()))
        for i in members:
            counts[m, chunks.index(ordered[i]['chunk'])] += 1
        rows.append(dict(meta_component_id=meta_ids[m], components=len(members), candidate_nodes=int(weight.sum()), source_chunks=int((counts[m] > 0).sum())))
    if np.any(assignment < 0):
        raise ValueError('Hierarchy leaves components unassigned.')
    output.mkdir(parents=True, exist_ok=True)
    means, stds = np.stack(means), np.stack(stds)
    np.savez_compressed(output / 'meta_encoder_features.npz', meta_ids=np.asarray(meta_ids, dtype=str),
        latent_mean=means, latent_std=stds, candidate_count=np.asarray(sizes), chunk_indices=chunks,
        chunk_component_counts=counts, component_ids=np.asarray([n['component_id'] for n in nodes], dtype=str),
        component_graph_keys=np.asarray([n['source_file'] for n in nodes], dtype=str),
        component_latent_mean=component_mean, component_meta_index=assignment)
    with (output / 'meta_statistics.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    ranked = sorted(range(len(metas)), key=lambda i: (-rows[i]['components'], meta_ids[i]))[:top]
    labels = [f"M{i}: {rows[i]['components']} components / {sizes[i]} nodes" for i in ranked]
    centered = component_mean - component_mean.mean(0)
    u, s, _ = np.linalg.svd(centered, full_matrices=False)
    xy = np.zeros((len(nodes), 2)); dims = min(2, len(s)); xy[:, :dims] = u[:, :dims] * s[:dims]
    fig, axes = plt.subplots(1, 3, figsize=(22, max(6, len(ranked)*.35+2)), gridspec_kw={'width_ratios': [1.3, 1, 1]})
    im = axes[0].imshow(np.log1p(counts[ranked]), aspect='auto', cmap='Blues')
    axes[0].set(yticks=range(len(ranked)), yticklabels=labels, xticks=range(len(chunks)), xticklabels=chunks,
        xlabel='Processing chunk (not a time window)', title='Exact membership: log(1 + component count)')
    axes[0].tick_params(axis='x', labelsize=7, rotation=90); fig.colorbar(im, ax=axes[0], shrink=.6)
    scale = means.std(0); normalized = (means-means.mean(0))/np.where(scale > 1e-12, scale, 1)
    im = axes[1].imshow(normalized[ranked], aspect='auto', cmap='coolwarm', vmin=-3, vmax=3)
    axes[1].set(yticks=range(len(ranked)), yticklabels=[f'M{i}' for i in ranked], xlabel='Latent coordinate z (learned, unnamed)', title='Node-weighted meta mean Z\nDisplay standardized within this day; clipped +/-3')
    fig.colorbar(im, ax=axes[1], shrink=.6)
    axes[2].scatter(xy[:, 0], xy[:, 1], s=5, c='#bbbbbb', alpha=.4)
    palette = plt.get_cmap('tab20')
    for color, m in enumerate(ranked):
        mask = assignment == m
        axes[2].scatter(xy[mask, 0], xy[mask, 1], s=7, color=palette(color % 20), label=f'M{m}')
    axes[2].set(title='Component mean embeddings: PCA view\nColor = existing meta membership', xlabel='PC1', ylabel='PC2'); axes[2].legend(fontsize=7, ncol=2)
    fig.suptitle(f'{day} | spectral encoder + existing daily Meta-components | run {run[:8]}')
    fig.text(.5, .015, f'Top {len(ranked)}/{len(metas)} groups in heatmaps; ALL groups exported. No new clustering or training. Separate-day latent axes are not aligned.\nLatent coordinates are not named behavior features or anomaly probabilities. Membership is not a causal edge.', ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .08, 1, .94)); save(fig, output / 'meta_encoder_schematic')
    summary = dict(day=day, autoencoder_run=run, autoencoder_manifest=str(manifest_path.resolve()),
        hierarchy_lineage=str(lineage_path.resolve()), membership_verified='exact_component_and_candidate_ids',
        components=len(nodes), meta_components=len(metas), candidate_nodes=sum(sizes),
        latent_dimension=means.shape[1], shown_meta_indices=ranked, chunks=chunks,
        semantics='Post-hoc node-weighted pooling of full-view spectral L1 latent; not an L2-trained encoder, neighborhood objective, temporal comparison or anomaly detector.')
    dump_json(output / 'report_manifest.json', summary)
    if 'edges' in lineage:
        from .neighborhood_report import write_neighborhood_report
        summary['neighborhood'] = write_neighborhood_report(output, component_mean, assignment, meta_ids, nodes, lineage['edges'], neighbors)
        dump_json(output / 'report_manifest.json', summary)
    return summary
