import networkx as nx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import os


def save_representative_graph(
        edges,
        representatives,
        path
):

    G = nx.Graph()


    for e in edges:

        G.add_edge(
            int(e["source"]),
            int(e["target"]),
            weight=float(e["weight"])
        )


    rep_nodes = [
        r["node_index"]
        for r in representatives
    ]


    pos = nx.spring_layout(
        G,
        seed=42
    )


    plt.figure(
        figsize=(12,10)
    )


    # کل گراف
    nx.draw_networkx_nodes(
        G,
        pos,
        node_size=20
    )


    nx.draw_networkx_edges(
        G,
        pos,
        alpha=0.25
    )

    attack_nodes = []

    normal_nodes = []


    for r in representatives:
        if r.get("label") != 0:

            attack_nodes.append(
                r["node_index"]
            )

        else:

            normal_nodes.append(
                r["node_index"]
            )

    # نماینده ها با حاشیه مشکی
    nx.draw_networkx_nodes(
        G,
        pos,
        nodelist=normal_nodes,
        node_size=180,
        edgecolors="green",
        linewidths=2
    )
    nx.draw_networkx_nodes(
        G,
        pos,
        nodelist=attack_nodes,
        node_size=200,
        edgecolors="red",
        linewidths=2
    )


    directory = os.path.dirname(path)

    os.makedirs(
        directory,
        exist_ok=True
    )


    plt.savefig(
        path,
        dpi=300,
        bbox_inches="tight"
    )


    plt.close()
