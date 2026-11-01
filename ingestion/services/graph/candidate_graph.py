from ingestion.pipelines.graph_pipeline import run_graph_pipeline

# Must match the GENERATION constant used by build_clustered_candidates.py.
CANDIDATE_GENERATION = "time_label_minibatch_medoids_risk_novelty_v3"


def build_clustered_day_graph(
    source_day,
    chunk_index,
    feature_fields=None,
    k=12,
    threshold=0.995,
    workers=-1,
    degree_cap=20,
):
    """Build a graph from the non-random candidate cohort for one day/chunk."""
    return run_graph_pipeline(
        source_day=source_day,
        chunk_index=chunk_index,
        candidate_generation=CANDIDATE_GENERATION,
        is_random=False,
        feature_fields=feature_fields,
        create_visualization=False,
        k=k,
        threshold=threshold,
        degree_cap=degree_cap,
        workers=workers,
    )
