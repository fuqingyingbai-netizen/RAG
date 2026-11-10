import hashlib
import importlib.util
import json
from pathlib import Path

spec=importlib.util.spec_from_file_location('retention',Path(__file__).parents[1]/'deploy/metadata_retention.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def archive(root,number):
    p=root/'backups'/f'knowledge-release-202611{number:02d}T000000Z';p.mkdir(parents=True)
    files={'database.dump':b'db','app.env':b'private','previous-release-manifest.json':b'{}'}
    for name,data in files.items():(p/name).write_bytes(data)
    (p/'verification.json').write_text(json.dumps({'scope':'database-and-config','previous':'/old',
        'new_commit':str(number)*40,'checksums':{n:hashlib.sha256(d).hexdigest() for n,d in files.items()}}))
    (p/'METADATA_COMPLETE').touch()
    return p


def test_only_exact_cloud_covered_archives_rotate_and_pinned_rollback_survives(tmp_path, monkeypatch):
    paths=[archive(tmp_path,n) for n in range(1,7)]
    live=tmp_path/'releases'/('a'*40);live.mkdir(parents=True)
    original_resolve=Path.resolve
    monkeypatch.setattr(Path,'resolve',lambda path,*a,**kw:live if path==tmp_path/'current' else original_resolve(path,*a,**kw))
    receipt=tmp_path/('knowledge-release-receipt-'+'a'*12+'.json')
    receipt.write_text(json.dumps({'commit':'a'*40,'backup':str(paths[0])}))
    rows=m.inventory(tmp_path)
    assert len(rows)==6
    assert m.candidates(tmp_path,rows,{})==[]
    assert set(m.candidates(tmp_path,rows,{'publication_archives':rows}))==set(paths[1:3])
    # A corrupted/replaced archive is neither a valid candidate nor valid proof coverage.
    (paths[1]/'database.dump').write_bytes(b'corruption')
    assert str(paths[1]) not in {r['path'] for r in m.inventory(tmp_path)}


def test_missing_receipt_or_unexpected_files_preserves_archives(tmp_path):
    p=archive(tmp_path,1)
    assert m.candidates(tmp_path,m.inventory(tmp_path),{})==[]
    (p/'untracked').write_text('unknown')
    assert m.inventory(tmp_path)==[]


def test_complete_metadata_archive_is_never_treated_as_stale_partial(tmp_path, monkeypatch):
    import os
    spec=importlib.util.spec_from_file_location('backup_policy_test',Path(__file__).parents[1]/'deploy/backup_policy.py')
    policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
    old=archive(tmp_path,1)
    os.utime(old,(1,1))
    full=tmp_path/'backups'/'knowledge-release-20261102T000000Z';full.mkdir()
    (full/'database.dump').write_bytes(b'full');(full/'COMPLETE').touch()
    monkeypatch.setattr(policy,'ROOT',tmp_path)
    monkeypatch.setattr(policy,'verify_legacy',lambda *a,**kw:{'path':str(full)})
    monkeypatch.setattr(policy,'fresh_offsite_proof',lambda *a:False)
    monkeypatch.setattr(policy,'live_references',lambda *a:False)
    result=policy.guard(dict(policy.DEFAULTS))
    assert old.exists() and result['deleted']==[]
