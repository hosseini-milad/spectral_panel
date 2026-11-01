"""Persist connected components independently of representative selection.

Membership IDs refer to the ordered nodes of a specific graph. Higher layers
retain immediate parent-component links without pretending to merge components.
"""
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone

import networkx as nx
import numpy as np
from bson import BSON, ObjectId
from mongoengine import get_db
from pymongo import ReplaceOne, UpdateOne

from ingestion.models.graph_component import GraphComponent
from ingestion.services.pooling.community import detect_communities

NUMERIC_FIELDS = (
    "bytes", "bytes_per_packet", "bytes_per_sec", "duration_s", "packets",
    "packets_per_sec", "flag_ack", "flag_syn", "flag_fin", "flag_psh", "flag_rst", "flag_urg",
)
CATEGORICAL_FIELDS = ("protocol", "src_port_category", "dst_port_category", "tcp_flags")


def ordered_components(graph):
    return sorted((sorted(nodes) for nodes in nx.connected_components(graph)), key=lambda nodes: (-len(nodes), nodes[0]))


def numeric_profile(docs, fields=NUMERIC_FIELDS):
    means, stds, counts = {}, {}, {}
    for field in fields:
        values = []
        for doc in docs:
            try:
                value = float(doc[field])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if math.isfinite(value):
                values.append(value)
        counts[field] = len(values)
        means[field] = float(np.mean(values)) if values else None
        stds[field] = float(np.std(values)) if values else None
    return {"mean": means, "std": stds, "observation_counts": counts}


def build_component_graph(node_ids, edges):
    node_ids = [str(value) for value in node_ids]
    if len(set(node_ids)) != len(node_ids):
        raise ValueError("Graph node_ids must be unique")
    graph = nx.Graph()
    graph.add_nodes_from(range(len(node_ids)))
    for edge in edges:
        if isinstance(edge, dict):
            left, right, weight = edge['source'], edge['target'], edge.get('weight', 1.0)
        else:
            left, right, weight = edge
        if not isinstance(left, (int, np.integer)) or not isinstance(right, (int, np.integer)):
            raise ValueError("Graph endpoints must be integer node indices")
        if not 0 <= left < len(node_ids) or not 0 <= right < len(node_ids):
            raise ValueError(f"Edge endpoint outside graph: {left}, {right}")
        if not math.isfinite(float(weight)):
            raise ValueError("Non-finite edge weight")
        graph.add_edge(int(left), int(right), weight=float(weight))
    return graph


def load_node_documents(db, node_ids, collection):
    result = {}
    for start in range(0, len(node_ids), 1000):
        ids = node_ids[start:start + 1000]
        values = ids + [ObjectId(value) for value in ids if ObjectId.is_valid(value)]
        for doc in db[collection].find({'_id': {'$in': values}}):
            result[str(doc['_id'])] = doc
    return result


def persist_components(metadata, *, edges=None, docs=None, graph_collection="graph_metadata", write_reports=True):
    db = get_db()
    source = metadata['source_file']
    params = metadata.get('graph_parameters') or {}
    layer = int(params.get('layer', 1 if graph_collection == 'graph_metadata' else 2))
    day_match = re.search(r'\d{4}-\d{2}-\d{2}', source)
    source_day = metadata.get('source_day') or (day_match.group() if day_match else None)
    chunk_match = re.search(r'(?:^|-)chunk-(\d+)(?:-|$)', source)
    chunk_index = params.get('chunk_index')
    if chunk_index is None and chunk_match:
        chunk_index = int(chunk_match.group(1))
    node_ids = [str(value) for value in metadata.get('node_ids', [])]
    if edges is None:
        edges = (db[metadata['edge_collection']].find({'source_file': source})
                 if metadata.get('edge_collection') else metadata.get('edges', []))
    graph = build_component_graph(node_ids, edges)
    expected_edges = metadata.get('edge_count')
    if expected_edges is not None and graph.number_of_edges() != expected_edges:
        raise ValueError('Stored edge count does not match graph metadata')
    components = ordered_components(graph)
    revision = hashlib.sha256(json.dumps({
        'nodes': node_ids,
        'edges': sorted((min(a, b), max(a, b), data['weight']) for a, b, data in graph.edges(data=True)),
    }, sort_keys=True).encode()).hexdigest()
    node_collection = 'sampled_security_data' if layer == 1 else ('graph_representatives' if layer == 2 else 'hyper_representatives')
    by_id = ({str(doc['_id']): doc for doc in docs} if docs is not None
             else load_node_documents(db, node_ids, node_collection))
    if layer == 2:
        # Layer-2 nodes are representatives; their features live on candidates.
        candidates = load_node_documents(db, [str(doc.get('original_id', '')) for doc in by_id.values()],
                                         'sampled_security_data')
        by_id = {key: {**{field: candidates.get(str(doc.get('original_id')), {}).get(field)
                         for field in NUMERIC_FIELDS + CATEGORICAL_FIELDS}, **doc}
                 for key, doc in by_id.items()}
    reps_collection = 'graph_representatives' if layer == 1 else 'hyper_representatives'
    representatives = list(db[reps_collection].find({'source_file': source}))
    existing = {
        tuple(sorted(row.get('node_ids') or [])): row
        for row in db.graph_components.find({'source_file': source, 'layer': layer})
    }
    # Validation happens before changing saved components or representative links.
    rep_by_node = {}
    for rep in representatives:
        index = rep.get('node_index')
        if not isinstance(index, int) or not 0 <= index < len(node_ids) or str(rep.get('original_id')) != node_ids[index]:
            raise ValueError(f"Stale representative mapping in {source}: {rep['_id']}")
        rep_by_node.setdefault(index, []).append(rep)
    saved = []
    for index, members in enumerate(components):
        ids = [node_ids[node] for node in members]
        identity = json.dumps([graph_collection, source, layer, sorted(ids)], ensure_ascii=False)
        cid = hashlib.sha256(identity.encode()).hexdigest()[:24]
        previous = existing.get(tuple(sorted(ids)))
        if previous:
            # Preserve IDs already referenced by representatives and higher layers.
            cid = previous['component_id']
        member_docs = [by_id[value] for value in ids if value in by_id]
        member_reps = [rep for node in members for rep in rep_by_node.get(node, [])]
        profile = numeric_profile(member_docs)
        subgraph = graph.subgraph(members)
        degree = [value for _, value in subgraph.degree()]
        signed = any(data['weight'] < 0 for _, _, data in subgraph.edges(data=True))
        partition = {} if signed else detect_communities(subgraph)
        community_sizes = sorted(Counter(partition.values()).values(), reverse=True)
        lineage = [{
            'node_id': value,
            'original_id': str(by_id.get(value, {}).get('original_id', value)),
            'source_file': str(by_id.get(value, {}).get('source_file', '')),
            'parent_component_id': by_id.get(value, {}).get('component_id'),
        } for value in ids]
        categories = {}
        for field in CATEGORICAL_FIELDS:
            counts = Counter(str(doc[field]) for doc in member_docs if doc.get(field) is not None)
            categories[field] = {
                'counts': dict(counts), 'observed': sum(counts.values()),
                'ratios': {key: value / sum(counts.values()) for key, value in counts.items()},
            }
        rep_profile = numeric_profile([by_id[node_ids[rep['node_index']]] for rep in member_reps if node_ids[rep['node_index']] in by_id])
        component = GraphComponent(
            id=previous['_id'] if previous else ObjectId(cid), component_id=cid, source_file=source,
            source_day=source_day, layer=layer, graph_collection=graph_collection,
            graph_revision=revision, chunk_index=chunk_index,
            component_index=index, node_collection=node_collection,
            node_indices=members, node_ids=ids, node_count=len(members),
            node_original_ids=[item['original_id'] for item in lineage], node_lineage=lineage,
            parent_component_ids=sorted({str(item['parent_component_id']) for item in lineage if item['parent_component_id']}),
            representative_ids=[str(rep['_id']) for rep in member_reps],
            representative_original_ids=[str(rep['original_id']) for rep in member_reps],
            representative_node_indices=[rep['node_index'] for rep in member_reps],
            representative_count=len(member_reps), mean_features=profile['mean'],
            feature_std=profile['std'], feature_observation_counts=profile['observation_counts'],
            feature_fields=list(NUMERIC_FIELDS), representative_profile=rep_profile,
            categorical_profile=categories, profile_scope='all_component_nodes',
            missing_node_ids=[value for value in ids if value not in by_id],
            component_statistics={
                'internal_edges': subgraph.number_of_edges(), 'density': nx.density(subgraph),
                'is_isolate': len(members) == 1 and degree[0] == 0,
                'min_degree': min(degree), 'max_degree': max(degree),
                'mean_degree': float(np.mean(degree)),
                'cycle_rank': subgraph.number_of_edges() - len(members) + 1,
                'bridge_count': sum(1 for _ in nx.bridges(subgraph)),
                'average_clustering': float(nx.average_clustering(subgraph)),
                'community_count': None if signed else len(community_sizes),
                'community_sizes': community_sizes,
                'community_method': 'unavailable_signed_weights' if signed else 'louvain_weighted_resolution_1_seed_42',
                'profiled_node_count': len(member_docs),
            },
            created_at=previous.get('created_at') if previous and previous.get('created_at') else datetime.now(timezone.utc),
        )
        component.validate()
        raw = component.to_mongo().to_dict()
        if len(BSON.encode(raw)) > 16 * 1024 * 1024:
            raise ValueError(f"Component {cid} exceeds MongoDB document limit")
        saved.append(raw)
    # Index creation also supports upgrading existing databases.
    GraphComponent.ensure_indexes()
    db[graph_collection].update_one({'source_file': source}, {'$set': {'component_status': 'building'}})
    try:
        # Free positional unique keys before a repartition/reordering. IDs remain
        # intact; component_status prevents treating an interrupted write as ready.
        prior_rows = list(existing.values())
        offset = min([row.get('component_index', 0) for row in prior_rows] + [0]) - len(prior_rows) - 1
        if prior_rows:
            db.graph_components.bulk_write([
                UpdateOne({'_id': row['_id']}, {'$set': {'component_index': offset - index}})
                for index, row in enumerate(prior_rows)
            ])
        if saved:
            db.graph_components.bulk_write([ReplaceOne({'component_id': row['component_id']}, row, upsert=True) for row in saved])
        db.graph_components.delete_many({'source_file': source, 'layer': layer, 'component_id': {'$nin': [row['component_id'] for row in saved]}})
        updates = []
        for row in saved:
            for rep_id in row['representative_ids']:
                updates.append(UpdateOne({'_id': ObjectId(rep_id)}, {'$set': {'component_id': row['component_id'], 'component_index': row['component_index']}}))
        if updates:
            db[reps_collection].bulk_write(updates)
        db[graph_collection].update_one({'source_file': source}, {'$set': {
            'component_status': 'complete', 'component_count': len(saved),
            'component_revision': revision, 'components_completed_at': datetime.now(timezone.utc),
        }})
    except Exception:
        db[graph_collection].update_one({'source_file': source}, {'$set': {'component_status': 'failed'}})
        raise
    result = {'source_file': source, 'layer': layer, 'graph_revision': revision,
              'node_count': len(node_ids), 'edge_count': graph.number_of_edges(),
              'component_count': len(saved), 'components': saved,
              'missing_node_count': sum(len(row['missing_node_ids']) for row in saved)}
    if write_reports:
        from ingestion.services.reporting.component_report import write_component_report
        result['paths'] = write_component_report(metadata, graph, result)
    return result
