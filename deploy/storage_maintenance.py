"""Reclaim only regenerable installer caches, yielding to publication/installers."""
from datetime import datetime, timezone, timedelta
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path('/opt/supermew')
STATE = ROOT / 'backup-policy/cache-maintenance-status.json'
UV_CACHE = Path('/root/.cache/uv')
PIP_CACHE = Path('/root/.cache/pip')
APT_CACHE = Path('/var/cache/apt/archives')
UV = ROOT / 'installer/bin/uv'
TARGET = 500_000_000
SMALL_CACHE_TARGET = 100_000_000
LOCKS = ('staging/.deployment.lock', '.frontend-deploy.lock', 'backups/.backup.lock')


def allocated(path):
    if path.is_symlink() or path.resolve() != path:
        raise RuntimeError('Unexpected cache path; refusing maintenance')
    if not path.exists():
        return 0
    total = 0
    seen = set()
    for parent, directories, files in os.walk(path, followlinks=False):
        directories[:] = [d for d in directories if not (Path(parent)/d).is_symlink()]
        for name in files:
            p = Path(parent)/name
            try:
                s = p.lstat()
            except FileNotFoundError:
                continue
            key = (s.st_dev, s.st_ino)
            if not p.is_symlink() and key not in seen:
                total += s.st_blocks * 512
                seen.add(key)
    return total


def busy_reason():
    # Read existing locks instead of acquiring a lock which could reject a release.
    identities = set()
    for relative in LOCKS:
        p = ROOT / relative
        if p.exists():
            s = p.stat()
            identities.add((os.major(s.st_dev), os.minor(s.st_dev), s.st_ino))
    for line in Path('/proc/locks').read_text().splitlines():
        f = line.split()
        if len(f) > 5 and f[1] == 'FLOCK':
            major, minor, inode = f[5].split(':')
            if (int(major, 16), int(minor, 16), int(inode)) in identities:
                return 'publication_or_local_backup_active'
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            args = (process/'cmdline').read_bytes().decode(errors='replace').split('\0')
        except OSError:
            continue
        program = Path(args[0]).name
        if program in ('uv', 'uvx', 'pip', 'pip3', 'apt', 'apt-get', 'dpkg'):
            return 'package_installation_active'
        if program.startswith('python') and args[1:2] == ['-m'] and args[2:3] in (['pip'], ['uv']):
            return 'package_installation_active'
    current_env = (ROOT/'current/.venv').resolve()
    if current_env.is_relative_to(UV_CACHE):
        return 'active_virtualenv_is_inside_cache'
    return None


def command(args):
    # Native uv cleanup coordinates with uv installers; never force its lock.
    reason = busy_reason()
    if reason:
        raise RuntimeError('Maintenance deferred: ' + reason)
    result = subprocess.run(args, capture_output=True, timeout=300,
                            env=dict(os.environ, UV_LOCK_TIMEOUT='1'))
    if result.returncode:
        raise RuntimeError('Maintenance deferred or tool failed: ' + Path(args[0]).name)


def maintain(previous):
    reason = busy_reason()
    if reason:
        return {'status': 'deferred', 'reason': reason}, 75
    caches = (UV_CACHE, PIP_CACHE, APT_CACHE)
    before = {str(p): allocated(p) for p in caches}
    stamp = datetime.now(timezone.utc)
    last = previous.get('last_prune_utc')
    weekly = not last or stamp-datetime.fromisoformat(last) >= timedelta(days=7)
    actions = []
    if weekly or sum(before.values()) > TARGET:
        if busy_reason():
            return {'status': 'deferred', 'reason': 'publication_or_installation_started'}, 75
        command([str(UV), 'cache', 'prune', '--ci', '--cache-dir', str(UV_CACHE), '--no-config', '--offline'])
        actions.append('uv_prune_ci')
        last = stamp.isoformat()
    if allocated(PIP_CACHE) > SMALL_CACHE_TARGET:
        command(['/usr/bin/pip', '--disable-pip-version-check', '--cache-dir', str(PIP_CACHE), 'cache', 'purge'])
        actions.append('pip_cache_purge')
    if allocated(APT_CACHE) > SMALL_CACHE_TARGET:
        command(['apt-get', 'clean'])
        actions.append('apt_cache_clean')
    if sum(allocated(p) for p in caches) > TARGET:
        if busy_reason():
            return {'status': 'deferred', 'reason': 'publication_or_installation_started', 'last_prune_utc': last}, 75
        command([str(UV), 'cache', 'clean', '--cache-dir', str(UV_CACHE), '--no-config', '--offline'])
        actions.append('uv_cache_clean_above_budget')
    after = {str(p): allocated(p) for p in caches}
    return {'status': 'checked', 'time_utc': stamp.isoformat(), 'last_prune_utc': last,
            'before_bytes': before, 'after_bytes': after, 'actions': actions,
            'target_bytes': TARGET, 'over_target': sum(after.values()) > TARGET}, 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    if not args.run:
        print(json.dumps({'status': 'plan', 'target_bytes': TARGET, 'weekly_prune_days': 7}))
        return 0
    if os.geteuid() != 0 or not (ROOT/'.deployment-owned').is_file():
        raise RuntimeError('Expected root on the managed server')
    previous = json.loads(STATE.read_text()) if STATE.exists() else {}
    try:
        result, code = maintain(previous)
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        result, code = {'status': 'deferred', 'reason': str(error) if isinstance(error, RuntimeError) else type(error).__name__}, 75
    result.setdefault('last_prune_utc', previous.get('last_prune_utc'))
    STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, indent=2));temporary.chmod(0o600);temporary.replace(STATE)
    print(json.dumps(result))
    return code


if __name__ == '__main__':
    sys.exit(main())
