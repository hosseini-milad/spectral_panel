import copy
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import networkx as nx
import numpy as np
import mongomock
from django.test import override_settings

from ingestion.services.pooling.spread import spread_representatives,coverage
from ingestion.services.pooling.representative import select_representatives,_select_classwise
from ingestion.services.pooling.spread_preview import preview_spread


class SpreadTests(unittest.TestCase):
    def test_normal_chain_cluster_spreads_without_changing_budget_or_features(self):
        graph=nx.path_graph(101);old=list(range(45,51));report={}
        new=spread_representatives(graph,old,labels={n:0 for n in graph},priorities={45:1},
            features=np.ones((101,3)),diagnostics=report)
        self.assertEqual(len(new),6);self.assertEqual(len(set(new)),6)
        self.assertIn(45,new)
        self.assertLess(coverage(graph,new)['max_hops'],coverage(graph,old)['max_hops'])
        self.assertGreater(coverage(graph,new)['min_rep_hops'],1)
        self.assertEqual(report['feature_error_after'],0)
        self.assertFalse(report['plot_coordinates_used'])

    def test_mixed_components_preserve_each_component_class_and_isolate_quota(self):
        graph=nx.disjoint_union(nx.path_graph(70),nx.path_graph(50));graph.add_node(120)
        labels={n:n%2 for n in graph};old=[25,26,27,28,29,30,85,86,87,88,120]
        new=spread_representatives(graph,old,labels=labels)
        for component in nx.connected_components(graph):
            self.assertEqual(Counter(labels[n] for n in old if n in component),Counter(labels[n] for n in new if n in component))
            self.assertLessEqual(coverage(graph.subgraph(component),[n for n in new if n in component])['max_hops'],
                                 coverage(graph.subgraph(component),[n for n in old if n in component])['max_hops'])
        self.assertIn(120,new)
        for component in nx.connected_components(graph):
            sub=graph.subgraph(component)
            self.assertLessEqual(coverage(sub,[n for n in new if n in component])['adjacent_rep_pairs'],
                                 coverage(sub,[n for n in old if n in component])['adjacent_rep_pairs'])

    def test_feature_distribution_guard_is_nonworsening(self):
        graph=nx.path_graph(90);x=np.random.default_rng(14).normal(size=(90,7));report={}
        spread_representatives(graph,list(range(30,39)),features=x,diagnostics=report)
        self.assertLessEqual(report['feature_error_after'],report['feature_error_before']+1e-8)

    def test_complete_graph_cannot_invent_hop_separation(self):
        graph=nx.complete_graph(20);old=[0,1,2,3]
        new=spread_representatives(graph,old)
        self.assertEqual(coverage(graph,new)['min_rep_hops'],1)
        self.assertEqual(set(old),set(new))

    def test_determinism_and_no_graph_mutation(self):
        graph=nx.path_graph(70);edges=list(graph.edges);old=[30,31,32,33,34]
        a=spread_representatives(graph,old)
        reordered=nx.Graph();reordered.add_nodes_from(reversed(list(graph)));reordered.add_edges_from(reversed(edges))
        b=spread_representatives(reordered,old)
        self.assertEqual(a,b);self.assertEqual(list(graph.edges),edges)
        self.assertEqual(old,[30,31,32,33,34])

    def test_rare_path_distances_include_importance_path(self):
        graph=nx.path_graph(11)
        result=_select_classwise([i for i in graph if i!=0],{n:0 for n in graph},1,
            labels={n:0 for n in graph},attack_ratio=0,G=graph,initial_selected=[0])
        self.assertEqual(result,[10])

    def test_main_selector_returns_count_and_all_class_paths(self):
        graph=nx.path_graph(100);labels={n:int(n>=50) for n in graph};report={}
        score={n:1/(1+abs(n-30)) for n in graph}
        result=select_representatives(score,graph,20,labels=labels,eigenvector_scores=score,
            features=np.ones((100,2)),spread_diagnostics=report)
        self.assertEqual(len(result),20);self.assertEqual(len(set(result)),20)
        self.assertTrue(report['component_class_quotas_preserved'])
        self.assertEqual(Counter(labels[n] for n in report['selected_before']),Counter(labels[n] for n in result))
        self.assertEqual({n for n in report['selected_before'] if labels[n]==1},{n for n in result if labels[n]==1})

    def test_invalid_features_fail_before_any_write(self):
        with self.assertRaises(ValueError):
            spread_representatives(nx.path_graph(10),[3,4],features=np.array([[np.nan]]))


class SpreadPipelineTests(unittest.TestCase):
    def test_pipeline_forwards_features_and_writes_versioned_complete_report(self):
        from bson import ObjectId
        from ingestion.pipelines.pooling_pipeline import run_pooling
        n=20;source='clustered-day-2026-06-15-chunk-0'
        docs=[dict(_id=ObjectId(),source_day='2026-06-15',chunk_index=0,label=0) for _ in range(n)]
        edges=[dict(source=i,target=i+1,weight=.99) for i in range(n-1)]
        component=dict(component_index=0,_id=ObjectId())
        with tempfile.TemporaryDirectory() as directory,override_settings(BASE_DIR=Path(directory)), \
             patch('ingestion.pipelines.pooling_pipeline.persist_components',return_value={'components':[component],'component_count':1}), \
             patch('ingestion.pipelines.pooling_pipeline.GraphRepresentative') as stored:
            result=run_pooling(source,edges,np.ones((n,2)).tolist(),docs,ratio=.3,
                anomaly_scores={i:0 for i in range(n)},create_visualization=False)
            self.assertEqual(len(result),6)
            files=list(Path(directory).glob('document/**/representative_spread/runs/*/representative_spread.json'))
            self.assertEqual(len(files),1)
            report=json.loads(files[0].read_text())
            self.assertEqual(report['persistence_status'],'complete')
            self.assertEqual(report['feature_error_after'],0)
            self.assertEqual(len(report['candidate_ids']),n)
            stored.objects.insert.assert_called_once()


class SpreadPreviewTests(unittest.TestCase):
    def test_preview_outputs_real_same_graph_metrics_and_never_writes_database(self):
        db=mongomock.MongoClient().siem_db;source='clustered-day-2026-06-15-chunk-0';n=60
        graph=dict(source_file=source,source_day='2026-06-15',node_ids=[f'n{i}' for i in range(n)],
            node_labels=[0]*n,features=np.ones((n,3)).tolist(),edges=[dict(source=i,target=i+1,weight=.99) for i in range(n-1)])
        db.graph_metadata.insert_one(graph)
        for i in [26,27,28,29,30]:
            db.graph_representatives.insert_one(dict(source_file=source,node_index=i,original_id=f'n{i}',attention=1,label=0))
        before=list(db.graph_representatives.find());snapshot=copy.deepcopy(db.graph_metadata.find_one())
        with tempfile.TemporaryDirectory() as directory,override_settings(BASE_DIR=Path(directory)):
            folder=Path(preview_spread(db,source))
            self.assertTrue((folder/'representative_spread_comparison.png').is_file())
            self.assertTrue((folder/'representative_spread_comparison.svg').is_file())
            report=json.loads((folder/'representative_spread.json').read_text())
            self.assertGreater(report['changed'],0)
            self.assertEqual(json.loads((folder/'run_status.json').read_text())['database_written'],False)
            self.assertTrue((folder/'before_evaluation.json').is_file())
            self.assertTrue((folder/'after_evaluation.json').is_file())
            self.assertTrue((folder/'feature_distribution.csv').is_file())
        self.assertEqual(before,list(db.graph_representatives.find()))
        self.assertEqual(snapshot,db.graph_metadata.find_one())
