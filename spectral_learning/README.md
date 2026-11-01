# Spectral phase 1

This app is rewritten for the CURRENT component hierarchy. The old ordinal-hour
services, temporal training commands, duplicate MongoEngine models and stale
tracked bytecode have been removed. Old MongoDB results and saved model artifacts
are retained; old checkpoints are not compatible with the new contract.

## Execute

With MongoDB running and a complete component hierarchy for the day:

```sh
python -u manage.py spectral_analysis --day 2026-06-21 --force
```

Default scope is all available chunk graphs AND the active daily component graph.
A first run can omit `--force`. Force creates a new spectral version; previous
results are retained. For a first local inspection of one chunk:

```sh
python -u manage.py spectral_analysis --day 2026-06-21 --scope chunks --chunk-index 0 --force
```

Options: `--scope all|chunks|components`, `--hierarchy-run-id ID`,
`--eigenvectors 8`, `--max-basis 32`, `--dense-limit 256`, `--higher-levels 2`,
`--planning-ratio 0.5`. A chunk index is allowed only with scope=chunks.
Higher-level counts are planning scenarios, never constructed graphs/spectra.

## Actual inputs and level semantics

- Layer 1: `graph_metadata` candidate-flow graphs plus `graph_components` membership.
- Layer 2: immutable `component_hierarchy_runs`, `component_hierarchy_nodes`,
  `component_hierarchy_edges`, `meta_components` snapshots. The default pins the
  active complete hierarchy run, never the legacy representative graph.
- Layer 3: current Meta-component memberships, not a meaningful inter-Meta graph.
- Layers 4+ describe two or more proposed levels ABOVE Meta-components. Default
  planning ratio .5 gives scenario counts, not a promise of structural preservation.

Structural level and temporal window are separate concepts. No chunk is turned
into a minute/hour. No APT detection, Ridge, Autoencoder or learned embedding is
run in this phase. Above-Meta spectral status is explicitly not_computed until
meaningful graphs, weights, membership and mass/prolongation rules exist.

When scope=all, current chunk graph/membership fingerprints must match the source
versions recorded by the selected hierarchy run. Node order comes from saved
metadata, not a new sampling query. Missing records, malformed edges, stale
partitions or source changes during execution stop publication of the run.

## Operator and eigensolver

The operator is the symmetric normalized Laplacian `D^-1/2 (D-A) D^-1/2`, with zero
isolate rows/diagonal. Source edges must be unique undirected finite positive
weights; self-loops need a separate explicit contract and are rejected here.

Connected blocks are solved independently. Small blocks (default <=256 nodes)
use a complete dense eigendecomposition. Larger blocks use scipy sparse eigsh on
a LinearOperator that shifts the KNOWN trivial mode to eigenvalue 3, outside the
normalized spectrum [0,2]. Thus a graph with thousands of disconnected blocks
does not require asking for thousands of zero modes before useful vectors.
Global dense N×N adjacency/Laplacian matrices are not formed.

Topology determines nullity and rank. A tiny positive Fiedler mode is not silently
removed because it falls under a numeric zero threshold. Raw eigenvalues are
checked BEFORE clipping. Residuals, orthogonality, overlap with the known kernel,
operator symmetry and solver convergence are validated. Solver failures leave
previous active results intact. Complete entropy/histograms are absent when any
block spectrum is partial; plots explicitly label complete-spectrum coverage.

## Eigenvector-aware message passing contract

The requested dimension is a target, not permission to cut a repeated eigenspace.
Whole equal/near-equal eigenvalue groups (tolerance 1e-7) are included, optionally
expanding beyond requested dimensions up to max-basis. A group beyond the budget
is omitted and recorded as basis-limited; missing channels have masks. A naturally
small block has fewer modes without being an error. Isolates have NO nontrivial
positional encoding; their masks are false.

`models/eigenvector_gnn.py` contains the new EigenvectorAwareMessagePassing module.
Phase 1 does not execute/train it. It consumes invariant signatures from retained
projector groups: three node heat diagonals and three edge diffusion distances
at diffusion scales [.1,1,10]. The latter are NOT time windows. Group-average
spectral weights make features insensitive to vector sign and orthogonal changes
of basis inside a retained eigenspace. They approximate the RETAINED nontrivial
spectral geometry, not the complete heat kernel. Raw eigenvectors are exported for
inspection but should not be directly compared/concatenated across arbitrary bases.

The module uses attribute masks and spectral masks, source edge weights and a
structural-level embedding. Undirected edges are stored once and expanded in both
directions inside message passing. Training losses, heads and anomaly scores are
reserved for later phases. Label/score/ID/time fields are excluded from the fixed
attribute schema; redundant log_* copies are not exported as additional inputs.

## Persistence and reports

Collections:
- spectral_analysis_runs: version, parameters, source signatures and status.
- spectral_analysis_active: active COMPLETE run pointer per day/scope/chunk selection.
- spectral_graphs: per-graph summaries and numerical metrics.
- spectral_blocks: connected-block eigenvalues, eigenspace groups and source IDs.
- spectral_node_encodings: ordered per-node vectors/values, masks, invariant
  signatures, attributes and source lineage.
- spectral_edge_encodings: source edge weights and masked invariant signatures.

Reports/encodings are written before publication; sources are revalidated, then
an optimistic active-pointer update prevents overwriting a concurrent run. Failed
partial runs are marked failed and excluded by the active pointer.

Per graph:
`document/spectral/layerN/<day>/<chunk-N-or-whole-day>/<graph-key>/runs/<run-id>/`

Files: spectral_summary.json/txt, metrics.csv, blocks.csv, spectral_blocks.json,
node_lineage.json, spectral_features.npz, spectral_overview.png/svg.
NPZ contains typed arrays and can be loaded with allow_pickle=False. node_ids,
edge_index/weights, feature schema/masks, basis vectors/values/masks, source block
indices and invariant node/edge signatures use the SAME stored node order.

Cross-level phase reports:
`document/spectral/phase1/<day>/runs/<run-id>/`

Files: phase_manifest.json, phase_summary.txt, graph_summary.csv,
hierarchy_readiness.csv, phase_overview.png/svg. The readiness table clearly
separates observed graph sizes from scenario estimates and unavailable layers.
Every executed graph receives statistics and schematics; no HTML or lineage-page
images are generated. Larger block drawings use a clearly labeled induced subset;
complete numerical outputs remain in NPZ/JSON/MongoDB. Runtime excludes report I/O
where stated, and peak memory is explicitly NOT measured.

## Validation

```sh
python manage.py test ingestion.tests hierarchy.tests spectral_learning.tests
```

Tests cover known path/cycle spectra, weak positive modes, isolates, sparse
non-densification, complete degenerate groups, sign/rotation invariance, a PyTorch
forward/backward contract smoke test, real spectral reports, version consistency,
failed-publication behavior and planning-only upper levels. MongoDB integration
uses disposable databases. Production siem_db data and legacy model artifacts are
not deleted.

Raw eigenvector arrays use block-local column slots. `basis_global_columns` maps
each valid slot to a distinct global eigenvector column, and
`global_basis_eigenvalues` stores the corresponding values in block/rank order.
Reconstruct a sparse global eigenbasis using those indices; concatenated local
slots alone are NOT columns of a single global diagonal eigendecomposition.

## Phase 2: executable eigenvector-aware message passing

```sh
python -u manage.py spectral_message_passing --day 2026-06-21 --force
```

Uses the active **full-day phase-1 run** including its selected hierarchy version.
`--spectral-run-id ID` selects a complete explicit run (including a scoped run).
Every source graph and attribute fingerprint must still match phase 1, before
and after execution. No upstream graph or previous phase output is overwritten.

`evaluate_message_passing(graph, result, ...)` runs two matched transductive
masked-feature probes: invariant spectral inputs enabled vs disabled. Both use
`EigenvectorAwareMessagePassing` with identical initial seeds, architecture,
splits and training schedule. Default: 30 epochs, hidden 32, 2 layers, Adam
lr .003, weight decay .0001, CPU, one thread. Change with `--epochs`,
`--hidden-dim`, `--layers`, `--seed`, `--perturbation-repeats` (default 3).
This is a preliminary representation-learning task with an auxiliary linear
feature head, not the future multi-objective graph Autoencoder.

Per attribute with >=5 observed entries, hold out 10% validation and 10% test
entries (at least one each). Fit column mean/SD using training entries only.
The held-out values AND their availability masks remain absent from encoder
inputs throughout training and evaluation. Randomly hide 20% of remaining
training entries each epoch and optimize only those entries. Select checkpoint
using validation MSE only; evaluate held-out test entries once afterward.
Attributes with <5 observations remain training-only; insufficient overall
validation/test data aborts publication. Graph topology is transductive and
may encode information about hidden feature values because graphs were built
upstream using those attributes. This is **not** inductive generalization.

The encoder consumes attribute values/masks, 3 node spectral channels and their
mask, structural-level embedding, weighted edges, 3 invariant edge channels and
their mask. For each layer:

```
h_i^0 = Linear([masked(x_i), mask_i, spectral_i, spectral_mask_i, level])
m_ij = w_ij * MLP([h_j, h_i, spectral_ij, spectral_mask_ij])
a_i = sum_j(m_ij) / max(sum_j(w_ij), epsilon)
h_i^(l+1) = h_i^l + Update([h_i^l, a_i])
```

Isolates receive no invented neighbors or spectral coordinates; their attributes
and level are retained. The encoder uses projector-group signatures to avoid
raw eigenvector sign/rotation ambiguity. Runtime audits check sign/group
rotation invariance (<=1e-9) and node permutation equivariance (<=1e-4).

Evaluation exports test MSE vs a train-column-mean baseline and the matched
spectral ablation. Positive spectral improvement means lower MSE in this probe,
not proven anomaly-detection improvement. One training seed is used; no
statistical significance claim. Interventions (3 repeats by default):

* weight changes: random 10% of edges multiplied by exp(U(-.05,.05));
* drop ceil(1% of edges), reporting component/encoding-count changes;
* feature noise: Gaussian SD = 5% of each observed column's SD.

Recompute eigenspaces/signatures for topology interventions; preserve weights
and model checkpoints otherwise. Compare embeddings in the **same model's**
coordinate system. Report relative Frobenius changes and signature changes on
nodes valid before AND after the intervention. Zero denominator -> unavailable.
Sensitivity has no universal pass threshold, and these are simulated changes,
not timestamp-based temporal tracking. Weight changes are not thresholded again
and may exceed original cosine range; they perturb the Laplacian, not rebuild
the original neighbor-selection process.

Input audit reports differing graph construction configurations (excluding chunk
IDs) and flagged label/score fields, including indirect `threat_intel_score`
effects through topology. These warnings permit exploratory runs but block any
claim that the inputs are uniformly constructed or free of label leakage.

Outputs:

* `document/spectral/layerN/<day>/<scope>/<graph>/message-passing/runs/<id>/`:
  evaluation JSON/TXT, metrics CSV, interventions CSV, training curves CSV,
  overview PNG/SVG, pooling schematic PNG/SVG, embeddings NPZ, both probe
  checkpoints, complete membership JSON.
* `document/spectral/phase2/<day>/runs/<id>/`: phase manifest, graph summary,
  input audit, phase summary and phase schematic PNG/SVG.
* MongoDB `spectral_message_passing_runs`, `spectral_message_passing_active`,
  `spectral_message_passing_graphs`, `spectral_message_passing_nodes`,
  `spectral_pooled_features`.

NPZ contains full-observed-attribute inference embeddings, disjoint entry masks,
scaler, block mapping, pooled means/SDs/sizes. Pooling treats each child equally,
not by original raw-flow volume. Existing connected-block membership is retained;
no new clustering or parent edges are inferred. Every child is included once,
including isolates. Pooled attributes are a handoff for the next phase, **not a
coarsened graph with demonstrated spectral preservation**. Schematics show the
largest 12 memberships; JSON/NPZ/MongoDB contain them all. Higher layers,
temporal analysis, anomaly scores and Ridge remain unexecuted.

Models are trained separately per graph. Embedding coordinates are graph/checkpoint
local, not aligned across chunks, days or levels. Do not compute direct cross-graph
cosine distances between them. A shared encoder/alignment is a later prerequisite
for cross-graph temporal comparisons. Pooled embeddings within the daily component
graph do share its single encoder.
