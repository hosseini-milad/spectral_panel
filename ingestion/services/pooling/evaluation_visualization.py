"""Visualization of saved representative-selection evaluation results.

Only consumes the evaluation report dict; does not access or modify MongoDB.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _section(data, key):
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _pct(value, digits=1):
    return "N/A" if value is None else f"{100 * float(value):.{digits}f}%"


def _num(value, digits=2):
    return "N/A" if value is None else f"{float(value):,.{digits}f}"


def _fraction_barh(ax, labels, values, title):
    valid = [0.0 if v is None else float(v) for v in values]
    positions = range(len(labels))
    bars = ax.barh(positions, valid)
    ax.set_yticks(list(positions), labels)
    ax.set_xlim(0, 1.13)
    ax.set_title(title)
    ax.invert_yaxis()
    for bar, value in zip(bars, values):
        ax.text(
            min(bar.get_width() + 0.02, 1.01),
            bar.get_y() + bar.get_height() / 2,
            _pct(value),
            va="center",
            fontsize=9,
        )
    ax.grid(axis="x", alpha=0.15)


def save_evaluation_dashboard(report, output_path):
    graph = _section(report, "graph")
    reps = _section(report, "representatives")
    balance = _section(report, "class_balance")
    homophily = _section(report, "edge_homophily")
    coverage = _section(report, "coverage")
    proxy = _section(report, "nearest_representative_proxy")
    eigen = _section(report, "eigenvector")

    fig, axes = plt.subplots(2, 3, figsize=(19, 11), constrained_layout=True)
    ax = axes[0, 0]
    ax.axis("off")
    ax.text(0, 1, "GRAPH & REPRESENTATIVES\n\n" + "\n".join([
        f"Nodes: {graph.get('nodes', 'N/A'):,}" if isinstance(graph.get('nodes'), int) else "Nodes: N/A",
        f"Edges: {graph.get('edges', 'N/A'):,}" if isinstance(graph.get('edges'), int) else "Edges: N/A",
        f"Components: {graph.get('components', 'N/A')}",
        f"Isolates: {graph.get('isolates', 'N/A')}",
        f"Representatives: {reps.get('count', 'N/A')}",
        f"Selection ratio: {_pct(reps.get('ratio'))}",
        f"Normal reps: {reps.get('normal', 'N/A')}",
        f"Attack reps: {reps.get('attack', 'N/A')}",
    ]), transform=ax.transAxes, va="top", family="monospace", fontsize=12)

    _fraction_barh(axes[0, 1],
        ["Reachable", "1-hop", "2-hop", "Component coverage"],
        [coverage.get(k) for k in (
            "reachable_fraction", "one_hop_fraction", "two_hop_fraction",
            "component_coverage_fraction")], "Graph coverage")

    _fraction_barh(axes[0, 2],
        ["Accuracy", "Balanced accuracy", "Macro-F1", "Weighted-F1"],
        [proxy.get(k) for k in (
            "accuracy", "balanced_accuracy", "macro_f1", "weighted_f1")],
        "Nearest-representative label proxy")

    ax = axes[1, 0]
    total_n = (balance.get("all_normal") or 0) + (balance.get("all_attack") or 0)
    total_r = (reps.get("normal") or 0) + (reps.get("attack") or 0)
    normal_share = [
        (balance.get("all_normal") or 0) / total_n if total_n else 0,
        (reps.get("normal") or 0) / total_r if total_r else 0,
    ]
    attack_share = [1 - n if (total_n if i == 0 else total_r) else 0
                    for i, n in enumerate(normal_share)]
    ax.barh([0, 1], normal_share, label="Normal")
    ax.barh([0, 1], attack_share, left=normal_share, label="Attack")
    ax.set_yticks([0, 1], ["All nodes", "Selected reps"])
    ax.set_xlim(0, 1)
    ax.invert_yaxis()
    ax.set_title("Class distribution (proportions)")
    ax.legend(loc="lower right")

    ax = axes[1, 1]
    ax.axis("off")
    lines = [
        "STRUCTURAL QUALITY", "",
        f"Cross-label edges: {homophily.get('cross_label_edges', 'N/A')}",
        f"Cross-label edge fraction: {_pct(homophily.get('cross_label_edge_fraction'), 2)}",
        f"Mean hops to nearest rep: {_num(coverage.get('mean_hops_reachable'))}",
        f"Max hops to nearest rep: {coverage.get('max_hops_reachable', 'N/A')}",
        f"Components represented: {coverage.get('represented_components', 'N/A')}"
        f"/{coverage.get('total_components', 'N/A')}",
        "", "LABEL PROXY NOTE", "F1 is not downstream model F1.",
    ]
    ax.text(0, 1, "\n".join(lines), transform=ax.transAxes,
            va="top", family="monospace", fontsize=11)

    eigen_keys = (
        "top_decile_recall", "top_decile_precision", "mean_selected_component_percentile"
    )
    if eigen and any(eigen.get(key) is not None for key in eigen_keys):
        _fraction_barh(axes[1, 2],
            ["Top-decile recall", "Top-decile precision", "Selected percentile"],
            [eigen.get(key) for key in eigen_keys], "Eigenvector centrality audit")
    else:
        axes[1, 2].axis("off")
        axes[1, 2].text(0.5, 0.5, "Eigenvector audit skipped\n(use without --skip-eigen)",
                        ha="center", va="center", transform=axes[1, 2].transAxes)

    fig.suptitle("Representative Selection Evaluation | " + str(report.get("source_file", "")),
                 fontsize=16)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=160, bbox_inches="tight")
    plt.close(fig)


def save_evaluation_summary_text(report, output_path):
    graph, reps = _section(report, "graph"), _section(report, "representatives")
    coverage = _section(report, "coverage")
    homophily = _section(report, "edge_homophily")
    proxy = _section(report, "nearest_representative_proxy")
    eigen = _section(report, "eigenvector")
    lines = [
        "REPRESENTATIVE SELECTION EVALUATION", "=" * 45,
        f"Source: {report.get('source_file', 'N/A')}",
        f"Graph: {graph.get('nodes', 'N/A')} nodes, {graph.get('edges', 'N/A')} edges",
        f"Components: {graph.get('components', 'N/A')} | Isolates: {graph.get('isolates', 'N/A')}",
        f"Representatives: {reps.get('count', 'N/A')} ({_pct(reps.get('ratio'))})",
        f"Normal: {reps.get('normal', 'N/A')} | Attack: {reps.get('attack', 'N/A')}",
        "", "COVERAGE", 
        f"Reachable: {_pct(coverage.get('reachable_fraction'))}",
        f"1-hop: {_pct(coverage.get('one_hop_fraction'))}",
        f"2-hop: {_pct(coverage.get('two_hop_fraction'))}",
        f"Component coverage: {_pct(coverage.get('component_coverage_fraction'))}",
        f"Mean hops: {_num(coverage.get('mean_hops_reachable'))}",
        f"Max hops: {coverage.get('max_hops_reachable', 'N/A')}",
        "", "STRUCTURE", 
        f"Cross-label edge fraction: {_pct(homophily.get('cross_label_edge_fraction'), 2)}",
        "", "NEAREST-REPRESENTATIVE LABEL PROXY",
        f"Macro-F1: {_pct(proxy.get('macro_f1'), 2)}",
        f"Weighted-F1: {_pct(proxy.get('weighted_f1'), 2)}",
        f"Accuracy: {_pct(proxy.get('accuracy'), 2)}",
        "This proxy is NOT the F1 score of a downstream classifier.",
        "", "EIGENVECTOR AUDIT",
        f"Top-decile recall: {_pct(eigen.get('top_decile_recall'), 2)}",
        f"Top-decile precision: {_pct(eigen.get('top_decile_precision'), 2)}",
        f"Mean selected component percentile: {_pct(eigen.get('mean_selected_component_percentile'), 2)}",
        "", "Interpret metrics jointly; high proxy F1 does not guarantee representative coverage.",
    ]
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
