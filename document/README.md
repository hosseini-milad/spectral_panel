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

Layer-1 graph creation and the legacy representative/hybrid hierarchy builders persist
components automatically. Pooling refreshes representative links and reports,
without deleting components or changing their identities. Legacy components
retain their IDs when membership is unchanged. A graph with saved layer-1
representatives cannot be rebuilt implicitly. The component-based layer-2
Meta-component builder is documented below.

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

## Component-based layer 2

```sh
python -u manage.py build_hierarchy_graph --day 2026-06-21 --force
```

This uses all layer-1 components, including components without representatives,
and produces Meta-components plus complete visual lineage automatically. Outputs
are under `document/hierarchy/layer2/<day>/whole-day/hierarchy-components-day-<day>-layer-2/runs/<run-id>/`.
HTML and `lineage_page_*` images are not generated in the current phase.
Inspect `overview.png`, `component_graph.png`, `evaluation_metrics.png`, and
`evaluation_metrics.csv`. The full metric table also appears in the console,
`evaluation.txt`, and `evaluation.json`, with units, definitions and assessments.
Complete memberships remain in JSON and CSV. Previous runs and legacy
representative-based graphs are retained. See `hierarchy/README.txt` for metrics,
defaults, missing-data rules and MongoDB collection names.

Run integration tests using `python manage.py test ingestion.tests hierarchy.tests --verbosity 2`.
They use a disposable MongoDB database and temporary output directory and do not
modify `siem_db` or existing user reports.

## Spectral phase 1

The rewritten phase is documented in `document/spectral/README.md` and
`spectral_learning/README.md`. Run one line:

```sh
python -u manage.py spectral_analysis --day 2026-06-21 --force
```

It analyzes version-consistent chunk and component graphs, exports eigenvectors
and invariant message-passing inputs, and writes metrics/PNG/SVG under
`document/spectral/layerN/...` plus a cross-level summary under
`document/spectral/phase1/...`. Above-Meta levels remain explicitly planning-only
until real graph operators exist. No old ordinal-hour training commands are used.

## ساخت و ارزیابی مجزای گراف روزانه

برای گراف روزانهٔ مؤلفه‌محور فقط دو فرمان hierarchy فعال هستند:

```console
python -u manage.py build_hierarchy_graph --day 2026-06-21 --force
```

```console
python -u manage.py evaluate_hierarchy_graph --day 2026-06-21
```

اولی گراف و فرامؤلفه‌ها را ذخیره می‌کند؛ دومی همان نسخهٔ ذخیره‌شده را ارزیابی
و ترسیم می‌کند. خروجی زیر `document/hierarchy/layer2/<day>/whole-day/<graph>/runs/<report-id>/`
قرار می‌گیرد. `meta_components.png` همهٔ فرامؤلفه‌ها و `meta_component_schematic.png`
مسیر عضویت چانک، مؤلفه و فرامؤلفه را نشان می‌دهد. عضویت کامل در JSON/CSV است.
شناسهٔ نسخهٔ مبدأ در `hierarchy_run_id` ثبت می‌شود. جزئیات در `hierarchy/README.md`.

ساخت گراف روزانه به‌صورت پیش‌فرض فقط چانک‌های موجود روز را ترکیب می‌کند؛ کامل‌بودن
روز شرط نیست. `day_coverage` وضعیت partial/complete/unverified، شمارهٔ چانک‌های
موجود و غایب و درصد پوشش تعداد چانک‌ها را ثبت می‌کند. گزینهٔ اختیاری
`--require-complete-day` برای ردکردن روز دارای چانک غایب است.
