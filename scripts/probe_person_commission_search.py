"""Two bounded real searches to verify commissioned query wiring, not findings."""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('intake', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if not args.live:
        parser.error('--live is required for paid provider calls')
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    from person_commission import search_rows
    from person_identity import build_anchor
    from company_platform import failure_kind
    from web_search import web_search_provider
    intake = json.loads(args.intake.read_text(encoding='utf-8'))
    intake['target_name'] = intake.get('target_name') or intake.get('company_name')
    intake['person_anchor'] = build_anchor(intake)
    rows = search_rows(intake)[:2]
    probes = []
    # One sequential request per topic. No automatic expansion or retries and
    # no unrequested ingestion of returned search snippets as report facts.
    for item, provider in zip(rows, ('bocha', 'exa')):
        started = time.monotonic()
        record = {'query': item['query'], 'commission_id': item['commission_id'], 'provider': provider}
        try:
            results = web_search_provider.search_single(provider, item['query'], limit=3)
            record.update(status='returned', result_count=len(results),
                          discovery_results=[{'title': r.get('title'), 'url': r.get('url')} for r in results])
        except Exception as exc:
            response = getattr(exc, 'response', None)
            message = str(exc) + ' ' + (response.text[:1000] if response is not None else '')
            record.update(status='failed', failure_kind=failure_kind({'error': message}), exception_type=type(exc).__name__)
        record['elapsed_seconds'] = round(time.monotonic()-started, 1)
        probes.append(record)
    output = {'scope': 'two_commission_queries_search_transport_only', 'paid_search_requests': len(probes),
              'original_fetches': 0, 'professional_calls': 0, 'report_facts_added': 0,
              'qualification': 'Discovery results only; original text, identity and dates remain unverified', 'probes': probes}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(output, ensure_ascii=False, indent=2)
    for key, value in os.environ.items():
        if value and len(value) >= 12 and any(t in key.upper() for t in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')):
            text = text.replace(value, '[REDACTED]')
    args.output.write_text(text, encoding='utf-8')
    print(json.dumps({'requests': len(probes), 'results': [{k: r.get(k) for k in ('provider', 'status', 'result_count', 'failure_kind')} for r in probes]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
