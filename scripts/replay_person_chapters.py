"""Replay only affected chapters, freezing every other body section byte-for-byte.

No searches, downloads or platform calls. Source snapshots remain immutable.
Changed model inputs cannot borrow an old answer. Default is a dry planning run.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts')]
from person_evidence import build_packages, generate_person_report, split_sections, cited_ids
from person_iteration import ChapterInvoker, compare_sections
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE


def read(root, name):
    return json.loads((root/name).read_text(encoding='utf-8'))


def generation_code_snapshot():
    files=[*ROOT.joinpath('backend').glob('person*.py'),
        ROOT/'backend/research_workflow.py',ROOT/'backend/report_agents/person_report_agent.py',
        ROOT/'backend/company_ocr.py',ROOT/'scripts/replay_person_chapters.py',ROOT/'scripts/person_iteration.py']
    return {str(path.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(files) if path.is_file()}


def retained_claims(text):
    rows = []
    for line in text.splitlines():
        prefix = '- 研究判断（待人工复核）：'
        if line.startswith(prefix):
            analysis = re.sub(r'\s*\[E-[A-Z0-9-]+\]', '', line[len(prefix):]).strip()
            rows.append({'analysis': analysis, 'evidence_ids': sorted(cited_ids(line))})
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--chapters', nargs='+', type=int, required=True)
    parser.add_argument('--live-model', action='store_true')
    parser.add_argument('--max-model-calls', type=int, default=12)
    parser.add_argument('--deadline-utc')
    parser.add_argument('--previous-replay', type=Path, help='Freeze the preceding partial replay body and audit')
    parser.add_argument('--feedback-records', type=Path, help='Validated extraction from the same retained originals')
    parser.add_argument('--reuse-model-run', type=Path, help='Reuse only complete exact-input responses')
    args = parser.parse_args()
    if not set(args.chapters) <= set(range(2,13)):
        parser.error('Only chapters 2 through 12 may be rewritten')
    start = time.monotonic()
    baseline, output = args.baseline.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    code_snapshot=generation_code_snapshot()
    (output/'generation-code-snapshot.json').write_text(json.dumps(code_snapshot,indent=2)+'\n',encoding='utf-8')
    intake, payload, ledger = [read(baseline,n) for n in ['intake.json','cleaned_facts.json','person_claim_ledger.json']]
    source_bytes = (baseline/'source-snapshots.json').read_bytes()
    sources = [SimpleNamespace(**s) for s in json.loads(source_bytes)]
    if args.feedback_records:
        feedback = read(args.feedback_records.parent, args.feedback_records.name)
        if feedback['sources_sha256'] != hashlib.sha256(source_bytes).hexdigest():
            raise ValueError('Feedback was extracted from another source corpus')
        for record in feedback['records']:
            source = next(s for s in sources if s.url == record['source_url'])
            source.source_metadata = {**source.source_metadata, 'person_feedback_records':
                [*source.source_metadata.get('person_feedback_records', []),record]}
    previous = read(baseline,'summary.json')
    project = SimpleNamespace(title=intake['target_name'], target_name=intake['target_name'], target_type='person', sources=sources,
        person_research_intake=intake, person_platform_attempts=previous['provider_attempts'], person_retrieval_audit=read(baseline,'person_retrieval_audit.json'))
    contract = build_packages(payload, project.target_name, PERSON_REPORT_OUTLINE, intake, sources, project.person_platform_attempts)
    selection = read(baseline,'chapter-selection-audit.json')
    before_text = ((args.previous_replay or baseline)/'desktop_report.md').read_text(encoding='utf-8')
    if args.previous_replay:
        prior_summary = read(args.previous_replay,'summary.json')
        if prior_summary['sources_sha256'] != hashlib.sha256(source_bytes).hexdigest():
            raise ValueError('Previous replay used another source corpus')
        prior_contract = read(args.previous_replay,'contract.json')
        selection = {n:{'selected_ids':[f['evidence_id'] for f in p['facts']]} for n,p in prior_contract['chapters'].items()}
        ledger = {'diagnostic':read(args.previous_replay,'audit.json')}
    before = split_sections(before_text)
    changed = [n for n in range(2,13) if set(selection[str(n)]['selected_ids']) != {f['evidence_id'] for f in contract['chapters'][n]['facts']}]
    outside = set(changed) - set(args.chapters)
    plan = {'baseline': str(baseline), 'sources_sha256': hashlib.sha256(source_bytes).hexdigest(),
        'generation_code_sha256':hashlib.sha256(json.dumps(code_snapshot,sort_keys=True).encode()).hexdigest(),
        'previous_replay': str(args.previous_replay) if args.previous_replay else None,
        'feedback_records': str(args.feedback_records) if args.feedback_records else None,
        'intake_sha256': hashlib.sha256((baseline/'intake.json').read_bytes()).hexdigest(),
        'material_changed_chapters': changed, 'rewrite_requested': args.chapters, 'outside_request': sorted(outside),
        'research_scope': {str(n):{'admitted_facts':len(contract['chapters'][n].get('research_facts',[])),
            'admitted_sources':len({f['source_url'] for f in contract['chapters'][n].get('research_facts',[])}),
            'personal_analysis_candidates':sum(f.get('analysis_allowed',False) for f in contract['chapters'][n].get('research_facts',[]))}
            for n in args.chapters},
        'new_search_calls': 0, 'new_fetch_calls': 0, 'new_professional_calls': 0}
    (output/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(plan,ensure_ascii=False), flush=True)
    if outside:
        raise ValueError('Changed chapter material outside requested rewrite: '+str(sorted(outside)))
    if not args.live_model:
        return
    retained = {}
    old_diagnostics = ledger['diagnostic'].get('section_diagnostics', {})
    for n in range(2,13):
        if n not in args.chapters:
            retained[n] = {'text':before[n], 'selected_ids':selection[str(n)]['selected_ids'],
                'diagnostic':old_diagnostics.get(str(n), {}), 'claims':retained_claims(before[n]),
                'gaps':next(r for r in ledger['diagnostic']['chapters'] if r['chapter']==n).get('gaps',[])}
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
    os.environ.update(PERSON_REPORT_SECTION_TIMEOUT_SECONDS='90', PERSON_REPORT_SECTION_MAX_RETRIES='0',
        LLM_MAX_RETRIES='0', PERSON_REPORT_REPAIR_REJECTED='true', PERSON_REPORT_SEMANTIC_REVIEW_ENABLED='true')
    from research_workflow import ResearchWorkflow
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    workflow._person_report_section_model = None
    secrets = [v for k,v in os.environ.items() if len(v)>=12 and any(t in k.upper() for t in ['KEY','TOKEN','SECRET','PASSWORD'])]
    def safe(data):
        value = json.dumps(data,ensure_ascii=False,default=str)
        for secret in secrets:
            value=value.replace(secret,'[REDACTED]')
        return json.loads(value)
    calls = []
    def bounded(role,prompt,emit=None):
        if len(calls)>=args.max_model_calls:
            raise RuntimeError('Explicit replay model-call cap reached')
        event={'role':role,'status':'started','started_utc':datetime.now(timezone.utc).isoformat()}
        calls.append(event)
        started=time.monotonic()
        try:
            answer=workflow._invoke_person_report_section(role,prompt,emit)
            event['status']='returned'
            return answer
        except Exception as exc:
            event.update(status='failed',exception_type=type(exc).__name__)
            raise
        finally:
            event['elapsed_seconds']=round(time.monotonic()-started,3)
            (output/'request-status.json').write_text(json.dumps(calls,ensure_ascii=False,indent=2),encoding='utf-8')
    invoke=ChapterInvoker(bounded,output,safe,reuse=args.reuse_model_run,rewrite=args.chapters,
        deadline=args.deadline_utc,force_rewrite=False)
    def emit(trace,*a,**kw):
        if isinstance(trace,dict):
            with (output/'trace.jsonl').open('a',encoding='utf-8') as handle:
                handle.write(json.dumps(safe(trace),ensure_ascii=False)+'\n')
    report=generate_person_report(project,json.dumps(payload,ensure_ascii=False),'{}',PERSON_REPORT_OUTLINE,
        invoke,lambda *a,**kw:None,emit,retained_sections=retained)
    audit,contract=project.person_delivery_diagnostic,project.person_evidence_contract
    after=split_sections(report)
    for n in retained:
        assert before[n]==after[n], f'Unexpected modification of chapter {n}'
    assert source_bytes==(baseline/'source-snapshots.json').read_bytes()
    # Retain originals by reference plus hash; avoid copying credential-bearing
    # platform archives into a public deliverable.
    (output/'desktop_report.md').write_text(report,encoding='utf-8')
    (output/'contract.json').write_text(json.dumps(safe(contract),ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'audit.json').write_text(json.dumps(safe(audit),ensure_ascii=False,indent=2),encoding='utf-8')
    comparisons=compare_sections(before_text,report)
    for n in args.chapters:
        (output/f'chapter-{n}-before.md').write_text(before[n],encoding='utf-8')
        (output/f'chapter-{n}-after.md').write_text(after[n],encoding='utf-8')
    plan.update(model_requests=len(calls),model_requests_returned=sum(r['status']=='returned' for r in calls),
        code_unchanged_during_run=code_snapshot==generation_code_snapshot(),
        exact_input_responses_reused=sum(e['status']=='exact_input_reused' for e in invoke.events),
        model_requests_failed=sum(r['status']=='failed' for r in calls),elapsed_seconds=round(time.monotonic()-start,3),
        unchanged_body_chapters=sorted(retained),comparisons=comparisons,
        actual_cost_available=False,cost_note='No billing response supplied by provider; no price or cost estimated',
        audit={k:v for k,v in audit.items() if k in ['status','issues','degradations']})
    (output/'summary.json').write_text(json.dumps(safe(plan),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in plan.items() if k!='comparisons'},ensure_ascii=False),flush=True)
    if not plan['code_unchanged_during_run']:
        raise RuntimeError('Generation code changed during the run; retain diagnostics and replay the final frozen code')


if __name__=='__main__':
    main()
