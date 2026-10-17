import networkx as nx


def select_representatives(score, G, k, labels=None, attack_ratio=0.0):
    """Choose high-scoring and structurally diverse graph nodes by class."""
    nodes = list(score)
    k = min(max(0, int(k)), len(nodes))
    if k == 0:
        return []

    if labels is None:
        return _select_diverse(nodes, score, G, k)

    attack_nodes = [node for node in nodes if labels.get(node) == 1]
    normal_nodes = [node for node in nodes if labels.get(node) == 0]
    attack_count = min(
        len(attack_nodes),
        max(1 if attack_nodes else 0, int(k * attack_ratio + 0.5)),
    )
    normal_count = min(len(normal_nodes), k - attack_count)

    # Reallocate unavailable slots while keeping the requested total when
    # the graph does not contain enough nodes from one class.
    attack_count = min(len(attack_nodes), k - normal_count)
    selected = _select_diverse(attack_nodes, score, G, attack_count)
    selected.extend(
        _select_diverse(normal_nodes, score, G, normal_count)
    )
    return selected


def _select_diverse(nodes, score, G, count):
    if not nodes or count <= 0:
        return []

    count = min(count, len(nodes))
    first = max(nodes, key=lambda node: (score.get(node, 0.0), -int(node)))
    selected = [first]

    values = [float(score.get(node, 0.0)) for node in nodes]
    min_score, max_score = min(values), max(values)
    score_range = max_score - min_score
    unreachable_distance = G.number_of_nodes() + 1
    min_distances = {node: unreachable_distance for node in nodes}

    def update_distances(source):
        for node, distance in nx.single_source_shortest_path_length(G, source).items():
            if node in min_distances:
                min_distances[node] = min(min_distances[node], distance)

    update_distances(first)

    while len(selected) < count:
        candidates = [node for node in nodes if node not in selected]

        def combined_score(node):
            importance = (
                (float(score.get(node, 0.0)) - min_score) / score_range
                if score_range > 0 else 0.0
            )
            diversity = min_distances[node] / unreachable_distance
            return 0.5 * importance + 0.5 * diversity

        next_node = max(candidates, key=lambda node: (combined_score(node), -int(node)))
        selected.append(next_node)
        update_distances(next_node)

    return selected
