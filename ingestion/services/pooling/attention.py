import numpy as np


def calculate_attention(centrality):

    nodes = list(centrality.keys())

    values = np.array(
        [
            centrality[n]
            for n in nodes
        ]
    )


    exp_values = np.exp(values)

    attention = exp_values / (
        np.sum(exp_values)
    )


    return {
        node:float(weight)
        for node,weight
        in zip(nodes,attention)
    }