import io
import json
import tempfile
import unittest
import uuid
from pathlib import Path

from bson import ObjectId
from django.conf import settings
from django.core.management import call_command, CommandError
from django.test import override_settings
from mongoengine import connect, disconnect, get_db

from ingestion.models.graph_component import GraphComponent
from ingestion.models.graph_metadata import GraphMetadata
from ingestion.services.graph.components import persist_components
from ingestion.utils.document_paths import document_directory


class ComponentIntegrationTests(unittest.TestCase):
    """Exercise real MongoDB in an isolated disposable database, never siem_db."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.overrides = override_settings(BASE_DIR=Path(cls.directory.name))
        cls.overrides.enable()
        disconnect()
        connect('test_components_' + uuid.uuid4().hex, host='localhost', port=27017,
                serverSelectionTimeoutMS=5000)
        cls.db = get_db()
        cls.db.client.admin.command('ping')

    @classmethod
    def tearDownClass(cls):
        cls.db.client.drop_database(cls.db.name)
        disconnect()
        connect('siem_db', host='localhost', port=27017)
        cls.overrides.disable()
        cls.directory.cleanup()

    def setUp(self):
        for name in self.db.list_collection_names():
            self.db[name].delete_many({})
        self.source = 'clustered-day-2026-06-21-chunk-0'
        self.docs = [{'_id': ObjectId(), 'bytes': value, 'protocol': 'tcp',
                      'source_file': 'input.parquet', 'source_day': '2026-06-21'}
                     for value in [10, 20, 30, 100, 200, 999]]
        self.db.sampled_security_data.insert_many(self.docs)
        self.metadata = {
            'source_file': self.source, 'source_day': '2026-06-21',
            'node_ids': [str(doc['_id']) for doc in self.docs],
            'edges': [{'source': a, 'target': b, 'weight': .99}
                      for a, b in [(0, 1), (1, 2), (0, 2), (3, 4)]],
            'graph_parameters': {'layer': 1, 'chunk_index': 0},
        }
        self.db.graph_metadata.insert_one(dict(self.metadata))

    def test_membership_profiles_isolates_reports_and_repeatability(self):
        first = persist_components(self.metadata)
        self.assertEqual([row['node_count'] for row in first['components']], [3, 2, 1])
        self.assertEqual(first['components'][0]['mean_features']['bytes'], 20)
        self.assertEqual(first['components'][0]['feature_observation_counts']['bytes'], 3)
        self.assertTrue(first['components'][2]['component_statistics']['is_isolate'])
        self.assertEqual(first['components'][0]['component_statistics']['cycle_rank'], 1)
        ids = [row['component_id'] for row in first['components']]
        self.db.graph_representatives.insert_one({
            'source_file': self.source, 'node_index': 0,
            'original_id': self.metadata['node_ids'][0],
        })
        second = persist_components(self.metadata)
        self.assertEqual(ids, [row['component_id'] for row in second['components']])
        self.assertEqual(second['components'][0]['mean_features']['bytes'], 20)
        self.assertEqual(second['components'][0]['representative_profile']['mean']['bytes'], 10)
        self.assertEqual(GraphComponent.objects.count(), 3)
        self.assertEqual(GraphMetadata.objects.first().component_status, 'complete')
        self.assertEqual(self.db.graph_representatives.find_one()['component_id'], ids[0])
        call_command('verify_graph_components', source_file=self.source, stdout=io.StringIO())
        for path in second['paths'].values():
            self.assertGreater(Path(path).stat().st_size, 0)
            self.assertIn('/document/component/layer1/2026-06-21/chunk-0/', path)
        payload = json.loads(Path(second['paths']['json']).read_text())
        self.assertTrue(payload['integrity']['partition_complete'])
        self.assertTrue(payload['integrity']['profiles_complete'])

    def test_backfill_without_representatives_and_missing_sources(self):
        self.db.sampled_security_data.delete_one({'_id': self.docs[-1]['_id']})
        output = io.StringIO()
        call_command('evaluate_graph_components', source_file=self.source, stdout=output)
        self.assertIn('missing_sources=1', output.getvalue())
        self.assertEqual(GraphComponent.objects.count(), 3)
        row = GraphComponent.objects(component_index=2).first()
        self.assertEqual(row.node_count, 1)
        self.assertEqual(row.missing_node_ids, [str(self.docs[-1]['_id'])])

    def test_invalid_graph_does_not_replace_saved_components(self):
        first = persist_components(self.metadata, write_reports=False)
        self.metadata['edges'].append({'source': 0, 'target': 100, 'weight': 1})
        with self.assertRaises(ValueError):
            persist_components(self.metadata)
        self.assertEqual(GraphComponent.objects.count(), 3)
        self.assertEqual(GraphComponent.objects.first().graph_revision, first['graph_revision'])

    def test_repartition_replaces_stale_memberships_without_index_conflicts(self):
        first = persist_components(self.metadata, write_reports=False)
        self.metadata['edges'].append({'source': 2, 'target': 3, 'weight': .98})
        second = persist_components(self.metadata, write_reports=False)
        self.assertEqual([row['node_count'] for row in second['components']], [5, 1])
        self.assertEqual(GraphComponent.objects.count(), 2)
        self.assertEqual(first['components'][-1]['component_id'], second['components'][-1]['component_id'])

    def test_layer2_separate_edges_and_parent_lineage(self):
        parents = persist_components(self.metadata, write_reports=False)['components']
        docs = [{'_id': ObjectId(), 'original_id': self.metadata['node_ids'][index],
                 'source_file': self.source, 'component_id': row['component_id']}
                for index, row in enumerate(parents)]
        self.db.graph_representatives.insert_many(docs)
        metadata = {
            'source_file': 'hierarchy-day-2026-06-21-layer-2', 'source_day': '2026-06-21',
            'node_ids': [str(doc['_id']) for doc in docs],
            'edge_collection': 'hyper_graph_edges', 'edge_count': 1,
            'graph_parameters': {'layer': 2}, 'status': 'complete',
        }
        self.db.hyper_graph_metadata.insert_one(dict(metadata))
        self.db.hyper_graph_edges.insert_one({'source_file': metadata['source_file'],
                                             'source': 0, 'target': 1, 'weight': .98})
        result = persist_components(metadata, graph_collection='hyper_graph_metadata')
        self.assertEqual([row['node_count'] for row in result['components']], [2, 1])
        self.assertEqual(set(result['components'][0]['parent_component_ids']),
                         {parents[0]['component_id'], parents[1]['component_id']})
        self.assertIn('/layer2/2026-06-21/whole-day/', result['paths']['json'])

    def test_graph_stage_saves_components_before_representative_stage(self):
        from ingestion.pipelines.graph_pipeline import run_graph_pipeline
        from ingestion.pipelines.pooling_pipeline import run_pooling
        source = 'pipeline-day-2026-06-22-chunk-0'
        docs = [{'_id': ObjectId(), 'source_file': source, 'source_day': '2026-06-22',
                 'chunk_index': 0, 'bytes': a, 'packets': b, 'label': 0}
                for a, b in [(1., 0.), (.99, .01), (0., 1.), (.01, .99), (0., 0.)]]
        self.db.sampled_security_data.insert_many(docs)
        run_graph_pipeline(source_file=source, feature_fields=['bytes', 'packets'],
                           k=1, threshold=.95, degree_cap=2, workers=1, create_visualization=False)
        self.assertEqual(GraphComponent.objects(source_file=source).count(), 3)
        graph = GraphMetadata.objects(source_file=source).first()
        by_id = {str(doc['_id']): doc for doc in docs}
        ordered_docs = [by_id[value] for value in graph.node_ids]
        ids_before = set(GraphComponent.objects(source_file=source).distinct('component_id'))
        run_pooling(source, graph.edges, graph.features, ordered_docs, ratio=.4,
                    anomaly_scores={i: 0 for i in range(5)}, create_visualization=False)
        self.assertEqual(ids_before, set(GraphComponent.objects(source_file=source).distinct('component_id')))
        call_command('verify_graph_components', source_file=source, stdout=io.StringIO())

    def test_document_path_isolation_and_empty_selection(self):
        path = document_directory('nominal', 'random-day-2026-06-21-chunk-4')
        self.assertIn('/nominal/layer1/2026-06-21/chunk-4/', str(path))
        self.assertNotEqual(path, document_directory('nominal', 'clustered-day-2026-06-21-chunk-4'))
        with self.assertRaises(CommandError):
            call_command('evaluate_graph_components', source_file='absent', stdout=io.StringIO())

    def test_legacy_component_identity_survives_profile_upgrade(self):
        legacy_id = ObjectId()
        self.db.graph_components.insert_one({
            '_id': legacy_id, 'component_id': str(legacy_id), 'source_file': self.source,
            'layer': 1, 'component_index': 0, 'node_indices': [0, 1, 2],
            'node_ids': self.metadata['node_ids'][:3], 'node_count': 3,
            'mean_features': {'bytes': 10},
        })
        result = persist_components(self.metadata, write_reports=False)
        self.assertEqual(result['components'][0]['component_id'], str(legacy_id))
        self.assertEqual(result['components'][0]['mean_features']['bytes'], 20)

    def test_integrity_audit_rejects_wrong_partition_with_full_coverage(self):
        persist_components(self.metadata, write_reports=False)
        rows = list(self.db.graph_components.find({}).sort('component_index', 1))
        # Swap nodes between two components while preserving counts and coverage.
        left, right = rows[:2]
        left['node_indices'][0], right['node_indices'][0] = right['node_indices'][0], left['node_indices'][0]
        left['node_ids'][0], right['node_ids'][0] = right['node_ids'][0], left['node_ids'][0]
        for row in (left, right):
            self.db.graph_components.replace_one({'_id': row['_id']}, row)
        with self.assertRaises(CommandError):
            call_command('verify_graph_components', source_file=self.source, stdout=io.StringIO(), stderr=io.StringIO())
