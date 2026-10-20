"""One opt-in live person workflow, isolated from application data and indexing.

Runs the production workflow with bounded real search, professional tools and
model calls. Only the database, object-store destination and knowledge indexing
are isolated. Source snapshots are retained locally for QA before the normal
transient-source cleanup runs. No credentials are written to the QA records.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='Authorize a new paid bounded run')
    args = parser.parse_args()
    if not args.live:
        parser.error('Use --live for real provider requests; this script has no automatic paid replay.')
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    started = time.monotonic()
    run = ROOT / 'work/person-optimization' / ('full-live-' + datetime.now().strftime('%Y%m%dT%H%M%S'))
    run.mkdir(parents=True)
    os.environ.update({
        'DATABASE_URL': 'sqlite:///' + (run / 'run.sqlite').as_posix(),
        'RESEARCH_OBJECT_STORE': 'local', 'RESEARCH_LOCAL_STORE': str(run / 'objects'),
        'RESEARCH_LEGACY_RAG_ENABLED': 'false', 'CLEANING_MODE': 'fast', 'CLEANING_LLM_ENABLED': 'false',
        'WORKFLOW_RESUME_ENABLED': 'false', 'PERSON_SEARCH_CALL_BUDGET': '48',
        'PERSON_SEARCH_RESULTS_PER_QUERY': '6', 'PERSON_WEB_FETCH_BUDGET': '44',
        'PERSON_PLATFORM_CALL_BUDGET': '18', 'WEB_FETCH_TOTAL_TIMEOUT_SECONDS': '20',
        'PERSON_REPORT_SECTION_TIMEOUT_SECONDS': '90', 'PERSON_REPORT_SECTION_MAX_RETRIES': '0',
        'LLM_TIMEOUT_SECONDS': '90', 'LLM_MAX_RETRIES': '0',
    })
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    import report_knowledge
    from models import Base, ResearchProject, User
    from research_workflow import ResearchWorkflow
    from research_store import research_store
    from person_evidence import split_sections, cited_ids
    # This run is not a product task. It must not enqueue uploads or write to a
    # shared vector store while validating the actual research/report stages.
    report_knowledge.sync_report_safely = lambda *a, **kw: None
    research_store.mode, research_store.local_root = 'local', run / 'objects'
    secret_values = [v for k, v in os.environ.items() if v and len(v) >= 12 and re.search('KEY|TOKEN|SECRET|PASSWORD', k)]

    def safe(value):
        text = json.dumps(value, ensure_ascii=False, default=str)
        for secret in secret_values:
            text = text.replace(secret, '[REDACTED]')
        text = re.sub(r'api_key=[^\s&"<>]+', 'api_key=[REDACTED]', text)
        return json.loads(text)

    def emit(event):
        event = safe(event)
        with (run / 'trace.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + '\n')
        if event.get('stage') not in {'web_search'} or event.get('label') in {'开始在线检索', '在线来源采集结束', '在线检索 Agent 启动'}:
            print(json.dumps({k: event.get(k) for k in ('stage', 'label', 'status', 'section') if event.get(k)}, ensure_ascii=False), flush=True)

    workflow = ResearchWorkflow()
    original_finalize = workflow._finalize_source_records

    def finalize(db, project, trace=None):
        snapshots = []
        for source in project.sources:
            snapshots.append({key: getattr(source, key) for key in ('id', 'source_type', 'title', 'url', 'content', 'summary', 'source_metadata', 'credibility_score')})
        (run / 'source-snapshots.json').write_text(json.dumps(safe(snapshots), ensure_ascii=False, indent=2), encoding='utf-8')
        if (run / 'objects').exists():
            shutil.copytree(run / 'objects', run / 'objects-before-cleanup', dirs_exist_ok=True)
        original_finalize(db, project, trace)
    workflow._finalize_source_records = finalize
    engine = create_engine(os.environ['DATABASE_URL'])
    Base.metadata.create_all(engine)
    summary = {'run_path': str(run), 'scope': 'full_live_person_workflow_isolated_storage_no_knowledge_index',
               'code_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
               'original_fetch_timeout_seconds': 20, 'section_timeout_seconds': 90,
               'knowledge_indexing': 'excluded_from_research_QA'}
    print(json.dumps({'started': str(run)}, ensure_ascii=False), flush=True)
    with Session(engine) as db:
        user = User(username='isolated-full-person-qa', password_hash='not-a-product-login')
        db.add(user)
        db.flush()
        project = ResearchProject(title='王传福人物背景调查全链路验收', target_name='王传福', target_type='person',
                                  industry='', description='公开资料背景调查接口与章节验收，不代替正式尽调及人工复核', created_by_id=user.id)
        db.add(project)
        db.commit()
        intake = {'target_type': 'person', 'company_name': '王传福',
                  'affiliation': '比亚迪股份有限公司 / 董事长',
                  'person_context': '定位线索为与比亚迪股份有限公司有关的王传福。职务、任职时期、学校与其他履历均需来源核对，同名其他人的记录不得归给目标。',
                  'focus_questions': ['核对教育与职业履历，区分历史任职与现任职责', '核对本人持股、关联企业和公开司法事项', '经营、管理及同业比较分别列证据与缺口'],
                  'special_requirements': '专项核查公开披露中的历史持股及任职变化，区分本人行为与关联企业事项。',
                  'as_of_date': datetime.now().date().isoformat(), 'ai_search_enabled': True}
        (run / 'intake.json').write_text(json.dumps(intake, ensure_ascii=False, indent=2), encoding='utf-8')
        try:
            artifacts, added = workflow.run_project(db, project, [], [], emit=emit, intake=intake)
            summary.update(status=project.status, sources_added=added)
            rows = db.query(type(artifacts[0])).filter_by(project_id=project.id).all()
            for artifact in rows:
                extension = '.json' if artifact.artifact_type in {'person_claim_ledger', 'person_retrieval_audit', 'cleaned_facts', 'risk_assessment'} else '.md'
                (run / (artifact.artifact_type + extension)).write_text(artifact.content or '', encoding='utf-8')
            report = next(a for a in artifacts if a.artifact_type == 'desktop_report')
            metadata = report.artifact_metadata or {}
            ledger = next(a for a in artifacts if a.artifact_type == 'person_claim_ledger')
            diagnostic = json.loads(ledger.content)['diagnostic']
            sections = split_sections(report.content)
            summary.update(chapters=sorted(sections), chapter_count=len(sections),
                           chapter_audit=diagnostic, report_metadata=metadata,
                           chapter_citation_counts={str(k): len(cited_ids(v)) for k, v in sections.items()},
                           provider_attempts=getattr(project, 'person_platform_attempts', []))
            key = metadata.get('docx_object_key')
            if key:
                docx = run / 'person-report.docx'
                docx.write_bytes(research_store.get_bytes(key))
                with zipfile.ZipFile(docx) as archive:
                    summary['docx_integrity_ok'] = archive.testzip() is None
                    summary['docx_document_xml_present'] = 'word/document.xml' in archive.namelist()
            summary['artifacts'] = [{'type': a.artifact_type, 'id': a.id, 'version': a.version} for a in rows]
        except Exception as exc:
            db.rollback()
            summary.update(status='failed', exception_type=type(exc).__name__, error=str(exc)[:1600])
            emit({'stage': 'full_live_qa', 'label': '全链路验收失败', 'status': 'error', 'detail': str(exc)[:1600]})
        summary['elapsed_seconds'] = round(time.monotonic()-started, 1)
        (run / 'summary.json').write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        print(json.dumps({'status': summary['status'], 'chapter_count': summary.get('chapter_count'),
                          'summary': str(run / 'summary.json'), 'elapsed_seconds': summary['elapsed_seconds']}, ensure_ascii=False), flush=True)
    if summary['status'] != 'completed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
