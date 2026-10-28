"""Fetch pinned upstream metadata and source paths for a narrow design audit."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'work/company-phase1-20261028/upstream'
REPOS = ['assafelovic/gpt-researcher', 'langchain-ai/open_deep_research',
         'stanford-oval/storm', 'duhu2000/financial-services-qcc',
         'alephdata/followthemoney', 'rgerjeki/Dossier', 'openaleph/openaleph']
PIN_INDEX=ROOT/'deliverables/company-phase1-20261028/upstream-source-index.json'


def pinned_record(repo):
    if not PIN_INDEX.exists():return {}
    return next((row for row in json.loads(PIN_INDEX.read_text(encoding='utf-8'))
                 if row['repository']=='https://github.com/'+repo),{})


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={
            'User-Agent': 'company-phase1-source-audit'}), timeout=35) as response:
        return response.read()


def inspect(repo):
    expected=pinned_record(repo)
    folder = OUT / repo.replace('/', '--')
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / 'metadata.json'
    if manifest.exists():
        previous = json.loads(manifest.read_text(encoding='utf-8'))
        if previous.get('status') == 'pinned' and (not expected or previous.get('commit')==expected['commit']):
            return previous
    result = {'repository': 'https://github.com/' + repo, 'repo': repo,
              'code_copied_into_runtime': False, 'status': 'not_fetched'}
    try:
        metadata = json.loads(fetch('https://api.github.com/repos/' + repo))
        sha = expected.get('commit') or json.loads(fetch('https://api.github.com/repos/' + repo + '/commits/HEAD'))['sha']
        tree = json.loads(fetch('https://api.github.com/repos/' + repo + '/git/trees/' + sha + '?recursive=1'))
        (folder / 'tree.json').write_text(json.dumps(tree, ensure_ascii=False), encoding='utf-8')
        paths = [i['path'] for i in tree.get('tree', []) if i['type'] == 'blob']
        licenses = [p for p in paths if '/' not in p and p.lower().startswith(('license', 'licence', 'copying'))]
        saved = []
        for path in licenses:
            raw = fetch('https://raw.githubusercontent.com/' + repo + '/' + sha + '/' + path)
            (folder / path).write_bytes(raw)
            saved.append({'path': path, 'sha256': hashlib.sha256(raw).hexdigest()})
        result.update(commit=sha, license=metadata.get('license'), license_files=saved,
                      tree_truncated=tree.get('truncated'), status='pinned',
                      candidate_files=[p for p in paths if any(s in p.lower() for s in (
                          'multi_agents', 'multi_agent', 'graph.py', 'state.py', 'schema',
                          'kyb', 'diligence', 'supervisor', 'citation', 'researcher.py',
                          'curation', 'reviewer', 'editor.py', 'source.py'))
                                       and p.endswith(('.py', '.json', '.yml', '.md', '.ts'))])
    except Exception as exc:
        result.update(status='retrieval_failed', error_type=type(exc).__name__, error=str(exc)[:200])
        # Anonymous API has a separate rate limit. A filtered Git checkout is
        # a supported read-only source transport, not an API retry loop.
        result['api_failure'] = result['error']
        try:
            checkout = folder / 'repo'
            proxy = urllib.request.getproxies().get('https')
            git_command = ['git'] + (['-c', 'http.proxy=' + proxy] if proxy else [])
            if not (checkout / '.git').exists():
                subprocess.run([*git_command, 'clone', '--depth=1', '--filter=blob:none', '--no-checkout',
                                'https://github.com/' + repo + '.git', str(checkout)],
                               check=True, capture_output=True, timeout=150)
            def git(*args):
                return subprocess.check_output([*git_command, '-C', str(checkout), *args], timeout=75)
            sha=expected.get('commit') or git('rev-parse','HEAD').decode().strip()
            if expected:
                try:git('cat-file','-e',sha+'^{commit}')
                except subprocess.CalledProcessError:git('fetch','--depth=1','origin',sha)
            paths = git('ls-tree', '-r', '--name-only', sha).decode().splitlines()
            (folder / 'paths.json').write_text(json.dumps(paths), encoding='utf-8')
            licenses = [p for p in paths if '/' not in p and p.lower().startswith(('license', 'licence', 'copying'))]
            saved = []
            for path in licenses:
                raw = git('show', sha+':' + path)
                (folder / path).write_bytes(raw)
                saved.append({'path': path, 'sha256': hashlib.sha256(raw).hexdigest()})
            result.update(status='pinned', commit=sha, transport='filtered_git', license_files=saved,
                          license='See exact retained license text; no code copying authorized by this label.',
                          candidate_files=[p for p in paths if any(s in p.lower() for s in (
                              'multi_agents', 'multi_agent', 'graph.py', 'state.py', 'schema',
                              'kyb', 'diligence', 'supervisor', 'citation', 'researcher.py',
                              'curation', 'reviewer', 'editor.py', 'source.py'))
                              and p.endswith(('.py', '.json', '.yml', '.md', '.ts'))])
            result.pop('error', None)
        except Exception as fallback:
            result.update(git_error_type=type(fallback).__name__, git_error=str(fallback)[:200])
            if isinstance(fallback, subprocess.CalledProcessError) and fallback.stderr:
                result['git_stderr'] = fallback.stderr.decode(errors='replace')[-1000:]
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main():
    with ThreadPoolExecutor(max_workers=2) as executor:
        for result in executor.map(inspect, REPOS):
            print(json.dumps({k: result.get(k) for k in ('repo', 'status', 'commit', 'license', 'error')}
                             | {'candidate_files': result.get('candidate_files', [])[:18]}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
