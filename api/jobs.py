"""Mongo-backed jobs. HTTP submits; only the separate API worker executes."""
from datetime import datetime,timezone
import hashlib
import json
import uuid

from django.conf import settings
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from . import db as database
from .registry import command_info,arguments

FINAL_STATES={'succeeded','failed','cancelled','interrupted'}


class Conflict(Exception):
    pass


def now():
    return datetime.now(timezone.utc)


def job_folder(job_id):
    # Only canonical UUIDs can become filesystem path segments.
    job_id=str(uuid.UUID(str(job_id)))
    return settings.BASE_DIR/'document'/'api'/'jobs'/job_id


def submit(action,params,idempotency_key=None):
    info=command_info(action);argv=arguments(action,params);db=database.get_database()
    db.api_jobs.create_index([('status',1),('created_at',1)])
    db.api_jobs.create_index('idempotency_key',unique=True,sparse=True)
    digest=hashlib.sha256(json.dumps(dict(action=action,params=params,schema=info['schema_hash']),sort_keys=True,allow_nan=False).encode()).hexdigest()
    if idempotency_key:
        existing=db.api_jobs.find_one({'idempotency_key':idempotency_key})
        if existing:
            if existing['request_hash']!=digest:raise Conflict('Idempotency-Key already belongs to a different request.')
            return existing,False
    job=dict(_id=str(uuid.uuid4()),action=action,command=info['command'],parameters=params,arguments=argv,
        schema_hash=info['schema_hash'],request_hash=digest,status='queued',created_at=now(),updated_at=now(),
        started_at=None,finished_at=None,error=None)
    if idempotency_key:job['idempotency_key']=idempotency_key
    try:
        db.api_jobs.insert_one(job)
    except DuplicateKeyError:
        existing=db.api_jobs.find_one({'idempotency_key':idempotency_key})
        if existing and existing['request_hash']==digest:return existing,False
        raise Conflict('Idempotency-Key already belongs to a different request.')
    return job,True


def public_job(job):
    job_id=job['_id']
    def utc(value):
        return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value
    return dict(id=job_id,action=job['action'],command=job['command'],parameters=job['parameters'],
        status=job['status'],created_at=utc(job['created_at']),updated_at=utc(job['updated_at']),
        started_at=utc(job.get('started_at')),finished_at=utc(job.get('finished_at')),error=job.get('error'),
        detail_url=f'/api/v1/jobs/{job_id}/',logs_url=f'/api/v1/jobs/{job_id}/logs/',
        log_artifact=f'api/jobs/{job_id}/stdout.log')


def cancel_queued(job_id):
    collection=database.get_database().api_jobs
    row=collection.find_one_and_update({'_id':job_id,'status':'queued'},
        {'$set':dict(status='cancelled',updated_at=now(),finished_at=now())},return_document=ReturnDocument.AFTER)
    if row:return row
    if not collection.find_one({'_id':job_id}):raise KeyError(job_id)
    raise Conflict('Only queued jobs can be cancelled. A running command is never interrupted by this endpoint.')
