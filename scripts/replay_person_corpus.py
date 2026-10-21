"""Replay a retained live person corpus without making new provider searches.

Only chapter writing uses live model calls. Source and intake hashes make the
comparison reproducible; output stays in an isolated SQLite/object store.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import zipfile
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline', type=Path)
    parser.add_argument('--live-model', action='store_true', help='Use paid real chapter model calls; otherwise record a model-free evidence replay')
    parser.add_argument('--chapter-followup', action='store_true', help='Paid bounded new chapter 7/8 searches and source extraction on the retained corpus')
    parser.add_argument('--retained-chapter-discovery', action='store_true', help='Reuse retained discovery originals; only query nominated peers')
    parser.add_argument('--model-responses', type=Path, help='Reuse retained real model responses for a validation-only replay, no model charges')
    parser.add_argument('--reuse-run', type=Path, help='Reuse responses only when the complete chapter prompt has the same SHA256')
    parser.add_argument('--rewrite-chapters', type=int, nargs='+', default=[], help='Paid rewrites of these chapters and dependent summary/assessment only')
    parser.add_argument('--deadline-utc', help='UTC ISO deadline; no new model request may start after it')
    parser.add_argument('--additional-search-budget', type=int, default=0, help='Explicit new follow-up allowance, at most 12 requests')
    parser.add_argument('--additional-fetch-budget', type=int, default=0, help='Explicit new original-page allowance, at most 20 pages')
    parser.add_argument('--professional-followup', action='store_true', help='Rerun bounded person/affiliation professional checks; retain historical outcomes')
    parser.add_argument('--additional-professional-budget', type=int, default=0, help='Explicit tool-call allowance for this professional follow-up, at most 18')
    parser.add_argument('--repair-rejected', action='store_true', help='At most one bounded model correction per rejected chapter')
    parser.add_argument('--repair-only', action='store_true', help='Reuse unchanged initial drafts too; pay only for missing correction prompts')
    parser.add_argument('--followup-chapters', type=int, choices=[7, 8], nargs='+', default=[7, 8], help='Limit new chapter research to the requested gaps')
    args = parser.parse_args()
    if args.live_model and args.model_responses:
        parser.error('--live-model and --model-responses are mutually exclusive')
    if (args.reuse_run or args.rewrite_chapters) and not args.live_model:
        parser.error('Targeted rewrites require --live-model')
    if args.repair_only and not (args.repair_rejected and args.reuse_run):
        parser.error('--repair-only requires --repair-rejected and --reuse-run')
    if args.reuse_run and not args.rewrite_chapters:
        parser.error('--reuse-run requires explicit --rewrite-chapters')
    if any(n < 1 or n > 13 for n in args.rewrite_chapters):
        parser.error('Only chapters 1 through 13 have model writing')
    if args.chapter_followup and not args.live_model:
        parser.error('--chapter-followup requires --live-model')
    if args.retained_chapter_discovery and not args.chapter_followup:
        parser.error('--retained-chapter-discovery requires --chapter-followup')
    if not 0 <= args.additional_search_budget <= 12 or not 0 <= args.additional_fetch_budget <= 20:
        parser.error('Follow-up allowances exceed bounded iteration limits')
    if (args.additional_search_budget or args.additional_fetch_budget) and not args.chapter_followup:
        parser.error('Additional allowances require explicit --chapter-followup')
    if args.professional_followup != bool(args.additional_professional_budget) or not 0 <= args.additional_professional_budget <= 18:
        parser.error('--professional-followup requires a positive --additional-professional-budget up to 18')
    if args.professional_followup and not args.live_model:
        parser.error('Professional follow-up requires --live-model for affected chapters')
    baseline = args.baseline.resolve()
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    if args.deadline_utc:
        os.environ['RESEARCH_USER_DEADLINE_UTC'] = args.deadline_utc
    os.environ['PERSON_REPORT_REPAIR_REJECTED'] = 'true' if args.repair_rejected else 'false'
    run = ROOT / 'work/person-optimization' / ('same-corpus-' + datetime.now().strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:6])
    run.mkdir(parents=True)
    os.environ.update({
        'DATABASE_URL': 'sqlite:///' + (run / 'run.sqlite').as_posix(),
        'RESEARCH_OBJECT_STORE': 'local', 'RESEARCH_LOCAL_STORE': str(run / 'objects'),
        'RESEARCH_LEGACY_RAG_ENABLED': 'false', 'CLEANING_MODE': 'fast', 'CLEANING_LLM_ENABLED': 'false',
        'WORKFLOW_RESUME_ENABLED': 'false', 'PERSON_REPORT_SECTION_TIMEOUT_SECONDS': '90',
        'PERSON_REPORT_SECTION_MAX_RETRIES': '0', 'LLM_TIMEOUT_SECONDS': '90', 'LLM_MAX_RETRIES': '0',
    })
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    import report_knowledge
    import research_workflow
    from models import Base, ResearchProject, ResearchSource, User
    from research_store import research_store
    from person_evidence import split_sections, cited_ids
    # Report-only replay: proposal was exercised separately in the baseline.
    research_workflow.FIXED_GENERATE_PROPOSAL = False
    report_knowledge.sync_report_safely = lambda *a, **kw: None
    research_store.mode, research_store.local_root = 'local', run / 'objects'
    from person_iteration import copy_retained_tree
    copy_retained_tree(baseline / 'objects-before-cleanup', run / 'objects')
    intake = json.loads((baseline / 'intake.json').read_text(encoding='utf-8'))
    snapshots = json.loads((baseline / 'source-snapshots.json').read_text(encoding='utf-8'))
    previous = json.loads((baseline / 'summary.json').read_text(encoding='utf-8'))
    retrieval = json.loads((baseline / 'person_retrieval_audit.json').read_text(encoding='utf-8'))
    if args.additional_search_budget:
        os.environ['PERSON_SEARCH_CALL_BUDGET'] = str(int(retrieval.get('calls_planned', 0)) + args.additional_search_budget)
        os.environ['PERSON_CHAPTER_7_8_CALL_BUDGET'] = str(args.additional_search_budget)
    if args.additional_fetch_budget:
        os.environ['PERSON_WEB_FETCH_BUDGET'] = str(int(retrieval.get('page_fetch_attempts', 0)) + args.additional_fetch_budget)
    workflow = research_workflow.ResearchWorkflow()
    professional_calls = {'tool_requests': 0, 'initializations': 0}
    if args.professional_followup:
        os.environ['PERSON_PLATFORM_CALL_BUDGET'] = str(args.additional_professional_budget)
        def counted(method, key):
            def call(*a, **kw):
                if args.deadline_utc and datetime.now().astimezone().timestamp() >= datetime.fromisoformat(args.deadline_utc.replace('Z', '+00:00')).timestamp()-60:
                    raise RuntimeError('User time budget reached; professional follow-up stopped')
                professional_calls[key] += 1
                return method(*a, **kw)
            return call
        workflow._mcp_call_tool = counted(workflow._mcp_call_tool, 'tool_requests')
        workflow._mcp_initialize = counted(workflow._mcp_initialize, 'initializations')
    replayed_roles = []
    model_invocations = []
    if args.model_responses:
        cached = {r['role']: r['response'] for r in [json.loads(line) for line in args.model_responses.read_text(encoding='utf-8').splitlines() if line.strip()]}
        def replay_invoke(role, *a, **kw):
            if role not in cached:
                raise RuntimeError('No retained model response for this chapter')
            replayed_roles.append(role)
            return cached[role]
        workflow._invoke_person_report_section = replay_invoke
    elif not args.live_model:
        workflow._invoke_person_report_section = lambda *a, **kw: '{"claims":[]}'

    def collect(db, project, *args, **kwargs):
        for row in snapshots:
            db.add(ResearchSource(project_id=project.id, **row))
        project.person_platform_attempts = previous['provider_attempts']
        project.person_retrieval_audit = retrieval
        db.commit()
        if args.professional_followup:
            db.expire(project, ['sources'])
            normalized = kwargs.get('intake') or {}
            normalized['confirmed_person_affiliations'] = workflow._discover_person_affiliations(list(project.sources), normalized)
            project.person_research_intake = normalized
        return len(snapshots)

    workflow.collect_web_sources = collect
    if not args.professional_followup:
        workflow.collect_structured_sources = lambda *a, **kw: 0
        workflow.collect_person_affiliation_structured_sources = lambda *a, **kw: 0
    else:
        original_affiliation_collection = workflow.collect_person_affiliation_structured_sources
        def professional_affiliations(db, project, value, emit=None):
            db.expire(project, ['sources'])
            value['confirmed_person_affiliations'] = workflow._discover_person_affiliations(list(project.sources), value)
            project.person_research_intake = value
            return original_affiliation_collection(db, project, value, emit=emit)
        workflow.collect_person_affiliation_structured_sources = professional_affiliations
    if not args.chapter_followup:
        workflow.collect_person_chapter_sources = lambda *a, **kw: 0
    else:
        original_chapter_collection = workflow.collect_person_chapter_sources
        workflow.collect_person_chapter_sources = lambda db, p, value, emit=None: original_chapter_collection(
            db, p, {**value, 'person_followup_chapters': args.followup_chapters,
                    **({'person_chapter_followup_mode': 'retained_only'} if args.retained_chapter_discovery else {})}, emit)
    # Entity resolution for a person is local, but disable any future remote
    # implementation here: this replay is explicitly restricted to the corpus.
    workflow.resolve_business_entity = lambda project, intake, **kw: intake
    secrets = [v for k, v in os.environ.items() if v and len(v) >= 12 and any(t in k.upper() for t in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD'))]

    def safe(value):
        text = json.dumps(value, ensure_ascii=False, default=str)
        for secret in secrets:
            text = text.replace(secret, '[REDACTED]')
        return json.loads(text)

    invoker = None
    if args.live_model:
        from person_iteration import ChapterInvoker
        invoker = ChapterInvoker(workflow._invoke_person_report_section, run, safe, args.reuse_run,
                                 args.rewrite_chapters, args.deadline_utc, not args.repair_only)
        workflow._invoke_person_report_section = invoker

    def emit(event):
        event = safe(event)
        with (run / 'trace.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(event, ensure_ascii=False) + '\n')
        print(json.dumps({k: event[k] for k in ('stage', 'label', 'status', 'section') if k in event}, ensure_ascii=False), flush=True)

    started = time.monotonic()
    engine = create_engine(os.environ['DATABASE_URL'])
    Base.metadata.create_all(engine)
    summary = {'scope': 'same_corpus_report_replay_live_chapter_models' if args.live_model else 'same_corpus_evidence_replay_no_model', 'baseline': str(baseline),
               'live_model_enabled': args.live_model,
               'new_search_calls': 0, 'new_professional_calls': 0, 'proposal': 'excluded_already_exercised_in_baseline',
               'corpus_sha256': hashlib.sha256((baseline / 'source-snapshots.json').read_bytes()).hexdigest(),
               'intake_sha256': hashlib.sha256((baseline / 'intake.json').read_bytes()).hexdigest()}
    summary['additional_allowances'] = {'search_requests': args.additional_search_budget, 'page_fetches': args.additional_fetch_budget,
                                       'professional_tool_requests': args.additional_professional_budget}
    if args.chapter_followup:
        summary['scope'] = 'retained_corpus_plus_bounded_chapter_7_8_research_and_live_models'
    if args.professional_followup:
        summary['scope'] = 'retained_corpus_plus_bounded_professional_followup_and_targeted_models'
    summary['baseline_corpus_sha256'] = summary['corpus_sha256']
    # Every iteration retains originals so a targeted rewrite can be chained.
    original_finalize = workflow._finalize_source_records
    def finalize(db, project, trace=None):
        snapshots = [{k: getattr(s, k) for k in ('id', 'source_type', 'title', 'url', 'content', 'summary', 'source_metadata', 'credibility_score')}
                     for s in project.sources]
        snapshot_path = run / 'source-snapshots.json'
        snapshot_path.write_text(json.dumps(safe(snapshots), ensure_ascii=False, indent=2), encoding='utf-8')
        (run / 'intake.json').write_text(json.dumps(getattr(project, 'person_research_intake', None) or intake, ensure_ascii=False, indent=2), encoding='utf-8')
        (run / 'person_retrieval_audit.json').write_text(json.dumps(safe(getattr(project, 'person_retrieval_audit', {}) or retrieval), ensure_ascii=False, indent=2), encoding='utf-8')
        summary['corpus_sha256'] = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
        summary['provider_attempts'] = getattr(project, 'person_platform_attempts', [])
        summary['chapter_followup'] = (getattr(project, 'person_retrieval_audit', {}) or {}).get('chapter_7_8_followup', {})
        summary['new_search_calls'] = len(summary['chapter_followup'].get('attempts', [])) if args.chapter_followup else 0
        summary['new_professional_calls'] = professional_calls['tool_requests']
        summary['new_professional_initializations'] = professional_calls['initializations']
        summary['retained_source_count'] = len(snapshots)
        copy_retained_tree(run / 'objects', run / 'objects-before-cleanup')
        original_finalize(db, project, trace)
    workflow._finalize_source_records = finalize
    if args.model_responses:
        summary.update(scope='same_corpus_validation_replay_retained_real_model_responses', actual_model_requests=0,
                       model_response_sha256=hashlib.sha256(args.model_responses.read_bytes()).hexdigest(),
                       model_call_count_note='Section model_calls count local writer invocations, not new API requests')
    print(json.dumps({'started': str(run)}, ensure_ascii=False), flush=True)
    with Session(engine) as db:
        user = User(username='same-corpus-person-qa', password_hash='not-a-product-login')
        db.add(user)
        db.flush()
        target = str(intake.get('target_name') or intake.get('company_name') or '').strip()
        if not target:
            raise ValueError('Baseline intake has no target name')
        project = ResearchProject(title=target, target_name=target, target_type='person',
                                  industry='', description='公开资料背景调查接口与章节验收，不代替正式尽调及人工复核', created_by_id=user.id)
        db.add(project)
        db.commit()
        artifacts, added = workflow.run_project(db, project, [], [], emit=emit, intake=intake)
        rows = db.query(type(artifacts[0])).filter_by(project_id=project.id).all()
        for artifact in rows:
            ext = '.json' if artifact.artifact_type in {'person_claim_ledger', 'person_retrieval_audit', 'cleaned_facts', 'risk_assessment'} else '.md'
            (run / (artifact.artifact_type + ext)).write_text(artifact.content or '', encoding='utf-8')
        report = next(a for a in artifacts if a.artifact_type == 'desktop_report')
        ledger = next(a for a in artifacts if a.artifact_type == 'person_claim_ledger')
        sections = split_sections(report.content)
        summary.update(status=project.status, sources_added=added, chapter_count=len(sections),
                       chapter_audit=json.loads(ledger.content)['diagnostic'], report_metadata=report.artifact_metadata,
                       chapter_citation_counts={str(k): len(cited_ids(v)) for k, v in sections.items()})
        summary['model_invocations'] = sum(e['status'] in {'returned', 'failed'} for e in invoker.events) if invoker else 0
        summary['exact_input_model_responses_reused'] = sum(e['status'] == 'exact_input_reused' for e in invoker.events) if invoker else 0
        summary['rewrite_chapters_requested'] = args.rewrite_chapters
        summary['deadline_utc'] = args.deadline_utc
        summary['new_paid_search_or_platform_requests'] = bool(summary['new_search_calls'] or summary['new_professional_calls'])
        trace_rows = [json.loads(line) for line in (run / 'trace.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
        metered = [r for r in trace_rows if isinstance(r.get('input_tokens'), int)]
        summary['model_token_usage'] = {'available': bool(metered),
            'input_tokens': sum(r['input_tokens'] for r in metered) if metered else None,
            'output_tokens': sum(r.get('output_tokens', 0) for r in metered) if metered else None,
            'metered_requests': len(metered)}
        contract = getattr(project, 'person_evidence_contract', {})
        selection = {str(n): {'selected_ids': [f['evidence_id'] for f in p['facts']],
                              'material_coverage': p.get('material_coverage', []),
                              'selection_audit': p.get('selection_audit', []),
                              'routing_audit': p.get('routing_audit', []),
                              'query_coverage': p.get('query_coverage', [])}
                     for n, p in contract.get('chapters', {}).items()}
        (run / 'chapter-selection-audit.json').write_text(json.dumps(safe(selection), ensure_ascii=False, indent=2), encoding='utf-8')
        key = (report.artifact_metadata or {}).get('docx_object_key')
        if key:
            docx = run / 'person-report.docx'
            docx.write_bytes(research_store.get_bytes(key))
            with zipfile.ZipFile(docx) as archive:
                summary['docx_integrity_ok'] = archive.testzip() is None
        summary['elapsed_seconds'] = round(time.monotonic()-started, 1)
        comparison_source = args.reuse_run or baseline
        if (comparison_source / 'desktop_report.md').exists():
            from person_iteration import compare_sections
            comparison = compare_sections((comparison_source / 'desktop_report.md').read_text(encoding='utf-8'), report.content)
            (run / 'iteration-comparison.json').write_text(json.dumps({'baseline': str(comparison_source), 'chapters': comparison,
                'model_events': invoker.events if invoker else [], 'new_search_calls': summary['new_search_calls'],
                'new_professional_calls': summary['new_professional_calls']}, ensure_ascii=False, indent=2), encoding='utf-8')
        if args.model_responses:
            summary['retained_model_responses_used'] = len(replayed_roles)
        (run / 'summary.json').write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'status': project.status, 'chapters': len(sections), 'run': str(run)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
