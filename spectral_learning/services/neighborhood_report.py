"""Post-hoc component-neighborhood diagnostics, never attack probabilities."""
import csv
import numpy as np
from .spectral_reports import dump_json, save
import matplotlib.pyplot as plt


def analyze_neighborhoods(z, assignment, meta_ids, nodes, edges, k=10):
    z = np.asarray(z, dtype=float)
    assignment = np.asarray(assignment, dtype=int)
    n = len(z)
    if k < 1 or z.ndim != 2 or n == 0 or not np.isfinite(z).all() or assignment.shape != (n,):
        raise ValueError('Invalid latent vectors, assignments or neighbor count.')
    if len(nodes) != n or np.any(assignment < 0) or np.any(assignment >= len(meta_ids)):
        raise ValueError('Invalid component membership.')
    adjacent = [set() for _ in range(n)]
    for edge in edges:
        a, b = edge['source'], edge['target']
        if not isinstance(a, int) or not isinstance(b, int) or not 0 <= a < n or not 0 <= b < n or a == b:
            raise ValueError('Invalid hierarchy edge endpoint.')
        if assignment[a] != assignment[b]:
            raise ValueError('Hierarchy edge crosses connected-component Meta membership.')
        adjacent[a].add(b); adjacent[b].add(a)
    norm = np.linalg.norm(z, axis=1)
    valid = norm > 1e-12
    valid_total = int(valid.sum())
    valid_per_meta = np.bincount(assignment[valid], minlength=len(meta_ids))
    unit = z / np.where(valid, norm, 1)[:, None]
    neighbor_ids = np.full((n, min(k, max(0, n-1))), -1, dtype=int)
    component_rows = []
    # Bounded blocks avoid materializing a dense all-pairs matrix. Index breaks ties.
    for start in range(0, n, 128):
        distances = np.clip(1-unit[start:start+128] @ unit.T, 0, 2)
        distances[:, ~valid] = np.inf
        for local, i in enumerate(range(start, min(start+128, n))):
            distances[local, i] = np.inf
            if valid[i]:
                order = np.lexsort((np.arange(n), distances[local]))
                near = order[np.isfinite(distances[local, order])][:k]
                neighbor_ids[i, :len(near)] = near
    distances_to_center = np.zeros(n)
    meta_rows = []
    for m, meta_id in enumerate(meta_ids):
        members = np.flatnonzero(assignment == m)
        if not len(members):
            raise ValueError('Empty Meta-component.')
        center = z[members].mean(0)
        radius = np.linalg.norm(z[members]-center, axis=1)
        distances_to_center[members] = radius
        # Component-balanced spread, deliberately distinct from candidate-weighted pooling.
        q1, q3 = np.quantile(radius, [.25, .75])
        fence = float(q3 + 1.5*(q3-q1))
        far = radius > fence + 1e-12
        meta_rows.append(dict(meta_component_id=meta_id, components=len(members),
            mean_radius=float(radius.mean()), p95_radius=float(np.quantile(radius, .95)), max_radius=float(radius.max()),
            rms_radius=float(np.sqrt(np.mean(radius**2))), iqr_fence=fence,
            exploratory_far_components=int(far.sum()) if len(members) >= 4 else None))
    for i, node in enumerate(nodes):
        near = neighbor_ids[i]; near = near[near >= 0]
        hits = len(set(near) & adjacent[i])
        count_same = int(np.sum(assignment[near] == assignment[i]))
        eligible = bool(valid[i] and len(near))
        group = meta_rows[assignment[i]]
        eligible_population = valid_total-1
        chance = (int(valid_per_meta[assignment[i]])-1)/eligible_population if eligible and eligible_population > 0 else None
        component_rows.append(dict(component_index=i, component_id=node['component_id'], source_file=node['source_file'],
            meta_component_id=meta_ids[assignment[i]], cosine_valid=bool(valid[i]), graph_degree=len(adjacent[i]),
            evaluated_k=len(near), graph_neighbors_retrieved=hits,
            graph_neighbor_recall=hits/len(adjacent[i]) if eligible and adjacent[i] else None,
            knn_same_meta_fraction=count_same/len(near) if eligible else None,
            same_meta_population_fraction=chance,
            same_meta_excess=count_same/len(near)-chance if eligible and chance is not None else None,
            distance_to_component_balanced_center=float(distances_to_center[i]),
            exploratory_far_from_center=bool(distances_to_center[i] > group['iqr_fence'] + 1e-12) if group['components'] >= 4 else None))
    for m, row in enumerate(meta_rows):
        group = [component_rows[i] for i in np.flatnonzero(assignment == m)]
        for metric in ('graph_neighbor_recall', 'knn_same_meta_fraction', 'same_meta_excess'):
            values = [r[metric] for r in group if r[metric] is not None]
            row['mean_'+metric] = float(np.mean(values)) if values else None
            row[metric+'_valid_components'] = len(values)
    recalls = [r['graph_neighbor_recall'] for r in component_rows if r['graph_neighbor_recall'] is not None]
    summary = dict(k_requested=k, components=n, graph_edges=sum(map(len, adjacent))//2,
        graph_isolates=sum(not a for a in adjacent), zero_norm_components=int((~valid).sum()),
        graph_neighbor_recall_valid_components=len(recalls),
        macro_graph_neighbor_recall=float(np.mean(recalls)) if recalls else None,
        definitions=dict(neighbors='Cosine kNN of full-dimensional component means; self excluded; zero-norm vectors excluded; ties use component index.',
            recall='Number of original L2 graph neighbors retrieved / original degree; isolates and invalid queries are undefined, not zero.',
            dispersion='Euclidean distance of raw component means to an equally component-weighted meta center; singleton radius zero is trivial.',
            excess='Observed same-meta kNN fraction minus same-meta fraction in eligible nonzero candidate vectors excluding self; descriptive size correction, not a significance test.',
            far='Radius above Q3 + 1.5 IQR for groups of at least four; exploratory flag, not an anomaly label.'),
        limitations=['Full-view, in-sample structural alignment, not held-out link evaluation or anomaly detection.',
            'Hierarchy graph is built from raw descriptors; agreement with learned neighborhoods is not guaranteed or necessarily optimal.',
            'Raw latent distance scales and axes cannot be compared across independently trained days.',
            'Cosine neighbor similarity and Euclidean dispersion intentionally measure different properties.',
            'L2 component neighbors are analyzed, not original candidate-node neighborhoods.'])
    return summary, component_rows, meta_rows, neighbor_ids


def write_neighborhood_report(output, z, assignment, meta_ids, nodes, edges, k=10):
    summary, components, metas, neighbors = analyze_neighborhoods(z, assignment, meta_ids, nodes, edges, k)
    for name, rows in [('component_neighborhoods', components), ('meta_neighborhoods', metas)]:
        with (output / f'{name}.csv').open('w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    np.savez_compressed(output / 'component_knn.npz', neighbor_indices=neighbors,
        component_ids=np.asarray([n['component_id'] for n in nodes], dtype=str), component_meta_index=assignment)
    dump_json(output / 'neighborhood_summary.json', summary)
    chosen = sorted(metas, key=lambda r: -r['components'])[:12]
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    x = np.arange(len(chosen)); labels = [r['meta_component_id'][-12:] for r in chosen]
    axes[0].bar(x, [r['rms_radius'] for r in chosen]); axes[0].set(title='Within-meta dispersion (raw latent space)', ylabel='Component-balanced RMS radius')
    for j, (metric, title) in enumerate([('mean_graph_neighbor_recall', f'Graph neighbor recall@{k}'), ('mean_same_meta_excess', f'Same-meta excess@{k}')], 1):
        values = [r[metric] for r in chosen]
        axes[j].bar(x, [v if v is not None else np.nan for v in values])
        axes[j].set_title(title+'\nUndefined groups omitted'); axes[j].axhline(0, color='gray', lw=.5)
    for ax in axes:
        ax.set_xticks(x, labels, rotation=90); ax.set_xlabel('Largest Meta-components (ID suffix)')
    fig.suptitle('Post-hoc spectral encoder neighborhood diagnostics')
    fig.text(.5, .015, 'All groups exported to CSV. Singleton spread is trivially zero. Far-point flags and reconstruction residuals are not attack probabilities.\nDifferent-day latent scales are not aligned. Full-view graph agreement is not a held-out prediction score.', ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .10, 1, .93)); save(fig, output / 'neighborhood_overview')
    text = ['Spectral encoder neighborhood diagnostics', f'k={k}; components={summary["components"]}; graph isolates={summary["graph_isolates"]}',
        f'Macro graph-neighbor recall: {summary["macro_graph_neighbor_recall"]}', '', 'Definitions:']
    text += [f'{key}: {value}' for key, value in summary['definitions'].items()]
    text += ['', 'Limitations:', *summary['limitations']]
    (output / 'neighborhood_evaluation.txt').write_text('\n'.join(text)+'\n', encoding='utf-8')
    return summary
