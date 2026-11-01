"""Statistical and schematic evidence for phase-1 spectra; no HTML generation."""
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from django.conf import settings

from ingestion.utils.document_paths import document_directory


def dump_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def save(fig, path):
    try:
        for extension in ('png', 'svg'):
            fig.savefig(str(path) + '.' + extension, dpi=150, bbox_inches='tight')
    finally:
        plt.close(fig)


def graph_metrics(summary):
    definitions = {
        'node_count': ('count', 'Nodes in the pinned source graph, not unsampled raw flows.'),
        'edge_count': ('count', 'Positive weighted undirected source edges.'),
        'component_count': ('count', 'Connected blocks including isolates.'),
        'isolate_count': ('count', 'Nodes with no edges; no nontrivial eigenvector exists.'),
        'expected_zero_modes': ('count', 'Topological nullity for normalized L with isolate diagonal zero; not inferred from a partial eigensolve.'),
        'expected_positive_rank': ('count', 'N minus connected-component count.'),
        'global_lambda2': ('eigenvalue', 'Zero on a disconnected graph; unavailable when N=1.'),
        'encoded_node_percent': ('%', 'Nodes with at least one complete retained nontrivial eigenspace / all nodes.'),
        'encoded_nonisolate_percent': ('%', 'Encoded nodes / non-isolated nodes; separate from isolate absence.'),
        'full_spectrum_node_coverage_percent': ('%', 'Nodes whose entire local spectrum is computed / all nodes.'),
        'full_spectrum_entropy': ('normalized', 'Computed only if the entire graph spectrum is available; otherwise not measured.'),
        'basis_limited_blocks': ('count', 'Blocks with a degenerate eigenspace exceeding the configured basis budget.'),
        'max_residual': ('norm', 'Maximum ||Lu-lambda*u|| over computed nontrivial eigenpairs.'),
        'max_orthogonality_error': ('absolute', 'Maximum elementwise |U.T U-I| over computed blocks.'),
        'max_kernel_overlap': ('absolute', 'Maximum overlap with the known normalized zero mode.'),
        'operator_symmetry_error': ('absolute', 'Maximum elementwise |L-L.T|.'),
        'dense_full_matrix_estimate_mib': ('MiB estimate', 'Estimated size of ONE hypothetical dense float64 N x N matrix; not measured peak memory.'),
        'elapsed_seconds': ('seconds', 'Operator construction and eigensolves; excludes report/database writing.'),
    }
    rows = []
    numerical = {'max_residual', 'max_orthogonality_error', 'max_kernel_overlap', 'operator_symmetry_error'}
    for field, (unit, definition) in definitions.items():
        value = summary[field]
        status = 'Not available' if value is None else ('PASS' if field in numerical else 'Observed')
        rows.append(dict(metric=field, value=value, unit=unit, assessment=status, definition=definition))
    rows.extend([
        dict(metric='learned_embeddings', value=None, unit='N/A', assessment='Not run', definition='Message passing and Autoencoder training belong to later phases.'),
        dict(metric='coarsened_spectral_preservation', value=None, unit='N/A', assessment='Not measured', definition='Requires a meaningful coarsened graph and an explicit prolongation/mass operator.'),
        dict(metric='anomaly_detection_accuracy', value=None, unit='N/A', assessment='Not measured', definition='No detector or calibration is trained in spectral phase 1.'),
    ])
    return rows


def write_graph(graph, result, run_id):
    folder = document_directory('spectral', graph.key, layer=graph.layer, day=graph.day, chunk=graph.chunk) / 'runs' / run_id
    folder.mkdir(parents=True, exist_ok=True)
    summary, blocks, arrays = result.summary, result.blocks, result.arrays
    summary['source'] = graph.source; summary['source_fingerprint'] = graph.signature
    summary['metrics'] = graph_metrics(summary)
    np.savez_compressed(folder / 'spectral_features.npz', **arrays)
    dump_json(folder / 'spectral_summary.json', summary)
    dump_json(folder / 'spectral_blocks.json', blocks)
    dump_json(folder / 'node_lineage.json', {'node_ids': graph.node_ids, 'lineage': graph.lineage})
    with (folder / 'metrics.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=['metric', 'value', 'unit', 'assessment', 'definition'])
        writer.writeheader(); writer.writerows(summary['metrics'])
    fields = ['block_index', 'source_component_id', 'node_count', 'solver', 'spectrum_kind', 'basis_dim',
              'basis_limited', 'residual_max', 'orthogonality_max', 'fiedler_value', 'elapsed_seconds']
    with (folder / 'blocks.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader(); writer.writerows(blocks)
    lines = [graph.key, f'phase_run_id={run_id}; layer={graph.layer}; node_type={graph.node_type}',
             f"source={graph.source}", 'Metric | Value | Unit | Assessment']
    lines.extend(f"{row['metric']} | {row['value']} | {row['unit']} | {row['assessment']}" for row in summary['metrics'])
    lines.extend(['', 'No temporal windows, learned embeddings or anomaly scores were inferred.',
                  'Full eigenspaces are retained; missing modes are masked, never treated as observed zero features.',
                  'Signs/rotations of raw vectors are not cross-run identifiers. Invariant signatures use retained projector groups.'])
    (folder / 'spectral_summary.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    graph_figure(folder, graph, result)
    return {'directory': str(folder), 'summary': str(folder / 'spectral_summary.json'),
            'features': str(folder / 'spectral_features.npz'), 'metrics': str(folder / 'metrics.csv'),
            'blocks': str(folder / 'blocks.csv'), 'schematic': str(folder / 'spectral_overview.png')}


def graph_figure(folder, graph, result):
    summary, blocks, arrays = result.summary, result.blocks, result.arrays
    fig, axes = plt.subplots(3, 2, figsize=(17, 15))
    axes[0, 0].bar(range(len(blocks)), [block['node_count'] for block in blocks])
    axes[0, 0].set_yscale('log')
    axes[0, 0].set(title='All connected-block sizes (including isolates)', xlabel='Block index, sorted by size', ylabel='Nodes')
    axes[0, 1].axis('off')
    keys = ['node_count', 'edge_count', 'component_count', 'expected_zero_modes', 'isolate_count',
            'encoded_node_percent', 'encoded_nonisolate_percent', 'basis_limited_blocks', 'max_residual']
    rows = [[key, 'N/A' if summary[key] is None else f'{summary[key]:.6g}'] for key in keys]
    table = axes[0, 1].table(cellText=rows, colLabels=['Metric', 'Value'], loc='center', cellLoc='left', colWidths=[.72, .28])
    table.auto_set_font_size(False); table.set_fontsize(10); table.scale(1, 1.6)
    full = [value for block in blocks for value in (block['full_eigenvalues'] or [])]
    axes[1, 0].hist(full, bins=np.linspace(-1e-8, 2 + 1e-8, 33))
    axes[1, 0].set(title=f"Complete local spectra only: {len(full)}/{summary['node_count']} nodes\nThis is NOT the full graph spectrum when coverage < 100%", xlabel='Eigenvalue', ylabel='Observed eigenvalue count')
    for block in blocks[:10]:
        values = block['computed_positive_values'][:16]
        if values:
            axes[1, 1].plot(range(1, len(values) + 1), values, marker='.', label=f"block {block['block_index']} (n={block['node_count']})")
    axes[1, 1].set(title='Computed nontrivial low modes of up to 10 largest blocks', xlabel='Within-block eigenvalue rank', ylabel='Eigenvalue')
    if any(block['computed_positive_values'] for block in blocks[:10]):
        axes[1, 1].legend(fontsize=7)
    ax = axes[2, 0]
    block = next((block for block in blocks if block['basis_dim']), None)
    if block:
        members = set(block['node_indices'])
        edges = arrays['edge_index'].T
        sub = nx.Graph(); sub.add_nodes_from(members)
        sub.add_edges_from((int(a), int(b)) for a, b in edges if int(a) in members and int(b) in members)
        shown = sorted(members, key=lambda node: (-sub.degree(node), node))[:150]
        displayed = sub.subgraph(shown)
        positions = nx.spring_layout(displayed, seed=42, iterations=25, weight=None)
        nx.draw_networkx_edges(displayed, positions, ax=ax, alpha=.25, width=.6)
        image = nx.draw_networkx_nodes(displayed, positions, ax=ax, nodelist=shown,
                                      node_color=arrays['eigenvectors'][shown, 0], cmap='coolwarm', node_size=35)
        fig.colorbar(image, ax=ax, label='First retained eigenvector coordinate (sign is arbitrary)')
        ax.set_title(f"Spectral schematic: block {block['block_index']}, {len(shown)}/{len(members)} nodes\n" +
                     ('Highest-degree induced view; omitted paths may disconnect it' if len(shown) < len(members) else 'Complete block view'))
    else:
        ax.text(.1, .5, 'No usable nontrivial basis\nSee isolate/basis-budget masks and metrics.', transform=ax.transAxes)
    ax.axis('off')
    residuals = [max(block['residual_max'], 1e-18) for block in blocks if block['node_count'] > 1]
    axes[2, 1].plot(range(len(residuals)), residuals, '.', markersize=3)
    axes[2, 1].set_yscale('log')
    axes[2, 1].set(title='Numerical residuals (plot floor 1e-18)', xlabel='Non-isolated block index', ylabel='Maximum ||Lu - lambda*u||')
    fig.suptitle(f'{graph.key} | layer {graph.layer} | phase 1: spectral analysis only\n'
                 'Projector-based invariant signatures exported for future eigenvector-aware message passing')
    fig.tight_layout(rect=(0, 0, 1, .95))
    save(fig, folder / 'spectral_overview')


def write_phase(day, run_id, summaries, context, higher_levels, planning_ratio, parameters=None):
    folder = Path(settings.BASE_DIR) / 'document' / 'spectral' / 'phase1' / day / 'runs' / run_id
    folder.mkdir(parents=True, exist_ok=True)
    readiness = [
        dict(level=0, unit='raw_flow_graph', nodes=context['raw_record_count'], graph_status='raw_records_only', spectral_status='not_computed', count_kind='raw_records_not_graph_nodes'),
        dict(level=1, unit='candidate_flow_graphs', nodes=sum(row['node_count'] for row in summaries if row['layer'] == 1) if any(row['layer'] == 1 for row in summaries) else None, graph_status='available' if any(row['layer'] == 1 for row in summaries) else 'not_selected', spectral_status='computed' if any(row['layer'] == 1 for row in summaries) else 'not_computed', count_kind='observed_graph_nodes'),
        dict(level=2, unit='component_similarity_graph', nodes=sum(row['node_count'] for row in summaries if row['layer'] == 2) if any(row['layer'] == 2 for row in summaries) else None, graph_status='available' if any(row['layer'] == 2 for row in summaries) else 'not_selected', spectral_status='computed' if any(row['layer'] == 2 for row in summaries) else 'not_computed', count_kind='observed_graph_nodes'),
        dict(level=3, unit='meta_component_graph', nodes=context['meta_component_count'], graph_status='membership_only_no_inter_meta_graph' if context['meta_component_count'] is not None else 'not_available', spectral_status='not_computed', count_kind='observed_membership_count'),
    ]
    estimate = context['meta_component_count']
    for offset in range(higher_levels):
        estimate = int(np.ceil(estimate * planning_ratio)) if estimate is not None else None
        readiness.append(dict(level=4 + offset, unit='above_meta_coarsened_graph', nodes=estimate,
                              graph_status='planned_graph_not_built', spectral_status='not_computed',
                              count_kind=f'scenario_only_ratio_{planning_ratio}'))
    with (folder / 'hierarchy_readiness.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=['level', 'unit', 'nodes', 'graph_status', 'spectral_status', 'count_kind'])
        writer.writeheader(); writer.writerows(readiness)
    columns = ['graph_key', 'layer', 'node_count', 'edge_count', 'component_count', 'isolate_count',
               'expected_zero_modes', 'spectrum_kind', 'encoded_node_percent', 'max_residual', 'analysis_status']
    with (folder / 'graph_summary.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader(); writer.writerows(summaries)
    manifest = dict(phase='spectral_analysis_1', run_id=run_id, source_day=day, context=context, parameters=parameters,
                    graphs=summaries, hierarchy_readiness=readiness,
                    message_passing='contract_and_invariant_inputs_only_not_trained',
                    temporal_analysis='not_run_no_synthetic_time_windows',
                    autoencoder='not_run', ridge='not_run', anomaly_scores='not_computed',
                    higher_level_estimates='scenario_only_not_computed_graphs', source_versions_verified=True)
    dump_json(folder / 'phase_manifest.json', manifest)
    text = [f'Spectral phase 1: {day}; run={run_id}', 'Graph | Level | Nodes | Blocks | Encoding % | Max residual']
    text.extend(f"{row['graph_key']} | {row['layer']} | {row['node_count']} | {row['component_count']} | {row['encoded_node_percent']:.3f} | {row['max_residual']:.3g}" for row in summaries)
    text.extend(['', 'Higher levels above Meta-components are planning scenarios, not constructed graphs.',
                 'No Autoencoder, Ridge, synthetic hourly windows or anomaly detector was run.'])
    (folder / 'phase_summary.txt').write_text('\n'.join(text) + '\n', encoding='utf-8')
    fig, axes = plt.subplots(1, 2, figsize=(16, max(6, .5 * len(readiness))))
    axes[0].axis('off')
    table = axes[0].table(cellText=[[f"L{row['level']}", str(row['nodes']), row['spectral_status'], row['count_kind']] for row in readiness],
                          colLabels=['Level', 'Units', 'Spectral status', 'Evidence'], loc='center', colWidths=[.10, .14, .25, .51])
    table.auto_set_font_size(False); table.set_fontsize(8); table.scale(1, 2.1)
    axes[0].set_title('Hierarchy readiness and above-Meta scenarios\nProcessing level is independent of temporal window')
    axes[1].bar(range(len(summaries)), [row['encoded_node_percent'] for row in summaries])
    axes[1].set_xticks(range(len(summaries)), [f"L{row['layer']}:{index}" for index, row in enumerate(summaries)], rotation=90)
    axes[1].set(title='Observed nontrivial-basis node coverage\nIsolates and limited eigenspaces remain explicitly masked', ylabel='Encoded nodes (%)', ylim=(0, 105))
    fig.suptitle(f'Spectral phase 1 — {day} — no trained embeddings or anomaly scores')
    fig.tight_layout(); save(fig, folder / 'phase_overview')
    return {'directory': str(folder), 'manifest': str(folder / 'phase_manifest.json'),
            'readiness': str(folder / 'hierarchy_readiness.csv'), 'schematic': str(folder / 'phase_overview.png')}
