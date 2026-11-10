"""Publication wins over cache reclamation; budgets retain small useful caches."""
import importlib.util
from datetime import datetime, timezone
import os
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('storage_policy',Path(__file__).resolve().parents[1]/'deploy/storage_maintenance.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)


def test_busy_publication_does_not_even_scan_or_modify_caches(monkeypatch):
    monkeypatch.setattr(p,'busy_reason',lambda:'publication_or_local_backup_active')
    monkeypatch.setattr(p,'allocated',lambda path:pytest.fail('Do not scan caches during publication'))
    monkeypatch.setattr(p,'command',lambda args:pytest.fail('Do not modify caches during publication'))
    result,code=p.maintain({})
    assert code==75 and result['status']=='deferred'


def test_small_recent_caches_are_retained(monkeypatch):
    monkeypatch.setattr(p,'busy_reason',lambda:None)
    monkeypatch.setattr(p,'allocated',lambda path:20_000_000)
    monkeypatch.setattr(p,'command',lambda args:pytest.fail('Useful small caches should survive'))
    result,code=p.maintain({'last_prune_utc':datetime.now(timezone.utc).isoformat()})
    assert code==0 and result['actions']==[] and not result['over_target']


def test_budget_falls_back_to_native_clean_when_pruning_is_insufficient(monkeypatch):
    monkeypatch.setattr(p,'busy_reason',lambda:None)
    sizes={p.UV_CACHE:900_000_000,p.PIP_CACHE:150_000_000,p.APT_CACHE:120_000_000}
    monkeypatch.setattr(p,'allocated',lambda path:sizes[path])
    def command(args):
        if args[1:3]==['cache','prune']:sizes[p.UV_CACHE]=600_000_000
        elif args[1:3]==['cache','clean']:sizes[p.UV_CACHE]=0
        elif args[0]=='/usr/bin/pip':sizes[p.PIP_CACHE]=0
        elif args[0]=='apt-get':sizes[p.APT_CACHE]=0
        else:pytest.fail('Unexpected cleanup scope')
    monkeypatch.setattr(p,'command',command)
    result,code=p.maintain({})
    assert code==0 and not result['over_target'] and sum(result['after_bytes'].values())<=p.TARGET


@pytest.mark.skipif(os.name=='nt',reason='Linux flock observation')
def test_observes_real_publication_lock_without_acquiring_it(tmp_path,monkeypatch):
    import fcntl
    monkeypatch.setattr(p,'ROOT',tmp_path)
    (tmp_path/'staging').mkdir()
    with (tmp_path/'staging/.deployment.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert p.busy_reason()=='publication_or_local_backup_active'


@pytest.mark.skipif(os.name=='nt',reason='Linux symlink and cache filesystem')
def test_refuses_cache_redirection_and_active_cache_virtualenv(tmp_path,monkeypatch):
    outside=tmp_path/'outside';outside.mkdir()
    redirected=tmp_path/'redirected';redirected.symlink_to(outside,target_is_directory=True)
    with pytest.raises(RuntimeError,match='Unexpected cache path'):p.allocated(redirected)
    root=tmp_path/'server';(root/'current').mkdir(parents=True)
    cache=tmp_path/'cache';(cache/'environment').mkdir(parents=True)
    (root/'current/.venv').symlink_to(cache/'environment',target_is_directory=True)
    monkeypatch.setattr(p,'ROOT',root);monkeypatch.setattr(p,'UV_CACHE',cache)
    assert p.busy_reason()=='active_virtualenv_is_inside_cache'
