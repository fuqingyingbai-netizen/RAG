"""Read current production control inputs without models or database writes."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', choices=['haitian', 'kingsoft', 'holdout'])
    args = parser.parse_args()
    os.environ['PYTHON_DOTENV_DISABLED'] = '1'
    sys.path.insert(0, str(ROOT / 'backend'))
    from report_agents.company_assessment import internal_control_observations, control_score, _recent
    from report_agents.company_assessment_sources import assessment_source_context, assessment_anchor
    from report_agents.company_evidence import source_body
    from report_agents.company_risk_register import iso_date, later_than_research_cutoff
    from report_agents.company_text import company_matching_cache

    native = ROOT / 'work/company-phase1-20261028/native' / args.case
    intake = json.loads((native / 'state/company_research_intake.json').read_text(encoding='utf-8'))
    cutoff = iso_date(intake.get('as_of_date', ''))
    if not cutoff:
        raise ValueError('Missing valid research cutoff; refusing a current-date substitute.')
    with sqlite3.connect((native / 'acceptance.sqlite').resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        target = db.execute('SELECT target_name FROM research_projects WHERE id=1').fetchone()[0]
        sources = [dict(row) for row in db.execute(
            'SELECT * FROM research_sources WHERE project_id=1 ORDER BY id')]
        artifact = db.execute("SELECT id,content FROM research_artifacts WHERE artifact_type='cleaned_facts' "
                              'AND project_id=1 ORDER BY id DESC LIMIT 1').fetchone()
        cleaned = json.loads(artifact['content']) if artifact else {}
    for source in sources:
        source['source_metadata'] = json.loads(source['source_metadata'] or '{}')
    source_snapshot = hashlib.sha256(json.dumps(sources, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    cards = defaultdict(list)
    for card in cleaned.get('facts', []):
        if isinstance(card, dict):
            cards[str(card.get('source_url') or '')].append(card)
    records = []
    source_results = []
    with company_matching_cache(max_chars=100_000_000, max_entries=30000):
        for source in sources:
            if source_body(source)[1] == 'discovery_summary' or later_than_research_cutoff(source, cutoff):
                continue
            context = assessment_source_context(source, target)
            if not context['usable']:
                continue
            base = assessment_anchor(source, cards)
            if not base:
                continue
            found = internal_control_observations(source, {**base, 'entity': target}, pages=context['pages'])
            if context['platform']:
                for row in found:
                    row['source_attribution'] = '专业平台所载；不冒称官方披露或独立审计'
            records.extend(found)
            source_results.append({'source_id': source['id'], 'source_url': source['url'],
                'source_text_sha256': context['original_sha256'], 'physical_or_fallback_pages': len(context['pages']),
                'control_records': len(found)})
    recent = [row for row in records if _recent(row['cutoff'], cutoff)]
    result = {'observed_at': datetime.now(timezone.utc).isoformat(), 'case': args.case,
        'target': target, 'as_of_date': cutoff, 'source_count': len(sources),
        'source_snapshot_sha256': source_snapshot, 'cleaned_artifact_id': artifact['id'] if artifact else None,
        'source_results': source_results, 'recent_records': recent, 'control_score': control_score(recent),
        'model_calls': 0, 'http_calls': 0, 'production_sources_modified': False, 'full_report_accepted': False,
        'boundary': 'Same production field parser and current persisted inputs; not complete report or independent audit acceptance.'}
    destination = native / 'control-input-audit.json'
    destination.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print(json.dumps({'output': str(destination), 'source_count': len(sources),
        'recent_record_count': len(recent), 'control_score': result['control_score']['score'],
        'model_calls': 0, 'production_sources_modified': False, 'full_report_accepted': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
