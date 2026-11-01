import networkx as nx


def _normalize(values, nodes):
    """Min-max normalization with deterministic handling of constant values."""
    raw = {node: float(values.get(node, 0.0) or 0.0) for node in nodes}
    if not raw:
        return {}

    low = min(raw.values())
    high = max(raw.values())
    span = high - low
    if span <= 0:
        return {node: 0.0 for node in nodes}

    return {node: (value - low) / span for node, value in raw.items()}


def _ranked(nodes, scores):
    """Sort by descending score and then ascending node ID."""
    return sorted(nodes, key=lambda node: (-float(scores.get(node, 0.0)), int(node)))


def _class_targets(count, attack_ratio):
    attack_count = min(count, max(0, int(count * attack_ratio + 0.5)))
    return count - attack_count, attack_count


def _distance_bonus(node, distances, graph):
    """Reward graph-geodesic separation without quickly saturating the score.

    Nodes in an as-yet-unrepresented connected component receive a strong
    coverage bonus. Isolates receive no distance bonus; they are handled by a
    separate, bounded rare-node quota.
    """
    if graph.degree(node) == 0:
        return 0.0
    if node not in distances:
        return 1.0

    distance = max(0.0, float(distances[node]))
    # Unlike min(distance / 4, 1), this retains useful discrimination beyond
    # four hops: d=1 -> .25, d=3 -> .50, d=6 -> .667, d=12 -> .80.
    return distance / (distance + 3.0)


def _select_classwise(
    candidates,
    scores,
    count,
    labels,
    attack_ratio,
    G,
    isolate_budget=None,
    flow_files=None,
):
    """Select a fixed count while preserving class proportions and flow diversity.

    The score combines node importance, graph-geodesic distance from selected
    representatives, and a bonus for flow_file groups not represented yet.
    """
    candidates = list(dict.fromkeys(candidates))
    count = min(max(0, int(count)), len(candidates))
    if count == 0:
        return []

    candidate_set = set(candidates)
    normal_nodes = [node for node in candidates if labels.get(node) == 0]
    attack_nodes = [node for node in candidates if labels.get(node) == 1]
    other_nodes = [node for node in candidates if labels.get(node) not in (0, 1)]

    normal_target, attack_target = _class_targets(count, attack_ratio)
    normal_target = min(normal_target, len(normal_nodes))
    attack_target = min(attack_target, len(attack_nodes))

    remaining = count - normal_target - attack_target
    extra_normal = min(remaining, len(normal_nodes) - normal_target)
    normal_target += extra_normal
    remaining -= extra_normal
    extra_attack = min(remaining, len(attack_nodes) - attack_target)
    attack_target += extra_attack
    remaining -= extra_attack
    other_target = min(remaining, len(other_nodes))

    selected = []

    def take_ranked(pool, amount, excluded=()):
        excluded = set(excluded)
        available = [node for node in pool if node not in excluded and node in candidate_set]
        chosen = []
        occupied = set(excluded)

        while available and len(chosen) < amount:
            sources = [node for node in occupied if node in G]
            if sources:
                distances = nx.multi_source_dijkstra_path_length(G, sources, weight=None)
            else:
                distances = {}

            represented_flows = {
                flow_files.get(item)
                for item in occupied
                if flow_files and flow_files.get(item) not in (None, "")
            }
            best_node = None
            best_value = float("-inf")
            for node in available:
                distance_score = _distance_bonus(node, distances, G)
                node_score = float(scores.get(node, 0.0))
                flow_file = flow_files.get(node) if flow_files else None
                flow_bonus = (
                    1.0
                    if flow_file not in (None, "") and flow_file not in represented_flows
                    else 0.0
                )
                value = 0.60 * node_score + 0.25 * distance_score + 0.15 * flow_bonus

                if (
                    value > best_value
                    or (value == best_value and (best_node is None or int(node) < int(best_node)))
                ):
                    best_value = value
                    best_node = node

            if best_node is None:
                break

            chosen.append(best_node)
            occupied.add(best_node)
            available.remove(best_node)

        return chosen

    # Isolates can be selected through the rare-node path, but their total
    # contribution is explicitly capped rather than being driven by eigenvector
    # centrality or by an unbounded distance bonus.
    class_targets = ((normal_nodes, normal_target), (attack_nodes, attack_target))
    if isolate_budget is not None:
        class_isolate_budget = min(max(0, int(isolate_budget)), count)

        for pool, target in class_targets:
            if target <= 0:
                continue
            cap = min(target, int(class_isolate_budget * target / max(1, count) + 0.5))
            isolates = [node for node in pool if G.degree(node) == 0]
            selected.extend(take_ranked(isolates, cap, selected))

        used_isolates = sum(G.degree(node) == 0 for node in selected)
        remaining_isolate_budget = max(0, class_isolate_budget - used_isolates)
        if remaining_isolate_budget:
            remaining_isolates = [
                node for node in candidates
                if G.degree(node) == 0 and node not in selected
            ]
            selected.extend(take_ranked(remaining_isolates, remaining_isolate_budget, selected))

    for pool, target in class_targets:
        pool_label = labels.get(pool[0]) if pool else None
        current = sum(labels.get(node) == pool_label for node in selected) if pool else 0
        needed = max(0, target - current)
        selected.extend(take_ranked(pool, needed, selected))

    selected.extend(take_ranked(other_nodes, other_target, selected))

    if len(selected) < count:
        selected.extend(take_ranked(candidates, count - len(selected), selected))

    # Defensive uniqueness and count guarantee.
    unique = list(dict.fromkeys(selected))
    return unique[:count]



def _approx_diameter(component_graph):
    """Estimate a component's diameter with two BFS sweeps (good for chains)."""
    if component_graph.number_of_nodes() <= 1:
        return 0, next(iter(component_graph.nodes), None)

    start = min(component_graph.nodes, key=int)
    distances = nx.single_source_shortest_path_length(component_graph, start)
    farthest = max(distances, key=lambda node: (distances[node], -int(node)))
    distances = nx.single_source_shortest_path_length(component_graph, farthest)
    endpoint = max(distances, key=lambda node: (distances[node], -int(node)))
    return int(distances[endpoint]), farthest

def _enforce_attack_chain_coverage(
    selected,
    nodes,
    G,
    labels,
    importance,
    target_per_component=8,
    min_component_size=12,
    min_diameter=8,
    max_components=5,
    bridge_distance=2,
    max_allowed_distance=2,
    max_spread_swaps=20,
):
    """Spread Attack representatives over long attack-rich structures.

    Attack nodes may be connected through short paths containing Normal nodes.
    The auxiliary proximity graph retains the original path length as an edge
    weight, so a two-hop bridge is not incorrectly treated as one hop.

    After meeting each component's quota, representatives are redistributed
    using a lexicographic coverage objective:
      1) minimize the maximum distance from any Attack node to its nearest rep;
      2) when tied, minimize the sum of nearest-representative distances.

    Only Attack representatives are exchanged, preserving total count and class
    balance. Deterministic tie-breaking is used throughout.
    """
    selected = list(dict.fromkeys(selected))
    selected_set = set(selected)
    attack_nodes = [n for n in nodes if labels.get(n) == 1 and n in G]
    if not attack_nodes or target_per_component <= 0:
        return selected

    attack_set = set(attack_nodes)
    proximity = nx.Graph()
    proximity.add_nodes_from(attack_nodes)
    cutoff = max(1, int(bridge_distance))

    # Build attack-node proximity while preserving the real graph-hop distance.
    for source in attack_nodes:
        distances = nx.single_source_shortest_path_length(G, source, cutoff=cutoff)
        for target, distance in distances.items():
            if target in attack_set and target != source and distance <= cutoff:
                old = proximity.get_edge_data(source, target, {}).get("weight")
                if old is None or distance < old:
                    proximity.add_edge(source, target, weight=float(distance))

    eligible = []
    for component in nx.connected_components(proximity):
        if len(component) < min_component_size:
            continue
        subgraph = proximity.subgraph(component)
        if len(component) <= 1:
            continue

        start_node = min(component, key=int)
        d0 = nx.single_source_dijkstra_path_length(
            subgraph, start_node, weight="weight"
        )
        endpoint_a = max(d0, key=lambda n: (d0[n], -int(n)))
        d1 = nx.single_source_dijkstra_path_length(
            subgraph, endpoint_a, weight="weight"
        )
        diameter = float(max(d1.values(), default=0.0))
        if diameter >= min_diameter:
            eligible.append((diameter, len(component), set(component), endpoint_a))

    eligible.sort(key=lambda item: (-item[0], -item[1], min(item[2])))
    eligible = eligible[:max(0, int(max_components))]
    if not eligible:
        print(
            "[CHAIN SPREAD] No eligible attack-chain components found "
            f"(attack_nodes={len(attack_nodes)}, bridge_distance={cutoff}, "
            f"min_component_size={min_component_size}, min_diameter={min_diameter}).",
            flush=True,
        )
        return selected

    protected_components = []

    def nearest_distances(component, representatives):
        """Return each component node's shortest distance to any selected rep."""
        subgraph = proximity.subgraph(component)
        result = {}
        for rep in representatives:
            if rep not in subgraph:
                continue
            dists = nx.single_source_dijkstra_path_length(
                subgraph, rep, weight="weight"
            )
            for node, distance in dists.items():
                if node not in result or distance < result[node]:
                    result[node] = float(distance)
        return result

    def coverage_objective(component, representatives):
        distances = nearest_distances(component, representatives)
        # Unreachable nodes count as uncovered; in each eligible component,
        # connectivity should normally make this finite.
        values = [
            distances.get(node, float("inf"))
            for node in component
        ]
        max_distance = max(values, default=0.0)
        total_distance = sum(values)
        return (max_distance, total_distance), distances

    for diameter, size, component, endpoint in eligible:
        subgraph = proximity.subgraph(component)
        current = [n for n in selected if n in component]
        target_count = min(max(0, int(target_per_component)), len(component))

        # First top up components below their minimum quota.
        while len(current) < target_count:
            candidates = [n for n in component if n not in selected_set]
            if not candidates:
                break

            if current:
                distances = nearest_distances(component, current)
            else:
                distances = nx.single_source_dijkstra_path_length(
                    subgraph, endpoint, weight="weight"
                )

            candidate = max(
                candidates,
                key=lambda n: (
                    float(distances.get(n, -1.0)),
                    float(importance.get(n, 0.0)),
                    -int(n),
                ),
            )
            donors = [
                n for n in selected
                if labels.get(n) == 1
                and n not in component
                and not any(n in protected for protected in protected_components)
            ]
            if not donors:
                break

            donor = min(
                donors,
                key=lambda n: (float(importance.get(n, 0.0)), -int(n)),
            )
            selected[selected.index(donor)] = candidate
            selected_set.remove(donor)
            selected_set.add(candidate)
            current.append(candidate)

        # Spread existing representatives. Unlike the previous version, a
        # swap is not rejected merely because the maximum distance ties:
        # reduction in total nearest-representative distance is also accepted.
        swaps = 0
        while len(current) >= 2 and swaps < max(0, int(max_spread_swaps)):
            candidates = [n for n in component if n not in selected_set]
            if not candidates:
                break

            current_objective, current_distances = coverage_objective(
                component, current
            )
            farthest = max(
                candidates,
                key=lambda n: (
                    float(current_distances.get(n, -1.0)),
                    float(importance.get(n, 0.0)),
                    -int(n),
                ),
            )
            if float(current_distances.get(farthest, float("inf"))) <= float(
                max_allowed_distance
            ):
                break

            # Try all possible in-component Attack-representative donors and
            # choose the swap that most improves the coverage objective.
            best_donor = None
            best_objective = current_objective
            for donor in current:
                trial_reps = [n for n in current if n != donor] + [farthest]
                trial_objective, _ = coverage_objective(component, trial_reps)
                if trial_objective < best_objective:
                    best_objective = trial_objective
                    best_donor = donor

            if best_donor is None:
                # Farthest-point candidate cannot improve this objective with
                # a single swap. Stop rather than making an arbitrary change.
                break

            selected[selected.index(best_donor)] = farthest
            selected_set.remove(best_donor)
            selected_set.add(farthest)
            current.remove(best_donor)
            current.append(farthest)
            swaps += 1

        final_objective, final_distances = coverage_objective(component, current)
        farthest_unselected = max(
            (
                final_distances.get(n, 0.0)
                for n in component
                if n not in selected_set
            ),
            default=0.0,
        )
        print(
            f"[CHAIN SPREAD] size={len(component)} diameter~{diameter:.1f}; "
            f"selected={len(current)}; swaps={swaps}; "
            f"max_distance={final_objective[0]:.1f}; "
            f"sum_distance={final_objective[1]:.1f}; "
            f"farthest_unselected_distance={farthest_unselected:.1f}",
            flush=True,
        )
        protected_components.append(component)

    return list(dict.fromkeys(selected))

def select_representatives(
    score,
    G,
    k,
    labels=None,
    attack_ratio=0.0,
    eigenvector_scores=None,
    anomaly_scores=None,
    risk_scores=None,
    flow_files=None,
):
    """Select representatives with importance, rarity, risk, and flow coverage.

    Path A (60%): structurally important nodes, with eigenvector centrality as
    the strongest individual feature.
    Path B (40%): anomalous/rare nodes, including a bounded isolate allowance.
    Within each path, graph distance adds a 35% diversity/coverage contribution.
    """
    nodes = sorted(score, key=int)
    k = min(max(0, int(k)), len(nodes))
    if k == 0:
        return []

    labels = labels or {}
    eigenvector_scores = eigenvector_scores or {}
    anomaly_scores = anomaly_scores or {}
    risk_scores = risk_scores or {}
    flow_files = flow_files or {}

    valid_labels = [labels[node] for node in nodes if labels.get(node) in (0, 1)]
    if valid_labels:
        attack_ratio = sum(label == 1 for label in valid_labels) / len(valid_labels)
    attack_ratio = min(1.0, max(0.0, float(attack_ratio)))

    # Singleton eigenvector centrality is mathematically arbitrary for this
    # purpose (often returned as 1.0); set it to zero so isolates do not enter
    # the importance path merely because they have no neighbours.
    eigen_for_ranking = {
        node: (0.0 if G.degree(node) == 0 else float(eigenvector_scores.get(node, 0.0) or 0.0))
        for node in nodes
    }
    eigen = _normalize(eigen_for_ranking, nodes)
    combined = _normalize(score, nodes)
    anomaly = _normalize(anomaly_scores, nodes)
    risk = _normalize(risk_scores, nodes)
    degree = _normalize({node: G.degree(node) for node in nodes}, nodes)

    component_size = {}
    for component in nx.connected_components(G.subgraph(nodes)):
        size = len(component)
        for node in component:
            component_size[node] = size

    rarity = _normalize(
        {node: 1.0 / max(1, component_size.get(node, 1)) for node in nodes},
        nodes,
    )

    # Path A: centrality/importance. Eigenvector is weighted most strongly.
    importance = {
        node: (
            0.50 * eigen[node]
            + 0.20 * degree[node]
            + 0.15 * combined[node]
            + 0.15 * risk[node]
        )
        for node in nodes
    }
    important_count = min(k, int(k * 0.60 + 0.5))
    rare_count = k - important_count

    important_nodes = _select_classwise(
        candidates=nodes,
        scores=importance,
        count=important_count,
        labels=labels,
        attack_ratio=attack_ratio,
        G=G,
        flow_files=flow_files,
    )

    important_set = set(important_nodes)
    remaining_nodes = [node for node in nodes if node not in important_set]

    low_degree = _normalize(
        {node: 1.0 / (1.0 + G.degree(node)) for node in nodes},
        nodes,
    )
    rare_score = {
        node: (
            0.55 * anomaly[node]
            + 0.20 * low_degree[node]
            + 0.10 * rarity[node]
            + 0.10 * combined[node]
            + 0.15 * risk[node]
        )
        for node in nodes
    }

    # For k=200 this reserves at most 30 representatives for isolates.
    isolate_budget = min(int(rare_count * 0.375 + 0.5), rare_count)
    rare_nodes = _select_classwise(
        candidates=remaining_nodes,
        scores=rare_score,
        count=rare_count,
        labels=labels,
        attack_ratio=attack_ratio,
        G=G,
        isolate_budget=isolate_budget,
        flow_files=flow_files,
    )

    selected = list(dict.fromkeys(important_nodes + rare_nodes))
    if len(selected) < k:
        remaining = [node for node in nodes if node not in set(selected)]
        selected.extend(_ranked(remaining, importance)[: k - len(selected)])

    # Ensure long attack-only chains receive several representatives. This
    # swaps existing Attack representatives, so total count and class balance
    # are preserved. Tune thresholds only after comparing evaluation metrics.
    selected = _enforce_attack_chain_coverage(
        selected=selected[:k],
        nodes=nodes,
        G=G,
        labels=labels,
        importance=importance,
        target_per_component=8,
        min_component_size=12,
        min_diameter=8,
        max_components=5,
        max_allowed_distance=2,
        max_spread_swaps=12,
    )

    return selected[:k]
