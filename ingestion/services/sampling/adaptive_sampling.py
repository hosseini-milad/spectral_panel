from .stratified import stratified_sample


def adaptive_sampling(docs, ratio=0.1):

    # مرحله 1: stratified
    sampled = stratified_sample(docs, ratio)

    return sampled