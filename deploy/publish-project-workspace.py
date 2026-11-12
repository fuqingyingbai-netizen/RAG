"""Atomically publish the project workspace UI while preserving the running backend."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request

ROOT = Path('/opt/supermew')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, payload, mode=0o644):
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def runtime():
    process = int(subprocess.check_output(['systemctl', 'show', 'supermew', '-p', 'MainPID', '--value']).strip())
    if process <= 0 or b'backend.app:app' not in Path(f'/proc/{process}/cmdline').read_bytes():
        raise RuntimeError('Expected the running research service')
    with urllib.request.urlopen('http://127.0.0.1:8010/version', timeout=10) as response:
        version = json.load(response)
    return process, version


def fingerprint(release, excluded=()):
    return {str(p.relative_to(release)): digest(p.read_bytes())
            for p in sorted(release.rglob('*'))
            if p.is_file() and not p.is_symlink()
            and not any(part in p.parts for part in ('.venv', 'data', '__pycache__', '.pytest_cache', '.git'))
            and str(p.relative_to(release)) not in excluded}


def publish(package):
    if os.geteuid() != 0 or not (ROOT / '.deployment-owned').is_file():
        raise RuntimeError('Expected the managed deployment')
    package = package.resolve(strict=True)
    if ROOT / 'staging' not in package.parents:
        raise RuntimeError('Expected a staged package')
    manifest = json.loads((package / 'project-workspace-manifest.json').read_text())
    commit = manifest['commit']
    if not re.fullmatch('[a-f0-9]{40}', commit):
        raise RuntimeError('Expected a fixed source commit')
    baseline = manifest['baseline']
    if set(baseline) != {'frontend/index.html', 'frontend/script.js'}:
        raise RuntimeError('Expected both entrypoint and source baselines')
    assets = {}
    for row in manifest['files']:
        name = row['path']
        if not re.fullmatch(r'frontend/(?:index\.html|script\.js|project-workspace\.(?:js|css)|(?:script|project-workspace|company-chapters)\.[a-f0-9]{12}\.(?:js|css))', name):
            raise RuntimeError('Unexpected workspace asset')
        path = package / name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(package):
            raise RuntimeError('Expected a regular staged asset')
        payload = path.read_bytes()
        if digest(payload) != row['sha256'] or name in assets:
            raise RuntimeError('Invalid asset checksum or duplicate')
        match = re.search(r'\.([a-f0-9]{12})\.', name)
        if match and digest(payload)[:12] != match[1]:
            raise RuntimeError('Immutable asset name differs from its bytes')
        assets[name] = payload
    if not {'frontend/index.html', 'frontend/script.js', 'frontend/project-workspace.js', 'frontend/project-workspace.css'} <= assets.keys():
        raise RuntimeError('Incomplete workspace package')
    html = assets['frontend/index.html'].decode('utf-8')
    if len(re.findall(r'src="project-workspace\.[a-f0-9]{12}\.js"', html)) != 1:
        raise RuntimeError('Expected a versioned workspace component')
    changed = set(assets) | {'release-manifest.json'}
    with ExitStack() as stack:
        for name in ('staging/.deployment.lock', '.frontend-deploy.lock'):
            lock = stack.enter_context((ROOT / name).open('a'))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        release = (ROOT / 'current').resolve(strict=True)
        process, version = runtime()
        if str(release) != manifest['expected_release'] or release.parent != ROOT / 'releases':
            raise RuntimeError('Another release changed the application')
        if Path(f'/proc/{process}/cwd').resolve() != release:
            raise RuntimeError('Running and current release differ')
        for name, checksum in baseline.items():
            if digest((release / name).read_bytes()) != checksum:
                raise RuntimeError('Workspace source changed during validation: ' + name)
        for name in assets:
            path = release / name
            if path.is_symlink() or not path.parent.resolve().is_relative_to(release):
                raise RuntimeError('Unexpected asset destination')
            if re.search(r'\.[a-f0-9]{12}\.', name) and path.exists() and path.read_bytes() != assets[name]:
                raise RuntimeError('Immutable asset collision')
        # Ensure every retained reference is present before changing the entrypoint.
        for name in re.findall(r'\s(?:src|href)="([^"?#]+)', html):
            if name.startswith(('http:', 'https:', '/', 'data:')):
                continue
            target = release / 'frontend' / name
            if not target.resolve().is_relative_to(release / 'frontend'):
                raise RuntimeError('Unexpected entrypoint reference')
            if 'frontend/' + name not in assets and not target.is_file():
                raise RuntimeError('Missing retained resource: ' + name)
        before = fingerprint(release, changed)
        originals = {name: (release / name).read_bytes() if (release / name).exists() else None for name in changed}
        backup = ROOT / 'backups' / ('project-workspace-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + commit[:12])
        backup.mkdir(mode=0o700, parents=True)
        for name, payload in originals.items():
            if payload is not None:
                path = backup / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
                if digest(path.read_bytes()) != digest(payload):
                    raise RuntimeError('Frontend backup failed verification')
        (backup / 'backup.json').write_text(json.dumps({'source_commit':commit, 'release':str(release), 'originals':{name:digest(data) if data is not None else None for name,data in originals.items()}}, indent=2))
        try:
            # Immutable resources first; the index changes only when all assets exist.
            for name, payload in assets.items():
                if name != 'frontend/index.html':
                    atomic_write(release / name, payload)
            if runtime() != (process, version) or (ROOT / 'current').resolve() != release:
                raise RuntimeError('Application changed during publication')
            atomic_write(release / 'frontend/index.html', assets['frontend/index.html'])
            with urllib.request.urlopen('http://127.0.0.1:8010/', timeout=10) as response:
                if response.read() != assets['frontend/index.html']:
                    raise RuntimeError('Served entrypoint differs from the validated package')
            if fingerprint(release, changed) != before or runtime() != (process, version):
                raise RuntimeError('Unrelated files or backend changed')
            release_manifest = json.loads((release / 'release-manifest.json').read_text())
            rows = {row['path']:row for row in release_manifest['files']}
            for name, payload in assets.items():
                rows[name] = {'path':name, 'sha256':digest(payload)}
            release_manifest['files'] = sorted(rows.values(), key=lambda row:row['path'])
            release_manifest['project_workspace_commit'] = commit
            atomic_write(release / 'release-manifest.json', json.dumps(release_manifest, indent=2).encode())
            receipt = {'status':'published', 'commit':commit, 'release':str(release), 'instance_id':version['instance_id'], 'pid':process, 'backup':str(backup), 'unrelated_files_verified':len(before), 'files':manifest['files']}
            atomic_write(ROOT / ('project-workspace-receipt-' + commit[:12] + '.json'), json.dumps(receipt, indent=2).encode(), 0o600)
            (backup / 'receipt.json').write_text(json.dumps(receipt, indent=2))
            print(json.dumps(receipt), flush=True)
        except BaseException:
            restore_order = ['frontend/index.html', 'release-manifest.json'] + sorted(changed - {'frontend/index.html', 'release-manifest.json'})
            for name in restore_order:
                payload = originals[name]
                path = release / name
                if payload is None:
                    # Already-loaded pages can still request these immutable resources.
                    if not re.search(r'\.[a-f0-9]{12}\.', name):
                        path.unlink(missing_ok=True)
                else:
                    atomic_write(path, payload)
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--run', action='store_true', required=True)
    publish(parser.parse_args().package)
