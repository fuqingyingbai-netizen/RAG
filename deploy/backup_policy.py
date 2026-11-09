"""Bounded local recovery copies and encrypted incremental OSS backups.

No default command stops the application or writes another full data tarball.
Secrets are supplied by systemd EnvironmentFile, never command-line arguments.
"""
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit
import uuid

ROOT = Path('/opt/supermew')
RUNTIME = Path('/run/supermew-backup')
CONFIG = Path('/etc/supermew/backup-policy.json')
TAG = 'supermew-policy-v2'
HOST = 'supermew-production'
GB = 1_000_000_000
DEFAULTS = {
    'schema': 2, 'repository': '', 'region': '', 'restic': '/usr/local/bin/restic',
    'min_free_bytes': 10 * GB, 'max_local_bytes': 8 * GB,
    'keep_local_full': 1, 'keep_local_database': 2,
    'max_database_bytes': GB, 'stale_partial_hours': 24,
    'keep_daily_days': 7, 'keep_weekly': 4,
    'database_restore_interval_days': 7, 'max_daily_sample_bytes': 1_000_000,
}


class BackupError(RuntimeError):
    pass


class LockBusy(BackupError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_policy(path=CONFIG):
    policy = dict(DEFAULTS)
    if path.exists():
        policy.update(json.loads(path.read_text(encoding='utf-8')))
    if policy['schema'] != 2:
        raise BackupError('Unsupported backup policy schema')
    for key in ('min_free_bytes', 'max_local_bytes', 'keep_local_full',
                'keep_local_database', 'max_database_bytes', 'stale_partial_hours',
                'keep_daily_days', 'keep_weekly', 'database_restore_interval_days', 'max_daily_sample_bytes'):
        if type(policy[key]) is not int or policy[key] <= 0:
            raise BackupError('Invalid positive policy limit: ' + key)
    return policy


def validate_repository(repository):
    if not repository.startswith('s3:https://'):
        raise BackupError('Configure a dedicated external OSS repository over HTTPS')
    parsed = urlsplit(repository[3:])
    if (not parsed.hostname or not parsed.hostname.endswith('.aliyuncs.com')
            or not parsed.hostname.startswith('oss-') or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.port not in (None, 443)):
        raise BackupError('Expected an OSS regional endpoint without embedded credentials')
    parts = parsed.path.strip('/').split('/')
    if len(parts) < 2 or any(part in ('', '.', '..') for part in parts):
        raise BackupError('Use a dedicated bucket/prefix for this backup repository')
    return repository


def command(args, timeout=300, **kwargs):
    result = subprocess.run(args, capture_output=True, timeout=timeout, **kwargs)
    if result.returncode:
        # Do not emit stderr: cloud errors can contain signed requests or secrets.
        raise BackupError('Command failed: ' + Path(str(args[0])).name)
    return result.stdout


def sql(query):
    return command(['runuser', '-u', 'postgres', '--', 'psql', '-d', 'supermew',
                    '-At', '-v', 'ON_ERROR_STOP=1', '-c', query]).decode().strip()


@contextmanager
def managed_locks():
    import fcntl
    if os.geteuid() != 0 or not (ROOT / '.deployment-owned').is_file():
        raise BackupError('Expected root on the managed SuperMew server')
    os.umask(0o077)
    with ExitStack() as stack:
        for relative in ('staging/.deployment.lock', '.frontend-deploy.lock', 'backups/.backup.lock'):
            handle = stack.enter_context((ROOT / relative).open('a'))
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise LockBusy('A deployment or backup is active; retry later') from None
        yield


@contextmanager
def offsite_backup_lock():
    """Serialize cloud jobs without occupying any application deployment lock."""
    import fcntl
    if os.geteuid() != 0 or not (ROOT / '.deployment-owned').is_file():
        raise BackupError('Expected root on the managed SuperMew server')
    os.umask(0o077)
    with (ROOT / 'backups/.offsite-backup.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise LockBusy('An offsite backup is active; retry later') from None
        yield


def safe_backup_path(path):
    parent = ROOT / 'backups'
    if (path.parent != parent or path.is_symlink() or path.resolve() != path
            or not path.is_dir() or os.path.ismount(path)
            or any(p.is_symlink() for p in path.parents)):
        raise BackupError('Backup path is outside the managed cleanup scope')
    # Managed legacy archives are flat; nested directories and links are refused.
    if any(p.is_symlink() or not p.is_file() for p in path.iterdir()):
        raise BackupError('Unexpected content in a legacy backup directory')
    return path


def live_references(path):
    prefix = str(path) + '/'
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        links = [process / 'cwd'] + list((process / 'fd').glob('*'))
        for link in links:
            try:
                value = os.readlink(link).removesuffix(' (deleted)')
                if value == str(path) or value.startswith(prefix):
                    return True
            except OSError:
                pass
    return False


def directory_bytes(path):
    if not path.exists():
        return 0
    return sum(p.lstat().st_size for p in path.rglob('*') if p.is_file() and not p.is_symlink())


def legacy_archives():
    rows = []
    for path in (ROOT / 'backups').iterdir():
        if not re.fullmatch(r'(?:backup|knowledge-release)-\d{8}T\d{6}Z', path.name):
            continue
        if path.is_dir() and not path.is_symlink() and (path / 'database.dump').is_file():
            rows.append(path)
    return sorted(rows, key=lambda p: p.stat().st_mtime, reverse=True)


def verify_legacy(path, cache=None):
    safe_backup_path(path)
    if not (path / 'COMPLETE').is_file():
        raise BackupError('Legacy backup lacks a completion marker')
    verification = json.loads((path / 'verification.json').read_text())
    checksums = verification.get('checksums', {})
    if not {'database.dump', 'data.tar.gz', 'milvus.tar.gz'} <= checksums.keys():
        raise BackupError('Legacy backup is missing recovery components')
    identity = {}
    for name, expected in checksums.items():
        file = path / name
        if file.parent != path or file.is_symlink() or not file.is_file():
            raise BackupError('Unsafe legacy checksum path')
        stat = file.stat()
        identity[name] = [stat.st_size, stat.st_mtime_ns, expected]
    if cache and cache.get('path') == str(path) and cache.get('identity') == identity:
        return cache
    for name, expected in checksums.items():
        if digest(path / name) != expected:
            raise BackupError('Legacy backup checksum mismatch')
    command(['pg_restore', '--list', str(path / 'database.dump')])
    return {'path': str(path), 'identity': identity, 'verified_at': now()}


def repository_key(policy):
    return hashlib.sha256(policy['repository'].encode()).hexdigest()


def fresh_offsite_proof(policy):
    file = ROOT / 'backup-policy' / 'offsite-verified.json'
    if not policy['repository'] or not file.is_file():
        return False
    proof = json.loads(file.read_text())
    if proof.get('retention_verified', True) is not True:
        return False
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(proof['verified_at'])).total_seconds()
    drill_at = proof.get('database_drill_verified_at', proof.get('verified_at') if proof.get('database_restored') else None)
    drill_age = ((datetime.now(timezone.utc) - datetime.fromisoformat(drill_at)).total_seconds()
                 if drill_at else float('inf'))
    return (0 <= age < 36 * 3600 and proof.get('repository_key') == repository_key(policy)
            and 0 <= drill_age <= (policy['database_restore_interval_days'] + 1) * 86400
            and proof.get('sample_restored') is True
            and bool(proof.get('snapshot_id')))


def guard(policy):
    """Clean only ended partial archives; trim valid archives after offsite verification."""
    state = ROOT / 'backup-policy'
    cache_file = state / 'legacy-verified.json'
    cached = json.loads(cache_file.read_text()) if cache_file.exists() else None
    archives = legacy_archives()
    verified = None
    for path in archives:
        if not (path / 'COMPLETE').is_file():
            continue
        try:
            verified = verify_legacy(path, cached)
            break
        except (BackupError, OSError, ValueError):
            continue
    if verified:
        atomic_json(cache_file, verified)
    deleted = []
    candidates = []
    if verified:
        for path in archives:
            if not (path / 'COMPLETE').exists() and time.time() - path.stat().st_mtime > policy['stale_partial_hours'] * 3600:
                candidates.append(path)
    # The current local recovery copy survives even if it exceeds the byte budget.
    if verified and fresh_offsite_proof(policy):
        full = [p for p in archives if (p / 'COMPLETE').is_file()]
        protected = {Path(verified['path']), *full[:policy['keep_local_full']]}
        candidates += [p for p in full if p not in protected]
    for path in dict.fromkeys(candidates):
        safe_backup_path(path)
        if live_references(path):
            continue
        metadata = {'path': str(path), 'bytes': directory_bytes(path), 'time_utc': now(),
                    'files': [{'name': p.name, 'bytes': p.stat().st_size} for p in path.iterdir()]}
        # Audit metadata is durable before deletion. app.env contents are never logged.
        atomic_json(state / 'retired' / (path.name + '.json'), metadata)
        shutil.rmtree(path)
        deleted.append(metadata)
    free = shutil.disk_usage(ROOT).free
    size = directory_bytes(ROOT / 'backups')
    warnings = []
    if free < policy['min_free_bytes']:
        warnings.append('disk_below_free_space_reserve')
    if size > policy['max_local_bytes']:
        warnings.append('local_backup_budget_exceeded')
    if not policy['repository']:
        warnings.append('oss_not_configured_existing_recovery_copies_preserved')
    elif not os.environ.get('AWS_ACCESS_KEY_ID') or not os.environ.get('AWS_SECRET_ACCESS_KEY'):
        warnings.append('oss_access_credentials_missing')
    elif not fresh_offsite_proof(policy):
        warnings.append('offsite_restore_verification_required')
    return {'time_utc': now(), 'free_bytes': free, 'local_backup_bytes': size,
            'warnings': warnings, 'deleted': deleted,
            'retained_verified_local': verified['path'] if verified else None}


def preflight(policy, estimated_bytes):
    if estimated_bytes < 0:
        raise BackupError('Invalid proposed backup size')
    free = shutil.disk_usage(ROOT).free
    size = directory_bytes(ROOT / 'backups')
    if free - estimated_bytes < policy['min_free_bytes']:
        raise BackupError('New local backup would consume the system free-space reserve')
    if size + estimated_bytes > policy['max_local_bytes']:
        raise BackupError('New local backup would exceed the local backup byte budget')
    return {'status': 'capacity_checked', 'free_bytes': free, 'estimated_bytes': estimated_bytes}


def restic(policy, args, timeout=3600):
    validate_repository(policy['repository'])
    if not os.environ.get('AWS_ACCESS_KEY_ID') or not os.environ.get('AWS_SECRET_ACCESS_KEY'):
        raise BackupError('OSS access credentials are required before backup')
    if not os.environ.get('RESTIC_PASSWORD_FILE') and not os.environ.get('RESTIC_PASSWORD'):
        raise BackupError('A separately preserved repository encryption key is required')
    env = dict(os.environ, RESTIC_REPOSITORY=policy['repository'])
    # Cache stays in bounded runtime space, not the root filesystem.
    prefix = [policy['restic'], '--no-cache', '-o', 's3.bucket-lookup=dns']
    if policy['region']:
        prefix += ['-o', 's3.region=' + policy['region']]
    return command(prefix + list(args), env=env, timeout=timeout)


def prepare_metadata(policy):
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    stage = RUNTIME / 'current'
    if stage.is_symlink() or stage.resolve().parent != RUNTIME.resolve():
        raise BackupError('Unsafe runtime staging path')
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(mode=0o700)
    # RuntimeDirectory is /run (tmpfs) in the installed service. No full data archive.
    size = int(sql("SELECT pg_database_size('supermew')"))
    if size > policy['max_database_bytes'] or shutil.disk_usage(RUNTIME).free < size * 2 + 128_000_000:
        raise BackupError('Insufficient bounded runtime space for database backup')
    import resource
    def limit_size():
        resource.setrlimit(resource.RLIMIT_FSIZE, (policy['max_database_bytes'], policy['max_database_bytes']))
    dump = stage / 'database.dump'
    with dump.open('xb') as output:
        process = subprocess.run(['runuser', '-u', 'postgres', '--', 'pg_dump', '-d', 'supermew', '-Fc'],
                                 stdout=output, stderr=subprocess.PIPE, timeout=300, preexec_fn=limit_size)
    if process.returncode:
        raise BackupError('Online database dump failed')
    command(['pg_restore', '--list', str(dump)])
    current = (ROOT / 'current').resolve(strict=True)
    shutil.copyfile('/etc/supermew/app.env', stage / 'app.env')
    code = stage / 'release'
    code.mkdir()
    for prefix in ('backend', 'frontend', 'deploy'):
        shutil.copytree(current / prefix, code / prefix,
                        ignore=shutil.ignore_patterns('__pycache__', 'node_modules', '*.pyc'), symlinks=False)
    for name in ('pyproject.toml', 'uv.lock', 'requirements.txt', 'release-manifest.json'):
        if (current / name).is_file():
            shutil.copyfile(current / name, code / name)
    operations = stage / 'operations'
    operations.mkdir()
    operational_files = {
        'backup_policy.py': ROOT / 'ops/backup/backup_policy.py',
        'backup-policy.json': CONFIG,
        'backup-oss.env': Path('/etc/supermew/backup-oss.env'),
    }
    for unit in ('supermew-backup.service', 'supermew-backup.timer',
                 'supermew-backup-guard.service', 'supermew-backup-guard.timer'):
        operational_files[unit] = Path('/etc/systemd/system') / unit
    for name, source in operational_files.items():
        if source.is_file():
            shutil.copyfile(source, operations / name)
    sample = next((p for p in (ROOT / 'shared/data/company_knowledge/originals').glob('*')
                   if p.is_file() and not p.is_symlink() and p.stat().st_size <= policy['max_daily_sample_bytes']), None)
    manifest = {'time_utc': now(), 'database_sha256': digest(dump),
                'sample': {'path': str(sample), 'sha256': digest(sample)} if sample else None,
                'scope': 'postgresql, shared/data originals and artifacts, app configuration, release source',
                'milvus': 'Derived index excluded from live file copy; rebuild from source data or retained offline archive'}
    atomic_json(stage / 'recovery.json', manifest)
    return stage, manifest


def recent_database_drill(policy):
    path = ROOT / 'backup-policy/database-drill.json'
    if not path.is_file():
        return None
    proof = json.loads(path.read_text())
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(proof['verified_at'])).total_seconds()
    if (proof.get('repository_key') == repository_key(policy) and proof.get('database_restored') is True
            and 0 <= age < policy['database_restore_interval_days'] * 86400):
        return proof
    return None


def verify_restore(policy, snapshot, stage, manifest):
    previous_drill = recent_database_drill(policy)
    do_database_drill = previous_drill is None
    if do_database_drill and shutil.disk_usage(RUNTIME).free < (stage / 'database.dump').stat().st_size * 2 + 96_000_000:
        raise BackupError('Insufficient bounded runtime space for restore verification')
    target = RUNTIME / 'restore-check'
    if target.is_symlink() or target.resolve().parent != RUNTIME.resolve():
        raise BackupError('Unsafe restore verification path')
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(mode=0o700)
    args = ['restore', snapshot, '--target', str(target), '--include', str(stage / 'recovery.json')]
    if do_database_drill:
        args += ['--include', str(stage / 'database.dump')]
    if manifest['sample']:
        args += ['--include', manifest['sample']['path']]
    restic(policy, args)
    if json.loads((target / str(stage / 'recovery.json').lstrip('/')).read_text()) != manifest:
        raise BackupError('Restored recovery manifest mismatch')
    restored = target / str(stage / 'database.dump').lstrip('/')
    if do_database_drill and digest(restored) != manifest['database_sha256']:
        raise BackupError('Restored database archive checksum mismatch')
    if manifest['sample']:
        sample = manifest['sample']
        if digest(target / sample['path'].lstrip('/')) != sample['sha256']:
            raise BackupError('Restored original checksum mismatch')
    if not do_database_drill:
        shutil.rmtree(target)
        return {'verified_at': now(), 'snapshot_id': snapshot, 'repository_key': repository_key(policy),
                'database_restored': False, 'database_drill_verified_at': previous_drill['verified_at'],
                'database_drill_snapshot': previous_drill['snapshot_id'],
                'manifest_restored': True, 'sample_restored': True,
                'sample_present': bool(manifest['sample'])}
    # Restore the whole database into a disposable database, never over production.
    if shutil.disk_usage(ROOT).free < restored.stat().st_size * 3 + 2 * GB:
        raise BackupError('Insufficient reserve for isolated database restore test')
    database = 'supermew_backup_verify_' + uuid.uuid4().hex[:12]
    command(['runuser', '-u', 'postgres', '--', 'createdb', '-T', 'template0', database])
    try:
        # postgres must be able to read the archive without opening access to secrets.
        transfer = Path('/run') / (database + '.dump')
        try:
            shutil.copyfile(restored, transfer)
            shutil.chown(transfer, user='postgres')
            transfer.chmod(0o600)
            command(['runuser', '-u', 'postgres', '--', 'pg_restore', '--exit-on-error', '--no-owner',
                     '--dbname', database, str(transfer)], timeout=300)
            command(['runuser', '-u', 'postgres', '--', 'psql', '-d', database, '-At', '-v',
                     'ON_ERROR_STOP=1', '-c', 'SELECT count(*) FROM company_documents'])
        finally:
            transfer.unlink(missing_ok=True)
    finally:
        command(['runuser', '-u', 'postgres', '--', 'dropdb', database])
    shutil.rmtree(target)
    timestamp = now()
    return {'verified_at': timestamp, 'snapshot_id': snapshot, 'repository_key': repository_key(policy),
            'database_restored': True, 'sample_restored': True,
            'database_drill_verified_at': timestamp, 'database_drill_snapshot': snapshot,
            'manifest_restored': True,
            'sample_present': bool(manifest['sample'])}


def retain_local_database(policy, stage):
    parent = ROOT / 'backups/policy-database'
    dump = stage / 'database.dump'
    if shutil.disk_usage(ROOT).free - dump.stat().st_size < policy['min_free_bytes']:
        return {'status': 'skipped_low_disk_space'}
    if directory_bytes(ROOT / 'backups') + dump.stat().st_size > policy['max_local_bytes']:
        return {'status': 'skipped_local_byte_budget'}
    parent.mkdir(mode=0o700, exist_ok=True)
    target = parent / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ.dump')
    temporary = parent / (target.name + '.partial')
    shutil.copyfile(dump, temporary)
    if digest(temporary) != digest(dump):
        temporary.unlink()
        raise BackupError('Local database copy verification failed')
    temporary.replace(target)
    for obsolete in sorted(parent.glob('*.dump'), reverse=True)[policy['keep_local_database']:]:
        if obsolete.is_symlink() or obsolete.resolve().parent != parent.resolve():
            raise BackupError('Unsafe local database retention path')
        obsolete.unlink()
    return {'status': 'saved', 'path': str(target)}


def backup(policy, initialize=False):
    validate_repository(policy['repository'])
    proof_file = ROOT / 'backup-policy/offsite-verified.json'
    if proof_file.is_file():
        previous_proof = json.loads(proof_file.read_text())
        previous_proof['retention_verified'] = False
        atomic_json(proof_file, previous_proof)
    if initialize:
        # Only an explicit operator invocation initializes the selected repository.
        restic(policy, ['init'])
    else:
        restic(policy, ['cat', 'config'])
    # Pin the release/configuration only while making the small local snapshot.
    # The long cloud transfer uses a separate lock and must not block releases.
    with managed_locks():
        stage, manifest = prepare_metadata(policy)
    try:
        raw = restic(policy, ['backup', '--json', '--host', HOST, '--tag', TAG,
                              str(ROOT / 'shared/data'), str(stage)], timeout=7200)
        summaries = [row for line in raw.decode().splitlines()
                     if (row := json.loads(line)).get('message_type') == 'summary']
        if not summaries or not summaries[-1].get('snapshot_id'):
            raise BackupError('No complete incremental snapshot was returned')
        snapshot = summaries[-1]['snapshot_id']
        restic(policy, ['check'])
        proof = verify_restore(policy, snapshot, stage, manifest)
        proof['retention_verified'] = False
        atomic_json(proof_file, proof)
        # Only the verified snapshot permits local retirement or cloud retention.
        restic(policy, ['forget', '--host', HOST, '--tag', TAG, '--group-by', 'host,tags',
                        '--keep-last', '1', '--keep-within-daily', str(policy['keep_daily_days']) + 'd',
                        '--keep-weekly', str(policy['keep_weekly']), '--prune'], timeout=7200)
        restic(policy, ['check'])
        proof['retention_verified'] = True
        atomic_json(proof_file, proof)
        if proof['database_restored']:
            atomic_json(ROOT / 'backup-policy/database-drill.json', proof)
        try:
            with managed_locks():
                cleanup = guard(policy)
                local = retain_local_database(policy, stage)
        except LockBusy:
            # The next capacity timer can retire old archives after publication.
            cleanup = {'status': 'deferred_active_deployment', 'deleted': []}
            local = {'status': 'deferred_active_deployment'}
        return {'status': 'offsite_verified', **proof, 'local_database': local, 'cleanup': cleanup,
                'data_added': summaries[-1].get('data_added'), 'application_restart': False}
    finally:
        # Locked, owned runtime directories contain only this job's temporary copies.
        if stage.exists() and not stage.is_symlink() and stage.resolve().parent == RUNTIME.resolve():
            shutil.rmtree(stage)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=CONFIG)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--guard', action='store_true')
    parser.add_argument('--init-repository', action='store_true')
    parser.add_argument('--preflight-bytes', type=int)
    args = parser.parse_args(argv)
    if args.init_repository and not args.run:
        parser.error('--init-repository requires --run')
    policy = load_policy(args.config)
    if args.preflight_bytes is not None:
        try:
            print(json.dumps(preflight(policy, args.preflight_bytes)))
            return 0
        except BackupError as exc:
            print(json.dumps({'status': 'action_required', 'reason': str(exc)}))
            return 2
    if not args.run:
        print(json.dumps({'status': 'plan', 'policy': policy, 'application_restart': False}))
        return 0
    def interrupted(signum, frame):
        raise BackupError('Backup interrupted; production services remain running')
    signal.signal(signal.SIGTERM, interrupted)
    result = None
    exit_code = 0
    try:
        if args.guard:
            with managed_locks():
                result = {'status': 'guard_checked', **guard(policy)}
                exit_code = 2 if result['warnings'] else 0
        else:
            with offsite_backup_lock():
                result = backup(policy, args.init_repository)
    except (BackupError, OSError, ValueError, subprocess.SubprocessError) as exc:
        # Exceptions are intentionally generic; upstream bodies are not published.
        result = {'status': 'action_required', 'time_utc': now(),
                  'reason': str(exc) if isinstance(exc, BackupError) else type(exc).__name__,
                  'application_restart': False}
        exit_code = 2
    atomic_json(ROOT / 'backup-policy' / ('guard-status.json' if args.guard else 'backup-status.json'), result)
    print(json.dumps(result, ensure_ascii=False))
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
