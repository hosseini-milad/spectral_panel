"""Complete machine-readable membership and bounded structural schematics."""
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np

from ingestion.utils.document_paths import document_directory, safe_name


def write_component_report(metadata, graph, result):
    folder = document_directory('component', result['source_file'], layer=result['layer'],
                                day=metadata.get('source_day'),
                                chunk=(metadata.get('graph_parameters') or {}).get('chunk_index'))
    stem = safe_name(result['source_file']) + '_components'
    paths = {suffix: str(folder / f'{stem}.{suffix}') for suffix in ('json', 'txt', 'png', 'svg')}
    rows = result['components']
    payload = {key: value for key, value in result.items() if key != 'paths'}
    payload['definition'] = 'Undirected connected components, including isolated nodes; not Louvain communities.'
    payload['profile_scope'] = 'All graph member nodes with available source documents; not all original pre-sampling flows.'
    payload['integrity'] = {
        'covered_nodes': sum(row['node_count'] for row in rows),
        'partition_complete': sum(row['node_count'] for row in rows) == graph.number_of_nodes(),
        'profiles_complete': result['missing_node_count'] == 0,
    }
    # ObjectIds and dates are serialized without altering their database values.
    with open(paths['json'], 'w', encoding='utf-8') as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False, default=str, allow_nan=False)
    lines = [
        f"Graph: {result['source_file']} | layer={result['layer']}",
        f"Revision: {result['graph_revision']}",
        f"Nodes={result['node_count']} Edges={result['edge_count']} Components={len(rows)}",
        f"Missing source documents={result['missing_node_count']}",
        'Components are connected components, not behavioral ground truth.',
        'Profiles cover graph nodes, not the unsampled original dataset.',
        'Index | Component ID | Nodes | Edges | Density | Bridges | Communities | Representatives | Missing sources',
    ]
    for row in rows:
        stats = row['component_statistics']
        lines.append(f"{row['component_index']} | {row['component_id']} | {row['node_count']} | "
                     f"{stats['internal_edges']} | {stats['density']:.6f} | "
                     f"{stats['bridge_count']} | {stats['community_count']} | "
                     f"{row['representative_count']} | {len(row['missing_node_ids'])}")
    with open(paths['txt'], 'w', encoding='utf-8') as stream:
        stream.write('\n'.join(lines) + '\n')

    fig, axes = plt.subplots(2, 2, figsize=(15, 11))
    sizes = [row['node_count'] for row in rows]
    ax = axes[0, 0]
    if rows:
        # One glyph per component, no edges: components are disconnected by definition.
        columns = max(1, int(np.ceil(np.sqrt(len(rows)))))
        x = np.arange(len(rows)) % columns
        y = -(np.arange(len(rows)) // columns)
        ax.scatter(x, y, s=[40 + 1500 * size / max(sizes) for size in sizes], c=sizes, cmap='viridis')
        if len(rows) <= 100:
            for i, (xx, yy) in enumerate(zip(x, y)):
                ax.annotate(f'C{i}\nn={sizes[i]}', (xx, yy), ha='center', va='center', fontsize=7,
                            color='white' if sizes[i] < max(sizes) / 2 else 'black')
        ax.margins(.2)
    ax.set_title(f'Component schematic: all {len(rows)} components (size = node count)')
    ax.axis('off')
    axes[0, 1].bar(range(len(rows)), sizes)
    axes[0, 1].set(xlabel='Component index (descending size)', ylabel='Nodes', title='Full component-size distribution')
    if sizes:
        axes[0, 1].set_yscale('log')
    axes[1, 0].scatter(sizes, [row['component_statistics']['density'] for row in rows])
    axes[1, 0].set(xlabel='Component nodes', ylabel='Density', title='Internal density versus size')
    ax = axes[1, 1]
    if rows:
        members = rows[0]['node_indices']
        shown = members if len(members) <= 150 else sorted(members, key=lambda node: (-graph.degree(node), node))[:150]
        subgraph = graph.subgraph(shown)
        pos = nx.spring_layout(subgraph, seed=42, iterations=30, weight=None)
        nx.draw_networkx(subgraph, pos=pos, ax=ax, node_size=35, with_labels=len(shown) <= 25,
                         width=.4, edge_color='#a0aec0', node_color='#2b6cb0', font_size=7)
        ax.set_title(f'Largest component: {len(shown)}/{len(members)} nodes shown' +
                     (' (highest-degree induced view)' if len(shown) < len(members) else ' (complete)'))
    ax.axis('off')
    fig.suptitle(f"{result['source_file']} — layer {result['layer']}\n"
                 f"{result['node_count']} nodes | {result['edge_count']} edges | {len(rows)} components")
    fig.tight_layout()
    try:
        fig.savefig(paths['png'], dpi=160)
        fig.savefig(paths['svg'])
    finally:
        plt.close(fig)
    return paths
