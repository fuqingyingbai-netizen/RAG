"""Freeze a small, reproducible upstream source review; never install projects."""
import hashlib
import json
from pathlib import Path
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'work/person-phase1-20261028/upstream-review'
REPOS = ['alephdata/followthemoney', 'stanford-oval/storm',
         'langchain-ai/open_deep_research', 'assafelovic/gpt-researcher',
         'rgerjeki/Dossier', 'openaleph/openaleph',
         'duhu2000/financial-services-qcc']


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers['User-Agent'] = 'RAG-person-source-review'
    receipts = []
    for repo in REPOS:
        start = time.monotonic()
        folder = DEST / repo.split('/')[-1]
        folder.mkdir(exist_ok=True)
        row = {'repository': 'https://github.com/' + repo, 'files': []}
        try:
            def get(endpoint):
                response = session.get('https://api.github.com/repos/' + repo + endpoint, timeout=25)
                response.raise_for_status()
                return response.json()
            metadata = get('')
            commit = get('/commits/' + metadata['default_branch'])['sha']
            tree = get('/git/trees/' + commit + '?recursive=1')
            paths = [r['path'] for r in tree['tree'] if r['type'] == 'blob']
            row.update(commit=commit, license=(metadata.get('license') or {}).get('spdx_id'),
                       tree_truncated=tree.get('truncated', False), paths=paths)
            (folder / 'metadata.json').write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'repo': repo, 'commit': commit, 'license': row['license'],
                              'candidate_files': [p for p in paths if any(t in p.lower() for t in
                              ['license', 'schema/person.', 'employment.', 'directorship.', 'reviewer',
                               'deep_researcher.py', 'knowledge_curation.py', 'evidence', 'provenance'])][:35]},
                             ensure_ascii=False), flush=True)
        except requests.RequestException as exc:
            row.update(error_type=type(exc).__name__, status='fetch_failed')
            print(json.dumps({'repo': repo, 'error_type': type(exc).__name__}), flush=True)
        row['elapsed_seconds'] = round(time.monotonic() - start, 3)
        receipts.append(row)
        (DEST / 'manifest.json').write_text(json.dumps(receipts, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
