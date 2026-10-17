import networkx as nx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import os


def save_graph(edges, labels, path):

    G = nx.Graph()

    for i, j, w in edges:
        G.add_edge(i, j, weight=w)

    plt.figure(figsize=(12, 10))
    pos = nx.spring_layout(G, seed=42)

    # 🎨 رنگ نودها
    node_colors = []

    for i in G.nodes():

        label_value = labels[i]

        try:
            if label_value == 0:
                node_colors.append("green")
            else:
                # شدت قرمز بر اساس مقدار
                intensity = float(label_value)
                node_colors.append((1, 1 - intensity, 1 - intensity))
        except:
            node_colors.append("gray")

    nx.draw(
        G,
        pos,
        node_color=node_colors,
        node_size=25,
        with_labels=False,
        edge_color='gray'
    )

    os.makedirs(os.path.dirname(path), exist_ok=True)

    plt.savefig(path)
    plt.close()
