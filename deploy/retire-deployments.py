"""Validate an explicit retirement plan; delete only with --run, without restart."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request

ROOT = Path('/opt/supermew')


def process_pid():
    return int(subprocess.check_output(['systemctl', 'show', 'supermew', '-p', 'MainPID', '--value']))


def version():
    with urllib.request.urlopen('http://127.0.0.1:8010/version', timeout=10) as response:
        return json.load(response)


def refs():
    result = set()
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        for link in [proc / 'cwd', proc / 'exe'] + list((proc / 'fd').glob('*')):
            try:
                target = os.readlink(link)
                if target.startswith(str(ROOT)):
                    result.add(target.removesuffix(' (deleted)'))
            except OSError:
                pass
        try:
            for line in (proc / 'maps').read_text().splitlines():
                if str(ROOT) in line:
                    result.add(line.split(maxsplit=5)[-1].removesuffix(' (deleted)'))
        except (OSError, IndexError):
            pass
    return result


def referenced(path, paths):
    return any(p == str(path) or p.startswith(str(path) + '/') for p in paths)


def check_instance(plan):
    if (ROOT / 'current').resolve() != Path(plan['baseline_current']):
        raise RuntimeError('Deployment changed; create a new retirement plan')
    if process_pid() != plan['baseline_pid'] or version()['instance_id'] != plan['baseline_instance']:
        raise RuntimeError('Running instance changed; create a new retirement plan')


def check_sources(plan):
    current = Path(plan['baseline_current'])
    for name, row in plan['protect_source_files'].items():
        path = current / name
        if not path.resolve().is_relative_to(current) or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise RuntimeError('Running source changed: ' + name)


def check_backups(plan):
    verified = 0
    for name in plan['keep_verified_backups']:
        p = Path(name)
        if p.parent != ROOT / 'backups' or p.is_symlink() or not (p / 'COMPLETE').is_file():
            raise RuntimeError('Retained backup is not complete')
        checks = json.loads((p / 'verification.json').read_text()).get('checksums', {})
        if not {'database.dump', 'data.tar.gz', 'milvus.tar.gz'}.issubset(checks):
            raise RuntimeError('Retained backup lacks expected verification')
        for filename, expected in checks.items():
            f = p / filename
            if f.parent != p or f.is_symlink():
                raise RuntimeError('Unsafe backup verification path')
            with f.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                    raise RuntimeError('Retained backup checksum mismatch')
        subprocess.run(['pg_restore', '--list', str(p / 'database.dump')], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
        verified += 1
    if verified < 2:
        raise RuntimeError('Require at least two verified retained backups')


def targets(plan):
    result = []
    for field, group in [('remove_releases', 'releases'), ('remove_validation', 'validation'),
                         ('remove_backups', 'backups'), ('remove_test_runtimes', 'candidates')]:
        for raw in plan[field]:
            p = Path(raw)
            if not p.is_absolute() or p.is_symlink() or not p.is_dir() or p.resolve() != p:
                raise RuntimeError('Refusing noncanonical retirement path: ' + raw)
            if group == 'candidates':
                valid = p.name == 'isolated-runtime' and p.is_relative_to(ROOT / 'candidates/industry-stability-20261103')
            else:
                valid = p.parent == ROOT / group
            if not valid or os.path.ismount(p) or any(x.is_symlink() for x in p.parents if x != Path('/')):
                raise RuntimeError('Path is outside the permitted retirement scope')
            if raw in plan['keep_releases'] + plan['keep_verified_backups'] + [plan['retain_incomplete_backup']]:
                raise RuntimeError('Protected recovery path is in the deletion list')
            result.append(p)
    for kept in plan['keep_releases']:
        p = Path(kept)
        if any(p == target or p.is_relative_to(target) for target in result):
            raise RuntimeError('A retained release would be removed')
        for parent, dirs, files in os.walk(p, followlinks=False):
            dirs[:] = [n for n in dirs if n not in ['node_modules', '__pycache__', '.git']]
            for name in dirs + files:
                link = Path(parent) / name
                if link.is_symlink() and any(link.resolve() == t or link.resolve().is_relative_to(t) for t in result):
                    raise RuntimeError('Retained release depends on a retirement target')
    return result


def retire(plan, execute):
    import fcntl
    if os.geteuid() != 0 or not (ROOT / '.deployment-owned').is_file() or not plan['preservation_verified']:
        raise RuntimeError('Expected an authorized, preserved managed-host retirement')
    with ExitStack() as stack:
        for name in ['staging/.deployment.lock', '.frontend-deploy.lock', 'backups/.backup.lock']:
            lock = stack.enter_context((ROOT / name).open('a'))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        check_instance(plan)
        check_sources(plan)
        check_backups(plan)
        paths = targets(plan)
        live = refs()
        if any(referenced(p, live) for p in paths):
            raise RuntimeError('A running process still uses a retirement target')
        before = shutil.disk_usage(ROOT).free
        removed = []
        if execute:
            for p in paths:
                check_instance(plan)
                if referenced(p, refs()):
                    raise RuntimeError('Target became active; stop retirement')
                shutil.rmtree(p)
                removed.append(str(p))
                print(json.dumps({'phase': 'removed', 'path': str(p)}), flush=True)
        check_instance(plan)
        check_sources(plan)
        return {'status': 'retired' if execute else 'validated', 'time_utc': datetime.now(timezone.utc).isoformat(),
                'deleted_paths': removed, 'planned_paths': len(paths), 'pid_unchanged': process_pid(),
                'instance_unchanged': version()['instance_id'], 'application_restart': False,
                'disk_free_before': before, 'disk_free_after': shutil.disk_usage(ROOT).free,
                'current_source_unchanged': True, 'verified_backups_retained': plan['keep_verified_backups']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    print(json.dumps(retire(json.loads(args.plan.read_text()), args.run)), flush=True)
