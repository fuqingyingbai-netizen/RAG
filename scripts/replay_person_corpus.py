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
    args = parser.parse_args()
    if args.live_model and args.model_responses:
        parser.error('--live-model and --model-responses are mutually exclusive')
    if args.chapter_followup and not args.live_model:
        parser.error('--chapter-followup requires --live-model')
    if args.retained_chapter_discovery and not args.chapter_followup:
        parser.error('--retained-chapter-discovery requires --chapter-followup')
    baseline = args.baseline.resolve()
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    run = ROOT / 'work/person-optimization' / ('same-corpus-' + datetime.now().strftime('%Y%m%dT%H%M%S'))
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
    shutil.copytree(baseline / 'objects-before-cleanup', run / 'objects', dirs_exist_ok=True)
    intake = json.loads((baseline / 'intake.json').read_text(encoding='utf-8'))
    snapshots = json.loads((baseline / 'source-snapshots.json').read_text(encoding='utf-8'))
    previous = json.loads((baseline / 'summary.json').read_text(encoding='utf-8'))
    retrieval = json.loads((baseline / 'person_retrieval_audit.json').read_text(encoding='utf-8'))
    workflow = research_workflow.ResearchWorkflow()
    replayed_roles = []
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
        return len(snapshots)

    workflow.collect_web_sources = collect
    workflow.collect_structured_sources = lambda *a, **kw: 0
    workflow.collect_person_affiliation_structured_sources = lambda *a, **kw: 0
    if not args.chapter_followup:
        workflow.collect_person_chapter_sources = lambda *a, **kw: 0
    elif args.retained_chapter_discovery:
        original_chapter_collection = workflow.collect_person_chapter_sources
        workflow.collect_person_chapter_sources = lambda db, p, value, emit=None: original_chapter_collection(
            db, p, {**value, 'person_chapter_followup_mode': 'retained_only'}, emit)
    # Entity resolution for a person is local, but disable any future remote
    # implementation here: this replay is explicitly restricted to the corpus.
    workflow.resolve_business_entity = lambda project, intake, **kw: intake
    secrets = [v for k, v in os.environ.items() if v and len(v) >= 12 and any(t in k.upper() for t in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD'))]

    def safe(value):
        text = json.dumps(value, ensure_ascii=False, default=str)
        for secret in secrets:
            text = text.replace(secret, '[REDACTED]')
        return json.loads(text)

    if args.live_model:
        original_invoke = workflow._invoke_person_report_section

        def recorded_invoke(role, prompt, emit=None):
            response = original_invoke(role, prompt, emit)
            with (run / 'chapter-model-responses.jsonl').open('a', encoding='utf-8') as f:
                f.write(json.dumps(safe({'role': role, 'response': response}), ensure_ascii=False) + '\n')
            return response
        workflow._invoke_person_report_section = recorded_invoke

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
    if args.chapter_followup:
        summary.update(scope='retained_corpus_plus_bounded_chapter_7_8_research_and_live_models',
                       baseline_corpus_sha256=summary['corpus_sha256'])
        original_finalize = workflow._finalize_source_records
        def finalize(db, project, trace=None):
            snapshots = [{k: getattr(s, k) for k in ('id', 'source_type', 'title', 'url', 'content', 'summary', 'source_metadata', 'credibility_score')}
                         for s in project.sources]
            snapshot_path = run / 'source-snapshots.json'
            snapshot_path.write_text(json.dumps(safe(snapshots), ensure_ascii=False, indent=2), encoding='utf-8')
            (run / 'intake.json').write_text(json.dumps(intake, ensure_ascii=False, indent=2), encoding='utf-8')
            summary['corpus_sha256'] = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
            summary['provider_attempts'] = getattr(project, 'person_platform_attempts', [])
            summary['chapter_followup'] = (getattr(project, 'person_retrieval_audit', {}) or {}).get('chapter_7_8_followup', {})
            summary['new_search_calls'] = len(summary['chapter_followup'].get('attempts', []))
            summary['retained_source_count'] = len(snapshots)
            shutil.copytree(run / 'objects', run / 'objects-before-cleanup', dirs_exist_ok=True)
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
        project = ResearchProject(title=f'{target}人物背景调查全链路验收', target_name=target, target_type='person',
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
        key = (report.artifact_metadata or {}).get('docx_object_key')
        if key:
            docx = run / 'person-report.docx'
            docx.write_bytes(research_store.get_bytes(key))
            with zipfile.ZipFile(docx) as archive:
                summary['docx_integrity_ok'] = archive.testzip() is None
        summary['elapsed_seconds'] = round(time.monotonic()-started, 1)
        if args.model_responses:
            summary['retained_model_responses_used'] = len(replayed_roles)
        (run / 'summary.json').write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'status': project.status, 'chapters': len(sections), 'run': str(run)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
