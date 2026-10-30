"""Two genuine production-entry person queries; retain originals separately."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--live', action='store_true')
    args = ap.parse_args()
    if not args.live:
        ap.error('--live required for the bounded real provider requests')
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    from research_workflow import ResearchWorkflow
    from person_identity import build_anchor
    from web_search import web_search_provider
    from tavily_keys import tavily_api_keys
    from research_store import research_store
    out = ROOT / 'work/person-phase1-20261028/new-collection-r1'
    out.mkdir(exist_ok=False)
    intake = json.loads((ROOT / 'work/person-phase1-20261028/frozen/zhang/intake.json').read_text(encoding='utf-8'))
    intake['as_of_date'] = '2026-10-28'
    intake['person_anchor'] = build_anchor(intake)
    secret_values = [v for k, v in os.environ.items() if len(v) >= 8 and any(
        t in k.upper() for t in ['KEY', 'TOKEN', 'SECRET', 'PASSWORD'])] + list(tavily_api_keys())
    def safe(value):
        text = json.dumps(value, ensure_ascii=False, default=str)
        for secret in sorted(secret_values, key=len, reverse=True):
            text = text.replace(secret, '[REDACTED]')
        return json.loads(text)
    def write(name, value):
        (out / name).write_text(json.dumps(safe(value), ensure_ascii=False, indent=2), encoding='utf-8')
    def emit(event):
        with (out / 'trace.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(safe(event), ensure_ascii=False) + '\n')
    queries = []
    for index, provider in enumerate(['bocha', 'exa']):
        if not web_search_provider.is_configured(provider):
            raise RuntimeError('Planned production provider not configured: ' + provider)
        queries.append({'module': '身份核验',
            'query': '"张勇" "海底捞" 官方 简历 任职 董事会',
            'preferred_providers': [provider], 'person_search_audit_index': index,
            'person_chapters': [2, 6, 9, 11],
            'requirement_ids': ['2.career'],
            'retrieval_reason': 'current_entry_identity_and_tenure_originals'})
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    plan = {'started_utc': datetime.now(timezone.utc).isoformat(), 'intake': intake,
            'model_calls': 0, 'provider_query_limit': 2, 'original_fetch_limit': 2,
            'professional_calls': 0, 'search_concurrency': 2,
            'historical_corpus_modified': False, 'queries': queries}
    write('plan.json', plan)
    began = time.monotonic()
    batches = workflow._search_query_items_parallel(queries, 3, ['bocha', 'exa'], emit)
    write('search-results.json', [{'query': q, 'results': rows} for q, rows in batches])
    unique = {}
    for _, rows in batches:
        for row in rows:
            if row.get('url', '').startswith('https://'):
                unique.setdefault(row['url'], row)
    originals = []
    for url, row in list(unique.items())[:2]:
        fetched = workflow._fetch_web_url_with_timeout(url, allow_browser=False, emit=emit,
            **({'document_profile': 'person'} if url.lower().endswith('.pdf') else {}))
        content = str(fetched.get('content') or '')
        identity = workflow._person_source_identity_confidence(row.get('title') or '', content, intake)
        item = {'url': url, 'title': row.get('title'), 'fetch': fetched, 'identity': identity,
                'content_sha256': hashlib.sha256(content.encode('utf-8')).hexdigest(),
                'report_admission': 'pending_source_and_event_review'}
        if content:
            item['object_key'] = research_store.put_text(
                'person-phase1/new-collection-r1/' + item['content_sha256'] + '.txt', content,
                'text/plain; charset=utf-8')
        originals.append(item)
        write('originals.json', originals)
    summary = {'provider_queries': len(queries), 'original_fetches': len(originals),
        'search_outcomes': [{k:q.get(k) for k in ['preferred_providers', 'person_search_status',
            'person_search_error_type', 'person_search_error_reason', 'search_result_audit']} for q, _ in batches],
        'unique_discovery_urls': len(unique), 'retained_originals': sum(bool(r['fetch'].get('content')) for r in originals),
        'elapsed_seconds': round(time.monotonic() - began, 3), 'model_calls': 0, 'professional_calls': 0,
        'actual_account_charge': None, 'account_charge_note': 'Provider receipt did not supply an account charge.',
        'historical_corpus_modified': False, 'facts_added_to_report': 0}
    write('summary.json', summary)
    print(json.dumps(safe(summary), ensure_ascii=False))


if __name__ == '__main__':
    main()
