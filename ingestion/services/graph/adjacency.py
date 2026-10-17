import numpy as np


def build_adjacency(n, edges):

    A = np.zeros((n, n))

    for i, j, w in edges:
        A[i][j] = w
        A[j][i] = w

    return A