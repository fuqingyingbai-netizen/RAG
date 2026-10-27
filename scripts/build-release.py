"""Build a deterministic source release from an explicit Git commit, never the worktree."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = {'README.md', 'pyproject.toml', 'uv.lock', '.python-version'}
SCRIPT_FILES = {'scripts/create-admin.py', 'scripts/migrate-accounts.py',
                'scripts/check-production-config.py'}
DOC_FILES = {'docs/PRODUCTION_READINESS.md', 'docs/RELEASE_WORKFLOW.md'}
SUFFIXES = {
    'backend': {'.py', '.json', '.txt', '.yaml', '.yml', '.toml', '.md'},
    'frontend': {'.html', '.css', '.js', '.mjs', '.json', '.png', '.jpg', '.jpeg',
                 '.svg', '.ico', '.webp', '.woff', '.woff2', '.ttf', '.otf', '.txt'},
    'deploy': {'.service', '.timer', '.conf', '.sh', '.py', '.json', '.md', '.example', '.yaml', '.yml'},
}
PRIVATE_PARTS = {'work', 'data', 'volumes', 'outputs', 'deliverables', 'log', 'logs',
                 'secrets', 'private', '.ssh', '.git', '.venv', '__pycache__'}
KNOWN_SECRETS = re.compile(
    rb'-----BEGIN (?:OPENSSH |RSA |EC |DSA |ENCRYPTED )?PRIVATE KEY-----|'
    rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\bsk-[A-Za-z0-9_-]{24,}\b')
ASSIGNED_SECRET = re.compile(
    rb'''(?m)^\s*["']?([A-Z_]*(?:API_KEY|SECRET_KEY|PASSWORD|ACCESS_KEY|ACCESS_TOKEN|PRIVATE_KEY))["']?\s*[:=]\s*["']([^\r\n"']{12,})["']''')
URL_PASSWORD = re.compile(rb'\b(?:postgresql(?:\+psycopg2)?|rediss?)://[^/\s:]+:([^@\s/]+)@')


def template_value(value):
    return any(word in value.lower() for word in (b'example', b'your_', b'change', b'replace', b'${', b'<'))


class ReleaseError(Exception):
    pass


def git(repo, *args, input=None):
    result = subprocess.run(['git', '-C', str(repo), *args], input=input, capture_output=True)
    if result.returncode:
        # Git stderr can expose URLs or other local configuration.
        raise ReleaseError('Git operation failed; verify repository and commit reference.')
    return result.stdout


def allowed(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name:
        return False
    if any(part.lower() in PRIVATE_PARTS for part in path.parts):
        return False
    if any(part.lower().startswith('.env') for part in path.parts):
        return False
    if name in TOP_FILES | SCRIPT_FILES | DOC_FILES:
        return True
    return len(path.parts) > 1 and path.suffix.lower() in SUFFIXES.get(path.parts[0], set())


def scan_payload(name, data):
    if KNOWN_SECRETS.search(data):
        raise ReleaseError(f'Possible credential in {name}; release not created.')
    for match in ASSIGNED_SECRET.finditer(data):
        value = match.group(2)
        if not template_value(value):
            raise ReleaseError(f'Possible credential in {name}; release not created.')
    for match in URL_PASSWORD.finditer(data):
        if len(match.group(1)) >= 16 and not template_value(match.group(1)):
            raise ReleaseError(f'Possible connection credential in {name}; release not created.')
    if name.endswith('.env.example'):
        for line in data.splitlines():
            key, separator, value = line.strip().partition(b'=')
            if separator and re.fullmatch(rb'[A-Z_]*(?:API_KEY|SECRET_KEY|PASSWORD|ACCESS_KEY|ACCESS_TOKEN|PRIVATE_KEY)', key):
                value = value.strip().strip(b'\"\'')
                if value and not template_value(value):
                    raise ReleaseError(f'Non-placeholder credential in {name}; release not created.')


def build_release(repo, ref, output_dir):
    commit = git(repo, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').decode().strip()
    timestamp = int(git(repo, 'show', '-s', '--format=%ct', commit).strip())
    tree = git(repo, 'rev-parse', commit + '^{tree}').decode().strip()
    entries, objects = {}, {}
    for record in git(repo, 'ls-tree', '-rz', '--full-tree', commit).split(b'\0'):
        if not record:
            continue
        metadata, raw_name = record.split(b'\t', 1)
        name = raw_name.decode('utf-8')
        mode, kind, object_id = metadata.decode().split()
        if allowed(name):
            if kind != 'blob' or mode not in {'100644', '100755'}:
                raise ReleaseError(f'Unsupported link or entry in runtime path: {name}')
            entries[name] = int(mode, 8) & 0o777
            objects[name] = object_id
        elif PurePosixPath(name).parts[0] in SUFFIXES:
            raise ReleaseError(f'Unexpected file in runtime directory: {name}; review the allowlist.')
    required = {'backend/app.py', 'frontend/index.html', 'pyproject.toml', 'uv.lock', 'README.md',
                'scripts/check-production-config.py', 'deploy/supermew.service', 'deploy/app.env.example'}
    if required - entries.keys():
        raise ReleaseError('Commit is missing required files: ' + ', '.join(sorted(required - entries.keys())))
    names = sorted(entries)
    request = ''.join(objects[name] + '\n' for name in names).encode('ascii')
    # Read Git objects directly: worktree files and local export attributes cannot alter payloads.
    source = io.BytesIO(git(repo, 'cat-file', '--batch', input=request))
    payloads = {}
    for name in names:
        header = source.readline().decode('ascii').split()
        if len(header) != 3 or header[:2] != [objects[name], 'blob']:
            raise ReleaseError('Unable to read committed runtime objects.')
        size = int(header[2])
        data = source.read(size)
        if len(data) != size or source.read(1) != b'\n':
            raise ReleaseError('Incomplete committed runtime object.')
        scan_payload(name, data)
        payloads[name] = data
    manifest = {
        'schema': 'supermew-source-release-v1', 'commit': commit, 'tree': tree,
        'commit_timestamp': timestamp,
        'files': [{'path': name, 'sha256': hashlib.sha256(payloads[name]).hexdigest(),
                   'size': len(payloads[name]), 'mode': entries[name]} for name in sorted(payloads)],
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f'supermew-{commit[:12]}.tar.gz'
    sidecar = target.with_suffix(target.suffix + '.sha256')
    manifest_path = output_dir / f'supermew-{commit[:12]}.manifest.json'
    if any(path.exists() for path in (target, sidecar, manifest_path)):
        raise ReleaseError('Release output already exists; use a new output directory.')
    # Assemble and scan before creating any final output file.
    temporary, created = None, []
    try:
        with tempfile.NamedTemporaryFile(dir=output_dir, suffix='.tmp', delete=False) as raw:
            temporary = Path(raw.name)
            with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as archive:
                    for name, data in [*sorted(payloads.items()), ('release-manifest.json', manifest_bytes)]:
                        item = tarfile.TarInfo(name)
                        item.size, item.mode, item.mtime = len(data), entries.get(name, 0o644), timestamp
                        archive.addfile(item, io.BytesIO(data))
        checksum = hashlib.sha256(temporary.read_bytes()).hexdigest()
        # Exclusive creation prevents accidentally replacing an existing release.
        with target.open('xb') as destination:
            created.append(target)
            with temporary.open('rb') as source_file:
                shutil.copyfileobj(source_file, destination)
        for path, data in ((manifest_path, manifest_bytes),
                           (sidecar, f'{checksum}  {target.name}\n'.encode('ascii'))):
            with path.open('xb') as destination:
                created.append(path)
                destination.write(data)
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', required=True, help='Explicit integrated commit or tag to package')
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'work' / 'releases')
    args = parser.parse_args()
    try:
        target, manifest = build_release(args.repo, args.ref, args.output_dir)
    except ReleaseError as error:
        print(f'FAIL release build: {error}')
        return 1
    except (OSError, ValueError, UnicodeError, tarfile.TarError):
        # No raw exception text: repository paths, filenames and ref arguments may contain secrets.
        print('FAIL release build: verify commit, runtime allowlist, credentials and output directory.')
        return 1
    print(f'PASS commit: {manifest["commit"]}')
    print(f'PASS files: {len(manifest["files"])}')
    print(f'PASS archive: {target}')
    print('Worktree edits and untracked files were not included. No upload or deployment performed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
