
def _normalize(values, nodes):
    raw = {node: float(values.get(node, 0.0)) for node in nodes}
    if not raw:
        return {}

    low = min(raw.values())
    high = max(raw.values())
    span = high - low

    if span <= 0:
        return {node: 0.0 for node in nodes}

    return {
        node: (value - low) / span
        for node, value in raw.items()
    }


def select_representatives(
    score,
    G,
    k,
    labels=None,
    attack_ratio=0.0,
    eigenvector_scores=None,
):
    """Greedy selection using combined score, eigenvector centrality,
    and fast local structural diversity.
    """
    nodes = list(score)
    k = min(max(0, int(k)), len(nodes))

    if k == 0:
        return []

    eigenvector_scores = eigenvector_scores or {}
    combined = _normalize(score, nodes)
    eigen = _normalize(eigenvector_scores, nodes)

    # Explicitly retain eigenvector centrality in representative ranking.
    importance = {
        node: 0.70 * combined[node] + 0.30 * eigen.get(node, 0.0)
        for node in nodes
    }

    if labels is None:
        return _select_greedy(nodes, importance, G, k)

    attack_nodes = [n for n in nodes if labels.get(n) == 1]
    normal_nodes = [n for n in nodes if labels.get(n) == 0]
    other_nodes = [n for n in nodes if labels.get(n) not in (0, 1)]

    attack_count = min(
        len(attack_nodes),
        max(1 if attack_nodes else 0, int(k * attack_ratio + 0.5)),
    )
    normal_count = min(len(normal_nodes), k - attack_count)

    # Reallocate unavailable class slots.
    attack_count = min(len(attack_nodes), k - normal_count)
    selected = _select_greedy(
        attack_nodes, importance, G, attack_count
    )
    selected.extend(
        _select_greedy(normal_nodes, importance, G, normal_count)
    )

    # Preserve the requested total if labels contain unclassified nodes.
    remaining = k - len(selected)
    if remaining > 0:
        already = set(selected)
        remaining_nodes = [
            n for n in nodes if n not in already
        ]
        selected.extend(
            _select_greedy(remaining_nodes, importance, G, remaining)
        )

    return selected[:k]


def _select_greedy(nodes, importance, G, count):
    if not nodes or count <= 0:
        return []

    count = min(count, len(nodes))
    node_set = set(nodes)

    # Deterministic tie-breaking.
    first = max(
        nodes,
        key=lambda n: (importance.get(n, 0.0), -int(n)),
    )
    selected = [first]
    selected_set = {first}

    # Nodes adjacent to an already selected representative.
    covered = set(G.neighbors(first)) & node_set

    while len(selected) < count:
        best_node = None
        best_value = float("-inf")

        for node in nodes:
            if node in selected_set:
                continue

            # Prefer nodes not directly adjacent to existing representatives.
            diversity = 0.0 if node in covered else 1.0
            value = (
                0.75 * importance.get(node, 0.0)
                + 0.25 * diversity
            )

            if (
                value > best_value
                or (
                    value == best_value
                    and (
                        best_node is None
                        or int(node) < int(best_node)
                    )
                )
            ):
                best_value = value
                best_node = node

        if best_node is None:
            break

        selected.append(best_node)
        selected_set.add(best_node)
        covered.update(set(G.neighbors(best_node)) & node_set)

    return selected
