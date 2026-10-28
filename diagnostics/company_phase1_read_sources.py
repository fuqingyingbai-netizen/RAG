"""Retain exact selected upstream files and function indexes, without vendoring."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'work/company-phase1-20261028/upstream'
FILES = {
    'assafelovic/gpt-researcher': ['multi_agents/agent.py', 'multi_agents/agents/orchestrator.py',
        'multi_agents/agents/editor.py', 'multi_agents/agents/reviewer.py', 'multi_agents/agents/reviser.py'],
    'langchain-ai/open_deep_research': ['src/open_deep_research/deep_researcher.py',
        'src/open_deep_research/state.py', 'src/open_deep_research/configuration.py'],
    'stanford-oval/storm': ['knowledge_storm/storm_wiki/modules/knowledge_curation.py'],
    'duhu2000/financial-services-qcc': ['commands/qcc-kyb-profile.md', 'skills/kyb-verification-qcc/SKILL.md'],
    'alephdata/followthemoney': ['followthemoney/proxy.py', 'followthemoney/schema/Company.yaml',
        'followthemoney/schema/Ownership.yaml', 'followthemoney/schema/Directorship.yaml',
        'followthemoney/schema/Document.yaml'],
    'rgerjeki/Dossier': ['src/dossier/models.py', 'src/dossier/case.py', 'src/dossier/ui/report_editor.py'],
    'openaleph/openaleph': ['aleph/model/document.py', 'aleph/model/entity.py', 'aleph/model/entityset.py'],
}


def retain(item):
    repo, paths = item
    directory = OUT / repo.replace('/', '--')
    metadata = json.loads((directory / 'metadata.json').read_text())
    sha = metadata['commit']
    results = []
    for path in paths:
        destination = directory / 'selected' / path
        url = f'https://raw.githubusercontent.com/{repo}/{sha}/{path}'
        try:
            if destination.exists():
                raw = destination.read_bytes()
            else:
                with urllib.request.urlopen(url, timeout=40) as response:
                    raw = response.read()
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(raw)
            text = raw.decode('utf-8')
            results.append({'path': path, 'url': f'https://github.com/{repo}/blob/{sha}/{path}',
                            'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
                            'definitions': [{'line': n, 'definition': line.strip()} for n, line in enumerate(text.splitlines(), 1)
                                            if re.match(r'\s*(?:async )?(?:def |class )', line)]})
        except Exception as exc:
            results.append({'path': path, 'error': type(exc).__name__ + ': ' + str(exc)[:120]})
    metadata['selected_files'] = results
    (directory / 'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'repo': repo, 'files': [{'path': row['path'], 'error': row.get('error')} for row in results]}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(retain, FILES.items()))
