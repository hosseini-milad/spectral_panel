"""Standalone score/alert audits for saved outputs and live frozen models."""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import roc_curve, precision_recall_curve

from .behavior_scoring import POLICIES, evaluate_score_channels
from .normal_behavior import tail_probabilities
from .message_passing_reports import write_csv
from .spectral_reports import dump_json, save


def write_score_analysis(folder, dataset, normal_day, *, alphas=(.01, .05, .1),
                         selected_policy='joint_spectral_gap', source=None):
    if selected_policy not in POLICIES:
        raise ValueError('Unknown score policy')
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    channels, metrics, state = evaluate_score_channels(dataset, normal_day, alphas)
    state['selected_policy'] = selected_policy
    state['score_unit'] = 'candidate_record_not_component_or_meta_component'
    state['source'] = source
    state['external_days_are_development_data'] = True
    state['limits'] = [
        'Only normal training residuals fit numerical scales; only normal calibration rows fit thresholds.',
        'Labels are used for retrospective evaluation and case tables, not score fitting or threshold calibration.',
        'Days already inspected during method development are not untouched final tests; confirm on another independent day.',
        'The gap score measures disagreement: graph/spectral reconstruction is easier than feature-only reconstruction. This is not proof of attack or oversmoothing.',
        'CSV alone cannot identify raw feature causes, component/Meta-component membership, or independently redo lineage checks.',
        'Model residuals must describe the same candidate, feature targets and evaluation mask; metadata alignment alone cannot establish common masks in arbitrary third-party CSV files.',
        'Calibration alpha is a nominal tail level, not a guaranteed operational false-positive rate.',
    ]
    write_csv(folder / 'score_policy_metrics.csv', metrics)
    chosen_alpha = alphas[0]
    metadata = dataset.metadata
    selected = channels[selected_policy]
    cutoff = state['thresholds'][selected_policy][str(chosen_alpha)]
    reconstruction_cutoff = state['thresholds']['spectral_reconstruction'][str(chosen_alpha)]
    gap_cutoff = state['thresholds']['feature_spectral_gap'][str(chosen_alpha)]
    reference_tails = {name: -np.log(tail_probabilities(distribution, channels[name]))
                       for name, distribution in state['normal_training_distributions'].items()}
    selected_rows = []
    for i, row in enumerate(metadata):
        valid = bool(dataset.valid[i])
        selected_rows.append(dict(**row, score_policy=selected_policy, score=float(selected[i]) if valid else None,
                                  valid=valid, alpha=chosen_alpha, threshold=cutoff,
                                  original_reconstruction_alert=bool(channels['spectral_reconstruction'][i] > reconstruction_cutoff) if valid else None,
                                  gap_alert=bool(channels['feature_spectral_gap'][i] > gap_cutoff) if valid else None,
                                  dominant_joint_channel=max(reference_tails, key=lambda name: reference_tails[name][i]) if valid else None,
                                  alert=bool(selected[i] > cutoff) if valid else None))
    write_csv(folder / 'selected_node_scores.csv', selected_rows)
    np.savez_compressed(folder / 'score_channels.npz', valid=dataset.valid,
        node_ids=np.asarray([r['node_id'] for r in metadata], dtype=str),
        raw_record_ids=np.asarray([r['raw_record_id'] for r in metadata], dtype=str),
        days=np.asarray([r['day'] for r in metadata], dtype=str),
        splits=np.asarray([r['split'] for r in metadata], dtype=str), **channels)
    cases = []
    external_days = sorted({r['day'] for r in metadata if r['split'] == 'external_test'})
    for day in external_days:
        indices = np.asarray([i for i, r in enumerate(metadata) if r['day'] == day and dataset.valid[i]])
        for label, alert, category in [('1', True, 'label1_alert'), ('0', True, 'label0_alert'),
                                        ('1', False, 'label1_missed'), ('0', False, 'label0_not_alerted')]:
            candidates = [i for i in indices if str(metadata[i]['raw_label']) == label and bool(selected[i] > cutoff) == alert]
            # Highest-ranked cases within each group are exported for raw-data follow-up.
            candidates.sort(key=lambda i: (-selected[i], metadata[i]['node_id']))
            for i in candidates[:100]:
                cases.append(dict(**selected_rows[i], category=category,
                                  feature_residual=float(dataset.residuals[i, 0]),
                                  graph_residual=float(dataset.residuals[i, 1]),
                                  spectral_residual=float(dataset.residuals[i, 2])))
    write_csv(folder / 'alert_case_samples.csv', cases,
              fields=[*selected_rows[0], 'category', 'feature_residual', 'graph_residual', 'spectral_residual'])
    labels = np.asarray([int(r['raw_label']) if str(r['raw_label']) in ('0', '1') else -1 for r in metadata])
    for day in external_days:
        chosen = np.asarray([r['day'] == day and r['split'] == 'external_test' for r in metadata]) & dataset.valid
        known = chosen & (labels >= 0)
        both = len(np.unique(labels[known])) == 2
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        for ax, policy in zip(axes[0], ('spectral_reconstruction', 'feature_spectral_gap')):
            score = channels[policy]
            for label in (0, 1):
                values = score[chosen & (labels == label)]
                if len(values):
                    ax.hist(values, bins=70, density=True, histtype='step', label=f'label {label}')
            ax.axvline(state['thresholds'][policy][str(chosen_alpha)], color='red', linestyle='--', label='normal calibration threshold')
            ax.set(title=policy, xlabel='Score (higher means more unusual)', ylabel='Within-label density'); ax.legend()
        if both:
            for policy, score in channels.items():
                fpr, tpr, _ = roc_curve(labels[known], score[known])
                precision, recall, _ = precision_recall_curve(labels[known], score[known])
                axes[1, 0].plot(fpr, tpr, label=policy)
                axes[1, 1].plot(recall, precision, label=policy)
            axes[1, 0].plot([0, 1], [0, 1], 'k--', alpha=.4)
            axes[1, 1].axhline(labels[known].mean(), color='gray', linestyle='--', label='label1 prevalence')
        axes[1, 0].set(title='Node-score ROC (not relation ROC)', xlabel='Label0 false-alert fraction', ylabel='Label1 recall')
        axes[1, 1].set(title='Node-score precision / recall', xlabel='Label1 recall', ylabel='Label1 precision')
        for ax in axes[1]:
            if both:
                ax.legend(fontsize=7)
        fig.suptitle(day + ': retrospective development evaluation; independent final test still needed')
        fig.tight_layout(); save(fig, folder / f'{day}_score_audit')
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for shift, policy, label in [(-.18, 'spectral_reconstruction', 'Original spectral residual'),
                                 (.18, selected_policy, selected_policy)]:
        group = [next(r for r in metrics if r['day'] == day and r['split'] == 'external_test'
                      and r['score_policy'] == policy and r['alpha'] == chosen_alpha) for day in external_days]
        for ax, field, title in zip(axes, ['false_alert_fraction_label0', 'recall_label1'],
                                     ['False-alert fraction among label 0', 'Recall among label 1']):
            ax.bar(np.arange(len(external_days)) + shift,
                   [100 * r[field] if r[field] is not None else np.nan for r in group], .36, label=label)
            ax.set_xticks(np.arange(len(external_days)), external_days)
            ax.set(title=title, ylabel='Percent'); ax.legend(fontsize=8)
    fig.suptitle(f'Normal calibration alpha={chosen_alpha}; development comparison, not a fresh final test')
    fig.tight_layout(); save(fig, folder / 'selected_policy_overview')
    lines = ['Normal-calibrated behavior score analysis', f'Selected policy: {selected_policy}; alpha={chosen_alpha}',
             'No model weights or external labels were fitted by this analysis.',
             'Day | Split | Policy | Nominal alpha | Label0 false alerts | Label1 recall | Label1 precision | Node-score AUC | AP']
    lines += [f"{r['day']} | {r['split']} | {r['score_policy']} | {r['alpha']} | {r['false_alert_fraction_label0']} | {r['recall_label1']} | {r['precision_label1']} | {r['node_score_roc_auc']} | {r['node_score_average_precision']}"
              for r in metrics if r['split'] in ('test', 'external_test')]
    lines += ['', *state['limits']]
    (folder / 'score_analysis.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    state['metrics'] = metrics
    dump_json(folder / 'score_analysis.json', dict(state, status='complete'))
    return dict(directory=str(folder), metrics=str(folder / 'score_policy_metrics.csv'),
                scores=str(folder / 'selected_node_scores.csv'), cases=str(folder / 'alert_case_samples.csv'),
                text=str(folder / 'score_analysis.txt')), state
