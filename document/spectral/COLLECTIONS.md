# Where additional structural information is stored

| Collection | Meaning |
|---|---|
| graph_components | L1 connected memberships, original candidate references and descriptive profiles |
| component_hierarchy_nodes | Daily L2 nodes: descriptors of L1 components, member lineage, counts |
| component_hierarchy_edges | Daily component-similarity weighted edges |
| component_hierarchy_graphs | Active complete daily hierarchy pointer |
| component_hierarchy_runs | Immutable hierarchy version metadata, parameters and source versions |
| component_hierarchy_evaluations | Separate evaluation runs, metrics and output paths |
| meta_components | Membership and descriptive profiles of daily connected Meta-components |
| spectral_node_encodings | Per-node eigenvectors/eigenvalues/basis masks, invariant node_spectral signatures, feature masks and lineage |
| spectral_edge_encodings | Invariant edge_spectral signatures, validity masks and source/target indices |
| spectral_blocks | Connected-block spectral diagnostics |
| spectral_graphs | Spectral graph summaries and report paths |
| spectral_analysis_runs / spectral_analysis_active | Spectral version metadata and active selection pointers |
| spectral_message_passing_nodes | Learned per-node embedding, block membership and lineage |
| spectral_pooled_features | Per-connected-group learned embedding mean/std and child count; component_id identifies the corresponding group |
| spectral_message_passing_graphs | Training/evaluation summaries for each graph |
| spectral_message_passing_runs / spectral_message_passing_active | MP version metadata and active selection pointers |
| upper_spectral_nodes | Experimental further structural aggregation within a day: own spectral/learned features and inherited pooled features |
| upper_spectral_edges / upper_spectral_components / upper_spectral_graphs | Experimental upper structural graph, groups and report summaries |
| upper_spectral_runs / upper_spectral_active | Pinned versions of that experiment; not a built weekly temporal level |

Additional spectral/learned fields are versioned separately; they are not silently
appended to the original meta_components document. On a daily L2 graph a node is
an L1 component, so the node encoding is not yet the pooled Meta-component vector.
For the latter use spectral_pooled_features with layer=2. For L1 that same
collection pools candidate-node embeddings into L1 components; distinguish layer,
graph_key and run_id.

Example Compass filter for all daily L2 pooled vectors for the second day:

```json
{"source_day":"2026-06-22","layer":2}
```

This may return multiple historical versions. Add the actual `run_id` of the
completed selected message-passing run to obtain one version. source_component_id
in spectral_blocks / component_id in spectral_pooled_features link back to the
persisted connected group; node_id in spectral_node_encodings links to the input
node. For daily input nodes these are component_hierarchy_nodes.component_id.

build_hierarchy_graph and evaluate_hierarchy_graph alone do not create spectral
or learned collections. They are written by spectral_analysis and
spectral_message_passing respectively, in the same configured database. Refresh
and inspect the full Compass list before concluding they are absent. Retain runs
and active pointers alongside node/edge arrays: their provenance is required.
