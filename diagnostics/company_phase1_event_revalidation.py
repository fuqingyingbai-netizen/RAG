"""Revalidate genuine current event receipts without creating or editing one."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', choices=['haitian', 'kingsoft', 'holdout'])
    args = parser.parse_args()
    os.environ['PYTHON_DOTENV_DISABLED'] = '1'
    sys.path.insert(0, str(ROOT / 'backend'))
    from report_agents.company_event_evidence import VERSION, validate_event
    native = ROOT / 'work/company-phase1-20261028/native' / args.case
    store = native / 'objects'
    pointer = json.loads((store / 'projects/1/company_generation_checkpoint/current.json').read_text(encoding='utf-8'))
    path = (store / pointer['key']).resolve()
    if not path.is_relative_to(store.resolve()):
        raise RuntimeError('Invalid checkpoint path.')
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != pointer['sha256']:
        raise RuntimeError('Checkpoint payload hash changed.')
    checkpoint = json.loads(payload)
    package = checkpoint['packages']['company_event_review_cache']
    if package['version'] != VERSION:
        raise RuntimeError('Event package version changed; no new receipt is fabricated.')
    events = []
    with sqlite3.connect((native / 'acceptance.sqlite').resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        for event in package['events']:
            source = dict(db.execute('SELECT * FROM research_sources WHERE url=?', (event['source_url'],)).fetchone())
            source['source_metadata'] = json.loads(source['source_metadata'] or '{}')
            errors = validate_event(event, SimpleNamespace(**source), package['target_name'], package['as_of_date'])
            events.append({'source_id': source['id'], 'source_url': source['url'],
                           'native_event_sha256': hashlib.sha256(json.dumps(event, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                           'original_sha256': event['original_sha256'],
                           'witness': event['independent_check_witness'],
                           'kind': event['kind'], 'source_date_role': event['source_date_role'],
                           'validation_errors': errors,
                           'independent_check': event['independent_check']})
    result = {'case': args.case, 'version': VERSION, 'checkpoint_sha256': pointer['sha256'],
              'events': events, 'new_model_calls': 0, 'new_search_calls': 0,
              'receipt_or_source_modified': False, 'full_report_accepted': False}
    (native / 'current-event-revalidation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'case': args.case, 'events': len(events),
                      'errors': sum(len(e['validation_errors']) for e in events),
                      'full_report_accepted': False}))
    return 1 if any(e['validation_errors'] for e in events) else 0


if __name__ == '__main__':
    raise SystemExit(main())
