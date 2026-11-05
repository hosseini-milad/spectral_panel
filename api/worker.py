"""One scientific command at a time, in a process separate from the HTTP server."""
import contextlib
import json
import os
import socket
import threading
import traceback
import uuid

import psutil
from django.core.management import call_command
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from . import db as database
from .jobs import now,job_folder,FINAL_STATES
from .registry import command_info,arguments,serializer_for

LOCK='scientific-command-worker'


def process_is_live(lock):
    if lock.get('hostname')!=socket.gethostname():return True
    try:
        process=psutil.Process(lock['pid'])
        return (process.is_running() and process.status()!=psutil.STATUS_ZOMBIE
                and abs(process.create_time()-lock['process_created_at'])<.01)
    except (psutil.NoSuchProcess,KeyError):return False
    except psutil.AccessDenied:return True


def acquire_lock(db):
    owner=str(uuid.uuid4())
    record=dict(_id=LOCK,owner=owner,hostname=socket.gethostname(),pid=os.getpid(),
        process_created_at=psutil.Process().create_time(),heartbeat_at=now(),job_id=None)
    for _ in range(3):
        try:
            db.api_runtime.insert_one(record);return owner
        except DuplicateKeyError:
            old=db.api_runtime.find_one({'_id':LOCK})
            if old is None:continue
            if process_is_live(old):raise RuntimeError('Another API worker is active; only one command worker is allowed.')
            # No automatic command retry: an interrupted force command must not
            # unexpectedly delete already rebuilt data a second time.
            if old.get('job_id'):
                status='interrupted';error=dict(type='WorkerInterrupted',message='Previous worker stopped before recording completion; not retried.')
                result_path=job_folder(old['job_id'])/'result.json'
                if result_path.is_file():
                    try:
                        result=json.loads(result_path.read_text(encoding='utf-8'))
                        if result.get('status') in FINAL_STATES:
                            status=result['status'];error=result.get('error')
                    except (OSError,ValueError):pass
                db.api_jobs.update_one({'_id':old['job_id'],'status':'running'},
                    {'$set':dict(status=status,error=error,finished_at=now(),updated_at=now())})
            db.api_runtime.delete_one({'_id':LOCK,'owner':old['owner']})
    raise RuntimeError('Could not acquire the API worker lock.')


def execute_one(db,owner):
    lock=db.api_runtime.find_one({'_id':LOCK,'owner':owner})
    if lock is None:raise RuntimeError('Worker lost its exclusive lock.')
    job=db.api_jobs.find_one_and_update({'status':'queued'},
        {'$set':dict(status='running',worker_id=owner,started_at=now(),updated_at=now())},
        sort=[('created_at',1),('_id',1)],return_document=ReturnDocument.AFTER)
    if job is None:return False
    # Keep the claimed job recoverable even if the worker dies before opening logs.
    db.api_runtime.update_one({'_id':LOCK,'owner':owner},{'$set':{'job_id':job['_id'],'heartbeat_at':now()}})
    folder=job_folder(job['_id']);folder.mkdir(parents=True,exist_ok=True)
    state='succeeded';error=None;interruption=None
    try:
        with (folder/'stdout.log').open('a',encoding='utf-8',buffering=1) as stream:
            with contextlib.redirect_stdout(stream),contextlib.redirect_stderr(stream):
                try:
                    info=command_info(job['action'])
                    if info['schema_hash']!=job['schema_hash'] or info['command']!=job['command']:
                        raise ValueError('Command schema changed after submission; resubmit the job.')
                    serializer=serializer_for(job['action'])(data=job['parameters'])
                    serializer.is_valid(raise_exception=True)
                    argv=arguments(job['action'],serializer.validated_data)
                    if argv!=job['arguments']:raise ValueError('Stored job arguments differ from validated parameters.')
                    print(f"[API JOB] {job['_id']} | command={job['command']}",flush=True)
                    call_command(job['command'],*argv,stdout=stream,stderr=stream,no_color=True)
                except BaseException as exc:
                    state='failed' if isinstance(exc,Exception) else 'interrupted'
                    error=dict(type=type(exc).__name__,message=str(exc))
                    traceback.print_exc(file=stream)
                    if not isinstance(exc,Exception):interruption=exc
    except Exception as exc:
        state='failed';error=dict(type=type(exc).__name__,message=str(exc))
    result=dict(status=state,error=error,finished_at=now().isoformat())
    temporary=folder/'result.json.tmp';temporary.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    temporary.replace(folder/'result.json')
    db.api_jobs.update_one({'_id':job['_id'],'status':'running','worker_id':owner},
        {'$set':dict(status=state,error=error,finished_at=now(),updated_at=now())})
    db.api_runtime.update_one({'_id':LOCK,'owner':owner},{'$set':{'job_id':None,'heartbeat_at':now()}})
    if interruption is not None:raise interruption
    return True


def heartbeat(db,owner,stop):
    while not stop.wait(2):
        try:
            db.api_runtime.update_one({'_id':LOCK,'owner':owner},{'$set':{'heartbeat_at':now()}})
        except Exception:
            # Do not release or expire the exclusive lock during a DB outage.
            pass


def recover_orphan_jobs(db):
    # Called only after acquiring the exclusive lock: no live API worker can
    # still own a running job, including a crash between claim and lock update.
    for orphan in db.api_jobs.find({'status':'running'}):
        state='interrupted';error=dict(type='WorkerInterrupted',message='Previous worker stopped; this job was not retried.')
        path=job_folder(orphan['_id'])/'result.json'
        if path.is_file():
            try:
                result=json.loads(path.read_text(encoding='utf-8'))
                if result.get('status') in FINAL_STATES:state=result['status'];error=result.get('error')
            except (OSError,ValueError):pass
        db.api_jobs.update_one({'_id':orphan['_id'],'status':'running'},
            {'$set':dict(status=state,error=error,finished_at=now(),updated_at=now())})


def run_worker(*,once=False,poll_interval=1,output=print):
    if not 0<poll_interval<=30:raise ValueError('poll_interval must be in (0, 30] seconds')
    db=database.get_database();owner=acquire_lock(db);stop=threading.Event();thread=None
    try:
        recover_orphan_jobs(db)
        thread=threading.Thread(target=heartbeat,args=(db,owner,stop),daemon=True);thread.start()
        output('[API WORKER] Ready; commands run serially. CLI processes are outside this lock.')
        while True:
            worked=execute_one(db,owner)
            if once:break
            if not worked:stop.wait(poll_interval)
    except KeyboardInterrupt:
        output('[API WORKER] Stopped; no automatic retry of interrupted jobs.')
    finally:
        stop.set()
        if thread is not None:thread.join(timeout=3)
        db.api_runtime.delete_one({'_id':LOCK,'owner':owner})
