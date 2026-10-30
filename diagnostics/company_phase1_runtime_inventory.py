"""Record reproducible runtime versions without loading secrets or networking."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    installed = {canonicalize_name(d.metadata['Name']): d.version
                 for d in metadata.distributions() if d.metadata.get('Name')}
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    requirements = []
    for value in project['project']['dependencies']:
        item = Requirement(value)
        active = item.marker is None or item.marker.evaluate()
        version = installed.get(canonicalize_name(item.name))
        requirements.append({'requirement': value, 'active_on_this_platform': active,
            'installed_version': version,
            'satisfies_declared_version': (not active or version is not None and
                                            (not item.specifier or item.specifier.contains(version)))})
    lock = tomllib.loads((ROOT / 'uv.lock').read_text(encoding='utf-8'))
    locked = {}
    for package in lock.get('package', []):
        if package.get('version'):
            locked.setdefault(canonicalize_name(package['name']), set()).add(package['version'])
    differences = [{'name': name, 'installed_version': version, 'locked_versions': sorted(locked[name])}
                   for name, version in sorted(installed.items()) if name in locked and version not in locked[name]]
    result = {'recorded_at': datetime.now(timezone.utc).isoformat(),
        'generator_sha256': sha(Path(__file__)),
        'repository_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'interpreter': {'version': sys.version, 'platform': platform.platform(),
                        'executable': sys.executable, 'sha256': sha(Path(sys.executable))},
        'dependency_inputs': {name: sha(ROOT / name) for name in ['pyproject.toml', 'uv.lock']},
        'installed_distributions': installed, 'declared_runtime_requirements': requirements,
        'installed_versions_differing_from_lock': differences,
        'notes': ['Read-only metadata inventory; no environment variables, credentials, direct URLs or file-origin metadata are recorded.',
                  'This inventory is not a dependency resolver or a claim that a clean lockfile installation was tested.',
                  'Tests and real report acceptance remain separate evidence.'],
        'report_acceptance': False, 'network_calls': 0, 'environment_mutated': False}
    output = ROOT / 'deliverables/company-phase1-20261028/runtime-inventory-20261030.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'installed_distributions': len(installed),
        'declared_requirements_not_satisfied': [r['requirement'] for r in requirements if not r['satisfies_declared_version']],
        'installed_versions_differing_from_lock': len(differences), 'report_acceptance': False}))


if __name__ == '__main__':
    main()
