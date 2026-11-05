import codecs
from datetime import date
from pathlib import Path
import re

from django.conf import settings
from django.http import FileResponse,Http404
from pymongo import timeout
from pymongo.errors import PyMongoError
from rest_framework import serializers,status
from rest_framework.exceptions import NotFound,ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema,OpenApiTypes,OpenApiParameter

from . import db as database
from .jobs import submit,public_job,cancel_queued,Conflict,job_folder,FINAL_STATES
from .registry import ACTIONS,command_info,serializer_for
from .serializers import (JobSerializer,SubmissionSerializer,PageQuery,JobQuery,LogQuery,
                          ArtifactQuery,ArtifactListQuery)


def validate_query(cls,request):
    serializer=cls(data=request.query_params);serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def worker_status(db):
    from .jobs import now
    lock=db.api_runtime.find_one({'_id':'scientific-command-worker'})
    if not lock:return dict(online=False,current_job_id=None)
    heartbeat=lock.get('heartbeat_at');age=None
    if heartbeat:
        if heartbeat.tzinfo is None:
            from datetime import timezone
            heartbeat=heartbeat.replace(tzinfo=timezone.utc)
        age=max(0.,(now()-heartbeat).total_seconds())
    return dict(online=age is not None and age<15,current_job_id=lock.get('job_id'),heartbeat_age_seconds=age)


class DatabaseView(APIView):
    def dispatch(self,request,*args,**kwargs):
        with timeout(settings.API_DB_TIMEOUT_SECONDS):
            return super().dispatch(request,*args,**kwargs)

    def handle_exception(self,exc):
        if isinstance(exc,PyMongoError):
            return Response(dict(detail='MongoDB is unavailable or timed out.',error_type=type(exc).__name__),status=503)
        if isinstance(exc,Conflict):return Response(dict(detail=str(exc)),status=409)
        return super().handle_exception(exc)


class HealthView(DatabaseView):
    @extend_schema(tags=['System'],responses=OpenApiTypes.OBJECT)
    def get(self,request):
        db=database.get_database();db.api_jobs.count_documents({})
        return Response(dict(status='ok',database=db.name,worker=worker_status(db)))


class ActionCatalogView(APIView):
    @extend_schema(tags=['System'],responses=OpenApiTypes.OBJECT)
    def get(self,request):
        return Response(dict(actions=[dict(action=key,command=command_info(key)['command'],
            route=f'/api/v1/actions/{key}/',method='POST',description=command_info(key)['help'],
            parameters=command_info(key)['parameters']) for key in ACTIONS]))


class ActionView(DatabaseView):
    action_key=None
    serializer_class=None

    def post(self,request):
        serializer=self.serializer_class(data=request.data);serializer.is_valid(raise_exception=True)
        key=request.headers.get('Idempotency-Key')
        if key is not None and (not key.strip() or len(key)>128):
            raise ValidationError({'Idempotency-Key':'Use 1..128 nonblank characters.'})
        job,created=submit(self.action_key,dict(serializer.validated_data),key)
        code=202 if created or job['status'] not in FINAL_STATES else 200
        return Response(dict(job=public_job(job),created=created),status=code,
                        headers={'Location':f"/api/v1/jobs/{job['_id']}/"})


def action_view(action):
    serializer=serializer_for(action);info=command_info(action)
    cls=type(serializer.__name__.replace('Request','ActionView'),(ActionView,),
             dict(action_key=action,serializer_class=serializer,__module__='api.views'))
    def post(self,request):
        return ActionView.post(self,request)
    cls.post=extend_schema(request=serializer,responses={202:SubmissionSerializer,200:SubmissionSerializer},
        tags=[action.split('/')[0].title()],operation_id=info['command'].replace('-','_'),
        summary=info['command'],description=info['help']+'\n\nEnqueues the unchanged CLI command; requires run_api_worker. HTTP 202 is not command completion.',
        parameters=[OpenApiParameter('Idempotency-Key',str,OpenApiParameter.HEADER,required=False,
                                     description='Reuse a key to avoid duplicate submission of the same action/parameters.')])(post)
    return cls.as_view()


class JobListView(DatabaseView):
    @extend_schema(tags=['Jobs'],operation_id='list_jobs',parameters=[JobQuery],responses=OpenApiTypes.OBJECT)
    def get(self,request):
        query=validate_query(JobQuery,request);db=database.get_database()
        selector={'status':query['status']} if 'status' in query else {}
        records=db.api_jobs.find(selector).sort([('created_at',-1),('_id',-1)]).skip(query['offset']).limit(query['limit'])
        return Response(dict(count=db.api_jobs.count_documents(selector),results=[public_job(r) for r in records],worker=worker_status(db)))


class JobDetailView(DatabaseView):
    @extend_schema(tags=['Jobs'],operation_id='retrieve_job',responses=JobSerializer)
    def get(self,request,job_id):
        row=database.get_database().api_jobs.find_one({'_id':str(job_id)})
        if not row:raise NotFound('Job not found.')
        return Response(public_job(row))


class JobCancelView(DatabaseView):
    @extend_schema(tags=['Jobs'],request=None,responses=JobSerializer,
                   description='Cancels a queued job only. Running scientific commands are never killed by this endpoint.')
    def post(self,request,job_id):
        try:row=cancel_queued(str(job_id))
        except KeyError:raise NotFound('Job not found.')
        return Response(public_job(row))


class JobLogsView(DatabaseView):
    @extend_schema(tags=['Jobs'],parameters=[LogQuery],responses=OpenApiTypes.OBJECT)
    def get(self,request,job_id):
        query=validate_query(LogQuery,request)
        row=database.get_database().api_jobs.find_one({'_id':str(job_id)})
        if not row:raise NotFound('Job not found.')
        path=job_folder(job_id)/'stdout.log';offset=query['offset'];next_offset=offset;text='';size=0
        if path.is_file():
            size=path.stat().st_size
            if offset>size:raise ValidationError({'offset':'Offset exceeds current log size.'})
            with path.open('rb') as stream:
                stream.seek(offset);chunk=stream.read(query['limit'])
            decoder=codecs.getincrementaldecoder('utf-8')(errors='replace');text=decoder.decode(chunk,final=False)
            next_offset=offset+len(chunk)-len(decoder.getstate()[0])
        return Response(dict(id=str(job_id),status=row['status'],text=text,offset=offset,next_offset=next_offset,
            byte_size=size,has_more=next_offset<size,finished=row['status'] in FINAL_STATES))


def artifact_path(value):
    root=(settings.BASE_DIR/'document').resolve();path=(root/value).resolve()
    if not path.is_relative_to(root):raise ValidationError({'path':'Path must stay inside document/.'})
    return root,path


class ArtifactListView(APIView):
    @extend_schema(tags=['Reports'],parameters=[ArtifactListQuery],responses=OpenApiTypes.OBJECT)
    def get(self,request):
        query=validate_query(ArtifactListQuery,request);root,path=artifact_path(query['path'])
        if not path.is_dir():raise NotFound('Report directory not found.')
        children=sorted(path.iterdir(),key=lambda p:(not p.is_dir(),p.name.lower()))
        result=[]
        for item in children:
            resolved=item.resolve()
            if not resolved.is_relative_to(root):continue
            result.append(dict(name=item.name,path=str(item.relative_to(root)).replace('\\','/'),
                is_directory=item.is_dir(),bytes=item.stat().st_size if item.is_file() else None))
        return Response(dict(count=len(result),results=result[query['offset']:query['offset']+query['limit']]))


class ArtifactFileView(APIView):
    @extend_schema(tags=['Reports'],parameters=[ArtifactQuery],responses=OpenApiTypes.BINARY)
    def get(self,request):
        query=validate_query(ArtifactQuery,request);_,path=artifact_path(query['path'])
        if not path.is_file():raise NotFound('Report file not found.')
        inline=path.suffix.lower() in ('.png','.jpg','.jpeg','.webp')
        return FileResponse(path.open('rb'),as_attachment=not inline,filename=path.name)


class DaysView(DatabaseView):
    @extend_schema(tags=['Data'],parameters=[PageQuery],responses=OpenApiTypes.OBJECT)
    def get(self,request):
        query=validate_query(PageQuery,request);db=database.get_database()
        rows=list(db.security_data.aggregate([{'$match':{'source_day':{'$type':'string'}}},
            {'$group':{'_id':'$source_day','raw_records':{'$sum':1}}},{'$sort':{'_id':1}}]))
        return Response(dict(count=len(rows),results=[dict(day=r['_id'],raw_records=r['raw_records'])
            for r in rows[query['offset']:query['offset']+query['limit']]]))


class ChunksView(DatabaseView):
    @extend_schema(tags=['Data'],responses=OpenApiTypes.OBJECT)
    def get(self,request,day):
        try:
            if date.fromisoformat(day).isoformat()!=day:raise ValueError()
        except ValueError:raise ValidationError({'day':'Use YYYY-MM-DD.'})
        db=database.get_database();prefix=f'clustered-day-{day}-chunk-';pattern='^'+re.escape(prefix)+r'\d+$';chunks={};unassigned={}
        for collection,index,name in [('normalized_security_data','normalization_chunk_index','normalized_records'),
                                       ('sampled_security_data','chunk_index','candidate_records')]:
            for row in db[collection].aggregate([{'$match':{'source_day':day}},{'$group':{'_id':'$'+index,'count':{'$sum':1}}}]):
                if isinstance(row['_id'],int) and not isinstance(row['_id'],bool):
                    chunks.setdefault(row['_id'],{'chunk_index':row['_id']})[name]=row['count']
                else:
                    unassigned[name]=unassigned.get(name,0)+row['count']
        for row in db.graph_metadata.aggregate([{'$match':{'source_file':{'$regex':pattern}}},{'$project':{
            'source_file':1,'graph_parameters':1,'component_status':1,
            'nodes':{'$size':{'$ifNull':['$node_ids',[]]}},'edges':{'$size':{'$ifNull':['$edges',[]]}}}}]):
            i=int(row['source_file'][len(prefix):]);entry=chunks.setdefault(i,{'chunk_index':i})
            entry['graph']={k:v for k,v in row.items() if k!='_id'}
        for collection,name in [('graph_representatives','representatives'),('graph_components','components')]:
            match={'source_file':{'$regex':pattern}}
            if name=='components':match['layer']=1
            for row in db[collection].aggregate([{'$match':match},{'$group':{'_id':'$source_file','count':{'$sum':1}}}]):
                i=int(row['_id'][len(prefix):]);chunks.setdefault(i,{'chunk_index':i})[name]=row['count']
        for entry in chunks.values():
            for name in ('normalized_records','candidate_records','representatives','components'):
                entry.setdefault(name,0)
            entry.setdefault('graph',None)
        return Response(dict(day=day,raw_records=db.security_data.count_documents({'source_day':day}),
            chunks_are_processing_partitions=True,unassigned_records=unassigned,results=[chunks[i] for i in sorted(chunks)]))
