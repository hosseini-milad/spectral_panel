# Action routes

All actions use POST and return a queued job. CLI commands remain unchanged.

| Route | Existing command |
|---|---|
| `/api/v1/actions/ingestion/ingest-parquet/` | `ingest_parquet_directory` |
| `/api/v1/actions/ingestion/normalize-parquet/` | `normalize_parquet_dataset` |
| `/api/v1/actions/ingestion/preview-normalization/` | `preview_normalization` |
| `/api/v1/actions/ingestion/report/` | `generate_ingest_report` |
| `/api/v1/actions/ingestion/reports/` | `generate_ingest_reports` |
| `/api/v1/actions/layer1/build-candidates/` | `build_clustered_candidates` |
| `/api/v1/actions/layer1/build-similarity-graph/` | `build_candidate_similarity_graph` |
| `/api/v1/actions/layer1/build-representatives/` | `build_day_representatives` |
| `/api/v1/actions/layer1/evaluate-representatives/` | `evaluate_representatives` |
| `/api/v1/actions/layer1/visualize-representatives/` | `visualize_representatives` |
| `/api/v1/actions/layer1/preview-representative-spread/` | `preview_representative_spread` |
| `/api/v1/actions/layer1/evaluate-components/` | `evaluate_graph_components` |
| `/api/v1/actions/layer1/verify-components/` | `verify_graph_components` |
| `/api/v1/actions/layer1/evaluate-component-structure/` | `evaluate_layer1_components` |
| `/api/v1/actions/layer1/evaluate-representative-allocation/` | `evaluate_layer1_component_allocation` |
| `/api/v1/actions/layer1/audit-representative-inputs/` | `audit_representative_inputs` |
| `/api/v1/actions/layer1/general-action/` | `general-action` |
| `/api/v1/actions/layer1/hyper-general-action/` | `hyper-general-action` |
| `/api/v1/actions/hierarchy/build/` | `build_hierarchy_graph` |
| `/api/v1/actions/hierarchy/evaluate/` | `evaluate_hierarchy_graph` |
| `/api/v1/actions/spectral/analyze/` | `spectral_analysis` |
| `/api/v1/actions/spectral/message-passing/` | `spectral_message_passing` |
| `/api/v1/actions/spectral/analyze-upper-hierarchy/` | `analyze_upper_hierarchy` |
| `/api/v1/actions/learning/train-layer1-autoencoder/` | `train_layer1_autoencoder` |
| `/api/v1/actions/learning/visualize-encoder-metas/` | `visualize_encoder_metas` |
| `/api/v1/actions/behavior/learn-normal/` | `learn_normal_behavior` |
| `/api/v1/actions/behavior/analyze-scores/` | `analyze_behavior_scores` |
| `/api/v1/actions/behavior/evaluate-feature-graph-gap/` | `evaluate_feature_graph_gap` |
| `/api/v1/actions/behavior/audit-representation/` | `audit_behavior_representation` |
| `/api/v1/actions/behavior/train-neighborhood/` | `train_neighborhood_representation` |
| `/api/v1/actions/behavior/build-signal-inputs/` | `build_behavior_signal_inputs` |
| `/api/v1/actions/behavior/analyze-hierarchy/` | `analyze_hierarchical_behavior` |
| `/api/v1/actions/behavior/prepare-normal-group-reference/` | `prepare_normal_group_reference` |
| `/api/v1/actions/maintenance/reset-processed-day/` | `reset_processed_day` |
| `/api/v1/actions/maintenance/cleanup-legacy/` | `cleanup_legacy_collections` |
| `/api/v1/actions/legacy/build-initial-candidates/` | `build_initial_candidates` |
| `/api/v1/actions/legacy/build-clustered-candidates-graph/` | `build_clustered_candidates_graph` |
| `/api/v1/actions/legacy/build-representatives-directory/` | `build_representatives_directory` |
| `/api/v1/actions/legacy/ingest-normalize-directory/` | `ingest_normalize_directory` |
| `/api/v1/actions/legacy/normalize-directory/` | `normalize_directory` |
| `/api/v1/actions/legacy/validate-model-input/` | `validate_model_input` |
