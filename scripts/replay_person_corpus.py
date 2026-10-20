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
    args = parser.parse_args()
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
    if not args.live_model:
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
    # Entity resolution for a person is local, but disable any future remote
    # implementation here: this replay is explicitly restricted to the corpus.
    workflow.resolve_business_entity = lambda project, intake, **kw: intake
    secrets = [v for k, v in os.environ.items() if v and len(v) >= 12 and any(t in k.upper() for t in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD'))]

    def safe(value):
        text = json.dumps(value, ensure_ascii=False, default=str)
        for secret in secrets:
            text = text.replace(secret, '[REDACTED]')
        return json.loads(text)

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
        (run / 'summary.json').write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'status': project.status, 'chapters': len(sections), 'run': str(run)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
