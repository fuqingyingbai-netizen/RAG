"""Verify bounded metadata backups and preserve the default full backup path."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def activation(tmp_path,monkeypatch):
    monkeypatch.setitem(sys.modules,'fcntl',SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *a:None))
    path=Path(__file__).resolve().parents[1]/'deploy/activate-release.py'
    spec=importlib.util.spec_from_file_location('classification_activation',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    root=tmp_path/'server';root.mkdir()
    for name in ('staging','backups','shared/data','shared/milvus','current'):(root/name).mkdir(parents=True)
    (root/'.deployment-owned').touch()
    (root/'shared/data/original.txt').write_bytes(b'UNCHANGED ORIGINAL')
    (root/'shared/milvus/vector.txt').write_bytes(b'UNCHANGED VECTOR')
    (root/'current/release-manifest.json').write_text('{}')
    ingress=root/'proxy.conf';flag=root/'drain.flag'
    ingress.write_text('# supermew-release-drain-v1 '+str(flag))
    monkeypatch.setattr(module,'ROOT',root);monkeypatch.setattr(module,'FLAG',flag);monkeypatch.setattr(module,'INGRESS',ingress)
    monkeypatch.setattr(module.os,'geteuid',lambda:0,raising=False)
    candidate=root/'candidate';candidate.mkdir()
    monkeypatch.setattr(module,'verify',lambda p:{'kind':'knowledge-two-levels-overlay','commit':'a'*40})
    monkeypatch.setattr(module,'workloads',lambda:{'research':0,'ingestion':0})
    monkeypatch.setattr(module,'await_ready',lambda:{'instance_id':'new'})
    monkeypatch.setattr(module,'link_release',lambda p:None)
    monkeypatch.setattr(module.time,'sleep',lambda _:None)
    real_copy=module.shutil.copyfile
    config=root/'app.env';config.write_bytes(b'SYNTHETIC CONFIG')
    monkeypatch.setattr(module.shutil,'copyfile',lambda source,destination:real_copy(config if str(source)=='/etc/supermew/app.env' else source,destination))
    calls=[]
    def run(args,**kwargs):
        calls.append(args)
        if args[0]=='curl':return b'503'
        if args[0]=='docker':return b'false'
        return b''
    monkeypatch.setattr(module,'run',run)
    def pg_dump(args,**kwargs):
        kwargs['stdout'].write(b'SYNTHETIC POSTGRES DUMP')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module.subprocess,'run',pg_dump)
    return module,root,candidate,calls


@pytest.mark.parametrize('metadata',[False,True])
def test_backup_scope_is_explicit_and_does_not_modify_originals(activation,metadata):
    module,root,candidate,calls=activation
    module.activate(candidate,root/'current',30,'company.test',metadata)
    backup=next(p for p in (root/'backups').iterdir() if p.is_dir())
    assert (backup/'database.dump').read_bytes()==b'SYNTHETIC POSTGRES DUMP'
    assert (backup/'verification.json').exists()
    assert (backup/'METADATA_COMPLETE').exists()==metadata
    assert (backup/'COMPLETE').exists()!=metadata
    assert (backup/'data.tar.gz').exists()!=metadata
    assert (backup/'milvus.tar.gz').exists()!=metadata
    assert (root/'shared/data/original.txt').read_bytes()==b'UNCHANGED ORIGINAL'
    assert (root/'shared/milvus/vector.txt').read_bytes()==b'UNCHANGED VECTOR'
    assert not module.FLAG.exists()
    assert ['systemctl','stop','supermew'] in calls and ['systemctl','start','supermew'] in calls
    assert json.loads((backup/'verification.json').read_text())['scope']==('database-and-config' if metadata else 'full')


def test_other_release_types_cannot_select_metadata_backup(activation,monkeypatch):
    module,root,candidate,calls=activation
    monkeypatch.setattr(module,'verify',lambda p:{'kind':'other-release','commit':'a'*40})
    with pytest.raises(RuntimeError,match='classification overlay'):
        module.activate(candidate,root/'current',30,'company.test',True)
    assert not calls and not [p for p in (root/'backups').iterdir() if p.is_dir()]
