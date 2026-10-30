"""Build a separate supplemented corpus using real fetched sources and cleaning."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts')]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--baseline', type=Path, required=True)
    ap.add_argument('--originals', type=Path, required=True)
    ap.add_argument('--feedback', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--as-of-date', required=True)
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    os.environ.update(CLEANING_MODE='fast', CLEANING_LLM_ENABLED='false')
    from person_iteration import copy_retained_tree
    from person_text import folded
    from research_workflow import ResearchWorkflow
    from person_evidence import build_packages
    from report_agents.person_report_agent import PERSON_REPORT_OUTLINE
    from replay_person_chapters import generation_code_snapshot
    read = lambda p: json.loads(p.read_text(encoding='utf-8'))
    out = args.output.resolve()
    if out.exists():
        raise ValueError('Supplement output already exists; use a new round directory')
    copy_retained_tree(args.baseline, out)
    parent_bytes = (args.baseline / 'source-snapshots.json').read_bytes()
    previous_sources = json.loads(parent_bytes)
    previous_by_url = {s['url']: s for s in previous_sources}
    next_id = max(int(s.get('id') or 0) for s in previous_sources) + 1
    additions = []
    for source in read(args.originals / 'source-snapshots.json'):
        if source['url'] in previous_by_url:
            continue
        if not source['source_metadata'].get('binary_archive_matches_extraction'):
            raise ValueError('Supplement original archive did not match the production fetch')
        additions.append({**source, 'id': next_id, 'summary': '', 'credibility_score': None})
        next_id += 1
    intake = read(out / 'intake.json')
    intake['as_of_date'] = args.as_of_date
    intake['supplemented_from_as_of_date'] = read(args.baseline / 'intake.json').get('as_of_date')
    old_summary = read(out / 'summary.json')
    project = SimpleNamespace(target_name=intake['target_name'], target_type='person',
        title=intake['target_name'], sources=[SimpleNamespace(**s) for s in additions],
        person_research_intake=intake, person_platform_attempts=old_summary['provider_attempts'],
        person_retrieval_audit={})
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    trace = []
    cleaned = json.loads(workflow.clean_sources(project, emit=lambda event: trace.append(event), plan={}))
    payload = read(out / 'cleaned_facts.json')
    payload['facts'] = [*payload['facts'], *cleaned['facts']]
    all_sources = [*previous_sources, *additions]
    snapshots = json.dumps(all_sources, ensure_ascii=False, indent=2).encode('utf-8')
    digest = hashlib.sha256(snapshots).hexdigest()
    feedback = read(args.feedback)
    if feedback['sources_sha256'] != hashlib.sha256(parent_bytes).hexdigest():
        raise ValueError('Parent extraction receipt belongs to another corpus')
    rebound = []
    for record in feedback['records']:
        original = previous_by_url.get(record['source_url'], {}).get('content') or ''
        quotes = [record.get(k) for k in ('quote', 'statement_quote', 'evaluator_context_quote') if record.get(k)]
        if not quotes or not all(folded(quote) in folded(original) for quote in quotes):
            raise ValueError('Inherited extraction could not be rebound to the identical retained original')
        rebound.append(record)
    feedback_out = {'sources_sha256': digest, 'records': rebound,
        'rebind_kind': 'extraction_only_from_byte_identical_parent_documents',
        'parent_extraction_sha256': hashlib.sha256(args.feedback.read_bytes()).hexdigest(),
        'review_verdicts_reused': 0, 'new_model_calls': 0}
    contract = build_packages(payload, intake['target_name'], PERSON_REPORT_OUTLINE, intake,
        [SimpleNamespace(**s) for s in all_sources], old_summary['provider_attempts'])
    files = {'intake.json': intake, 'cleaned_facts.json': payload, 'current-contract.json': contract,
        'new-source-cleaning.json': cleaned, 'new-source-cleaning-trace.json': trace,
        'feedback-records.json': feedback_out,
        'supplement-receipt.json': {'parent_sources_sha256': hashlib.sha256(parent_bytes).hexdigest(),
            'sources_sha256': digest, 'parent_sources': len(previous_sources), 'new_sources': len(additions),
            'new_rule_cleaned_facts': len(cleaned['facts']), 'total_raw_facts': len(payload['facts']),
            'source_extractions_rebound': len(rebound), 'review_verdicts_reused': 0,
            'as_of_date': args.as_of_date, 'model_calls': 0, 'historical_corpus_modified': False,
            'generation_code_snapshot': generation_code_snapshot(), 'report_accepted': False,
            'created_utc': datetime.now(timezone.utc).isoformat()}}
    (out / 'source-snapshots.json').write_bytes(snapshots)
    for name, value in files.items():
        (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(files['supplement-receipt.json'] | {'generation_code_snapshot': 'retained_in_receipt'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
