import numpy as np


def build_mutual_knn(sim_matrix, k=10, threshold=0.7):

    n = sim_matrix.shape[0]

    neighbors = []

    for i in range(n):
        idx = np.argsort(sim_matrix[i])[::-1][1:k+1]
        neighbors.append(set(idx))

    edges = []

    for i in range(n):
        for j in neighbors[i]:
            if i in neighbors[j] and sim_matrix[i][j] >= threshold:
                edges.append((i, j, sim_matrix[i][j]))

    return edges