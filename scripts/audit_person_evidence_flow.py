"""Read-only retained-corpus audit. Counts documents, cards and citations separately."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from person_evidence import cited_ids, split_sections


def read(root, name):
    return json.loads((root / name).read_text(encoding='utf-8'))


def audit(root):
    from search_results import canonical_source_url
    sources = read(root, 'source-snapshots.json')
    cleaned = read(root, 'cleaned_facts.json')
    ledger = read(root, 'person_claim_ledger.json')
    selection = read(root, 'chapter-selection-audit.json')
    report = split_sections((root / 'desktop_report.md').read_text(encoding='utf-8'))
    facts = ledger['facts']
    by_id = {f['evidence_id']: f for f in facts}
    result = {'run': str(root), 'sources_sha256': hashlib.sha256((root / 'source-snapshots.json').read_bytes()).hexdigest(),
              'source_records': len(sources), 'unique_urls': len({canonical_source_url(s['url']) for s in sources}),
              'cleaned_cards': len(cleaned['facts']), 'report_cards': len(facts), 'chapters': [], 'sources': []}
    body_ids = set().union(*(cited_ids(report.get(n, '')) for n in range(1, 14)))
    result.update(body_evidence_ids=len(body_ids), body_unique_urls=len({canonical_source_url(by_id[e]['source_url']) for e in body_ids if e in by_id}))
    for n in range(1, 16):
        sel = selection[str(n)]
        ids = cited_ids(report.get(n, ''))
        result['chapters'].append({'chapter': n, 'title': report.get(n, '').splitlines()[0],
            'candidates_audited': len(sel['selection_audit']), 'selected': len(sel['selected_ids']), 'cited_ids': len(ids),
            'unique_urls': len({canonical_source_url(by_id[e]['source_url']) for e in ids if e in by_id}),
            'exclusions': dict(Counter(r['reason'] for r in sel['selection_audit'] if r['status'] != 'selected')),
            'material_coverage': sel['material_coverage'],
            'uncited_selected': sorted(set(sel['selected_ids']) - ids),
            'review': next((r for r in ledger['diagnostic']['chapters'] if r['chapter'] == n), {})})
    for s in sources:
        url = s['url']
        meta = s.get('source_metadata') or {}
        cards = [f for f in facts if f['source_url'] == url]
        flow = []
        for f in cards:
            eid = f['evidence_id']
            flow.append({'id': eid, 'fact': f['fact'], 'scope': f.get('subject_scope'),
                'candidate_chapters': [int(n) for n, v in selection.items() if any(r['evidence_id'] == eid for r in v['selection_audit'])],
                'selected_chapters': [int(n) for n, v in selection.items() if eid in v['selected_ids']],
                'cited_chapters': [n for n in range(1, 14) if eid in cited_ids(report.get(n, ''))],
                'indexed': eid in cited_ids(report.get(14, '')),
                'selection': {n: next(r for r in v['selection_audit'] if r['evidence_id'] == eid) for n,v in selection.items() if any(r['evidence_id'] == eid for r in v['selection_audit'])}})
        result['sources'].append({'source_id': s['id'], 'title': s['title'], 'url': url, 'canonical_url': canonical_source_url(url),
            'body_chars': len(s.get('content') or ''), 'body_sha256': hashlib.sha256((s.get('content') or '').encode()).hexdigest(),
            'content_kind': meta.get('content_kind'), 'fetch_status': meta.get('fetch_status'),
            'identity_status': meta.get('identity_status'), 'identity_confidence': meta.get('identity_confidence'),
            'discovery_only': meta.get('person_discovery_only'), 'pdf_pages': meta.get('fetched_pages'),
            'metadata': meta, 'cleaned_cards': sum(f['source_url'] == url for f in cleaned['facts']),
            'report_cards': len(cards), 'body_cited_cards': sum(f['evidence_id'] in body_ids for f in cards),
            'rejected_cards': [r for r in [*cleaned.get('person_rejected_facts', []), *ledger.get('rejected_facts', [])] if r.get('source_url') == url],
            'facts': flow})
    result['retrieval'] = read(root, 'person_retrieval_audit.json')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'sources','retrieval','chapters'}}, ensure_ascii=False))
    for c in result['chapters']:
        print(json.dumps({k:v for k,v in c.items() if k not in {'review','material_coverage'}}, ensure_ascii=False))
    for s in result['sources']:
        print(json.dumps({k:s[k] for k in ['source_id','title','body_chars','content_kind','fetch_status','identity_confidence','cleaned_cards','report_cards','body_cited_cards']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
