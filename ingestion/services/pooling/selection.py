import random


def split_by_label(nodes, labels):
    attack = []
    benign = []

    for n in nodes:
        if labels.get(n) == "attack":
            attack.append(n)
        else:
            benign.append(n)

    return attack, benign


def simple_diversity_select(nodes, score, k):
    # مرتب بر اساس score
    nodes_sorted = sorted(nodes, key=lambda n: score[n], reverse=True)

    selected = []

    for n in nodes_sorted:
        if len(selected) >= k:
            break

        # جلوگیری از تمرکز ساده (فاصله اندیسی)
        if all(abs(n - s) > 5 for s in selected):
            selected.append(n)

    # اگر کم شد
    for n in nodes_sorted:
        if len(selected) >= k:
            break
        if n not in selected:
            selected.append(n)

    return selected


def select_representatives(score, G, k, labels=None, attack_ratio=0.15):

    nodes = list(score.keys())

    if labels:
        attack_nodes, benign_nodes = split_by_label(nodes, labels)

        attack_k = int(k * attack_ratio)
        benign_k = k - attack_k

        selected_attack = simple_diversity_select(
            attack_nodes, score, attack_k
        )

        selected_benign = simple_diversity_select(
            benign_nodes, score, benign_k
        )

        return selected_attack + selected_benign

    else:
        return simple_diversity_select(nodes, score, k)