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
