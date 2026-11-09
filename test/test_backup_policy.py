"""Recovery copies survive failed, unconfigured, stale and partial backup runs."""
import importlib.util
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('bounded_backup_policy',
    Path(__file__).resolve().parents[1] / 'deploy/backup_policy.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, 'ROOT', tmp_path)
    (tmp_path / 'backups').mkdir()
    monkeypatch.setattr(policy, 'command', lambda *a, **kw: b'')
    monkeypatch.setattr(policy, 'live_references', lambda p: False)
    monkeypatch.setattr(policy.shutil, 'disk_usage', lambda p: SimpleNamespace(free=20*policy.GB))
    return tmp_path


def archive(root, name, complete=True, corrupt=False):
    p = root / 'backups' / name
    p.mkdir()
    for filename in ('database.dump', 'data.tar.gz', 'milvus.tar.gz', 'app.env'):
        (p / filename).write_bytes(b'synthetic non-production fixture')
    hashes = {f.name: policy.digest(f) for f in p.iterdir()}
    (p / 'verification.json').write_text(json.dumps({'checksums': hashes}))
    if complete:
        (p / 'COMPLETE').touch()
    if corrupt:
        (p / 'data.tar.gz').write_bytes(b'corrupt')
    return p


def proof(root, config, age=0):
    config['repository'] = 's3:https://oss-cn-hangzhou.aliyuncs.com/test-backup/policy'
    policy.atomic_json(root / 'backup-policy/offsite-verified.json', {
        'verified_at': (datetime.now(timezone.utc)-timedelta(hours=age)).isoformat(),
        'repository_key': policy.repository_key(config), 'snapshot_id': 'synthetic',
        'database_restored': True, 'sample_restored': True,
    })


def test_unconfigured_offsite_preserves_all_completed_backups(host):
    first = archive(host, 'backup-20261106T190226Z')
    second = archive(host, 'knowledge-release-20261106T035726Z')
    result = policy.guard(dict(policy.DEFAULTS))
    assert first.exists() and second.exists()
    assert 'oss_not_configured_existing_recovery_copies_preserved' in result['warnings']
    assert result['deleted'] == []


def test_valid_offsite_proof_allows_only_older_completed_archives_to_retire(host):
    older = archive(host, 'backup-20261104T190437Z')
    newer = archive(host, 'backup-20261106T190226Z')
    os.utime(older, (1, 1))
    config = dict(policy.DEFAULTS)
    proof(host, config)
    result = policy.guard(config)
    assert newer.exists() and not older.exists()
    assert [r['path'] for r in result['deleted']] == [str(older)]
    assert (host / 'backup-policy/retired' / (older.name+'.json')).is_file()


@pytest.mark.parametrize('age', [37, -1])
def test_stale_or_future_offsite_proof_cannot_remove_recovery_copies(host, age):
    older = archive(host, 'backup-20261104T190437Z')
    newer = archive(host, 'backup-20261106T190226Z')
    config = dict(policy.DEFAULTS)
    proof(host, config, age)
    policy.guard(config)
    assert older.exists() and newer.exists()


def test_proof_for_another_repository_does_not_allow_retirement(host):
    older = archive(host, 'backup-20261104T190437Z')
    archive(host, 'backup-20261106T190226Z')
    config = dict(policy.DEFAULTS)
    proof(host, config)
    config['repository'] += '-other'
    policy.guard(config)
    assert older.exists()


def test_old_failed_partial_is_cleaned_only_when_good_local_recovery_exists(host):
    partial = archive(host, 'backup-20261105T190238Z', complete=False)
    os.utime(partial, (1, 1))
    policy.guard(dict(policy.DEFAULTS))
    assert partial.exists()
    archive(host, 'backup-20261106T190226Z')
    result = policy.guard(dict(policy.DEFAULTS))
    assert not partial.exists() and len(result['deleted']) == 1


def test_corrupt_newer_backup_does_not_replace_valid_recovery_copy(host):
    good = archive(host, 'backup-20261104T190437Z')
    bad = archive(host, 'backup-20261106T190226Z', corrupt=True)
    os.utime(good, (1, 1))
    config = dict(policy.DEFAULTS)
    proof(host, config)
    result = policy.guard(config)
    assert good.exists() and bad.exists()
    assert result['retained_verified_local'] == str(good)


def test_partial_referenced_by_live_process_is_not_deleted(host, monkeypatch):
    archive(host, 'backup-20261106T190226Z')
    partial = archive(host, 'backup-20261105T190238Z', complete=False)
    os.utime(partial, (1, 1))
    monkeypatch.setattr(policy, 'live_references', lambda p: True)
    policy.guard(dict(policy.DEFAULTS))
    assert partial.exists()


def test_local_budget_never_deletes_only_verified_full_backup(host):
    only = archive(host, 'backup-20261106T190226Z')
    config = dict(policy.DEFAULTS, max_local_bytes=1)
    proof(host, config)
    result = policy.guard(config)
    assert only.exists() and 'local_backup_budget_exceeded' in result['warnings']


def test_low_disk_refuses_new_local_backup_before_writing(host, monkeypatch):
    monkeypatch.setattr(policy.shutil, 'disk_usage', lambda p: SimpleNamespace(free=3*policy.GB))
    with pytest.raises(policy.BackupError, match='reserve'):
        policy.preflight(dict(policy.DEFAULTS), policy.GB)
    assert list((host / 'backups').iterdir()) == []


@pytest.mark.parametrize('repository', [
    '/tmp/repo', 's3:http://oss-cn-hangzhou.aliyuncs.com/bucket/prefix',
    's3:https://localhost/bucket/prefix', 's3:https://oss-cn-hangzhou.aliyuncs.com/bucket',
    's3:https://secret@oss-cn-hangzhou.aliyuncs.com/bucket/prefix',
    's3:https://oss-cn-hangzhou.aliyuncs.com/bucket/../prefix',
])
def test_offsite_configuration_rejects_local_insecure_or_ambiguous_destinations(repository):
    with pytest.raises(policy.BackupError):
        policy.validate_repository(repository)


def test_failed_remote_snapshot_does_not_publish_proof_or_prune(host, monkeypatch):
    stage = host / 'runtime/current'
    stage.mkdir(parents=True)
    monkeypatch.setattr(policy, 'RUNTIME', stage.parent)
    config = dict(policy.DEFAULTS, repository='s3:https://oss-cn-hangzhou.aliyuncs.com/bucket/prefix')
    monkeypatch.setattr(policy, 'prepare_metadata', lambda cfg: (stage, {}))
    calls = []
    def restic(cfg, args, **kwargs):
        calls.append(args[0])
        if args[0] == 'backup':
            raise policy.BackupError('Command failed: restic')
        return b'{}'
    monkeypatch.setattr(policy, 'restic', restic)
    with pytest.raises(policy.BackupError):
        policy.backup(config)
    assert not (host/'backup-policy/offsite-verified.json').exists()
    assert 'forget' not in calls and not stage.exists()


def test_failed_restore_does_not_publish_proof_or_prune(host, monkeypatch):
    stage = host / 'runtime/current'
    stage.mkdir(parents=True)
    monkeypatch.setattr(policy, 'RUNTIME', stage.parent)
    config = dict(policy.DEFAULTS, repository='s3:https://oss-cn-hangzhou.aliyuncs.com/bucket/prefix')
    monkeypatch.setattr(policy, 'prepare_metadata', lambda cfg: (stage, {}))
    calls = []
    def restic(cfg, args, **kwargs):
        calls.append(args[0])
        return b'{"message_type":"summary","snapshot_id":"synthetic"}\n' if args[0]=='backup' else b'{}'
    monkeypatch.setattr(policy, 'restic', restic)
    monkeypatch.setattr(policy, 'verify_restore', lambda *args: (_ for _ in ()).throw(policy.BackupError('restore failed')))
    with pytest.raises(policy.BackupError):
        policy.backup(config)
    assert not (host/'backup-policy/offsite-verified.json').exists()
    assert 'forget' not in calls


def test_complete_snapshot_checks_recovery_before_retention(host, monkeypatch):
    stage = host / 'runtime/current'
    stage.mkdir(parents=True)
    monkeypatch.setattr(policy, 'RUNTIME', stage.parent)
    config = dict(policy.DEFAULTS, repository='s3:https://oss-cn-hangzhou.aliyuncs.com/bucket/prefix')
    monkeypatch.setattr(policy, 'prepare_metadata', lambda cfg: (stage, {}))
    calls = []
    def restic(cfg, args, **kwargs):
        calls.append(args[0])
        if args[0]=='forget':
            assert (host/'backup-policy/offsite-verified.json').exists()
        return b'{"message_type":"summary","snapshot_id":"synthetic"}\n' if args[0]=='backup' else b'{}'
    monkeypatch.setattr(policy, 'restic', restic)
    def verify(*args):
        calls.append('restore-verified')
        return {'database_restored': True, 'sample_restored': True}
    monkeypatch.setattr(policy, 'verify_restore', verify)
    monkeypatch.setattr(policy, 'guard', lambda cfg: {})
    monkeypatch.setattr(policy, 'retain_local_database', lambda *args: {})
    result = policy.backup(config)
    assert calls.index('restore-verified') < calls.index('forget')
    assert calls[-1] == 'check' and result['status']=='offsite_verified'


def test_changed_archive_invalidates_previous_checksum_cache(host):
    p = archive(host, 'backup-20261106T190226Z')
    cache = policy.verify_legacy(p)
    (p/'data.tar.gz').write_bytes(b'new corrupt content')
    with pytest.raises(policy.BackupError, match='checksum'):
        policy.verify_legacy(p, cache)


@pytest.mark.parametrize('age,expected', [(1,True),(8,False),(-1,False)])
def test_database_rehearsal_expires_and_rejects_future_clock(host, age, expected):
    config=dict(policy.DEFAULTS, repository='s3:https://oss-cn-beijing.aliyuncs.com/test/policy')
    policy.atomic_json(host/'backup-policy/database-drill.json',{
        'verified_at':(datetime.now(timezone.utc)-timedelta(days=age)).isoformat(),
        'database_restored':True,'repository_key':policy.repository_key(config),'snapshot_id':'old-drill'})
    assert bool(policy.recent_database_drill(config))==expected


def test_daily_check_restores_manifest_and_small_original_without_full_database_download(host,monkeypatch):
    monkeypatch.chdir(host)
    runtime=host/'runtime';runtime.mkdir()
    monkeypatch.setattr(policy,'RUNTIME',runtime)
    stage=Path('stage');stage.mkdir()
    (stage/'database.dump').write_bytes(b'synthetic database archive')
    original=Path('original.txt');original.write_bytes(b'synthetic original')
    manifest={'database_sha256':policy.digest(stage/'database.dump'),
              'sample':{'path':str(original),'sha256':policy.digest(original)}}
    (stage/'recovery.json').write_text(json.dumps(manifest))
    config=dict(policy.DEFAULTS,repository='s3:https://oss-cn-beijing.aliyuncs.com/test/policy')
    timestamp=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
    policy.atomic_json(host/'backup-policy/database-drill.json',{
        'verified_at':timestamp,'database_restored':True,
        'repository_key':policy.repository_key(config),'snapshot_id':'previous-weekly-drill'})
    observed=[]
    def restic(cfg,args,**kwargs):
        observed.extend(args)
        target=Path(args[args.index('--target')+1])
        for source in (stage/'recovery.json',original):
            destination=target/str(source)
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_bytes(source.read_bytes())
        return b''
    monkeypatch.setattr(policy,'restic',restic)
    monkeypatch.setattr(policy,'command',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('No database restore on daily sample check')))
    result=policy.verify_restore(config,'new-daily-snapshot',stage,manifest)
    assert str(stage/'database.dump') not in observed
    assert result['database_restored'] is False and result['database_drill_verified_at']==timestamp
    assert result['manifest_restored'] and result['sample_restored']


def test_expired_database_rehearsal_prevents_local_retirement(host):
    older=archive(host,'backup-20261104T190437Z')
    newer=archive(host,'backup-20261106T190226Z')
    config=dict(policy.DEFAULTS)
    proof(host,config)
    location=host/'backup-policy/offsite-verified.json'
    row=json.loads(location.read_text())
    row.update(database_restored=False,database_drill_verified_at=(datetime.now(timezone.utc)-timedelta(days=9)).isoformat())
    location.write_text(json.dumps(row))
    policy.guard(config)
    assert older.exists() and newer.exists()
