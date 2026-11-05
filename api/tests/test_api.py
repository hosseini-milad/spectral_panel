import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mongomock
from django.core.management import CommandError,call_command
from django.test import override_settings
from rest_framework.test import APIClient
from pymongo.errors import ServerSelectionTimeoutError

from api import jobs,worker
from api.registry import ACTIONS,serializer_for,command_info,arguments


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name);self.settings=override_settings(BASE_DIR=self.root)
        self.settings.enable();self.addCleanup(self.settings.disable)
        self.db=mongomock.MongoClient().siem_db
        self.database=patch('api.db.get_database',return_value=self.db);self.database.start();self.addCleanup(self.database.stop)
        self.client=APIClient()

    def post(self,params=None,**headers):
        return self.client.post('/api/v1/actions/layer1/hyper-general-action/',
            params or {'source_file':'clustered-day-2026-06-17','limit':10},format='json',**headers)

    def test_action_queues_exact_command_and_never_executes_in_http(self):
        with patch('api.worker.call_command',side_effect=AssertionError('HTTP must not execute commands')):
            response=self.post({'source_file':'clustered-day-2026-06-17','limit':10,'force':True})
        self.assertEqual(response.status_code,202)
        row=self.db.api_jobs.find_one();self.assertEqual(row['status'],'queued')
        self.assertEqual(row['command'],'hyper-general-action')
        parsed=command_info(row['action'])['parser'].parse_args(row['arguments'])
        self.assertEqual(parsed.limit,10);self.assertTrue(parsed.force)
        self.assertEqual(parsed.sample_per_day,20000)

    def test_no_auth_swagger_schema_and_local_assets_do_not_need_mongodb(self):
        with patch('api.db.get_database',side_effect=AssertionError('Swagger must not query Mongo')):
            response=self.client.get('/swagger/')
            self.assertEqual(response.status_code,200)
            self.assertIn(b'drf_spectacular_sidecar',response.content)
            schema=self.client.get('/api/schema/?format=json')
            self.assertEqual(schema.status_code,200)
            data=schema.json();self.assertFalse(data.get('components',{}).get('securitySchemes'))
            path='/api/v1/actions/layer1/hyper-general-action/'
            ref=data['paths'][path]['post']['requestBody']['content']['application/json']['schema']['$ref'].split('/')[-1]
            properties=data['components']['schemas'][ref]['properties']
            self.assertIn('source_file',properties);self.assertEqual(properties['force']['default'],False)
            other=data['paths']['/api/v1/actions/maintenance/cleanup-legacy/']['post']['requestBody']['content']['application/json']['schema']['$ref']
            self.assertNotEqual(other.split('/')[-1],ref)
            asset=self.client.get('/static/drf_spectacular_sidecar/swagger-ui-dist/swagger-ui-bundle.js')
            self.assertEqual(asset.status_code,200);asset.close()

    def test_all_actions_are_explicit_and_catalog_has_cli_defaults(self):
        response=self.client.get('/api/v1/actions/');self.assertEqual(response.status_code,200)
        rows=response.json()['actions'];self.assertEqual(len(rows),len(ACTIONS))
        from django.core.management import get_commands
        expected={name for name,app in get_commands().items() if app in ('ingestion','spectral_learning','hierarchy')}
        self.assertEqual(set(ACTIONS.values()),expected)
        import ingestion.urls
        self.assertEqual(len(ingestion.urls.urlpatterns),5)
        hyper=next(r for r in rows if r['command']=='hyper-general-action')
        self.assertEqual(next(p['default'] for p in hyper['parameters'] if p['name']=='sample_per_day'),20000)
        self.assertEqual(self.client.post('/api/v1/actions/shell/',{},format='json').status_code,404)

    def test_invalid_missing_extra_and_nonfinite_inputs_fail_before_queue(self):
        for params in [{},{'source_file':'x','unknown':True},{'source_file':'x','settings':'other'},
                       {'source_file':'x','limit':'not-an-int'}]:
            response=self.client.post('/api/v1/actions/layer1/hyper-general-action/',params,format='json')
            self.assertEqual(response.status_code,400)
        serializer=serializer_for('layer1/hyper-general-action')(data={'source_file':'x','threshold':float('nan')})
        self.assertFalse(serializer.is_valid());self.assertEqual(self.db.api_jobs.count_documents({}),0)

    def test_lists_and_mutually_exclusive_command_inputs(self):
        s=serializer_for('behavior/train-neighborhood')(data={'reference_bundle':'bundle','days':['2026-06-23'],'seeds':[17]})
        self.assertTrue(s.is_valid(),s.errors)
        parsed=command_info('behavior/train-neighborhood')['parser'].parse_args(arguments('behavior/train-neighborhood',s.validated_data))
        self.assertEqual(parsed.seeds,[17]);self.assertEqual(parsed.days,['2026-06-23'])
        s=serializer_for('behavior/analyze-hierarchy')(data={});self.assertFalse(s.is_valid())
        s=serializer_for('behavior/analyze-hierarchy')(data={'signal_bundle':'a','signal_run_id':'b'});self.assertFalse(s.is_valid())
        s=serializer_for('behavior/train-neighborhood')(data={'reference_bundle':'bundle','days':['--force']});self.assertFalse(s.is_valid())

    def test_directory_is_a_literal_argument_not_shell_code(self):
        directory='F:/parquet/folder with spaces; echo should-not-run'
        s=serializer_for('ingestion/ingest-parquet')(data={'directory':directory})
        self.assertTrue(s.is_valid(),s.errors)
        parsed=command_info('ingestion/ingest-parquet')['parser'].parse_args(arguments('ingestion/ingest-parquet',s.validated_data))
        self.assertEqual(parsed.directory,directory)

    def test_idempotency_prevents_repeated_force_submission_and_rejects_conflict(self):
        params={'source_file':'clustered-day-2026-06-17','limit':10,'force':True}
        a=self.post(params,HTTP_IDEMPOTENCY_KEY='force-day17-once')
        b=self.post(params,HTTP_IDEMPOTENCY_KEY='force-day17-once')
        self.assertEqual(a.json()['job']['id'],b.json()['job']['id'])
        self.assertFalse(b.json()['created']);self.assertEqual(self.db.api_jobs.count_documents({}),1)
        c=self.post(dict(params,limit=11),HTTP_IDEMPOTENCY_KEY='force-day17-once')
        self.assertEqual(c.status_code,409)

    def test_queue_cancellation_and_running_cancellation_conflict(self):
        job=self.post().json()['job'];url=f"/api/v1/jobs/{job['id']}/cancel/"
        self.assertEqual(self.client.post(url).json()['status'],'cancelled')
        self.assertEqual(self.client.post(url).status_code,409)
        self.db.api_jobs.update_one({'_id':job['id']},{'$set':{'status':'running'}})
        self.assertEqual(self.client.post(url).status_code,409)

    def test_worker_calls_existing_command_and_persists_logs_and_result(self):
        job=self.post().json()['job'];owner=worker.acquire_lock(self.db)
        def execute(name,*args,**kwargs):
            self.assertEqual(name,'hyper-general-action');print('سلام از کامند')
        with patch('api.worker.call_command',side_effect=execute) as runner:
            self.assertTrue(worker.execute_one(self.db,owner));self.assertFalse(worker.execute_one(self.db,owner))
        runner.assert_called_once()
        response=self.client.get(job['detail_url']);self.assertEqual(response.json()['status'],'succeeded')
        logs=self.client.get(job['logs_url']).json();self.assertIn('سلام از کامند',logs['text'])
        self.assertTrue(logs['finished']);self.assertTrue((jobs.job_folder(job['id'])/'result.json').exists())

    def test_worker_failure_keeps_cause_without_retry(self):
        job=self.post().json()['job'];owner=worker.acquire_lock(self.db)
        with patch('api.worker.call_command',side_effect=CommandError('source mismatch')):
            worker.execute_one(self.db,owner)
        result=self.client.get(job['detail_url']).json()
        self.assertEqual(result['status'],'failed');self.assertEqual(result['error']['message'],'source mismatch')
        self.assertFalse(worker.execute_one(self.db,owner))

    def test_worker_does_not_steal_live_lock(self):
        owner=worker.acquire_lock(self.db)
        with self.assertRaisesRegex(RuntimeError,'Another API worker'):
            worker.acquire_lock(self.db)
        self.assertEqual(self.db.api_runtime.find_one()['owner'],owner)

    def test_stale_worker_recovers_interruption_without_reexecuting_force(self):
        job=self.post().json()['job'];self.db.api_jobs.update_one({'_id':job['id']},{'$set':{'status':'running'}})
        self.db.api_runtime.insert_one(dict(_id=worker.LOCK,owner='old',hostname=socket.gethostname(),pid=999999999,
                                           process_created_at=0,job_id=job['id']))
        owner=worker.acquire_lock(self.db)
        self.assertEqual(self.db.api_jobs.find_one()['status'],'interrupted')
        self.assertFalse(worker.execute_one(self.db,owner))

    def test_restart_recovers_completed_job_even_if_lock_job_update_was_lost(self):
        job=self.post().json()['job']
        self.db.api_jobs.update_one({'_id':job['id']},{'$set':{'status':'running'}})
        folder=jobs.job_folder(job['id']);folder.mkdir(parents=True)
        (folder/'result.json').write_text(json.dumps({'status':'succeeded','error':None}))
        with patch('api.worker.call_command',side_effect=AssertionError('Must not retry completed job')):
            worker.run_worker(once=True,output=lambda message:None)
        self.assertEqual(self.db.api_jobs.find_one()['status'],'succeeded')
        self.assertEqual(self.db.api_runtime.count_documents({}),0)

    def test_interruption_marks_job_and_is_never_automatically_retried(self):
        self.post();owner=worker.acquire_lock(self.db)
        with patch('api.worker.call_command',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):worker.execute_one(self.db,owner)
        self.assertEqual(self.db.api_jobs.find_one()['status'],'interrupted')
        self.assertFalse(worker.execute_one(self.db,owner))

    def test_utf8_log_offsets_preserve_persian_characters(self):
        job=self.post().json()['job'];folder=jobs.job_folder(job['id']);folder.mkdir(parents=True)
        (folder/'stdout.log').write_text('سلام\n',encoding='utf-8')
        a=self.client.get(job['logs_url'],{'limit':5}).json()
        b=self.client.get(job['logs_url'],{'limit':5,'offset':a['next_offset']}).json()
        self.assertEqual(a['text']+b['text'],'سلام\n')

    def test_reports_reject_path_traversal_and_serve_generated_png(self):
        folder=self.root/'document/report';folder.mkdir(parents=True)
        (folder/'plot.png').write_bytes(b'png-test')
        self.assertEqual(self.client.get('/api/v1/artifacts/',{'path':'../'}).status_code,400)
        self.assertEqual(self.client.get('/api/v1/artifacts/file/',{'path':'../../config/settings.py'}).status_code,400)
        result=self.client.get('/api/v1/artifacts/',{'path':'report'}).json()
        self.assertEqual(result['results'][0]['path'],'report/plot.png')
        file=self.client.get('/api/v1/artifacts/file/',{'path':'report/plot.png'})
        self.assertEqual(b''.join(file.streaming_content),b'png-test');file.close()

    def test_days_chunks_report_partial_state_without_modifying_data(self):
        day='2026-06-17';source=f'clustered-day-{day}-chunk-0'
        self.db.security_data.insert_many([dict(source_day=day),dict(source_day=day)])
        self.db.graph_metadata.insert_one(dict(source_file=source,node_ids=['n'],edges=[]))
        self.db.sampled_security_data.insert_one(dict(source_day=day,chunk_index=0))
        self.assertEqual(self.client.get('/api/v1/days/').json()['results'][0]['raw_records'],2)
        response=self.client.get(f'/api/v1/days/{day}/chunks/').json()
        self.assertTrue(response['chunks_are_processing_partitions'])
        self.assertEqual(response['results'][0]['graph']['nodes'],1)
        self.assertEqual(response['results'][0]['normalized_records'],0)
        self.assertEqual(self.db.graph_metadata.count_documents({}),1)

    def test_db_error_returns_503_without_running_command(self):
        with patch('api.db.get_database',side_effect=ServerSelectionTimeoutError('offline')):
            self.assertEqual(self.post().status_code,503)

    def test_real_command_replay_exports_preview_and_is_available_through_artifact_route(self):
        day='2026-06-15';source=f'clustered-day-{day}-chunk-0';n=40
        self.db.graph_metadata.insert_one(dict(source_file=source,source_day=day,node_ids=[f'n{i}' for i in range(n)],
            node_labels=[0]*n,features=[[1.,1.]]*n,edges=[dict(source=i,target=i+1,weight=.99) for i in range(n-1)]))
        for i in [17,18,19,20]:
            self.db.graph_representatives.insert_one(dict(source_file=source,node_index=i,original_id=f'n{i}',label=0))
        response=self.client.post('/api/v1/actions/layer1/preview-representative-spread/',{'day':day,'chunk_index':0},format='json')
        self.assertEqual(response.status_code,202)
        with patch('ingestion.management.commands.preview_representative_spread.get_db',return_value=self.db):
            call_command('run_api_worker',once=True)
        job=self.client.get(response.json()['job']['detail_url']).json()
        self.assertEqual(job['status'],'succeeded',job['error'])
        image=next((self.root/'document').glob('nominal/**/representative_spread_comparison.png'))
        download=self.client.get('/api/v1/artifacts/file/',{'path':str(image.relative_to(self.root/'document'))})
        self.assertEqual(download.status_code,200);download.close()
        self.assertEqual(self.db.graph_representatives.count_documents({}),4)
