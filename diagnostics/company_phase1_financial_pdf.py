"""Read-only current retrieval of four financial QA documents; no report edits."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from datetime import datetime, timezone
import requests

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'work/company-phase1-20261028'


def main():
    output = RUN / 'financial-pdf-review'
    output.mkdir(exist_ok=True)
    rows = []
    for case, sid in [('haitian', 25), ('haitian', 165), ('kingsoft', 2), ('kingsoft', 30)]:
        baseline = (RUN / 'baseline' / case / 'acceptance.sqlite').resolve()
        with sqlite3.connect(baseline.as_uri() + '?mode=ro', uri=True) as db:
            title, url, content, raw_meta = db.execute('SELECT title,url,content,source_metadata FROM research_sources WHERE id=?', (sid,)).fetchone()
        metadata = json.loads(raw_meta or '{}')
        baseline_pdf_hash = ((metadata.get('document_extraction') or {}).get('ocr') or {}).get('source_sha256')
        path = output / f'{case}-{sid}.pdf'
        record = {'case': case, 'source_id': sid, 'title': title, 'source_url': url,
                  'baseline_text_sha256': hashlib.sha256((content or '').encode()).hexdigest(),
                  'baseline_pdf_sha256': baseline_pdf_hash,
                  'baseline_content_origin': metadata.get('content_origin'),
                  'baseline_extraction_status': metadata.get('extraction_status'), 'attempts': []}
        # Resume verified local QA downloads without an unnecessary new fetch.
        old_path = output / f'{case}-{sid}-receipt.json'
        if path.exists() and old_path.exists():
            old = json.loads(old_path.read_text(encoding='utf-8'))
            if hashlib.sha256(path.read_bytes()).hexdigest() == old.get('current_pdf_sha256'):
                rows.append({**old, 'reused_local_qa_download': True})
                continue
        for candidate in [url] + ([url.replace('http://', 'https://', 1)] if url.startswith('http://') else []):
            before = time.monotonic()
            attempt = {'url': candidate, 'at': datetime.now(timezone.utc).isoformat(), 'sdk_retries': 0}
            try:
                response = requests.get(candidate, timeout=(15, 60))
                attempt.update(http_status=response.status_code, bytes=len(response.content),
                               final_url=response.url, content_type=response.headers.get('content-type'))
                if response.status_code == 200 and response.content.startswith(b'%PDF-'):
                    path.write_bytes(response.content)
                    record.update(current_pdf_sha256=hashlib.sha256(response.content).hexdigest(),
                                  local_pdf=path.relative_to(ROOT).as_posix(), downloaded=True)
                    record['matches_baseline_pdf_bytes'] = (record['current_pdf_sha256'] == baseline_pdf_hash) if baseline_pdf_hash else None
            except requests.RequestException as exc:
                attempt['error_type'] = type(exc).__name__
            attempt['elapsed_seconds'] = round(time.monotonic() - before, 3)
            record['attempts'].append(attempt)
            if record.get('downloaded'):
                break
        record.update(report_accepted=False, visual_review='pending', production_source_records_modified=False)
        old_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        rows.append(record)
    result = {'documents': rows, 'new_model_calls': 0,
              'scope': 'Manual QA retrieval, counted separately from the bounded production runner. No response or source transplantation.',
              'report_accepted': False}
    (output / 'retrieval-summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps([{k: r.get(k) for k in ['case', 'source_id', 'downloaded', 'matches_baseline_pdf_bytes']} for r in rows]))


if __name__ == '__main__':
    main()
