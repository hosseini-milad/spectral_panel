LAYER-1 COMPLETION PATCH
========================

Scope
-----
This patch completes the layer-1 component records with profiles computed from
ALL nodes in each connected component, while preserving a separate profile of
the selected representatives. It also adds a read-only structural audit command.

Files to replace
----------------
1. ingestion/models/graph_component.py
2. ingestion/pipelines/graph_pipeline.py
3. ingestion/pipelines/pooling_pipeline.py
4. ingestion/management/commands/build_day_representatives.py

New file
--------
5. ingestion/management/commands/evaluate_layer1_components.py

Important behavior
------------------
- `GraphComponent.node_feature_profile` is computed from all nodes in the
  component using the graph's stored feature matrix and feature_fields.
- `representative_feature_profile` is computed separately from selected reps.
- Categorical profiles are read from raw `security_data`, not normalized
  sampled values, because normalization encodes categorical strings.
- `behavioral_profile` stores prevalence of approved binary protocol/flag
  fields.
- Legacy fields `mean_features`, `feature_std`, and
  `feature_observation_counts` remain representative-only for compatibility.
- Louvain community count and connected-component count are logged separately.
- `threat_intel_score` is excluded from graph feature construction and from
  the IsolationForest selection feature list. Existing graphs must therefore
  be rebuilt to apply the new feature schema.

Recommended execution
---------------------
After backing up the current graph metadata, representatives, and components:

1) Rebuild graph (this intentionally deletes old reps/components when --force
   is supplied):
   python manage.py build_day_representatives --day 2026-06-21 --chunk-index 0 --stage graph --force

2) Rebuild layer-1 components and representatives:
   python manage.py build_day_representatives --day 2026-06-21 --chunk-index 0 --stage reps --force

3) Verify integrity:
   python manage.py verify_graph_components --source-file clustered-day-2026-06-21-chunk-0

4) Generate read-only layer-1 structure report:
   python manage.py evaluate_layer1_components --source-file clustered-day-2026-06-21-chunk-0

Output
------
files/evaluation/clustered-day-2026-06-21-chunk-0/layer1_component_structure/
  clustered-day-2026-06-21-chunk-0_layer1_structure.json
  clustered-day-2026-06-21-chunk-0_layer1_structure.txt

The audit command does not modify MongoDB.

Important limitation
--------------------
The existing representative-selection function still has label-aware class
allocation and attack-chain coverage logic. This patch does NOT silently alter
that selection policy. If the project requirement is strictly unsupervised
representative selection as well as unsupervised graph construction, that
should be a separate explicit change to representative.py and the candidate
sampling strategy.
