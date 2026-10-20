"""Re-fetch only known PDFs rejected before identity matching, without searches."""
import argparse
import json
import hashlib
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline', type=Path)
    parser.add_argument('--max-documents', type=int, default=2, choices=range(1, 5))
    parser.add_argument('--deadline-utc', required=True)
    parser.add_argument('--fetch-cache-dir', type=Path, help='Reuse explicitly retained original-extraction responses by exact URL')
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    from research_workflow import ResearchWorkflow
    from person_chapter_research import compact, peer_excerpts, document_issuer_context
    from types import SimpleNamespace
    baseline = args.baseline.resolve()
    out = ROOT / 'work/person-optimization' / ('pdf-recovered-' + datetime.now().strftime('%Y%m%dT%H%M%S'))
    out.mkdir(parents=True)
    snapshots = json.loads((baseline / 'source-snapshots.json').read_text(encoding='utf-8'))
    audit = json.loads((baseline / 'person_retrieval_audit.json').read_text(encoding='utf-8'))
    summary = json.loads((baseline / 'summary.json').read_text(encoding='utf-8'))
    followup = audit.get('chapter_7_8_followup') or {}
    peers = followup.get('peer_candidates') or []
    candidates = []
    for attempt in followup.get('attempts', []):
        peer = next((p for p in peers if p['name'] in attempt.get('query', '')), None)
        for item in attempt.get('sources', []):
            if peer and item.get('reason') == 'peer_name_or_company_missing' and urlparse(item['url']).path.lower().endswith('.pdf'):
                candidates.append((item['url'], peer))
    results, seen, new_fetches = [], set(), 0
    workflow = ResearchWorkflow()
    deadline = datetime.fromisoformat(args.deadline_utc.replace('Z', '+00:00'))
    for url, peer in candidates:
        if len(results) >= args.max_documents or (deadline-datetime.now(timezone.utc)).total_seconds() < 60:
            break
        if url in seen:
            continue
        seen.add(url)
        print(json.dumps({'stage': 'pdf_original', 'status': 'running', 'url': url}, ensure_ascii=False), flush=True)
        cached = args.fetch_cache_dir / (hashlib.sha256(url.encode()).hexdigest() + '.json') if args.fetch_cache_dir else None
        retained = json.loads(cached.read_text(encoding='utf-8')) if cached and cached.exists() else None
        reused = bool(retained and retained.get('url') == url and retained.get('profile') == 'person_full_pdf_ocr_v1')
        if reused:
            fetched = retained['fetched']
        else:
            new_fetches += 1
            fetched = workflow._fetch_web_url_with_timeout(url, False, document_profile='person')
            if cached:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps({'url': url, 'profile': 'person_full_pdf_ocr_v1', 'fetched': fetched}, ensure_ascii=False), encoding='utf-8')
        text = fetched.get('content') or ''
        matched = fetched.get('status') == 'done' and all(compact(v) in compact(text) for v in (peer['name'], peer['company']))
        kind = workflow._detect_source_type(urlparse(url).netloc, '', url)
        context = SimpleNamespace(url=url, source_type=kind, source_metadata={'document_pages': fetched.get('document_pages', [])})
        quotes = peer_excerpts(text, peer, document_issuer_context(context, peer)) if matched else []
        (out / ('original-' + str(len(results)+1) + '.txt')).write_text(text, encoding='utf-8')
        receipt = {'url': url, 'status': fetched.get('status'), 'text_chars': len(text),
                   'retained_fetch_reused': reused,
                   'peer_identity_matched': matched, 'own_subject_excerpts': len(quotes),
                   'document_extraction': fetched.get('document_extraction', {})}
        results.append(receipt)
        print(json.dumps({k: v for k, v in receipt.items() if k != 'document_extraction'}, ensure_ascii=False), flush=True)
        if not matched:
            continue
        existing = next((s for s in snapshots if s['url'] == url), None)
        row = existing or {'id': max(s['id'] for s in snapshots) + 1, 'url': url}
        row.update(source_type=workflow._detect_source_type(urlparse(url).netloc, '', url), title='同行人物原始披露 ' + peer['name'],
                   content=text, summary='', credibility_score=70,
                   source_metadata={'module': '可比人物资料', 'person_chapters': [8], 'identity_confidence': 'low',
                       'identity_status': 'quarantined', 'identity_reason': '可比人物专用，禁止归入目标本人',
                       'person_peer_context': peer, 'person_peer_records': [{'quote': q, 'nomination': peer} for q in quotes],
                       'fetch_status': 'done', 'content_kind': 'pdf_text_extracted', 'provider': 'retained_query_pdf_recovery',
                       'retrieved_at': datetime.now(timezone.utc).isoformat(),
                       'document_pages': fetched.get('document_pages', []), 'document_extraction': fetched.get('document_extraction', {})})
        if not existing:
            snapshots.append(row)
    audit['page_fetch_attempts'] = audit.get('page_fetch_attempts', 0) + new_fetches
    audit['pdf_identity_recovery'] = {'baseline': str(baseline), 'requests': new_fetches, 'results': results,
                                    'new_search_requests': 0, 'new_professional_requests': 0}
    summary.update(scope='retained_corpus_plus_bounded_native_pdf_recovery', baseline=str(baseline), source_count=len(snapshots))
    for name in ['intake.json', 'desktop_report.md']:
        shutil.copyfile(baseline / name, out / name)
    from person_iteration import copy_retained_tree
    copy_retained_tree(baseline / 'objects-before-cleanup', out / 'objects-before-cleanup')
    for name, data in [('source-snapshots.json', snapshots), ('person_retrieval_audit.json', audit), ('summary.json', summary)]:
        (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'saved': str(out), 'requests': new_fetches, 'source_count': len(snapshots)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
