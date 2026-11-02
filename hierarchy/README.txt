Component-based layer-2 hierarchy
=================================

After all layer-1 day chunks finish, build the saved daily graph:
python -u manage.py build_hierarchy_graph --day 2026-06-21 --force

Then evaluate that saved graph and draw all schematics:
python -u manage.py evaluate_hierarchy_graph --day 2026-06-21

Full command contract: hierarchy/README.md. The build CLI does not render reports.

The default command now uses graph_components (layer=1), not graph_representatives.
Every valid component participates, including isolates and components without
representatives. It audits each chunk's actual graph partition and traces every
candidate member to its sampled record and original ID. Incomplete existing chunk graphs, stale revisions, overlapping memberships, and
missing sampled records stop construction. Missing day chunks are allowed by
default; only available graphs are included. --require-complete-day optionally
rejects missing chunks. When raw counts and normalization chunk size are available, the
expected trailing chunk is checked too. Otherwise trailing completeness is marked
unverified in the report. Input source data is read-only.

Descriptions and similarity
---------------------------
Descriptors are recomputed from ALL member candidates, never from representative
means. Numeric features use an explicit allowlist of normalized behavioral flow
measurements (no labels, threat scores, IPs, raw port identifiers, IDs or chunk
indices). Seven quantiles approximate each numeric distribution. Integral
quantile differences use shared candidate-population scales for this day;
scales are estimated using candidate-count-weighted quantile grids. This is a
quantile approximation, not an exact empirical Wasserstein calculation.

Raw categorical distributions come from security_data via original_id. Behavior
uses binary flag prevalence. At least 80% observation coverage is needed for a
field and at least three numeric fields must be shared for a comparable pair.
Missing categorical/behavior families are omitted and available family weights
renormalized; missing data does not count as perfect categorical similarity.
Family weights: numeric=0.60, categorical=0.25, behavior=0.15. Graph structural
statistics and component size are descriptive, not inputs to the similarity.
Categorical fields with more than 128 distinct values are excluded from similarity
and explicitly reported, bounding the distribution-comparison memory footprint.

Default graph parameters: threshold=0.85, neighbors=8, degree-cap=12.
All unordered pairs are examined using one-to-many vectorized comparisons without
allocating a full square similarity matrix. Edges require mutual top-k selection
and the minimum similarity threshold. Exact metric-descriptor duplicates also
receive a sparse ring to prevent deterministic kNN ties from isolating later
nodes. The final degree cap applies to every edge, including ring edges.
The edge bound is floor(component_count * degree_cap / 2).

Meta-components are connected components of this sparse graph, including
singletons. Membership preserves original layer-1 component IDs and graph
revisions. Aggregate means/stds are weighted by observed member counts; quantiles
are not averaged and presented as pooled quantiles. Reports explicitly measure
minimum/mean all-pair similarity inside each meta and warn about chaining below
the edge threshold. Uncomparable internal pairs are counted separately.
Thresholds, weights and k are experimental defaults, not validated detection
parameters. Chunk order is processing order, not proof of causal/time adjacency.

Storage and versioning
----------------------
The new source key is hierarchy-components-day-YYYY-MM-DD-layer-2.
Collections:
  component_hierarchy_graphs: active complete run pointer per day/source key
  component_hierarchy_runs: version metadata, parameters, source fingerprints,
                           completion/failure, and report paths
  component_hierarchy_nodes: immutable component descriptors and member lineage
  component_hierarchy_edges: sparse similarities with available-family evidence
  meta_components: immutable per-run Meta-component membership and profiles

--force creates a NEW run and retains prior runs and reports. The active pointer
changes only after database writes succeed, source
fingerprints still match, and no concurrent build changed the active pointer.
A failed run is recorded as failed and leaves the previous active run intact.
Layer-1 graphs/components and legacy hyper_graph_metadata/hyper_graph_edges are
not overwritten. Compare active_run_id when querying per-run collections.

Outputs
-------
document/hierarchy/layer2/YYYY-MM-DD/whole-day/
  hierarchy-components-day-YYYY-MM-DD-layer-2/runs/<report-id>/
    evaluation.json / evaluation.txt
    lineage.json                  complete IDs, descriptors and memberships
    evaluation_metrics.csv       explicit metric values, units, definitions, assessments
    evaluation_metrics.png / evaluation_metrics.svg
    overview.png / overview.svg
    component_graph.png / component_graph.svg
    meta_components.png / meta_components.svg       ALL Meta-components
    meta_component_schematic.png / .svg            chunk/component/meta lineage
    component_membership.csv
    chunk_meta_matrix.csv

HTML and lineage_page images are not generated in this reporting phase. Prior
run files are retained. Complete memberships remain in lineage.json and CSV.
The overview includes a compact table; the console, evaluation.txt, evaluation.json,
and evaluation_metrics.csv contain the full metric table. Observed compression,
singleton rates (with explicit input/output denominators), cross-chunk grouping,
sparsity, coverage and chaining are distinguished from aggregation conservation.
Pooled numeric moments and categorical counts are checked for conservation.
Inter-meta edge, spectral and rare-behavior preservation are explicitly marked
NOT MEASURED: these are not implied by complete membership coverage.
The dashboard bounds the matrix to 30 metas plus an explicitly aggregated Other
column. The full chunk/meta matrix remains in CSV. Candidate-node coverage refers
to layer-1 graph inputs, not unsampled raw flow records.

Removed legacy commands
-----------------------
Representative/hybrid build, representative selection/visualization/evaluation
and old diagnosis/allocation management actions have been removed. Existing
database data is retained. Only build_hierarchy_graph and evaluate_hierarchy_graph
remain as hierarchy management commands. Evaluation reads a complete saved version
(default active day, optional --run-id) and does not rebuild its graph. Every
report has its own ID and records hierarchy_run_id for the original graph version.

Validation
----------
python manage.py test ingestion.tests hierarchy.tests
The suites use disposable MongoDB databases and temporary report directories.

Partial-day coverage: saved day_coverage records included and missing chunk indices,
known expected count and partial/complete/unverified status. Evaluation reports
chunk-count coverage separately from candidate membership coverage.
