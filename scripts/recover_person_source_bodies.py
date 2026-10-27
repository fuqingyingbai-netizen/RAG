"""Recover retained leads into a new dated corpus; never rewrite the baseline."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'backend'), str(ROOT/'scripts')]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
    # This operation recovers existing URLs only, without browser or model use.
    os.environ.update(WEB_FETCH_TOTAL_TIMEOUT_SECONDS='20', PERSON_PDF_FETCH_TOTAL_TIMEOUT_SECONDS='30')
    from research_workflow import ResearchWorkflow
    from person_chapter_research import contextual_identity
    from audit_person_source_use import inspect
    run, out = args.run.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    summary = json.loads((run/'summary.json').read_text(encoding='utf-8'))
    baseline = Path(summary['baseline'])
    snapshot = baseline/'source-snapshots.json'
    original_bytes = snapshot.read_bytes()
    sources = json.loads(original_bytes)
    intake = json.loads((baseline/'intake.json').read_text(encoding='utf-8'))
    audit = inspect(run)
    candidates = [r for r in audit['sources'] if r['state'] in {
        'retained_lead_or_unavailable_original', 'identity_not_admitted',
        'scanned_no_admissible_person_statement'} and r['url'].startswith(('https://','http://'))]
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    receipts = []

    def fetch(row):
        started = datetime.now(timezone.utc).isoformat()
        try:
            result = workflow._fetch_web_url_with_timeout(row['url'], False, document_profile='person')
        except Exception as exc:
            result = {'status': 'failed', 'error_type': type(exc).__name__}
        body = result.get('content') or ''
        source = sources[row['source_row']-1]
        identity = contextual_identity(workflow, source['title'], body, intake)
        receipt = {'source_row': row['source_row'], 'url': row['url'], 'started_utc': started,
                   'finished_utc': datetime.now(timezone.utc).isoformat(),
                   'status': result.get('status'), 'text_chars': len(body),
                   'text_sha256': hashlib.sha256(body.encode()).hexdigest(), 'identity': identity,
                   'previous_state': row['state'], 'accepted_replacement': False}
        if result.get('status') == 'done' and len(body) >= 120 and identity['confidence'] in {'medium','high'}:
            source['content'], source['summary'] = body, body[:500]
            meta = source['source_metadata']
            meta.update(identity_confidence=identity['confidence'], identity_status='accepted',
                        identity_reason=identity['reason'], person_discovery_only=False,
                        content_kind='pdf_text_extracted' if result.get('pages') else 'full_text',
                        fetch_status='done', fetched_chars=len(body), retrieved_at=receipt['finished_utc'],
                        supplement_retrieved_at=receipt['finished_utc'],
                        supplement_boundary='原研究截止后重新获取的网页；不保证网页内容与截止日相同，事件日期以原文为准。')
            for key in ('document_pages','document_extraction','content_type','fetch_attempt'):
                if key in result:
                    meta[key] = result[key]
            receipt['accepted_replacement'] = True
        return receipt

    with ThreadPoolExecutor(max_workers=5) as pool:
        for future in as_completed([pool.submit(fetch, row) for row in candidates]):
            row = future.result()
            receipts.append(row)
            (out/'new-fetch-receipts.json').write_text(json.dumps(sorted(receipts,key=lambda r:r['source_row']),ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({k:row[k] for k in ('source_row','status','text_chars','accepted_replacement')},ensure_ascii=False),flush=True)
    for name in ('intake.json','cleaned_facts.json','person_claim_ledger.json','chapter-selection-audit.json','desktop_report.md'):
        shutil.copyfile(baseline/name,out/name)
    retrieval = json.loads((baseline/'person_retrieval_audit.json').read_text(encoding='utf-8'))
    retrieval['dated_body_recovery'] = {'baseline_sources_sha256':hashlib.sha256(original_bytes).hexdigest(),
        'new_search_calls':0,'new_professional_calls':0,'new_fetch_calls':len(receipts),'fetches':receipts}
    baseline_summary = json.loads((baseline/'summary.json').read_text(encoding='utf-8'))
    summary.update(provider_attempts=baseline_summary['provider_attempts'], baseline=str(baseline), original_sources_sha256=hashlib.sha256(original_bytes).hexdigest(),
        scope='retained_urls_with_dated_new_body_fetches', new_search_calls=0,new_professional_calls=0,
        new_fetch_calls=len(receipts), recovered_sources=sum(r['accepted_replacement'] for r in receipts))
    for name,data in [('source-snapshots.json',sources),('person_retrieval_audit.json',retrieval),('summary.json',summary)]:
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    assert snapshot.read_bytes()==original_bytes
    print(json.dumps({'output':str(out),'calls':len(receipts),'recovered':summary['recovered_sources']},ensure_ascii=False))


if __name__ == '__main__':
    main()
