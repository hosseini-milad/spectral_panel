import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from spectral_learning.services.hierarchy_behavior import (
    pooled_moments, _group, reference_models, score_group, build_groups, run_hierarchy_behavior,
)
from spectral_learning.services.neighborhood_experiment import run_neighborhood_experiment
from spectral_learning.services.behavior_signal_inputs import build_behavior_signal_inputs
from spectral_learning.services.spectral_inputs import fingerprint
from spectral_learning.tests import test_normal_behavior as fixtures


def member(i, split='train'):
    return dict(z=[float(i),float(i+1)],split=split,observation_id=f'obs-{i}',raw_id=f'raw-{i}',
        component_id='c',graph_key='g',isolated=False,residuals={k:float(i)/10 for k in ['feature','degree','neighbor_mean','neighbor_std']},
        exceeds={k:False for k in ['feature','degree','neighbor_mean','neighbor_std']})


class HierarchyBehaviorMathTests(unittest.TestCase):
    def test_pooling_retains_within_and_between_component_variance(self):
        a=np.array([[0.,2.],[2.,4.]]); b=np.array([[20.,30.]])
        mean,var,mass=pooled_moments([a.mean(0),b.mean(0)],[a.var(0),b.var(0)],[2,1])
        np.testing.assert_allclose(mean,np.r_[a,b].mean(0));np.testing.assert_allclose(var,np.r_[a,b].var(0))
        self.assertEqual(mass,3)

    def test_mixed_reference_meta_is_excluded_and_external_cannot_fit_reference(self):
        groups=[]
        for split in ['train','calibration','test']:
            for i in range(4):
                groups.append(_group('2026-06-20','component',f'{split}-{i}',[member(i,split)],1,{},'2026-06-20'))
        mixed=_group('2026-06-20','meta_component','mix',[member(1,'train'),member(2,'calibration')],2,{},'2026-06-20')
        groups.append(mixed); before=reference_models(groups,.25,2)
        groups.append(_group('2026-06-23','component','ext',[member(9999,'additional_day')],1,{},'2026-06-20'))
        after=reference_models(groups,.25,2)
        self.assertEqual(before,after)
        self.assertTrue(all(s['status']=='excluded' for s in score_group(mixed,after,'r').values()))

    def test_entire_new_normal_days_have_group_roles_without_chunk_mixing(self):
        for role,expected in [('normal_group_train','train'),('normal_group_calibration','calibration'),('normal_group_test','test')]:
            result=_group('2026-06-15','meta_component','m',[member(1,role),member(2,role)],2,{},'2026-06-20')
            self.assertEqual(result['split'],expected)
        with self.assertRaisesRegex(ValueError,'conflicting'):
            _group('2026-06-15','meta_component','m',[member(1,'normal_group_train'),member(2,'normal_group_test')],2,{},'2026-06-20')

    def test_sparse_or_unseen_size_strata_remain_uncalibrated(self):
        g=_group('2026-06-20','component','x',[member(1)],1,{},'2026-06-20')
        states=reference_models([g],.01,2)
        signals=score_group(g,states,'r')
        self.assertTrue(all(s['status']=='uncalibrated' and s['tail_probability'] is None for s in signals.values()))

    def test_exact_candidate_and_raw_membership_required(self):
        node=dict(component_id='c',source_file='g',member_node_ids=['n'],member_original_ids=['wrong'],node_count=1)
        snapshot=dict(day='2026-06-20',nodes=[node],metas=[])
        with self.assertRaisesRegex(ValueError,'raw membership'):
            build_groups(snapshot,{'n':member(1)},'2026-06-20')


class HierarchyBehaviorIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=fixtures.NormalBehaviorTests();cls.fixture.setUp()
        reference=Path(cls.fixture.run_pipeline()['paths']['directory'])
        with patch('spectral_learning.services.neighborhood_experiment.get_db',return_value=cls.fixture.db), \
             patch('spectral_learning.services.neighborhood_experiment.load_raw_chunks',side_effect=lambda day:copy.deepcopy(cls.fixture.graphs[day])):
            experiment=run_neighborhood_experiment(reference,['2026-06-21'],seeds=[17],epochs=1)
        with patch('spectral_learning.services.behavior_signal_inputs.get_db',return_value=cls.fixture.db), \
             patch('spectral_learning.services.behavior_signal_inputs.load_raw_chunks',side_effect=lambda day:copy.deepcopy(cls.fixture.graphs[day])):
            result=build_behavior_signal_inputs(experiment['directory'],alpha=.25)
        cls.bundle=Path(result['directory']);cls.snapshots={}
        for day in ['2026-06-20','2026-06-21']:
            nodes=[];metas=[]
            for graph in cls.fixture.graphs[day]:
                for part,cid in graph.block_lookup.items():
                    ids=[graph.node_ids[i] for i in sorted(part)]
                    nodes.append(dict(component_id=cid,source_file=graph.key,member_node_ids=ids,member_original_ids=ids,
                        node_count=len(ids),structure=dict(internal_edges=max(0,len(ids)-1),density=0 if len(ids)==1 else 2/len(ids),bridge_count=max(0,len(ids)-1))))
                    metas.append(dict(meta_component_id=f'm-{cid}',child_component_ids=[cid],component_count=1,
                        member_node_count=len(ids),internal_edges=0,density=0,bridge_count=0))
            if day=='2026-06-20':
                # Combine components from train and validation; these must not fit/calibrate.
                left,right=nodes[0],nodes[4]
                metas=[m for m in metas if m['child_component_ids'][0] not in [left['component_id'],right['component_id']]]
                metas.append(dict(meta_component_id='mixed',child_component_ids=[left['component_id'],right['component_id']],
                    component_count=2,member_node_count=left['node_count']+right['node_count'],internal_edges=1,density=1,bridge_count=1))
            cls.snapshots[day]=dict(day=day,run_id='hierarchy-'+day,nodes=nodes,metas=metas,digest=fingerprint(dict(nodes=nodes,metas=metas)))

    @classmethod
    def tearDownClass(cls):
        cls.fixture.doCleanups()

    def run_pipeline(self, **options):
        with patch('spectral_learning.services.hierarchy_behavior.get_db',return_value=self.fixture.db), \
             patch('spectral_learning.services.hierarchy_behavior.load_hierarchy',side_effect=lambda db,day:copy.deepcopy(self.snapshots[day])), \
             patch('spectral_learning.services.hierarchy_behavior.load_raw_chunks',side_effect=lambda day:copy.deepcopy(self.fixture.graphs[day])), \
             patch('torch.optim.Adam',side_effect=AssertionError('No training')):
            return run_hierarchy_behavior(self.bundle,alpha=.25,min_train=2,**options)

    def test_export_membership_coverage_pooling_and_figures(self):
        result=self.run_pipeline();folder=Path(result['directory'])
        manifest=json.loads((folder/'manifest.json').read_text())
        self.assertEqual(manifest['status'],'complete');self.assertTrue(manifest['pooling_verified'])
        rows=[json.loads(r) for r in (folder/'group_observations.jsonl').read_text().splitlines()]
        self.assertEqual(len(rows),47)
        mixed=next(r for r in rows if r['entity']['id']=='mixed')
        self.assertTrue(all(s['status']=='excluded' for s in mixed['signals'].values()))
        self.assertTrue(all(r['fusion']['alert'] is None for r in rows))
        ids={r['_id'] for r in rows}
        links=[json.loads(r) for r in (folder/'memberships.jsonl').read_text().splitlines()]
        self.assertEqual(sum(r['child_type']=='candidate_flow' for r in links),72)
        self.assertTrue(all(r['parent_group_observation_id'] in ids for r in links))
        self.assertTrue(all(r['child_observation_id'] in ids for r in links if r['child_type']=='component'))
        for name in ['hierarchy_deviations.png','hierarchy_behavior_schematic.svg','group_coverage.csv','reference_models.json']:
            self.assertGreater((folder/name).stat().st_size,0)

    def test_exact_run_lookup_finds_complete_export_without_guessing_latest(self):
        from spectral_learning.services.hierarchy_behavior import find_signal_bundle
        parent=json.loads((self.bundle/'manifest.json').read_text())
        self.assertEqual(find_signal_bundle(parent['_id']),self.bundle)
        with self.assertRaisesRegex(ValueError,'No completed'):
            find_signal_bundle('f'*64)

    def test_hierarchy_storage_reader_validates_live_component_snapshots(self):
        import mongomock
        from spectral_learning.services.hierarchy_behavior import load_hierarchy
        from hierarchy.services.component_hierarchy import source_fingerprints
        db=mongomock.MongoClient().siem_db;day='2026-06-20';run_id='h1'
        source='clustered-day-2026-06-20-chunk-0'
        graph=dict(_id='graph',source_file=source,node_ids=['n'],edges=[])
        component=dict(component_id='c',source_file=source,layer=1,node_indices=[0],node_ids=['n'])
        db.graph_metadata.insert_one(copy.deepcopy(graph));db.graph_components.insert_one(copy.deepcopy(component))
        node=dict(run_id=run_id,node_index=0,component_id='c',chunk_index=0,source_file=source,
                  node_count=1,member_node_ids=['n'],member_original_ids=['raw'])
        meta=dict(run_id=run_id,meta_component_id='m',node_indices=[0],child_component_ids=['c'],
                  component_count=1,member_node_count=1,internal_edges=0,density=0)
        db.component_hierarchy_nodes.insert_one(node);db.meta_components.insert_one(meta)
        db.component_hierarchy_runs.insert_one(dict(_id=run_id,source_file='hierarchy',source_day=day,status='complete',
            component_count=1,meta_component_count=1,sources=[dict(source_file=source,**source_fingerprints(graph,[component]))]))
        db.component_hierarchy_graphs.insert_one(dict(_id=f'hierarchy-components-day-{day}-layer-2',status='complete',active_run_id=run_id))
        result=load_hierarchy(db,day)
        self.assertEqual(result['nodes'][0]['component_id'],'c')
        db.meta_components.update_one({'meta_component_id':'m'},{'$set':{'node_indices':[0,0],'child_component_ids':['c','c']}})
        with self.assertRaisesRegex(ValueError,'Duplicate child'):
            load_hierarchy(db,day)
        db.meta_components.update_one({'meta_component_id':'m'},{'$set':{'node_indices':[0],'child_component_ids':['c']}})
        db.graph_metadata.update_one({'_id':'graph'},{'$set':{'node_ids':['changed']}})
        with self.assertRaisesRegex(ValueError,'stale'):
            load_hierarchy(db,day)

    def test_group_storage_is_idempotent_and_checks_complete_parent(self):
        from spectral_learning.services.hierarchy_behavior import persist_hierarchy
        result=self.run_pipeline();folder=Path(result['directory'])
        run=json.loads((folder/'manifest.json').read_text())
        files={name:folder/item['path'] for name,item in run['files'].items()}
        db=self.fixture.db
        def bulk(collection):
            def execute(operations,ordered=False):
                for op in operations:collection.update_one(op._filter,op._doc,upsert=op._upsert)
            return execute
        a=db.behavior_group_observations;b=db.behavior_hierarchy_memberships
        for c in [a,b,db.behavior_hierarchy_runs]:c.delete_many({})
        try:
            with patch.object(a,'bulk_write',side_effect=RuntimeError('interrupted')):
                with self.assertRaisesRegex(RuntimeError,'interrupted'):
                    persist_hierarchy(db,run,files)
            self.assertEqual(db.behavior_hierarchy_runs.find_one()['status'],'failed')
            with patch.object(a,'bulk_write',side_effect=bulk(a)),patch.object(b,'bulk_write',side_effect=bulk(b)):
                persist_hierarchy(db,run,files);persist_hierarchy(db,run,files)
            self.assertEqual(a.count_documents({}),47)
            self.assertEqual(db.behavior_hierarchy_runs.find_one()['status'],'complete')
        finally:
            for c in [a,b,db.behavior_hierarchy_runs]:c.delete_many({})

    def test_source_snapshot_changes_stop_output(self):
        original=copy.deepcopy(self.snapshots)
        from spectral_learning.services.hierarchy_behavior import _figures
        def mutate(*args):
            _figures(*args);self.snapshots['2026-06-20']['digest']='changed'
        try:
            with patch('spectral_learning.services.hierarchy_behavior._figures',side_effect=mutate):
                with self.assertRaisesRegex(ValueError,'snapshot changed'):
                    self.run_pipeline()
        finally:self.snapshots.clear();self.snapshots.update(original)
