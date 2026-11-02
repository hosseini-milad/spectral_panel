# Daily component hierarchy: two commands

Build the daily L2 graph from **all** L1 chunk components, including components
without representatives and singleton components:

```console
python -u manage.py build_hierarchy_graph --day 2026-06-21 --force
```

This command persists a new immutable graph/Meta-component version and publishes
it only after source integrity checks. It does not render reports. Old runs and
legacy database collections are retained. `--force` creates a new version, not
a destructive replacement. Construction parameters remain `--threshold`,
`--neighbors`, `--degree-cap`.

Evaluate the saved version and render statistical and schematic evidence:

```console
python -u manage.py evaluate_hierarchy_graph --day 2026-06-21
```

Default: active complete daily run. Optional `--run-id ID` selects a historical
complete version. This does not rebuild graph edges, rerun representative
selection, modify original graph records or change the active graph pointer.
Every evaluation produces a separate report ID. It checks persisted node/edge
integrity, exact connected partition, child references, candidate uniqueness,
degree cap and conservation metrics. Chaining, within-group similarity,
compression, cross-chunk coverage and limitations appear in the metric table.
These metrics do not establish attack-detection accuracy, rare-behavior or
spectral preservation.

Legacy completed component runs can also be evaluated. Saved diagnostic summaries
are used when available. For older runs without them, pair diagnostics are
recomputed **from saved component descriptors**, without rebuilding the graph or
requiring current upstream records. This fallback can take time for large days;
progress is logged. Source snapshot mutation during reporting fails publication.
Graph/data remain intact if evaluation or rendering fails.

Reports:
`document/hierarchy/layer2/<day>/whole-day/hierarchy-components-day-<day>-layer-2/runs/<report-id>/`

* `evaluation.json/txt`, `evaluation_metrics.csv/png/svg`: defined metrics,
  coverage, conservation, graph statistics and limitations.
* `meta_components.png/svg`: ALL Meta-components as markers; size reflects number
  of children, color reflects number of source chunks. Grid layout is schematic;
  no inter-meta edge is inferred.
* `meta_component_schematic.png/svg`: chunk -> input component -> Meta-component
  lineage for the largest 12 groups, up to 4 child markers each. All memberships
  remain in JSON/CSV, including singletons.
* `overview.png/svg`, `component_graph.png/svg`: distribution/heatmap dashboard
  and component-similarity graph.
* `lineage.json`, `component_membership.csv`, `chunk_meta_matrix.csv`: complete
  exact memberships and chunk counts. No HTML or lineage-page files.

MongoDB `component_hierarchy_evaluations` records evaluation IDs, source run,
snapshot digest, success/failure and output paths. A new build also retains its
diagnostic summary in `component_hierarchy_runs.evaluation_snapshot`.

Removed old management actions: build_hierarchy_graph_hybrid,
build_hierarchy_graph_hybrid_v2, build_representative_hierarchy_graph,
build_hierarchy_representatives, visualize_hierarchy_representatives,
evaluate_hierarchy_representatives, evaluate_component_allocation,
diagnose_hierarchy_graph. They operated on the independent representative-based
hyper_graph collections and are not part of the current component workflow.

Spectral analysis and message passing remain separate later stages. A second
structural aggregation within the same day is not a weekly temporal layer.
