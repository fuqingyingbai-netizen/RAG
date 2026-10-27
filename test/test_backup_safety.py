"""Backup interruption must not leave the application stopped."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def backup_host(tmp_path,monkeypatch):
    path=Path(__file__).resolve().parents[1]/'deploy/backup-production.py'
    spec=importlib.util.spec_from_file_location('backup_safety',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.ROOT=tmp_path
    (tmp_path/'.deployment-owned').touch()
    for name in ['data','milvus']:
        folder=tmp_path/'shared'/name;folder.mkdir(parents=True);(folder/'record').write_text('synthetic')
    (tmp_path/'current').mkdir()
    (tmp_path/'current'/'release-manifest.json').write_text(json.dumps({'commit':'synthetic'}))
    monkeypatch.setattr(module.os,'geteuid',lambda:0,raising=False)
    monkeypatch.setattr(module.os,'umask',lambda _:0)
    monkeypatch.setitem(sys.modules,'fcntl',SimpleNamespace(flock=lambda *a:None,LOCK_EX=1,LOCK_NB=2))
    original_copy=module.shutil.copyfile
    def copy(source,target):
        if str(source)=='/etc/supermew/app.env':Path(target).write_text('SYNTHETIC_ONLY=true')
        else:original_copy(source,target)
    monkeypatch.setattr(module.shutil,'copyfile',copy)
    def process(args,**kw):
        if 'pg_dump' in args:kw['stdout'].write(b'synthetic pg dump')
        return subprocess.CompletedProcess(args,0,stdout=b'',stderr=b'')
    monkeypatch.setattr(module.subprocess,'run',process)
    calls=[]
    def run(args,**kw):
        calls.append(args)
        if 'psql' in args:return b'0'
        if args[:2]==['docker','inspect']:return b'true'
        return b''
    monkeypatch.setattr(module,'run',run)
    return module,calls


def test_backup_archive_failure_restores_application_and_vector(backup_host,monkeypatch):
    module,calls=backup_host
    monkeypatch.setattr(module.tarfile,'open',lambda *a,**kw:(_ for _ in ()).throw(OSError('synthetic archive failure')))
    with pytest.raises(OSError):module.backup()
    assert ['docker','start','supermew-milvus'] in calls
    assert calls[-1]==['systemctl','start','supermew']
    assert not list((module.ROOT/'backups').glob('*/COMPLETE'))


def test_failure_to_restart_vector_still_attempts_to_restart_application(backup_host,monkeypatch):
    module,calls=backup_host;original=module.run
    def run(args,**kw):
        result=original(args,**kw)
        if args[:2]==['docker','start']:raise RuntimeError('synthetic vector start error')
        return result
    monkeypatch.setattr(module,'run',run)
    with pytest.raises(RuntimeError):module.backup()
    assert calls[-1]==['systemctl','start','supermew']


def test_backup_records_a_complete_snapshot_before_retention(backup_host):
    module,calls=backup_host
    result=module.backup()
    folder=Path(result['directory'])
    assert (folder/'COMPLETE').is_file() and result['commit']=='synthetic'
    assert set(result['checksums'])=={'database.dump','data.tar.gz','milvus.tar.gz','app.env','release-manifest.json'}
    assert calls[-1]==['systemctl','start','supermew']
