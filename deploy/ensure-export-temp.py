"""Repair an unavailable service temporary directory without restarting workers.

Run explicitly on the managed host as root. Never change systemd's shared
inaccessible-directory permissions or bind anything in the host mount namespace.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path('/opt/supermew')
DROPIN = Path('/etc/systemd/system/supermew.service.d/knowledge-export-temp.conf')


def run(args, **kwargs):
    return subprocess.check_output(args, timeout=30, **kwargs).decode().strip()


def repair():
    import pwd
    if os.geteuid() != 0 or not (ROOT / '.deployment-owned').is_file():
        raise RuntimeError('Expected root on the managed deployment')
    pid = int(run(['systemctl', 'show', 'supermew', '-p', 'MainPID', '--value']))
    process = Path('/proc') / str(pid)
    if pid <= 0 or b'backend.app:app' not in (process / 'cmdline').read_bytes():
        raise RuntimeError('Expected a running research service')
    namespace = os.readlink(process / 'ns/mnt')
    if namespace == os.readlink('/proc/self/ns/mnt'):
        raise RuntimeError('Refusing a repair in the host mount namespace')
    user = pwd.getpwnam('supermew')
    target = ROOT / 'shared/export-tmp'
    if target.is_symlink() or (ROOT / 'shared').resolve() != ROOT / 'shared':
        raise RuntimeError('Unexpected temporary storage link')
    target.mkdir(mode=0o700, exist_ok=True)
    target.chmod(0o700)
    os.chown(target, user.pw_uid, user.pw_gid)
    probe = "import tempfile; f=tempfile.TemporaryFile(dir=__import__('sys').argv[1]); f.write(b'probe'); f.close(); print('writable')"
    python = str(ROOT / 'current/.venv/bin/python')
    prefix = ['nsenter', '-t', str(pid), '-m', '--']
    before = {}
    for directory in ('/tmp', '/var/tmp'):
        try:
            run(prefix + ['runuser', '-u', 'supermew', '--', python, '-c', probe, directory], stderr=subprocess.DEVNULL)
            before[directory] = 'writable'
        except subprocess.CalledProcessError:
            before[directory] = 'unavailable'
    config = b'# Managed by ensure-export-temp.py; applies on the next normal start.\n[Service]\nEnvironment="TMPDIR=/opt/supermew/shared/export-tmp"\n'
    previous = DROPIN.read_bytes() if DROPIN.exists() else None
    if previous is not None and not previous.startswith(b'# Managed by ensure-export-temp.py;'):
        raise RuntimeError('Unrecognized existing temporary-directory override')
    DROPIN.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=DROPIN.parent, delete=False) as output:
        output.write(config)
        pending = Path(output.name)
    pending.chmod(0o644)
    pending.replace(DROPIN)
    run(['systemctl', 'daemon-reload'])
    # The namespace is pinned to this PID; abort if another deployment replaced it.
    if int(run(['systemctl', 'show', 'supermew', '-p', 'MainPID', '--value'])) != pid:
        raise RuntimeError('Service changed; do not modify its namespace')
    mounted = []
    for directory, state in before.items():
        if state == 'unavailable':
            run(prefix + ['mount', '--bind', str(target), directory])
            mounted.append(directory)
        run(prefix + ['runuser', '-u', 'supermew', '--', python, '-c', probe, directory])
    if int(run(['systemctl', 'show', 'supermew', '-p', 'MainPID', '--value'])) != pid:
        raise RuntimeError('Service changed during repair; verify its current instance')
    receipt = {'status': 'repaired', 'time_utc': datetime.now(timezone.utc).isoformat(),
               'pid_unchanged': pid, 'application_restart': False, 'before': before,
               'namespace_bindings': mounted, 'temporary_directory': str(target),
               'next_start_override': str(DROPIN)}
    print(json.dumps(receipt))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', required=True)
    parser.parse_args()
    repair()
