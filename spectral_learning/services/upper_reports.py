"""Schematic/statistical evidence for real upper graphs, distinct from planning."""
from pathlib import Path
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from django.conf import settings

from ingestion.utils.document_paths import document_directory
from .spectral_reports import dump_json, save
from .message_passing_reports import write_csv


def write_upper_graph(graph, state, audit, result, inherited_embedding, inherited_spectral, run_id):
    folder = document_directory('spectral', graph.key, layer=graph.layer, day=graph.day) / 'upper-graph' / 'runs' / run_id
    folder.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(folder / 'upper_graph.npz', node_ids=np.asarray(graph.node_ids, dtype=str),
                        node_features=graph.features, node_feature_mask=graph.feature_mask,
                        feature_names=np.asarray(graph.feature_names), edge_index=result.arrays['edge_index'],
                        edge_weight=result.arrays['edge_weight'], moment_mean=state.mean, moment_variance=state.variance,
                        moment_count=state.count, original_component_mass=state.mass,
                        inherited_embedding_mean=inherited_embedding[0], inherited_embedding_std=inherited_embedding[1],
                        inherited_spectral_mean=inherited_spectral[0], inherited_spectral_std=inherited_spectral[1], inherited_spectral_valid_count=inherited_spectral[2])
    dump_json(folder / 'node_lineage.json', dict(node_ids=graph.node_ids, lineage=graph.lineage))
    dump_json(folder / 'graph_construction.json', dict(source=graph.source, aggregation_audit=audit,
        inherited_feature_semantics='Child pooled embeddings/signatures are exported as auxiliary data; not used to construct edges or as held-out targets. Encoder coordinates remain source-checkpoint local.',
        spectral_summary=result.summary))
    metrics = [dict(metric=key, value=value, assessment='observed') for key, value in audit.items() if not isinstance(value, (list, dict))]
    metrics += [dict(metric='edge_count', value=len(graph.edges), assessment='observed'),
                dict(metric='max_degree', value=graph.source['graph_parameters']['max_degree'], assessment='bounded_by_neighbors')]
    write_csv(folder / 'metrics.csv', metrics)
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    network = nx.Graph(); network.add_nodes_from(range(len(graph.node_ids)))
    network.add_weighted_edges_from((edge['source'], edge['target'], edge['weight']) for edge in graph.edges)
    shown = list(range(min(1000, len(graph.node_ids))))
    sub = network.subgraph(shown)
    positions = nx.spring_layout(sub, seed=17, iterations=35, weight='weight')
    nx.draw_networkx_edges(sub, positions, ax=axes[0, 0], alpha=.12, width=.4)
    nx.draw_networkx_nodes(sub, positions, ax=axes[0, 0], node_size=7, node_color=result.arrays['block_index'][shown], cmap='tab20')
    axes[0, 0].set_title(f'NEW descriptor similarity graph: {len(shown)}/{len(graph.node_ids)} nodes shown\nColors = upper connected groups; layout alone is not a quality metric')
    axes[0, 0].axis('off')
    chunks = sorted({c for row in graph.lineage for c in row['source_chunks']})
    heat = np.zeros((max(1, len(chunks)), min(30, len(graph.node_ids))))
    for j, row in enumerate(graph.lineage[:30]):
        for chunk in row['source_chunks']:
            heat[chunks.index(chunk), j] = 1
    axes[0, 1].imshow(heat, aspect='auto', cmap='Blues', vmin=0, vmax=1)
    axes[0, 1].set_yticks(range(max(1, len(chunks))), [str(x) for x in chunks] or ['unknown'])
    axes[0, 1].set(title='Source-chunk presence in first 30 upper nodes (binary)', xlabel='Upper node index', ylabel='Source chunk')
    axes[1, 0].bar(range(len(result.blocks)), [b['node_count'] for b in result.blocks]); axes[1, 0].set_yscale('log')
    axes[1, 0].set(title='Groups discovered in the new upper graph', xlabel='Connected group index', ylabel='Upper node count')
    rows = [('Child nodes', audit['child_node_count']), ('Upper nodes', len(graph.node_ids)), ('Upper edges', len(graph.edges)),
            ('Upper groups', len(result.blocks)), ('Isolates', result.summary['isolate_count']),
            ('Original component mass', int(state.mass.sum())), ('Global mean error', f"{audit['global_mean_max_absolute_error']:.3g}"),
            ('Source quotient edges', audit['quotient_cross_edges']), ('Spectral preservation', 'not established')]
    axes[1, 1].axis('off'); table = axes[1, 1].table(cellText=rows, colLabels=['Metric', 'Value'], loc='center'); table.auto_set_font_size(False); table.set_fontsize(11); table.scale(1, 1.8)
    fig.suptitle(f'{graph.key}\nExisting lower memberships -> raw moment descriptors -> NEW graph -> spectral analysis + message passing')
    fig.tight_layout(rect=(0, 0, 1, .94)); save(fig, folder / 'upper_graph_overview')
    return dict(directory=str(folder), graph=str(folder / 'upper_graph.npz'), construction=str(folder / 'graph_construction.json'),
                lineage=str(folder / 'node_lineage.json'), metrics=str(folder / 'metrics.csv'), schematic=str(folder / 'upper_graph_overview.png'))


def write_upper_phase(day, run_id, source_run, records, parameters, source_audit):
    folder = Path(settings.BASE_DIR) / 'document' / 'spectral' / 'upper' / day / 'runs' / run_id
    folder.mkdir(parents=True, exist_ok=True)
    manifest = dict(phase='upper_structural_graph_spectral_and_message_passing', run_id=run_id, source_message_passing_run=source_run,
                    source_day=day, parameters=parameters, levels=records, source_input_audit=source_audit,
                    source_versions_verified=True, temporal_detection='not_run', spectral_preservation='not_established_rebuilt_similarity_graphs')
    dump_json(folder / 'phase_manifest.json', manifest)
    rows = [dict(layer=r['layer'], node_count=r['spectral']['node_count'], edge_count=r['spectral']['edge_count'],
                 component_count=r['spectral']['component_count'], isolate_count=r['spectral']['isolate_count'],
                 max_residual=r['spectral']['max_residual'], message_passing_status=r['message_passing_status'],
                 spectral_test_mse=r['message_passing']['spectral_probe']['test_mse'] if r['message_passing'] else None,
                 plain_test_mse=r['message_passing']['plain_probe']['test_mse'] if r['message_passing'] else None) for r in records]
    write_csv(folder / 'graph_summary.csv', rows)
    write_csv(folder / 'input_audit.csv', source_audit, ['graph_key', 'check', 'status', 'detail'])
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    labels = ['L2 source components'] + [f'L{r["layer"]} nodes' for r in records]
    counts = [records[0]['aggregation_audit']['child_node_count']] + [r['spectral']['node_count'] for r in records]
    axes[0].bar(labels, counts); axes[0].set(title='Observed graph sizes (not planning scenarios)', ylabel='Nodes')
    axes[1].axis('off')
    text = ['Pinned L2 graph + trained child embeddings', 'Existing groups become upper nodes', 'Attribute moments define new mutual-kNN edges',
            'Spectral analysis on the new graph', 'Eigenvector-aware MP + matched plain probe', 'Complete lineage + conserved moment statistics',
            '', 'Inherited embeddings/signatures exported as auxiliary data.', 'No automatic temporal or spectral-preservation claim.']
    axes[1].text(.03, .92, '\n\n'.join(text), va='top', fontsize=11)
    fig.suptitle(f'{day} | real upper graph analysis | source MP run {source_run[:12]}'); fig.tight_layout(); save(fig, folder / 'phase_overview')
    (folder / 'phase_summary.txt').write_text('\n'.join(str(row) for row in rows) + '\nNew descriptor-similarity edges, not source quotient edges.\n', encoding='utf-8')
    return dict(directory=str(folder), manifest=str(folder / 'phase_manifest.json'), summary=str(folder / 'graph_summary.csv'),
                audit=str(folder / 'input_audit.csv'), schematic=str(folder / 'phase_overview.png'))
