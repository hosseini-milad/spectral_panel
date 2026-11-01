"""Phase-2 evidence, learned representations and visual lineage; no HTML."""
import csv
from pathlib import Path
import numpy as np
import torch
import matplotlib.pyplot as plt
from django.conf import settings
from ingestion.utils.document_paths import document_directory
from .spectral_reports import dump_json, save


def write_csv(path, rows, fields=None):
    with Path(path).open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def input_audit(graphs):
    rows = []; configurations = {}
    for graph in graphs:
        parameters = graph.source.get('graph_parameters', {})
        if graph.layer == 1:
            configurations[graph.key] = {key: value for key, value in parameters.items() if key not in {'chunk_index', 'source_file', 'source_day'}}
            fields = parameters.get('feature_fields') or []
            risky = [field for field in fields if field in {'label', 'attack', 'is_attack', 'threat_intel_score', 'attack_type'}]
            rows.append(dict(graph_key=graph.key, check='source_graph_feature_provenance',
                             status='review_required' if risky else ('not_reported' if not fields else 'no_flagged_fields'),
                             detail=', '.join(risky) if risky else 'No flagged field recorded; this is not proof of absence of leakage.'))
    from .spectral_inputs import fingerprint
    unique = {fingerprint(value) for value in configurations.values()}
    rows.append(dict(graph_key='all_chunk_graphs', check='graph_parameter_consistency',
                     status='consistent' if len(unique) == 1 else ('not_available' if not unique else 'mixed'),
                     detail=f'{len(unique)} distinct recorded configurations; inspect phase manifest for exact parameters.'))
    rows.append(dict(graph_key='all', check='temporal_change_detection', status='not_measured',
                     detail='Processing chunks are not real time windows. No cross-time tracking or anomaly accuracy is claimed.'))
    return rows


def graph_report(graph, result, evaluated, run_id, phase1_id, parameters, *, source_spectral_collection='spectral_analysis_runs'):
    folder = document_directory('spectral', graph.key, layer=graph.layer, day=graph.day, chunk=graph.chunk) / 'message-passing' / 'runs' / run_id
    folder.mkdir(parents=True, exist_ok=True)
    spectral, plain = evaluated['spectral'], evaluated['plain']
    first, second = spectral['metrics'], plain['metrics']
    gain = (second['test_mse'] - first['test_mse']) / second['test_mse'] * 100 if second['test_mse'] > 1e-12 else None
    metrics = [dict(metric='spectral_test_masked_mse', value=first['test_mse'], assessment='measured', definition='Held-out feature entries, standardized using training entries; transductive graph.'),
               dict(metric='plain_test_masked_mse', value=second['test_mse'], assessment='measured', definition='Same seed/split/model dimensions, spectral channels disabled.'),
               dict(metric='train_mean_test_mse', value=first['test_mean_baseline_mse'], assessment='baseline', definition='Predict training-column means on the same held-out entries.'),
               dict(metric='spectral_test_improvement_percent', value=gain, assessment='observed_not_significance_test', definition='Positive means lower MSE with spectral inputs; one training seed only.'),
               dict(metric='permutation_max_absolute_error', value=evaluated['permutation_error'], assessment='PASS', definition='Same model, remapped nodes/edges; required <=1e-4.'),
               dict(metric='eigenspace_sign_rotation_error', value=evaluated['eigenspace_invariance_error'], assessment='PASS', definition='Invariant node/edge features under signs and within-group rotations; required <=1e-9.'),
               dict(metric='coarsened_spectral_preservation', value=None, assessment='not_measured', definition='Pooled block attributes are exported; no inter-block graph or prolongation operator exists.'),
               dict(metric='temporal_change_sensitivity', value=None, assessment='not_measured', definition='Requires actual timestamp-based windows and entity correspondence.'),
               dict(metric='anomaly_accuracy', value=None, assessment='not_measured', definition='No anomaly detector or labels used as targets.')]
    summary = dict(graph_key=graph.key, phase='eigenvector_aware_message_passing_probe', run_id=run_id,
                   phase1_run_id=phase1_id, spectral_run_id=phase1_id, source_spectral_collection=source_spectral_collection,
                   source_fingerprint=graph.signature, parameters=parameters,
                   node_count=len(graph.node_ids), embedding_dim=spectral['embedding'].shape[1],
                   pooled_count=len(evaluated['pooled_sizes']), node_type=graph.node_type,
                   spectral_probe=first, plain_probe=second, metrics=metrics,
                   interventions=evaluated['interventions'],
                   embedding_semantics='full_observed_attributes_transductive_embeddings_after_probe_training',
                   embedding_coordinate_scope='graph_and_checkpoint_local_not_cross_graph_aligned',
                   pooling_semantics='equal_child_mean_std_and_size_not_raw_flow_weighted_no_parent_graph',
                   evaluation_scope='single_seed_transductive_masked_feature_probe_not_inductive_detection',
                   message_passing_executed=True, learned_embeddings_generated=True,
                   full_graph_autoencoder_trained=False, anomaly_scores_generated=False)
    np.savez_compressed(folder / 'message_passing_features.npz', node_ids=np.asarray(graph.node_ids, dtype=str),
                        node_embeddings=spectral['embedding'], plain_embeddings=plain['embedding'],
                        block_index=result.arrays['block_index'], pooled_mean=evaluated['pooled_mean'],
                        pooled_std=evaluated['pooled_std'], pooled_sizes=evaluated['pooled_sizes'],
                        training_entry_mask=spectral['train'], validation_entry_mask=spectral['validation'], test_entry_mask=spectral['test'],
                        feature_mean=spectral['mean'], feature_scale=spectral['scale'])
    for name, probe in [('spectral', spectral), ('plain', plain)]:
        torch.save(dict(state_dict=probe['model'].state_dict(), parameters=parameters, feature_names=list(graph.feature_names),
                        feature_mean=probe['mean'].tolist(), feature_scale=probe['scale'].tolist(),
                        level=graph.layer, source_fingerprint=graph.signature, spectral_enabled=name == 'spectral'), folder / f'{name}_probe.pt')
    membership = [dict(block_index=block['block_index'], component_id=block['source_component_id'],
                       child_node_ids=[graph.node_ids[index] for index in block['node_indices']],
                       child_count=block['node_count']) for block in result.blocks]
    dump_json(folder / 'pool_membership.json', membership)
    dump_json(folder / 'evaluation.json', summary)
    write_csv(folder / 'metrics.csv', metrics)
    write_csv(folder / 'interventions.csv', evaluated['interventions'])
    history = [dict(model=name, **row) for name, probe in [('spectral', spectral), ('plain', plain)] for row in probe['history']]
    write_csv(folder / 'training_history.csv', history)
    per_feature_rows = [dict(model=name, **row) for name, probe in [('spectral', spectral), ('plain', plain)] for row in probe['metrics']['per_feature']]
    write_csv(folder / 'feature_metrics.csv', per_feature_rows)
    subgroup_rows = [dict(model=name, **row) for name, probe in [('spectral', spectral), ('plain', plain)] for row in probe['metrics']['spectral_coverage_groups']]
    write_csv(folder / 'coverage_group_metrics.csv', subgroup_rows)
    (folder / 'evaluation.txt').write_text('\n'.join([graph.key, summary['evaluation_scope'], summary['embedding_coordinate_scope'], 'Metric | Value | Assessment'] +
        [f"{row['metric']} | {row['value']} | {row['assessment']}" for row in metrics]) + '\n', encoding='utf-8')
    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    for name, probe in [('spectral', spectral), ('plain', plain)]:
        axes[0, 0].plot([row['epoch'] for row in probe['history']], [row['validation_mse'] for row in probe['history']], label=name)
    axes[0, 0].set(title='Validation only: checkpoint selection', xlabel='Epoch', ylabel='Standardized masked-entry MSE'); axes[0, 0].legend()
    axes[0, 1].bar(['Spectral MP', 'Plain MP', 'Train mean'], [first['test_mse'], second['test_mse'], first['test_mean_baseline_mse']])
    axes[0, 1].set(title='Untouched held-out feature entries (single training seed)', ylabel='Test MSE (lower is better)')
    kinds = ['edge_weight', 'edge_drop', 'feature_noise']
    for offset, field, label in [(-.18, 'spectral_embedding_relative_change', 'Spectral MP'), (.18, 'plain_embedding_relative_change', 'Plain MP')]:
        groups = [[row[field] for row in evaluated['interventions'] if row['intervention'] == kind and row[field] is not None] for kind in kinds]
        axes[1, 0].bar(np.arange(3) + offset, [np.mean(values) if values else 0 for values in groups], width=.36,
                       yerr=[np.std(values) if values else 0 for values in groups], label=label)
    axes[1, 0].set_xticks(range(3), kinds); axes[1, 0].set(title='Controlled perturbations: mean +/- population SD', ylabel='Relative embedding change (sensitivity, no pass target)'); axes[1, 0].legend()
    sizes = evaluated['pooled_sizes']; axes[1, 1].bar(range(len(sizes)), sizes); axes[1, 1].set_yscale('log')
    axes[1, 1].set(title='Membership pooling: every child appears once', xlabel='Connected block index', ylabel='Child count (no parent edges inferred)')
    fig.suptitle(f'{graph.key}\nEigenvector-aware message passing + masked-feature probe; not anomaly detection')
    fig.tight_layout(rect=(0, 0, 1, .94)); save(fig, folder / 'message_passing_overview')
    lineage_figure(folder / 'pooling_schematic', graph, result, evaluated)
    summary['artifacts'] = dict(directory=str(folder), summary=str(folder / 'evaluation.json'), metrics=str(folder / 'metrics.csv'),
                                interventions=str(folder / 'interventions.csv'), features=str(folder / 'message_passing_features.npz'),
                                schematic=str(folder / 'message_passing_overview.png'), pooling_schematic=str(folder / 'pooling_schematic.png'))
    dump_json(folder / 'evaluation.json', summary)
    return summary


def lineage_figure(path, graph, result, evaluated):
    fig, ax = plt.subplots(figsize=(15, 8)); ax.axis('off')
    blocks = result.blocks[:12]; shown = set(index for block in blocks for index in block['node_indices'])
    def node_chunks(index):
        row = (graph.lineage[index] or {}) if graph.lineage else {}
        return {str(value) for value in row.get('source_chunks', [])} or {str(row.get('chunk_index', graph.chunk))}
    chunks = sorted({chunk for index in shown for chunk in node_chunks(index)})
    def box(x, y, label, color):
        ax.text(x, y, label, transform=ax.transAxes, ha='center', va='center', fontsize=9,
                bbox=dict(boxstyle='round,pad=.4', fc=color, ec='#466477'))
    def arrow(a, b):
        ax.annotate('', xy=b, xytext=a, xycoords='axes fraction', arrowprops=dict(arrowstyle='->', color='#8294a0', alpha=.65))
    positions = {chunk: .86 - .70 * i / max(len(chunks)-1, 1) for i, chunk in enumerate(chunks)}
    for chunk, y in positions.items(): box(.08, y, f'Source chunk {chunk}', '#dceefa')
    for index, block in enumerate(blocks):
        y = .87 - index * .065
        members = block['node_indices']
        source_chunks = {chunk for i in members for chunk in node_chunks(i)}
        for chunk in source_chunks: arrow((.15, positions[chunk]), (.38, y))
        box(.48, y, f'Block {block["block_index"]}: {len(members)} child nodes\nSpectral-aware child embeddings', '#e8e0fa')
        arrow((.61, y), (.76, y))
        box(.86, y, f'Pooled block {block["block_index"]}\nmean + std + size', '#def1e4')
    ax.set_title(f'{graph.key}\nSource chunks -> existing component membership -> learned child embeddings -> pooled attributes', pad=20)
    ax.text(.5, .01, f'Showing {len(blocks)}/{len(result.blocks)} largest blocks; exact ALL memberships in pool_membership.json.\nPooling retains existing memberships; no next-parent edges are inferred by this pooling step.', transform=ax.transAxes, ha='center', fontsize=10)
    save(fig, path)


def phase_report(day, run_id, phase1_id, summaries, audits, parameters):
    folder = Path(settings.BASE_DIR) / 'document' / 'spectral' / 'phase2' / day / 'runs' / run_id
    folder.mkdir(parents=True, exist_ok=True)
    rows = [dict(graph_key=s['graph_key'], nodes=s['node_count'], pooled_count=s['pooled_count'],
                 spectral_test_mse=s['spectral_probe']['test_mse'], plain_test_mse=s['plain_probe']['test_mse'],
                 train_mean_test_mse=s['spectral_probe']['test_mean_baseline_mse']) for s in summaries]
    write_csv(folder / 'graph_summary.csv', rows); write_csv(folder / 'input_audit.csv', audits)
    manifest = dict(phase='eigenvector_aware_message_passing_probe', run_id=run_id, phase1_run_id=phase1_id,
                    parameters=parameters, graphs=summaries, input_audit=audits,
                    readiness='exploratory_review_input_audit_before_comparing_or_deploying',
                    temporal_analysis='not_run', anomaly_scores='not_computed', parent_graph='not_created',
                    source_versions_verified=True)
    dump_json(folder / 'phase_manifest.json', manifest)
    architecture_figure(folder / 'phase_overview', f'{day}: {len(summaries)} graphs | learned message-passing features + evaluation')
    (folder / 'phase_summary.txt').write_text('Phase 2: transductive masked-feature probe, not a detector.\n' +
        '\n'.join(f"{row['graph_key']}: spectral={row['spectral_test_mse']:.6g}, plain={row['plain_test_mse']:.6g}" for row in rows) +
        '\nInput audit must be reviewed; no temporal or parent-graph preservation claim.\n', encoding='utf-8')
    return dict(directory=str(folder), manifest=str(folder / 'phase_manifest.json'), summary=str(folder / 'graph_summary.csv'),
                audit=str(folder / 'input_audit.csv'), schematic=str(folder / 'phase_overview.png'))


def architecture_figure(path, title="Phase 2: eigenvector-aware message passing and evaluation"):
    fig, ax = plt.subplots(figsize=(15, 6)); ax.axis('off')
    boxes = [(.10, 'Pinned graphs\nAttributes + masks\nWeighted edges'), (.35, 'Phase 1\nEigenvectors\nInvariant signatures'),
             (.61, 'Phase 2 (this run)\nEigenvector-aware MP\nMasked-feature probe'), (.87, 'Exports\nNode embeddings\nPooled attributes')]
    for x, label in boxes:
        ax.text(x, .65, label, ha='center', va='center', transform=ax.transAxes, fontsize=12,
                bbox=dict(boxstyle='round,pad=.7', fc='#e4eff9', ec='#466477'))
    for left, right in zip(boxes, boxes[1:]):
        ax.annotate('', xy=(right[0]-.105, .65), xytext=(left[0]+.10, .65), xycoords='axes fraction', arrowprops=dict(arrowstyle='->', lw=2))
    ax.text(.50, .28, 'Evaluation: spectral ablation | held-out feature MSE | weight/drop/noise interventions | node permutation\n\nLater phases: meaningful parent graph, temporal windows, graph Autoencoder, scoring and detection\nThese later phases are NOT executed here.', ha='center', transform=ax.transAxes, fontsize=12)
    ax.set_title(title, fontsize=15)
    save(fig, path)
