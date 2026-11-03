"""Activate a prepared release only after this deployment's workloads have drained.

Run as root on the existing supermew host. A validated Nginx mutation gate must
already be installed; this tool never kills a busy worker or stops other apps.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tarfile
import time
import urllib.request

ROOT=Path('/opt/supermew')
FLAG=Path('/run/supermew-release-draining.flag')


def run(args,timeout=300,**kwargs):
    result=subprocess.run(args,capture_output=True,timeout=timeout,**kwargs)
    if result.returncode: raise RuntimeError('Deployment command failed: '+args[0])
    return result.stdout


def sql(query):
    return run(['runuser','-u','postgres','--','psql','-d','supermew','-At','-v','ON_ERROR_STOP=1','-c',query]).decode().strip()


def workloads():
    # Unknown research states also block activation. A paused task is saved work.
    result={'research':int(sql("SELECT count(*) FROM research_projects WHERE status NOT IN ('draft','completed','failed','paused','cancelled')")),
            'ingestion':int(sql("SELECT count(*) FROM company_documents WHERE state IN ('queued','uploading','parsing','indexing')"))}
    for table in ('assistant_threads','company_chat_threads'):
        result[table]=int(sql(f"SELECT count(*) FROM {table} WHERE busy_until > (now() AT TIME ZONE 'UTC')"))
    return result


def verify(candidate):
    if candidate.is_symlink() or candidate.resolve().parent != ROOT/'releases':
        raise RuntimeError('Candidate must be a direct release directory')
    manifest=json.loads((candidate/'release-manifest.json').read_text())
    if candidate.name != manifest['commit'] or len(candidate.name)!=40:
        raise RuntimeError('Candidate name must match its complete commit')
    for row in manifest['files']:
        path=candidate/row['path']
        if path.is_symlink() or candidate not in path.resolve().parents:
            raise RuntimeError('Invalid candidate file path')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
            raise RuntimeError('Candidate differs from release manifest: '+row['path'])
    if (candidate/'data').resolve()!=ROOT/'shared/data' or not (candidate/'.venv/bin/python').is_file():
        raise RuntimeError('Candidate data link or virtual environment is missing')
    return manifest


def link_release(path):
    temporary=ROOT/'current.next'
    if temporary.exists() or temporary.is_symlink(): raise RuntimeError('Temporary release link already exists')
    temporary.symlink_to(path)
    temporary.replace(ROOT/'current')


def await_ready(timeout=90):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        try:
            with urllib.request.urlopen('http://127.0.0.1:8010/version',timeout=3) as response:
                if response.status==200:return json.load(response)
        except Exception: time.sleep(1)
    raise RuntimeError('Application did not become ready')


def activate(candidate,expected,wait):
    if os.geteuid()!=0 or not (ROOT/'.deployment-owned').is_file():
        raise RuntimeError('Expected root on the managed supermew deployment')
    os.umask(0o077)
    with ExitStack() as stack:
        for name in ('staging/.deployment.lock','.frontend-deploy.lock','backups/.backup.lock'):
            lock=stack.enter_context((ROOT/name).open('a'))
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        manifest=verify(candidate)
        old=(ROOT/'current').resolve(strict=True)
        if old!=expected.resolve(strict=True):raise RuntimeError('Current version changed during preparation')
        config=Path('/etc/nginx/snippets/supermew-public-proxy.conf').read_text()
        if '# supermew-release-drain-v1' not in config or str(FLAG) not in config:
            raise RuntimeError('Validated public mutation gate is not installed')
        run(['nginx','-t'])
        if FLAG.exists():raise RuntimeError('Another maintenance gate is present')
        FLAG.write_text(datetime.now(timezone.utc).isoformat());FLAG.chmod(0o644)
        stopped=False;vector_stopped=False;success=False;backup=None
        try:
            until=time.monotonic()+wait;stable=0
            while True:
                busy=workloads()
                # Existing HTTP streams/downloads must finish too. New reads may retry.
                connections=run(['ss','-Hnt','state','established','sport','=',':8010']).strip()
                if not any(busy.values()) and not connections: stable+=1
                else: stable=0
                print(json.dumps({'phase':'draining','workloads':busy,'open_http_connections':bool(connections)}),flush=True)
                if stable>=2:break
                if time.monotonic()>=until:raise RuntimeError('Still busy; old application left running')
                time.sleep(3 if not any(busy.values()) else 20)
            if (ROOT/'current').resolve()!=old:raise RuntimeError('Current version changed while draining')
            stopped=True;run(['systemctl','stop','supermew'])
            backup=ROOT/'backups'/datetime.now(timezone.utc).strftime('knowledge-release-%Y%m%dT%H%M%SZ')
            backup.mkdir(mode=0o700)
            if run(['docker','inspect','--format','{{.State.Running}}','supermew-milvus']).strip()==b'true':
                vector_stopped=True;run(['docker','stop','-t','30','supermew-milvus'])
            print(json.dumps({'phase':'consistent_backup','directory':str(backup)}),flush=True)
            with (backup/'database.dump').open('xb') as out:
                result=subprocess.run(['runuser','-u','postgres','--','pg_dump','-d','supermew','-Fc'],stdout=out,stderr=subprocess.PIPE,timeout=300)
                if result.returncode:raise RuntimeError('Database backup failed')
            run(['pg_restore','--list',str(backup/'database.dump')])
            for name in ('data','milvus'):
                with tarfile.open(backup/(name+'.tar.gz'),'w:gz',compresslevel=1) as archive:
                    archive.add(ROOT/'shared'/name,arcname=name)
            shutil.copyfile('/etc/supermew/app.env',backup/'app.env')
            shutil.copyfile(old/'release-manifest.json',backup/'previous-release-manifest.json')
            checksums={}
            for path in backup.iterdir():
                if path.is_file():
                    with path.open('rb') as stream:checksums[path.name]=hashlib.file_digest(stream,'sha256').hexdigest()
            (backup/'verification.json').write_text(json.dumps({'previous':str(old),'new_commit':manifest['commit'],'checksums':checksums},indent=2))
            (backup/'COMPLETE').touch(mode=0o600)
            if vector_stopped:run(['docker','start','supermew-milvus']);vector_stopped=False
            link_release(candidate)
            run(['systemctl','start','supermew'])
            loaded=await_ready()
            success=True
            receipt={'status':'activated','commit':manifest['commit'],'previous':str(old),'backup':str(backup),
                     'time_utc':datetime.now(timezone.utc).isoformat(),'loaded':loaded,'drained_workloads':busy}
            (ROOT/('knowledge-release-receipt-'+candidate.name[:12]+'.json')).write_text(json.dumps(receipt,indent=2))
            print(json.dumps(receipt),flush=True)
        finally:
            try:
                if vector_stopped:run(['docker','start','supermew-milvus'])
                if stopped and not success:
                    run(['systemctl','stop','supermew'])
                    if (ROOT/'current').resolve()!=old:link_release(old)
                    run(['systemctl','start','supermew']);await_ready()
                    print(json.dumps({'status':'rolled_back','current':str(old),'backup':str(backup)}),flush=True)
            finally:FLAG.unlink(missing_ok=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--expected-current',type=Path,required=True)
    parser.add_argument('--wait-seconds',type=int,default=1800)
    parser.add_argument('--run',action='store_true',required=True)
    args=parser.parse_args()
    def interrupted(signum,frame):raise InterruptedError('Deployment interrupted; restoring the previous service')
    signal.signal(signal.SIGTERM,interrupted)
    activate(args.candidate,args.expected_current,args.wait_seconds)
