from ingestion.pipelines.graph_pipeline import run_graph_pipeline


CANDIDATE_GENERATION = "time_label_minibatch_medoids_with_tails_v1"


def build_clustered_day_graph(source_day, k=12, threshold=0.999, workers=-1, degree_cap=None):
    """Build a day-level graph using the selected non-random candidate cohort."""
    return run_graph_pipeline(
        source_day=source_day,
        candidate_generation=CANDIDATE_GENERATION,
        is_random=False,
        create_visualization=False,
        k=k,
        threshold=threshold,
        degree_cap=degree_cap,
        workers=workers,
    )
