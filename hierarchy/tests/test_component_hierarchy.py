import copy
import io
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import networkx as nx
import numpy as np
from bson import ObjectId
from django.core.management import call_command, CommandError
from django.test import override_settings
from mongoengine import connect, disconnect, get_db

from hierarchy.services.component_hierarchy import (
    CATEGORICAL, Similarity, build_hierarchy, component_graph, load_components, meta_components,
)


class ComponentHierarchyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.settings = override_settings(BASE_DIR=Path(cls.directory.name))
        cls.settings.enable()
        disconnect()
        connect('test_meta_' + uuid.uuid4().hex, host='localhost', port=27017, serverSelectionTimeoutMS=5000)
        cls.db = get_db()
        cls.db.client.admin.command('ping')

    @classmethod
    def tearDownClass(cls):
        cls.db.client.drop_database(cls.db.name)
        disconnect(); connect('siem_db', host='localhost', port=27017)
        cls.settings.disable(); cls.directory.cleanup()

    def setUp(self):
        for name in self.db.list_collection_names():
            self.db[name].delete_many({})
        self.day = '2026-06-21'
        for chunk in range(2):
            source = f'clustered-day-{self.day}-chunk-{chunk}'
            docs = []
            for index, value in enumerate([.10, .12, .80, .82, .45]):
                original = ObjectId()
                protocol = 'tcp' if index < 2 else ('udp' if index < 4 else ('icmp' if chunk == 0 else 'gre'))
                value += chunk * .01
                doc = {'_id': ObjectId(), 'original_id': str(original), 'source_day': self.day,
                       'source_file': source, 'bytes': value, 'packets': value, 'duration_s': value,
                       'label': 1 - chunk}  # Labels must have no effect on similarity.
                docs.append(doc)
                self.db.security_data.insert_one({'_id': original, 'source_day': self.day, 'protocol': protocol})
                self.db.normalized_security_data.insert_one({'_id': original, 'source_day': self.day,
                                                             'normalization_sample_per_day': 5})
            self.db.sampled_security_data.insert_many(docs)
            self.db.graph_metadata.insert_one({'source_file': source, 'source_day': self.day,
                                               'component_status': 'complete', 'component_revision': f'revision-{chunk}',
                                               'node_ids': [str(doc['_id']) for doc in docs],
                                               'edges': [{'source': a, 'target': b, 'weight': .99} for a, b in [(0, 1), (2, 3)]]})
            for index, members in enumerate([[0, 1], [2, 3], [4]]):
                self.db.graph_components.insert_one({'component_id': str(ObjectId()), 'source_file': source,
                    'source_day': self.day, 'layer': 1, 'graph_revision': f'revision-{chunk}',
                    'component_index': index, 'node_indices': members,
                    'node_ids': [str(docs[i]['_id']) for i in members], 'node_count': len(members),
                    'representative_count': 0})
        self.db.hyper_graph_metadata.insert_one({'source_file': 'legacy', 'node_ids': ['representative-id']})

    def test_build_uses_all_components_and_writes_complete_visual_lineage(self):
        self.db.sampled_security_data.update_many({}, {'$set': {'flag_syn': 1}})
        evaluation, paths = build_hierarchy(self.day)
        self.assertEqual(evaluation['component_count'], 6)
        self.assertEqual(evaluation['candidate_node_count'], 10)
        self.assertEqual(evaluation['components_without_representatives'], 6)
        self.assertEqual(evaluation['edge_count'], 2)
        self.assertEqual(evaluation['meta_component_count'], 4)
        self.assertEqual(evaluation['cross_chunk_meta_components'], 2)
        self.assertEqual(evaluation['components_with_categorical_data'], 6)
        self.assertTrue(all(evaluation['integrity'].values()))
        self.assertEqual(self.db.hyper_graph_metadata.find_one()['node_ids'], ['representative-id'])
        self.assertEqual(self.db.graph_representatives.count_documents({}), 0)
        self.assertEqual(self.db.component_hierarchy_nodes.count_documents({}), 6)
        self.assertEqual(self.db.meta_components.count_documents({}), 4)
        node = self.db.component_hierarchy_nodes.find_one()
        self.assertTrue(node['source_file'].startswith('clustered-day-'))
        lineage = json.loads(Path(paths['lineage']).read_text())
        child_ids = [value for meta in lineage['meta_components'] for value in meta['child_component_ids']]
        self.assertEqual(len(child_ids), len(set(child_ids)))
        self.assertEqual(len(child_ids), 6)
        meta = next(meta for meta in lineage['meta_components'] if meta['component_count'] == 2 and meta['numeric']['bytes']['mean'] < .2)
        self.assertAlmostEqual(meta['numeric']['bytes']['mean'], .115)
        self.assertAlmostEqual(meta['numeric']['bytes']['std'], float(np.std([.10, .12, .11, .13])))
        self.assertEqual(meta['behavior']['flag_syn'], {'count': 4, 'present': 4, 'prevalence': 1.})
        for name in ('evaluation', 'text', 'overview', 'interactive_lineage', 'lineage', 'graph'):
            self.assertGreater(Path(paths[name]).stat().st_size, 0)
        pages = evaluation['lineage_pages']
        self.assertEqual(sorted(i for page in pages for i in page['node_indices']), list(range(6)))
        html = Path(paths['interactive_lineage']).read_text()
        self.assertNotIn('https://', html)
        self.assertIn('Meta-component', html)

    def test_force_retains_previous_run_and_failed_report_preserves_active_pointer(self):
        first, _ = build_hierarchy(self.day)
        with self.assertRaisesRegex(ValueError, 'exists'):
            build_hierarchy(self.day)
        with patch('hierarchy.services.component_hierarchy_report.write_reports', side_effect=OSError('disk unavailable')):
            with self.assertRaisesRegex(OSError, 'disk unavailable'):
                build_hierarchy(self.day, force=True)
        active = self.db.component_hierarchy_graphs.find_one()['active_run_id']
        self.assertEqual(active, first['run_id'])
        self.assertEqual(self.db.component_hierarchy_runs.count_documents({'status': 'failed'}), 1)
        second, _ = build_hierarchy(self.day, force=True)
        self.assertNotEqual(first['run_id'], second['run_id'])
        self.assertEqual(self.db.component_hierarchy_runs.count_documents({'status': 'complete'}), 2)
        self.assertEqual(self.db.meta_components.count_documents({'run_id': first['run_id']}), 4)

    def test_missing_chunk_or_bad_membership_is_rejected_before_writes(self):
        self.db.graph_metadata.delete_one({'source_file': f'clustered-day-{self.day}-chunk-1'})
        with self.assertRaisesRegex(ValueError, 'Incomplete day graphs'):
            build_hierarchy(self.day)
        self.assertEqual(self.db.component_hierarchy_runs.count_documents({}), 0)

    def test_missing_member_and_stale_revision_are_rejected(self):
        self.db.graph_components.update_one({}, {'$set': {'graph_revision': 'outdated'}})
        with self.assertRaisesRegex(ValueError, 'Stale source component'):
            load_components(self.db, self.day)
        self.db.graph_components.update_many({'source_file': f'clustered-day-{self.day}-chunk-0'}, {'$set': {'graph_revision': 'revision-0'}})
        self.db.sampled_security_data.delete_one({})
        with self.assertRaisesRegex(ValueError, 'Missing sampled member'):
            build_hierarchy(self.day)

    def test_duplicate_profile_ties_remain_connected_with_bounded_degree(self):
        nodes, _, _ = load_components(self.db, self.day)
        prototype = nodes[0]
        nodes = [copy.deepcopy(prototype) for _ in range(15)]
        for i, node in enumerate(nodes):
            node['node_index'] = i; node['component_id'] = str(i)
        graph, _ = component_graph(nodes, Similarity(nodes), neighbors=2, degree_cap=2)
        self.assertTrue(nx.is_connected(graph))
        self.assertTrue(all(value == 2 for _, value in graph.degree()))

    def test_large_meta_lineage_is_paginated_without_omitting_children(self):
        from hierarchy.services.component_hierarchy_report import write_lineage_pages
        nodes, _, _ = load_components(self.db, self.day)
        children = [copy.deepcopy(nodes[0]) for _ in range(170)]
        for index, child in enumerate(children):
            child.update(node_index=index, component_id=str(index), chunk_index=index % 15, component_index=index // 15)
        metas = [{'meta_index': 0, 'meta_component_id': 'test-meta', 'node_indices': list(range(170)),
                  'component_count': 170, 'member_node_count': 340}]
        folder = Path(self.directory.name) / 'pagination'; folder.mkdir(exist_ok=True)
        pages = write_lineage_pages(folder, children, metas)
        self.assertEqual(len(pages), 3)
        self.assertEqual(sorted(index for page in pages for index in page['node_indices']), list(range(170)))
        self.assertTrue(all((folder / page['png']).exists() and (folder / page['svg']).exists() for page in pages))

    def test_missing_category_is_not_zero_similarity_and_labels_are_unused(self):
        nodes, _, _ = load_components(self.db, self.day)
        nodes[0]['categorical'] = {field: {} for field in CATEGORICAL}
        score, valid, details = Similarity(nodes).compare(0, [3])
        self.assertTrue(valid[0])
        self.assertFalse(details['categorical_available'][0])
        self.assertAlmostEqual(details['available_weight'][0], .6)
        self.assertGreater(score[0], .8)

    def test_distribution_shape_matters_even_when_means_match(self):
        nodes, _, _ = load_components(self.db, self.day)
        left, right = copy.deepcopy(nodes[0]), copy.deepcopy(nodes[0])
        for field in left['numeric']:
            left['numeric'][field].update(mean=.5, quantiles=[.1, .1, .1, .5, .9, .9, .9])
            right['numeric'][field].update(mean=.5, quantiles=[.5] * 7)
        score, valid, _ = Similarity([left, right]).compare(0, [1])
        self.assertTrue(valid[0])
        self.assertLess(score[0], .95)

    def test_meta_reports_weak_direct_similarity_hidden_by_connectivity(self):
        nodes, _, _ = load_components(self.db, self.day)
        children = [copy.deepcopy(nodes[0]) for _ in range(3)]
        for i, child in enumerate(children):
            child.update(node_index=i, component_id=str(i))
            for field in child['numeric']:
                child['numeric'][field].update(mean=.1 * (i + 1), quantiles=[.1 * (i + 1)] * 7)
        similarity = Similarity(children)
        graph, _ = component_graph(children, similarity, threshold=.5, neighbors=2, degree_cap=2)
        metas = meta_components(children, graph, similarity, 'test', .5)
        self.assertEqual(len(metas), 1)
        self.assertTrue(metas[0]['chaining_warning'])
        self.assertLess(metas[0]['pair_similarity_min'], .5)

    def test_command_checks_arguments(self):
        for options in ({'day': '2026-02-30'}, {'day': self.day, 'threshold': 2},
                        {'day': self.day, 'degree_cap': 1}):
            with self.assertRaises(CommandError):
                call_command('build_hierarchy_graph', stdout=io.StringIO(), **options)

    def test_source_change_during_reporting_does_not_publish_a_stale_run(self):
        from hierarchy.services.component_hierarchy_report import write_reports
        def change_source(*args, **kwargs):
            result = write_reports(*args, **kwargs)
            self.db.graph_metadata.update_one({}, {'$set': {'component_revision': 'changed-during-build'}})
            return result
        with patch('hierarchy.services.component_hierarchy_report.write_reports', side_effect=change_source):
            with self.assertRaisesRegex(ValueError, 'changed during build'):
                build_hierarchy(self.day)
        self.assertEqual(self.db.component_hierarchy_graphs.count_documents({}), 0)
        self.assertEqual(self.db.component_hierarchy_runs.find_one()['status'], 'failed')

    def test_single_component_day_has_a_singleton_meta(self):
        source = f'clustered-day-{self.day}-chunk-0'
        component = self.db.graph_components.find_one({'source_file': source, 'component_index': 0})
        keep_ids = component['node_ids']
        self.db.graph_metadata.delete_many({'source_file': {'$ne': source}})
        self.db.graph_metadata.update_one({'source_file': source}, {'$set': {
            'node_ids': keep_ids, 'edges': [{'source': 0, 'target': 1, 'weight': .99}]}})
        self.db.graph_components.delete_many({'component_id': {'$ne': component['component_id']}})
        originals = [row['original_id'] for row in self.db.sampled_security_data.find({'_id': {'$in': [ObjectId(value) for value in keep_ids]}})]
        self.db.security_data.delete_many({'_id': {'$nin': [ObjectId(value) for value in originals]}})
        evaluation, paths = build_hierarchy(self.day)
        self.assertEqual(evaluation['component_count'], 1)
        self.assertEqual(evaluation['meta_component_count'], 1)
        self.assertEqual(evaluation['edge_count'], 0)
        self.assertTrue(Path(paths['overview']).exists())
