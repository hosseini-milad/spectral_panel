import numpy as np


def aggregate_features(
        node,
        adjacency,
        features
):
    features = np.array(
        features,
        dtype=float
    )
    neighbors = np.where(
        adjacency[node] > 0
    )[0]


    if len(neighbors)==0:
        return features[node]


    weights = np.array(
        adjacency[node][neighbors],
        dtype=float
    )


    result = np.average(
        features[neighbors],
        axis=0,
        weights=weights
    )


    return result