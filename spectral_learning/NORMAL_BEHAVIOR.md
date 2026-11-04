# Normal-reference self-supervision and frozen evaluation

Current development focus is the ML core / behavior representation rather than
optimizing label1 alert recall. Use `audit_behavior_representation` with a saved
reference bundle for disjoint covering-mask reconstruction, latent geometry,
node-order equivariance and component moment conservation. This audit does not
train, fit thresholds, generate anomaly scores or promote the model. Its
`representation_contract.json` explicitly leaves named feature weights
unestimated and predictive uncertainty uncalibrated. See the repository-root
`BEHAVIOR_REPRESENTATION_ACTIONS_FA.txt` for commands, artifact definitions and
remaining ML tasks. The score workflows below are retained baselines.

This workflow keeps the existing feature, graph and spectral masked autoencoders.
It trains only on the declared normal reference (2026-06-20 by default) and
evaluates independent retained records from other days without updating weights,
scaling, checkpoint selection or thresholds. It does **not** add a new
neighborhood-reconstruction objective or change stored graphs/hierarchies.

The current reference is an artificial mixture of normal-labelled records from
other days. It is not an independent temporal day. In particular, original
records from days 21 and 22 can occur in it. The workflow audits candidate raw
IDs, `artificial_day.original_id`, top-level `original_id` and exact event content
(excluding copy metadata, day, IDs and labels). Use `--origin-id-field FIELD`
when copies retain the original ID under a different dotted field.

Overlapping candidate nodes and their incident edges are removed from external
evaluation graphs **in memory**. Connected components and spectra are recomputed
on these induced graphs. No stored graph or raw record is changed. An external
day with no independent nodes fails rather than reporting contaminated results.
Duplicates within the reference fail before training. Changed copies with no
provenance may escape exact matching: the audit is not proof against all forms
of leakage. Inspect `lineage_audit.csv` and coverage before using the results.

## Prerequisites and commands

Run commands from the repository root with MongoDB available at localhost:27017
and the existing `siem_db`. Raw day 20 alone is insufficient: complete L1 graph
and component records are needed for each selected day. At least four reference
chunks are required for separate train, validation, calibration and test sets.
These are processing chunks, not fixed time windows. Existing L1 graphs for days
21 and 22 can be reused; L2 hierarchy construction is not required by this command.

If day 20 has not been processed, prepare it using the existing resumable workflow:

```sh
python -u manage.py hyper-general-action --source-file clustered-day-2026-06-20
```

Train, calibrate, freeze, and evaluate:

```sh
python -u manage.py learn_normal_behavior --normal-day 2026-06-20 --evaluate-days 2026-06-21 2026-06-22 --epochs 60 --alpha 0.01
```

For later evaluations, use the complete output directory printed by the command:

```sh
python -u manage.py learn_normal_behavior --normal-day 2026-06-20 --evaluate-days 2026-06-23 --reference-bundle PATH_TO_COMPLETE_NORMAL_BEHAVIOR_RUN
```

Replay loads the saved weights/scaler/calibration/thresholds and does not train.
The saved normal reference must still match the current data. Use its original
`--origin-id-field` setting. Replay uses the saved seed, relation-pair budget and
alpha; training options are irrelevant to loaded weights. Every invocation
creates a new retained report directory; existing runs are not overwritten.

## Improved score policies and offline analysis

The original reconstruction scores and reports remain available. Additional
policies compare the feature-only residual with the graph/spectral residual on
the **same** masked targets. A large stabilized log-ratio is model disagreement;
it is not proof that an event is malicious. Numerical floors are 1% of the normal
training residual median for each variant, with minimum 1e-8. Floors never use
external examples or labels.

The new default `--score-policy joint_spectral_gap` combines unusual spectral
reconstruction error and unusual feature/spectral disagreement. Each channel is
ranked against normal **training** scores, the larger tail surprise is taken,
and this joint score is separately calibrated on normal **calibration** rows.
This controls the nominal joint tail instead of simply OR-ing two 1% alarms.
It does not guarantee retaining every old alert under the same nominal budget.
The gap-only option is `--score-policy feature_spectral_gap`; a graph-only
disagreement alternative is `--score-policy feature_graph_gap`.

Replay of an older bundle keeps its model weights, scaler and original residual
thresholds. The new gap/joint policies fit their scales and calibrate their own
thresholds using only the same normal reference outputs. No model retraining or
external-label threshold selection is performed.

Saved node scores can be analyzed without MongoDB queries or retraining:

```sh
python -u manage.py analyze_behavior_scores --scores node_scores.zip --normal-day 2026-06-20
```

The command also accepts plain `node_scores.csv`. It aligns model rows by
day/graph/node identity, rejects duplicate/missing variants, and compares nominal
normal-calibration tail levels .01/.05/.1. To inspect a different budget:

```sh
python -u manage.py analyze_behavior_scores --scores node_scores.zip --normal-day 2026-06-20 --alphas 0.01 0.02 0.05 --score-policy joint_spectral_gap
```

Outputs appear under `document/autoencoder/layer1/<normal-day>/whole-day/score_analysis/runs/<id>/`.
Inside a full `learn_normal_behavior` run they appear in its `score_analysis/`
subdirectory. Read these **new policy reports**, not just the original residual
overview:

- `score_policy_metrics.csv`: node-score ROC-AUC/AP (distinct from relation
  ROC-AUC), label1 recall/precision, label0 false-alert fraction, and retained,
  lost and newly added original alerts. Thresholds are fitted on normal data;
  external labels only evaluate outcomes.
- `selected_node_scores.csv`: selected policy, scores and original/gap alert
  flags. These are **candidate records**, not anomalous Meta-components.
- `alert_case_samples.csv`: up to 100 high-score cases per day/category for
  label1 alerts, label0 alerts, missed label1 and unflagged label0, with raw IDs
  and all three residuals. These are ranked examples, not a random sample.
- `score_analysis.json/txt`, `score_channels.npz`: fitted numerical floors,
  normal-training reference distributions, thresholds, policy definitions,
  input checksum when analyzed offline, and aligned numeric scores.
- `selected_policy_overview.png/svg`, `<day>_score_audit.png/svg`: baseline
  comparison, label-conditional score distributions and ROC/PR curves.
- A full live/replayed run also exports `feature_explanations.csv`: the masked
  feature with largest feature-to-graph error reduction for `feature_graph_gap`,
  or feature-to-spectral reduction for the other policies, per valid node,
  targets/predictions in transformed space. This is a reconstruction diagnostic,
  not causal attribution. Scalar CSV alone cannot recover feature causes.

For a replay-only entry point with the graph disagreement policy fixed, use
`evaluate_feature_graph_gap`. It requires a complete reference bundle, validates
its status/checksums, reuses its lineage field, and exposes no training epochs,
policy switching or new alpha setting. `--check-only` validates files only and
does not query MongoDB source data or establish graph readiness. Full commands
and prerequisites are in `FEATURE_GRAPH_GAP_ACTIONS_FA.txt` at the repository root.

Days 21 and 22 have now been inspected during method development. Results on
them are **retrospective development evidence**, not an untouched final test.
Validate the chosen policy on another independent day before claiming improved
generalization. Exact-event lineage checks remain necessary; this scorer does
not solve missing provenance or near-duplicate leakage. The neighborhood-decoder
training objective remains a separate future ablation; weights are preserved.

## Evaluation and artifacts

Reports are under:

`document/autoencoder/layer1/2026-06-20/whole-day/normal_behavior/runs/<run-id>/`

- `manifest.json`, `run_status.json`: source signatures, split membership,
  fixed-model verification, checkpoint checksums and completion/failure state.
- `feature_model.pt`, `graph_model.pt`, `spectral_model.pt`,
  `reference_arrays.npz`: reusable weights, training-only scaler and calibration
  samples. All arrays load with `allow_pickle=False`; models use
  `torch.load(..., weights_only=True)`.
- `evaluation_metrics.csv`, `evaluation.txt`: reconstruction, held-out relation
  ROC-AUC/AP, alert fractions and held-out normal false alerts per model.
- `node_scores.csv`, `component_scores.csv`, daily NPZ arrays: identity, score,
  validity, fixed threshold, alert, tail rank, embeddings and reconstruction.
- `lineage_audit.csv`, `coverage.csv`, `input_audit.csv`,
  `feature_shift_audit.csv`: excluded copies, available candidate coverage,
  upstream selection risks and previously constant/unobserved feature shifts.
- `normal_behavior_schematic.png/svg`, `evaluation_overview.png/svg`,
  `<day>/behavior_schematic.png/svg`: experiment design, evaluation, shared
  normal-train PCA display and induced example topology (up to 120 nodes).
- `dispersion_permutation.csv`: 20 seeded shuffles of node embeddings within
  each chunk compared with observed L1 component RMS spread. Singletons have
  trivial zero spread. This is not L2 Meta-component dispersion or a new loss.
- `latent_distance_ties.csv`: cosine kNN boundary ties in spectral component
  means, at most 512 query components against all components, with zero norms
  reported separately. No graph-neighbor recall or tie-resolved accuracy is
  inferred from this diagnostic.

Training chunks fit the scaler and weights; separate validation chunks select
the checkpoint. Separate calibration chunks set a conservative upper-tail order
statistic (default nominal alpha=1%). Alerts use `score > threshold`; tied scores
are handled conservatively in the exported tail ranks. Separate normal test
chunks estimate held-out false alerts. At least 99 valid calibration nodes are
needed for alpha=.01. Candidate dependence and artificial sampling mean this is
not a distribution-free operational false-positive guarantee.

External-day alert fractions are deviations, not attack precision or FPR. The
exported raw label0/label1 alert fractions are conditional on existing tags.
The reference is validated against contradictory label=1 candidates; missing
labels are recorded and do not establish independently verified normality.
Only observed active training features are scored; excluded feature shifts are
reported separately. No downstream response is triggered automatically.

## Tests

```sh
python -m pip install -r requirements-test.txt
```

```sh
python manage.py test spectral_learning.tests.test_normal_behavior spectral_learning.tests.test_spectral_core spectral_learning.tests.test_neighborhood_report spectral_learning.tests.test_encoder_meta_report
```

Tests execute actual PyTorch training and reporting on synthetic fixtures with
an in-memory MongoDB substitute. They validate frozen replay, calibration,
leakage filtering, file artifacts and failed-source checks; they do not validate
the user's real population or production MongoDB performance.

### Neighborhood-objective ablation (experimental)

`train_neighborhood_representation` compares fresh, paired graph/spectral cores with and without auxiliary encoder gradients for full-source log-degree and neighbor feature mean/std reconstruction. It reuses the verified reference feature scaler and chunk split, fits neighborhood normalization only on normal train chunks, and selects both arms using the original validation objective. Existing reference checkpoints and MongoDB collections remain unchanged. See [Persian actions and output contract](../NEIGHBORHOOD_REPRESENTATION_ACTIONS_FA.txt). Outputs live under the reference day's `neighborhood_learning/runs`; they are experimental checkpoints, not normal-behavior bundles or calibrated alerts.
