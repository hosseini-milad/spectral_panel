# Generated project documents

The document root is `<repository>/document/`. Input datasets remain under
`files/`; existing output files are preserved and are not moved or deleted.
All updated report commands write new outputs to this layout:

```text
document/
  nominal/       # graph and representative visualizations
  component/     # connected-component membership, evaluation, schematics
  report/        # ingestion, representative, spectral/model reports
  hierarchy/     # higher-layer graph diagnostics and visualizations
    layer1/      # each category has layer1, layer2, layer3, ...
    layer2/
    layer3/
```

Within a layer: `YYYY-MM-DD/chunk-N/<graph-key>/`. Whole-day graphs use
`YYYY-MM-DD/whole-day/<graph-key>/`. Graph-specific folders prevent random,
clustered, and experimental variants from overwriting each other. Sources without
an explicit day use `unknown-day`; no acquisition date is invented. Aggregate
cross-source reports use `unknown-day/whole-day/`.

Example:

```text
document/component/layer1/2026-06-21/chunk-0/
  clustered-day-2026-06-21-chunk-0/
    clustered-day-2026-06-21-chunk-0_components.json
    clustered-day-2026-06-21-chunk-0_components.txt
    clustered-day-2026-06-21-chunk-0_components.png
    clustered-day-2026-06-21-chunk-0_components.svg
```

## Persist and evaluate components

For the complete layer-1 workflow, use one line from the repository directory:

```sh
python -u manage.py general-action --source-file clustered-day-2026-06-21-chunk-0
```

This runs normalization, candidate selection, graph construction, representative
selection, component persistence/schematics, integrity audit, layer-1 structural
evaluation, allocation evaluation, representative evaluation, and visualization.
The day and chunk are extracted from the key. Defaults remain 20,000 raw rows per
chunk, 10% candidates, 10% representatives, k=12, cosine threshold=0.995, and degree
cap=20. Raw Parquet records for that day must already be ingested.

Complete intermediate outputs are reused; all six reporting/audit stages rerun.
Existing graph parameters are logged and retained. Graph flags affect newly
built graphs only. Incompatible/partial cohorts stop the pipeline instead of
overwriting downstream data. Retry the same one-line command after resolving an
error. Changing chunk size or representative ratio is not an implicit rebuild.
This command processes one layer-1 chunk, not whole-day or layer-2 graphs.

To process every chunk of a day automatically, use:

```sh
python -u manage.py hyper-general-action --source-file clustered-day-2026-06-21
```

This counts the day's raw records, derives all zero-based chunk indices (including
a shorter final chunk), and calls the same complete `general-action` workflow
for each chunk in order. No manual index is required. Defaults and graph/report
options are forwarded unchanged. On failure it stops before later chunks and
reports the failed index and cause. Rerunning the same day command reuses complete
intermediate data and refreshes reports through the canonical chunk workflow.
`--start-chunk` and `--max-chunks` remain optional controls for a restricted run.
This command does not build layer-2 hierarchy graphs.

Use the project's configured Python environment and running MongoDB:

```sh
source /workspace/.venvs/spectral_project/bin/activate
export PYTHONDONTWRITEBYTECODE=1
export MPLCONFIGDIR=/workspace/.cache/matplotlib
python manage.py evaluate_graph_components --source-file clustered-day-2026-06-21-chunk-0
python manage.py verify_graph_components --source-file clustered-day-2026-06-21-chunk-0
# Backfill all existing layer-1 graphs, including graphs without representatives:
python manage.py evaluate_graph_components --all
# Existing complete higher-layer similarity graphs:
python manage.py evaluate_graph_components --all --layer 2
```

Layer-1 graph creation and the three hierarchy similarity graph builders persist
components automatically. Pooling refreshes representative links and reports,
without deleting components or changing their identities. Legacy components
retain their IDs when membership is unchanged. A graph with saved layer-1
representatives cannot be rebuilt implicitly. This change does not implement
Meta-Component merging or reinterpret temporal traffic snapshots as similarity
graphs.

`graph_components` stores every connected component, including isolates and
components without representatives. It records the source graph/layer, ordered
node indices and IDs, source collection, original IDs, immediate node lineage,
parent-component IDs, membership revision, all-member numeric and categorical
profiles, structural statistics, and a separate representative profile.
`mean_features` and `feature_std` now describe **all available component nodes**,
not just selected representatives. They do not describe unsampled raw flows.
Missing source records remain in membership and are explicitly reported; they
are never silently removed or replaced with synthetic feature values.

Graph metadata records component completion/failure and the graph revision.
Connected components are deterministically ordered by size and minimum node
index. The JSON contains complete membership; PNG/SVG show all components and
an internal view of the largest. Above 150 nodes the internal view is explicitly
marked as a highest-degree induced subset, not the complete component. Metrics
include size, density, degree statistics, bridges, cycle rank, clustering, and
Louvain community sizes. These are structural diagnostics, not proof of anomaly
detection accuracy. Louvain is not reported for graphs with negative weights.

Run integration tests using `python manage.py test ingestion.tests --verbosity 2`.
They use a disposable MongoDB database and temporary output directory and do not
modify `siem_db` or existing user reports.
