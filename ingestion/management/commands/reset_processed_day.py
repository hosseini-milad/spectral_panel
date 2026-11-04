"""Explicit no-backup reset of allowlisted derived data, never security_data."""
from datetime import date,datetime,timezone
from pathlib import Path
import json
import re
import shutil
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from mongoengine import get_db

STAGES={
    'component_hierarchy_runs':('component_hierarchy_graphs','component_hierarchy_nodes','component_hierarchy_edges','meta_components'),
    'spectral_analysis_runs':('spectral_analysis_active','spectral_graphs','spectral_blocks','spectral_node_encodings','spectral_edge_encodings'),
    'spectral_message_passing_runs':('spectral_message_passing_active','spectral_message_passing_graphs','spectral_message_passing_nodes','spectral_pooled_features'),
    'autoencoder_runs':('autoencoder_active',),
    'upper_spectral_runs':('upper_spectral_active','upper_spectral_graphs','upper_spectral_nodes','upper_spectral_edges','upper_spectral_components'),
}


def reset_processed_day(db,day,base_dir,*,apply=False,report=None):
    if date.fromisoformat(day).isoformat()!=day:raise ValueError('Use YYYY-MM-DD')
    raw_count=db.security_data.count_documents({'source_day':day})
    if not raw_count:raise ValueError('No raw records for requested day; nothing reset')
    # Restrict to explicit derived collections and an exact date token.
    pattern=rf'(?:^|[-_]){re.escape(day)}(?:[-_]|$)'
    scoped={'$or':[{'source_day':day},{'source_day':None,'$or':[
        {'source_file':{'$regex':pattern}},{'graph_key':{'$regex':pattern}}]}]}
    queries={}
    for runs,children in STAGES.items():
        ids=[r['_id'] for r in db[runs].find({'source_day':day},{'_id':1})]
        queries[runs]={'source_day':day}
        for name in children:
            queries[name]={'$or':[scoped,{'run_id':{'$in':ids}},{'active_run_id':{'$in':ids}}]}
    hierarchy_ids=[r['_id'] for r in db.component_hierarchy_runs.find({'source_day':day},{'_id':1})]
    group_ids=[r['_id'] for r in db.behavior_group_observations.find({'entity.day':day},{'_id':1})]
    node_runs=[r['_id'] for r in db.behavior_analysis_runs.find({'$or':[
        {f'identity.source_signatures.{day}':{'$exists':True}},
        {f'identity.protected_historical_signatures.{day}':{'$exists':True}}]}, {'_id':1})]
    group_runs=[r['_id'] for r in db.behavior_hierarchy_runs.find({'$or':[
        {f'identity.hierarchy.{day}':{'$exists':True}}, {'parent_signal_run_id':{'$in':node_runs}}]}, {'_id':1})]
    queries.update({
        'behavior_observations':{'entity.source_day':day},
        'behavior_group_observations':{'entity.day':day},
        'behavior_hierarchy_memberships':{'$or':[{'parent_group_observation_id':{'$in':group_ids}},
                                                   {'hierarchy_run_id':{'$in':hierarchy_ids}}]},
    })
    for name in ('graph_representatives','graph_components','graph_metadata','hyper_representatives','hyper_graph_edges','hyper_graph_metadata'):
        queries[name]=scoped
    for name in ('sampled_security_data','normalized_security_data'):
        queries[name]={'source_day':day}
    document=Path(base_dir)/'document';paths=[]
    for category in ('nominal','component','report','hierarchy','spectral','autoencoder'):
        for path in (document/category).glob(f'layer*/{day}'):
            if path.is_symlink() or not path.resolve().is_relative_to(document.resolve()):
                raise ValueError('Unsafe generated-report path; reset not started')
            paths.append(path)
    folder=document/'report'/'database-maintenance'/('force-reset-'+uuid.uuid4().hex)
    folder.mkdir(parents=True,exist_ok=False)
    existing=set(db.list_collection_names())
    plan=[dict(collection=name,query=query,matched=db[name].count_documents(query),deleted=0)
          for name,query in queries.items() if name in existing]
    manifest=dict(version='processed_day_reset_v1',day=day,database=db.name,apply=apply,backup_created=False,
        status='planning',raw_records_preserved=raw_count,collections=plan,
        generated_day_directories=[str(p.relative_to(document)) for p in paths],
        invalidated_node_run_ids=node_runs,invalidated_group_run_ids=group_runs,
        created_at=datetime.now(timezone.utc).isoformat())
    def save():
        (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    save()
    try:
        if apply:
            # Invalidate cross-day run pointers, retaining unrelated-day evidence.
            for name,ids in [('behavior_analysis_runs',node_runs),('behavior_hierarchy_runs',group_runs)]:
                if ids:
                    db[name].update_many({'_id':{'$in':ids}},{'$set':{'status':'invalidated',
                        'invalidation_reason':'source_day_force_reset','invalidated_source_day':day}})
            manifest['status']='deleting';save()
            for row in plan:
                if row['collection']=='security_data':raise AssertionError('Raw data is never a reset target')
                row['deleted']=db[row['collection']].delete_many(row['query']).deleted_count;save()
                if report and row['deleted']:report(f"[FORCE RESET] {row['collection']}: deleted={row['deleted']}")
            for path in paths:shutil.rmtree(path)
            if db.security_data.count_documents({'source_day':day})!=raw_count:
                raise ValueError('Raw count changed externally; this command never writes raw data')
        manifest['status']='complete';save()
    except BaseException as exc:
        manifest.update(status='failed',error=str(exc));save();raise
    if report:report(f'[FORCE RESET] day={day}; raw preserved={raw_count}; no backup; report={folder}')
    return manifest


class Command(BaseCommand):
    help='Preview or permanently delete derived records/reports for one day, without backup; preserve raw and other days. Stop active pipelines first.'
    requires_system_checks=[]

    def add_arguments(self,parser):
        parser.add_argument('--day',required=True)
        parser.add_argument('--apply',action='store_true')

    def handle(self,*args,**options):
        try:
            reset_processed_day(get_db(),options['day'],settings.BASE_DIR,apply=options['apply'],report=self.stdout.write)
        except Exception as exc:
            raise CommandError(f'Processed-day reset failed: {exc}') from exc
