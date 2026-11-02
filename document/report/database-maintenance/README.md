# Collection cleanup and current data ownership

The cleanup command uses the configured MongoEngine database and prints its name.
It has a fixed allowlist: `hyper_graph_edges`, `hyper_graph_metadata`, and
`hyper_representatives`. These belong to the retired representative-based daily
hierarchy. The command only drops them if empty when checked; nonempty collections
are retained and reported. It cannot target arbitrary names and has no force mode.

```console
python -u manage.py cleanup_legacy_collections
```

This writes a preview only. Execute the scoped cleanup with:

```console
python -u manage.py cleanup_legacy_collections --apply
```

Plans and per-collection outcomes are saved in
`document/report/database-maintenance/<UTC-timestamp-and-id>/cleanup.json/txt`.
An initial plan is written before any deletion. Existing nonempty historical
collections require separate data review; they are not dropped by this command.
No local command can modify a user's Windows MongoDB from this cloud workspace;
the user runs this management command on their own configured database.

KEEP raw/normalized/candidate data, graph_metadata, graph_components,
graph_representatives, component_hierarchy_*, meta_components, spectral_*,
upper_spectral_*. In particular graph_representatives is still checked/created
by the active general-action L1 pipeline, despite not being the L2 graph input.
Historical run records are not automatically orphans: downstream spectral runs
pin explicit hierarchy and message-passing run IDs.

The redundant ingestion evaluate_component_allocation action has been removed.
evaluate_graph_components now supports L1 only; use evaluate_hierarchy_graph
for the component-based daily L2 snapshot. No active command offers legacy
hyper-graph construction/evaluation via these entry points.
