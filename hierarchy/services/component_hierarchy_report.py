"""Static hierarchy diagrams, membership exports and explicit evaluation tables."""
import csv
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np

from ingestion.utils.document_paths import document_directory
from hierarchy.services.hierarchy_metrics import build_metrics_table, format_metrics_table, format_value


def save_figure(fig, base):
    try:
        for extension in ('png', 'svg'):
            fig.savefig(str(base) + '.' + extension, dpi=150, bbox_inches='tight')
    finally:
        plt.close(fig)


def write_dashboard(folder, evaluation, nodes, graph):
    metas = evaluation['meta_components']; chunks = sorted({node['chunk_index'] for node in nodes})
    fig, axes = plt.subplots(2, 2, figsize=(16, 11))
    meta_for = {index: meta['meta_index'] for meta in metas for index in meta['node_indices']}
    matrix = np.zeros((len(chunks), len(metas)), dtype=int)
    chunk_rows = {chunk: index for index, chunk in enumerate(chunks)}
    for node in nodes:
        matrix[chunk_rows[node['chunk_index']], meta_for[node['node_index']]] += 1
    # Full matrix is retained as CSV; bound static label clutter.
    shown = matrix[:, :30]
    if matrix.shape[1] > 30:
        shown = np.column_stack([shown, matrix[:, 30:].sum(axis=1)])
    image = axes[0, 0].imshow(shown, aspect='auto', cmap='Blues', interpolation='nearest')
    axes[0, 0].set_yticks(range(len(chunks)), [f'chunk {value}' for value in chunks])
    labels = [f'M{i}' for i in range(min(30, len(metas)))] + (['Other metas'] if len(metas) > 30 else [])
    axes[0, 0].set_xticks(range(len(labels)), labels, rotation=90, fontsize=7)
    axes[0, 0].set_title('Chunk → Meta-component membership (number of child components)')
    fig.colorbar(image, ax=axes[0, 0])
    axes[0, 1].bar(range(len(metas)), [meta['component_count'] for meta in metas])
    axes[0, 1].set(xlabel='Meta-component index', ylabel='Child components', title='All meta-component sizes')
    axes[0, 1].set_yscale('log')
    hist = evaluation['diagnostics']
    bins = np.array(hist['histogram_bins'])
    axes[1, 0].bar(bins[:-1], hist['histogram_counts'], width=.01, align='edge')
    axes[1, 0].axvline(evaluation['parameters']['threshold'], color='red', label='Threshold')
    axes[1, 0].set(xlabel='Component similarity', ylabel='Comparable pairs', title='All-pair similarity distribution')
    axes[1, 0].legend()
    ax = axes[1, 1]; ax.axis('off')
    selected_keys = {'input_components', 'meta_components', 'compression_percent',
                     'singleton_meta_components', 'unmerged_input_percent', 'cross_chunk_meta_components',
                     'edge_count', 'max_degree', 'component_coverage_percent', 'chaining_meta_components'}
    rows = [row for row in evaluation['metrics_table'] if row['metric'] in selected_keys]
    table = ax.table(cellText=[[row['label'], format_value(row['value']), row['unit']] for row in rows],
                     colLabels=['Metric', 'Value', 'Unit'], colWidths=[.68, .22, .10], loc='center', cellLoc='left')
    table.auto_set_font_size(False); table.set_fontsize(9); table.scale(1, 1.6)
    ax.set_title('Evaluation summary (complete table: evaluation_metrics.csv)')
    fig.suptitle(evaluation['source_file'] + '\nLayer-2 nodes are layer-1 components, not representative flows')
    fig.tight_layout()
    save_figure(fig, folder / 'overview')

    fig, ax = plt.subplots(figsize=(15, 12))
    positions = nx.spring_layout(graph, seed=42, iterations=30, weight='weight')
    palette = plt.get_cmap('tab20')
    colors = lambda index: palette((2 * (index % 10) + index // 10 % 2) % 20)
    nx.draw_networkx_edges(graph, positions, ax=ax, alpha=.2, width=.5)
    for chunk in chunks:
        indices = [node['node_index'] for node in nodes if node['chunk_index'] == chunk]
        nx.draw_networkx_nodes(graph, positions, nodelist=indices, ax=ax,
                               node_color=[colors(chunk % 20)], node_size=25, label=f'chunk {chunk}')
    if len(nodes) <= 40:
        nx.draw_networkx_labels(graph, positions, {node['node_index']: f"ch{node['chunk_index']}:C{node['component_index']}" for node in nodes}, ax=ax, font_size=7)
    ax.legend(fontsize=7, ncol=max(1, len(chunks) // 15 + 1))
    ax.set_title('Component similarity graph — nodes colored by source chunk\nExact IDs and memberships: lineage.json / component_membership.csv')
    ax.axis('off')
    save_figure(fig, folder / 'component_graph')
    return matrix, chunks


def write_metrics_figure(folder, rows):
    fig, ax = plt.subplots(figsize=(15, max(7, len(rows) * .32)))
    ax.axis('off')
    table = ax.table(cellText=[[row['label'], format_value(row['value']), row['unit'], row['assessment']] for row in rows],
                     colLabels=['Metric', 'Value', 'Unit', 'Assessment'], colWidths=[.55, .16, .09, .20],
                     loc='center', cellLoc='left')
    table.auto_set_font_size(False); table.set_fontsize(9); table.scale(1, 1.5)
    ax.set_title('Hierarchy evaluation metrics\nDefinitions and denominators: evaluation_metrics.csv / evaluation.txt', pad=15)
    save_figure(fig, folder / 'evaluation_metrics')


def write_reports(evaluation, nodes, graph):
    root = document_directory('hierarchy', evaluation['source_file'], layer=2, day=evaluation['source_day'])
    folder = root / 'runs' / evaluation['run_id']; folder.mkdir(parents=True, exist_ok=True)
    evaluation['metrics_table'] = build_metrics_table(evaluation, nodes)
    evaluation['generated_outputs'] = {'html': False, 'lineage_pages': False}
    evaluation.pop('lineage_pages', None)
    matrix, chunks = write_dashboard(folder, evaluation, nodes, graph)
    fields = ['metric', 'label', 'value', 'unit', 'assessment', 'definition']
    with (folder / 'evaluation_metrics.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(evaluation['metrics_table'])
    write_metrics_figure(folder, evaluation['metrics_table'])
    with (folder / 'evaluation.json').open('w', encoding='utf-8') as stream:
        json.dump(evaluation, stream, ensure_ascii=False, indent=2, allow_nan=False)
    with (folder / 'lineage.json').open('w', encoding='utf-8') as stream:
        json.dump({'nodes': nodes, 'meta_components': evaluation['meta_components'],
                   'edges': [{'source': a, 'target': b, **data} for a, b, data in graph.edges(data=True)]},
                  stream, ensure_ascii=False, indent=2, allow_nan=False)
    with (folder / 'chunk_meta_matrix.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['chunk_index'] + [meta['meta_component_id'] for meta in evaluation['meta_components']])
        for chunk, row in zip(chunks, matrix):
            writer.writerow([chunk] + row.tolist())
    with (folder / 'component_membership.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream); writer.writerow(['chunk', 'component_id', 'source_file', 'candidate_nodes', 'meta_component_id'])
        for meta in evaluation['meta_components']:
            for index in meta['node_indices']:
                node = nodes[index]
                writer.writerow([node['chunk_index'], node['component_id'], node['source_file'], node['node_count'], meta['meta_component_id']])
    lines = [evaluation['source_file'], f"run_id: {evaluation['run_id']}",
             f"chunks={len(chunks)} components={len(nodes)} edges={graph.number_of_edges()} metas={len(evaluation['meta_components'])}",
             f"candidate_nodes_traced={evaluation['candidate_node_count']}",
             f"unrepresented_components_included={evaluation['components_without_representatives']}",
             f"integrity={evaluation['integrity']}", '', 'EVALUATION METRICS',
             format_metrics_table(evaluation['metrics_table']), '',
             'Metric definitions:', *[f"{row['metric']}: {row['definition']}" for row in evaluation['metrics_table']],
             '', 'Meta | Children | Candidate nodes | Chunks | Min pair similarity | Chaining warning']
    for meta in evaluation['meta_components']:
        lines.append(f"M{meta['meta_index']} | {meta['component_count']} | {meta['member_node_count']} | "
                     f"{meta['source_chunks']} | {meta['pair_similarity_min']} | {meta['chaining_warning']}")
    lines.extend(['', 'Limitations:', *evaluation['limitations']])
    (folder / 'evaluation.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return {'directory': str(folder), 'evaluation': str(folder / 'evaluation.json'),
            'text': str(folder / 'evaluation.txt'), 'overview': str(folder / 'overview.png'),
            'metrics_csv': str(folder / 'evaluation_metrics.csv'),
            'metrics_image': str(folder / 'evaluation_metrics.png'), 'lineage': str(folder / 'lineage.json'),
            'graph': str(folder / 'component_graph.png')}
