# Normal-reference self-supervision and frozen evaluation

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
