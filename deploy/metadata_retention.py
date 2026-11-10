"""Rotate complete publication archives only after exact offsite coverage is proven."""
import hashlib
import json
from pathlib import Path
import re


def inventory(root):
    result = []
    for path in sorted((root/'backups').iterdir(), reverse=True):
        if not re.fullmatch(r'knowledge-release-\d{8}T\d{6}Z', path.name):
            continue
        if path.is_symlink() or not path.is_dir() or not (path/'METADATA_COMPLETE').is_file():
            continue
        try:
            manifest = json.loads((path/'verification.json').read_text())
            hashes = manifest['checksums']
            if manifest['scope'] != 'database-and-config' or not {'database.dump', 'app.env', 'previous-release-manifest.json'} <= hashes.keys():
                continue
            files = list(path.iterdir())
            if any(p.is_symlink() or not p.is_file() for p in files):
                continue
            if {p.name for p in files} != set(hashes) | {'verification.json', 'METADATA_COMPLETE'}:
                continue
            for name, expected in hashes.items():
                if Path(name).name != name or not re.fullmatch('[a-f0-9]{64}', expected):
                    raise ValueError()
                with (path/name).open('rb') as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                        raise ValueError()
            result.append({'path': str(path), 'verification_sha256': hashlib.sha256((path/'verification.json').read_bytes()).hexdigest(),
                'previous': manifest['previous'], 'new_commit': manifest['new_commit']})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return result


def candidates(root, rows, proof, keep=3):
    """Caller owns deployment/backup locks and validates proof freshness first."""
    if type(keep) is not int or keep < 3:
        raise ValueError('Keep at least three publication archives')
    protected = {row['path'] for row in rows[:keep]}
    current = (root/'current').resolve()
    # The receipt for the active release identifies its exact rollback archive.
    receipt = root/('knowledge-release-receipt-'+current.name[:12]+'.json')
    if receipt.exists():
        try:
            data = json.loads(receipt.read_text())
            if data['commit'] != current.name:
                return []
            protected.add(data['backup'])
        except (ValueError, KeyError, TypeError):
            return []
    else:
        return []  # Unknown rollback provenance: preserve everything.
    covered = {r['path']: r['verification_sha256'] for r in proof.get('publication_archives', [])}
    return [Path(row['path']) for row in rows if row['path'] not in protected and
        covered.get(row['path']) == row['verification_sha256']]
