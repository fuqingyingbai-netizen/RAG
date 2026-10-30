"""Revalidate cached native event proposals; refuse all new model requests."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', choices=['haitian', 'kingsoft', 'holdout'])
    parser.add_argument('--checkpoint-sha')
    args = parser.parse_args()
    if args.checkpoint_sha and not re.fullmatch('[0-9a-f]{64}', args.checkpoint_sha):
        parser.error('checkpoint-sha must be a lowercase SHA256 digest')
    os.environ['PYTHON_DOTENV_DISABLED'] = '1'
    sys.path.insert(0, str(ROOT / 'backend'))
    from report_agents.company_event_evidence import review_primary_events, validate_event, VERSION
    from report_agents.company_risk_register import iso_date

    native = ROOT / 'work/company-phase1-20261028/native' / args.case
    store = native / 'objects'
    directory = store / 'projects/1/company_generation_checkpoint'
    pointer = json.loads((directory / 'current.json').read_text(encoding='utf-8'))
    digest = args.checkpoint_sha or pointer['sha256']
    checkpoint = directory / (digest + '.json')
    payload = checkpoint.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == digest
    cache = json.loads(payload)['packages']['company_event_review_cache']
    cache_bytes = json.dumps(cache, ensure_ascii=False, sort_keys=True).encode()
    before = hashlib.sha256(cache_bytes).hexdigest()
    intake = json.loads((native / 'state/company_research_intake.json').read_text(encoding='utf-8'))
    as_of = iso_date(intake.get('as_of_date', ''))
    if not as_of:raise ValueError('Research cutoff unavailable.')
    with sqlite3.connect((native / 'acceptance.sqlite').resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        target = db.execute('SELECT target_name FROM research_projects WHERE id=1').fetchone()[0]
        sources = [dict(row) for row in db.execute('SELECT * FROM research_sources WHERE project_id=1 ORDER BY id')]
    assert cache['target_name'] == target and cache['as_of_date'] == as_of
    urls = {row.get('source_url') for key in ('events', 'receipts') for row in cache.get(key, []) if isinstance(row, dict)}
    sources = [row for row in sources if row['url'] in urls]
    for source in sources:source['source_metadata'] = json.loads(source['source_metadata'] or '{}')
    by_url = {source['url']: source for source in sources}
    literal = []
    for receipt in cache.get('receipts', []):
        source = by_url.get(receipt.get('source_url'))
        row = (receipt.get('repair_proposal') or {}).get('event')
        if source and isinstance(row, dict):
            literal.append({'source_url': source['url'], 'old_error': receipt.get('error'),
                'current_literal_errors': validate_event(row, source, target, as_of, require_independent=False)})
    attempted_roles = []
    def refuse_model(role, *args):
        attempted_roles.append(role)
        raise RuntimeError('Offline audit refuses new model calls; fresh independent review remains required.')
    result = review_primary_events(sources, target, as_of, refuse_model, cache=cache)
    assert before == hashlib.sha256(json.dumps(cache, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    assert checkpoint.read_bytes() == payload
    output = {'case': args.case, 'checkpoint_sha256': digest, 'current_version': VERSION,
        'previous_version': cache['version'], 'cached_event_sources_only': len(sources),
        'cached_response_package_sha256_before_and_after': before, 'literal_checks': literal,
        'attempted_roles_refused_before_model': attempted_roles,
        'restored_proposals': [{k: row[k] for k in ('source_url', 'state', 'error_type', 'error',
            'proposal_reused_from_raw_cache', 'cached_proposal_witness') if k in row} for row in result['receipts']],
        'accepted_events': len(result['events']), 'new_model_calls': 0, 'new_http_calls': 0,
        'raw_responses_modified': False, 'production_cache_modified': False, 'full_report_accepted': False,
        'boundary': 'Literal/proposal replay only; every refused independent review remains pending.'}
    destination = native / 'event-proposal-revalidation.json'
    destination.write_bytes((json.dumps(output, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print(json.dumps({k: output[k] for k in ('case', 'literal_checks', 'attempted_roles_refused_before_model',
        'accepted_events', 'new_model_calls', 'raw_responses_modified', 'production_cache_modified',
        'full_report_accepted')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
