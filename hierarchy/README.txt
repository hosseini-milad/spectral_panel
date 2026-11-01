Hierarchy layer-2 graph command

Run:
    python -u manage.py build_hierarchy_graph --day 2026-06-21

Algorithm:
    Exact blockwise all-pairs cosine threshold graph. Every unordered pair is checked.
    Default threshold=0.995. Degree cap defaults to 0 (disabled).
    --block-size controls memory, not which pairs are compared.

Storage:
    siem_db.hyper_graph_metadata: one metadata document per graph, including nodes,
    labels, stats, graph parameters, edge count, edge collection and status.
    siem_db.hyper_graph_edges: one document per edge with source_file, source, target,
    and weight. Edges are inserted in batches of 5,000 to avoid BSON document limits.

The metadata status is "building" while edges are saved, "complete" only after all
edges are saved, or "failed" if edge storage fails. Use --force to rebuild a graph;
it deletes only that graph key's metadata and edge records first.

This change modifies only the hierarchy app; no ingestion files are changed.


Layer-2 representative selection

Run:
    python -u manage.py build_hierarchy_representatives --source-file hierarchy-day-2026-06-21-layer-2 --ratio 0.10

This command:
- Reads the completed graph from hyper_graph_metadata.
- Reads edge documents from hyper_graph_edges.
- Uses the existing ingestion centrality, scoring and representative selection
  functions without modifying any ingestion file.
- Saves selected representatives to siem_db.hyper_representatives.
- Preserves parent lineage through original_id, parent_source_file,
  parent_node_index, and parent_original_id.
- Defaults to 10% of graph nodes. Use --force to replace only this source_file's
  existing hyper_representatives.
Note: anomaly scores are not computed at this hierarchy layer; the existing
selector receives an empty anomaly score mapping, while graph centrality, degree,
component rarity, label balance and graph-distance selection remain active.
