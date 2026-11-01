"""Evaluation definitions distinguish coverage, compression and unmeasured preservation."""
import math
from collections import Counter


def pooled_moments(profiles):
    count = sum(profile['count'] for profile in profiles)
    if not count:
        return 0, None, None
    mean = sum(profile['count'] * profile['mean'] for profile in profiles) / count
    variance = sum(profile['count'] * (profile['std'] ** 2 + (profile['mean'] - mean) ** 2)
                   for profile in profiles) / count
    return count, mean, math.sqrt(max(0., variance))


def build_metrics_table(evaluation, nodes):
    metas = evaluation['meta_components']
    n, m = len(nodes), len(metas)
    multi = sum(meta['component_count'] > 1 for meta in metas)
    single = sum(meta['component_count'] == 1 for meta in metas)
    chaining = sum(meta['chaining_warning'] for meta in metas)
    assigned = [index for meta in metas for index in meta['node_indices']]
    rows = []

    def row(key, label, value, unit, definition, assessment='Descriptive'):
        rows.append(dict(metric=key, label=label, value=value, unit=unit,
                         definition=definition, assessment=assessment))

    def percent(numerator, denominator):
        return 100 * numerator / denominator if denominator else None

    row('chunk_count', 'Source chunks', evaluation['chunk_count'], 'count', 'Number of included layer-1 chunk graphs.')
    row('input_components', 'Input layer-1 components', n, 'count', 'All valid input components, including those without representatives.')
    row('candidate_nodes', 'Candidate nodes traced', evaluation['candidate_node_count'], 'count', 'Member nodes of layer-1 graphs; excludes unsampled raw flows.')
    row('meta_components', 'Output Meta-components', m, 'count', 'Connected components in the sparse layer-2 similarity graph.')
    row('compression_percent', 'Reduction in analysis units', percent(n - m, n), '%', '100 * (input components - output metas) / input components. This is not an accuracy measure.')
    row('compression_factor', 'Input/output unit ratio', n / m if m else None, 'ratio', 'Input component count divided by output meta count.')
    row('multi_member_metas', 'Multi-member Meta-components', multi, 'count', 'Meta-components with at least two child components.')
    row('singleton_meta_components', 'Singleton Meta-components', single, 'count', 'Meta-components containing exactly one input component.')
    row('singleton_meta_percent', 'Singleton share of output metas', percent(single, m), '%', '100 * singleton metas / all output metas; denominator is metas.')
    row('unmerged_input_percent', 'Input components left unmerged', percent(single, n), '%', '100 * singleton metas / input components; denominator is input components.')
    row('cross_chunk_meta_components', 'Cross-chunk Meta-components', evaluation['cross_chunk_meta_components'], 'count', 'Metas whose children originate from at least two different chunks.')
    row('cross_chunk_multi_percent', 'Cross-chunk share of multi-member metas', percent(evaluation['cross_chunk_meta_components'], multi), '%', '100 * cross-chunk metas / multi-member metas.')
    cross_children = sum(meta['component_count'] for meta in metas if len(meta['source_chunks']) > 1)
    row('cross_chunk_input_percent', 'Inputs in cross-chunk metas', percent(cross_children, n), '%', '100 * child components in cross-chunk metas / all input components.')
    row('largest_meta_input_percent', 'Largest meta share of input components', percent(max((meta['component_count'] for meta in metas), default=0), n), '%', 'Largest child-component count divided by total input component count.')
    row('edge_count', 'Retained similarity edges', evaluation['edge_count'], 'count', 'Edges retained after threshold, mutual-kNN, duplicate-ring and degree-cap rules.')
    row('graph_density_percent', 'Component-graph density', 100 * evaluation['density'], '%', '100 * retained edges / all possible unordered input-component pairs.')
    row('average_degree', 'Average component-graph degree', 2 * evaluation['edge_count'] / n if n else None, 'degree', '2 * retained edges / input component count.')
    row('max_degree', 'Maximum degree', evaluation['max_degree'], 'degree', 'Maximum observed degree; must not exceed configured degree cap.',
        'PASS' if evaluation['max_degree'] <= evaluation['parameters']['degree_cap'] else 'FAIL')
    row('qualifying_pair_percent', 'All pairs above similarity threshold', percent(evaluation['diagnostics']['threshold_qualifying_pairs'], evaluation['diagnostics']['comparable_pairs']), '%', 'Qualifying pairs / comparable pairs BEFORE sparse edge selection.')
    row('chaining_meta_components', 'Metas with below-threshold internal pairs', chaining, 'count', 'Connectivity can join indirectly related children. Diagnostic, not automatic rejection.', 'Diagnostic')
    row('chaining_multi_percent', 'Chaining share of multi-member metas', percent(chaining, multi), '%', '100 * metas with below-threshold internal pairs / multi-member metas.', 'Diagnostic')
    covered = set(assigned) & set(range(n))
    row('component_coverage_percent', 'Input component membership coverage', percent(len(covered), n), '%', 'Unique assigned valid input indices / all input components.', 'PASS' if len(covered) == n else 'FAIL')
    partition_ok = len(assigned) == n and set(assigned) == set(range(n))
    row('partition_exactly_once', 'Each input assigned exactly once', partition_ok, 'boolean', 'No duplicated, missing or out-of-range component memberships.', 'PASS' if partition_ok else 'FAIL')
    retained_members = sum(meta['member_node_count'] for meta in metas)
    candidate_count = evaluation['candidate_node_count']
    row('candidate_coverage_percent', 'Candidate-member count coverage', percent(retained_members, candidate_count), '%',
        'Sum of meta candidate-member counts / input candidate count; component membership uniqueness is checked separately.',
        'PASS' if retained_members == candidate_count and partition_ok else 'FAIL')
    row('categorical_coverage_percent', 'Inputs with categorical data', percent(evaluation['components_with_categorical_data'], n), '%', 'Components with sufficiently observed raw categorical descriptors / all inputs.')
    row('missing_raw_members', 'Missing original member records', evaluation['missing_raw_member_count'], 'count', 'Missing raw records affect categorical availability; sampled membership is audited independently.')

    # Conservation of pooled moments is an aggregation check, not proof that
    # distributions, rare behavior or graph topology have been preserved.
    errors, counts_ok = [], True
    for field in sorted({field for node in nodes for field in node['numeric']}):
        before = pooled_moments([node['numeric'][field] for node in nodes if field in node['numeric']])
        after = pooled_moments([meta['numeric'][field] for meta in metas if field in meta['numeric']])
        counts_ok = counts_ok and before[0] == after[0]
        if before[0] and after[0]:
            errors.extend([abs(before[1] - after[1]), abs(before[2] - after[2])])
    error = max(errors) if errors else None
    row('numeric_moment_max_abs_error', 'Pooled numeric mean/std maximum error', error, 'absolute',
        'Maximum absolute difference of population means/stds before vs after weighted aggregation, over normalized numeric fields. Does not test full distributions.',
        'FAIL' if not counts_ok else ('Unavailable' if error is None else ('PASS' if error <= 1e-10 else 'FAIL')))
    categories_ok, observed = True, 0
    for field in sorted({field for node in nodes for field in node['categorical']}):
        before, after = Counter(), Counter()
        for node in nodes:
            before.update(node['categorical'].get(field, {}))
        for meta in metas:
            after.update(meta['categorical'].get(field, {}))
        categories_ok = categories_ok and before == after
        observed += sum(before.values())
    row('categorical_counts_conserved', 'Categorical counts conserved', categories_ok if observed else None, 'boolean',
        'Exact equality of aggregated category counts; does not establish that every meta is behaviorally homogeneous.',
        ('PASS' if categories_ok else 'FAIL') if observed else 'Unavailable')
    row('coarsened_edge_preservation', 'Inter-meta edge-weight preservation', None, 'N/A',
        'Not measured: a coarsened graph with aggregated inter-meta edge weights is not yet constructed.', 'Not measured')
    row('spectral_preservation', 'Spectral structure preservation', None, 'N/A',
        'Not measured: no original/coarsened Laplacian comparison is implemented.', 'Not measured')
    row('rare_behavior_preservation', 'Rare-behavior preservation', None, 'N/A',
        'Not measured: requires a defined rare-behavior reference and a comparison protocol.', 'Not measured')
    return rows


def format_value(value):
    if value is None:
        return 'not measured'
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if isinstance(value, int):
        return f'{value:,}'
    if isinstance(value, float):
        return f'{value:.6g}'
    return str(value)


def format_metrics_table(rows):
    lines = [f"{'Metric':<44} | {'Value':>13} | {'Unit':<8} | Assessment", '-' * 90]
    for row in rows:
        lines.append(f"{row['label']:<44} | {format_value(row['value']):>13} | {row['unit']:<8} | {row['assessment']}")
    return '\n'.join(lines)
