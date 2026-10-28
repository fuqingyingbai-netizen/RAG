"""Exercise the real company workflow with isolated persistence and an audit trail.

No source fixtures, model replacement, response cache, collection quota override,
or delivery-gate bypass. Credentials are read from --env-file, never copied.
The only overrides isolate writes and provide the local document renderer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True)
    parser.add_argument('--industry', default='')
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--soffice', type=Path)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--pause-file', type=Path, help='Use the workflow cooperative pause at its next checkpoint.')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    pause_file = (args.pause_file or output / 'pause.requested').resolve()
    if (output / 'acceptance.sqlite').exists() and not args.resume:
        parser.error('Output already has a run; use a fresh directory or --resume.')

    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=True)
    secrets = sorted({value for key, value in os.environ.items() if len(value) >= 8 and
                      (re.search(r'(?:API_KEY|SECRET|TOKEN|PASSWORD)', key, re.I)
                       or ('MCP' in key and key.endswith('URL')))}, key=len, reverse=True)

    def serialized(value, **options):
        text = json.dumps(value, ensure_ascii=False, default=str, **options)
        for secret in secrets:
            text = text.replace(secret, '[REDACTED]')
        return text
    overrides = {
        'DATABASE_URL': 'sqlite:///' + (output / 'acceptance.sqlite').as_posix(),
        'RESEARCH_OBJECT_STORE': 'local',
        'RESEARCH_LOCAL_STORE': str(output / 'objects'),
        'COMPANY_KNOWLEDGE_OBJECT_STORE': 'local',
        'COMPANY_KNOWLEDGE_LOCAL_STORE': str(output / 'knowledge-outbox'),
        'BM25_STATE_PATH': str(output / 'bm25.json'),
        'DOCX_RENDER_QA_WORKDIR': str(output / 'render-work'),
        'RESEARCH_LEGACY_RAG_ENABLED': 'false',
        'PYTHON_DOTENV_DISABLED': '1',
    }
    if args.soffice:
        overrides['LIBREOFFICE_SOFFICE_PATH'] = str(args.soffice.resolve())
    os.environ.update(overrides)
    sys.path.insert(0, str(root / 'backend'))
    import research_workflow as runtime
    from database import Base, engine, SessionLocal
    from models import ResearchArtifact, ResearchProject, User
    import company_catalog  # Register the isolated report outbox tables.

    lock = threading.RLock()
    started = time.monotonic()
    counts = {'model_calls': 0, 'model_failures': 0, 'artifacts': 0}

    def write(name, value):
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with lock:
            path.write_text(serialized(value, indent=2), encoding='utf-8')

    def emit(event):
        with lock:
            item = {'at': datetime.now(timezone.utc).isoformat(),
                    'elapsed_seconds': round(time.monotonic() - started, 2), **event}
            with (output / 'events.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(serialized(item) + '\n')
            write('progress.json', {'counts': counts, 'event': item})
            print(serialized(item), flush=True)

    # Observe the actual LangChain model factory; preserve every invocation,
    # parameter, retry, return value, and exception used by the application.
    factory = runtime.init_chat_model

    class ObservedModel:
        def __init__(self, delegate, model, settings):
            self.delegate, self.model, self.settings = delegate, model, settings

        def __getattr__(self, name):
            return getattr(self.delegate, name)

        def invoke(self, messages, *positional, **keywords):
            with lock:
                counts['model_calls'] += 1
                number = counts['model_calls']
            receipt = {'model': self.model, 'model_settings': self.settings,
                       'effective_streaming': keywords.get('stream', self.settings.get('streaming', False)),
                       'messages': messages, 'kwargs': keywords,
                       'started_at': datetime.now(timezone.utc).isoformat()}
            before = time.monotonic()
            try:
                result = self.delegate.invoke(messages, *positional, **keywords)
                receipt.update(response=result.content,
                               response_metadata=result.response_metadata,
                               usage_metadata=getattr(result, 'usage_metadata', None))
                return result
            except Exception as exc:
                with lock:
                    counts['model_failures'] += 1
                receipt.update(error_type=type(exc).__name__, error=str(exc))
                raise
            finally:
                receipt['elapsed_seconds'] = round(time.monotonic() - before, 2)
                write(f'model-receipts/{run_tag}-{number:06d}.json', receipt)

    def observe_factory(*positional, **keywords):
        delegate = factory(*positional, **keywords)
        settings = {key: keywords[key] for key in ('model_provider', 'temperature', 'stream_usage',
            'timeout', 'max_retries', 'max_tokens', 'max_completion_tokens', 'reasoning_effort') if key in keywords}
        settings['streaming'] = getattr(delegate, 'streaming', False)
        return ObservedModel(delegate, keywords.get('model', ''), settings)

    run_tag = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    if (output / 'acceptance.json').exists():
        shutil.copyfile(output / 'acceptance.json', output / f'acceptance-before-{run_tag}.json')
    if (output / 'failure.json').exists():
        (output / 'failure.json').rename(output / f'failure-before-{run_tag}.json')
    runtime.init_chat_model = observe_factory

    def snapshot_sources(project, name):
        write(name, [{'id': source.id, 'source_type': source.source_type, 'title': source.title,
                      'url': source.url, 'object_key': source.object_key, 'content': source.content,
                      'summary': source.summary, 'source_metadata': source.source_metadata,
                      'credibility_score': source.credibility_score, 'created_at': source.created_at}
                     for source in project.sources])

    def snapshot_state(project):
        for key, value in vars(project).copy().items():
            if key.startswith('company_'):
                write('state/' + key + '.json', value)

    class ObservedWorkflow(runtime.ResearchWorkflow):
        def save_artifact(self, db, project, *positional, **keywords):
            artifact = super().save_artifact(db, project, *positional, **keywords)
            with lock:
                counts['artifacts'] += 1
            stem = f'artifacts/{artifact.id:04d}-{artifact.artifact_type}-v{artifact.version}'
            (output / (stem + '.md')).parent.mkdir(parents=True, exist_ok=True)
            suffix='.html' if artifact.artifact_type=='company_evidence_annex' else '.md'
            (output / (stem + suffix)).write_text(artifact.content, encoding='utf-8')
            write(stem + '.json', artifact.artifact_metadata)
            for key, value in artifact.artifact_metadata.items():
                if key.endswith('object_key') and isinstance(value, str) and value:
                    source_path = (output / 'objects' / value).resolve()
                    if source_path.is_file() and (output / 'objects') in source_path.parents:
                        shutil.copyfile(source_path, output / (stem + '-' + key + source_path.suffix))
            snapshot_sources(project, 'source-snapshots-latest.json')
            snapshot_state(project)
            emit({'stage': 'acceptance', 'label': '产物已保存', 'artifact_type': artifact.artifact_type,
                  'artifact_id': artifact.id, 'delivery_status': artifact.artifact_metadata.get('delivery_status')})
            return artifact

        def _finalize_source_records(self, db, project, emit=None):
            # The production retention policy deletes temporary bodies. Keep an
            # independent diagnostic snapshot BEFORE calling that unchanged policy.
            snapshot_sources(project, 'source-snapshots-before-retention.json')
            snapshot_state(project)
            return super()._finalize_source_records(db, project, emit)

    proof_files = sorted([p for p in (root / 'backend').rglob('*.py')]
                         + [Path(__file__).resolve()])
    safe_settings = ['MODEL', 'GRADE_MODEL', 'WEB_SEARCH_PROVIDER', 'CLEANING_LLM_ENABLED',
                     'STRUCTURED_SOURCE_ENABLED', 'STRUCTURED_SOURCE_REQUIRED',
                     'COMPANY_REPORT_EDITOR_ENABLED', 'COMPANY_REPORT_EDITOR_REQUIRED',
                     'DOCX_RENDER_QA_ENABLED', 'DOCX_RENDER_QA_REQUIRED', 'WORKFLOW_RESUME_ENABLED',
                     'COMPANY_REPORT_EDITOR_STREAMING_ENABLED', 'COMPANY_CLEANING_STREAMING_ENABLED', 'COMPANY_EDITORIAL_WORKERS',
                     'COMPANY_REPORT_READING_MODE',
                     'COMPANY_CORPUS_REVIEW_WORKERS']
    manifest = {'target': args.target, 'industry': args.industry, 'as_of': args.as_of,
                'resume': args.resume,
                'pause_file': str(pause_file),
                'scope': '真实生产工作流；独立 SQLite 和本地存储；无源材料或模型响应替换',
                'settings': {key: os.getenv(key) for key in safe_settings},
                'isolation_overrides': overrides,
                'code_root': str(root), 'started_at': datetime.now(timezone.utc).isoformat(),
                'code_sha256': {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in proof_files}}
    write(f'run-input-{run_tag}.json', manifest)
    shutil.copyfile(Path(__file__), output / f'runner-source-{run_tag}.py')
    Base.metadata.create_all(bind=engine)
    failure = None
    with SessionLocal() as db:
        project = db.query(ResearchProject).first() if args.resume else None
        if project is not None and project.target_name != args.target:
            parser.error('Resume target differs from the isolated project target.')
        if project is None:
            owner = User(username='isolated-live-acceptance', password_hash='disabled-test-account', role='user')
            db.add(owner)
            db.flush()
            project = ResearchProject(title=args.target + ' 背景调查报告', target_name=args.target,
                                      target_type='company', industry=args.industry, created_by_id=owner.id)
            db.add(project)
            db.commit()
        try:
            ObservedWorkflow().run_project(db, project, [], [], emit=emit,
                pause_requested=lambda: pause_file.exists(),
                intake={'target_type': 'company', 'company_name': args.target,
                        'industry': args.industry, 'as_of_date': args.as_of})
        except Exception as exc:
            failure = traceback.format_exc()
            db.rollback()
            if isinstance(exc, runtime.WorkflowPaused):
                # The HTTP worker normally persists this terminal status.
                # This CLI owns that same responsibility for its isolated DB.
                project.status = 'paused'
                db.commit()
            write('failure.json', {'traceback': failure})
        finally:
            snapshot_sources(project, 'source-snapshots-final.json')
            snapshot_state(project)
            artifacts = db.query(ResearchArtifact).filter_by(project_id=project.id).all()
            reports = [item for item in artifacts if item.artifact_type == 'desktop_report']
            report = max(reports, key=lambda item: item.version, default=None)
            metadata = report.artifact_metadata if report else {}
            ready = bool((metadata.get('company_delivery_contract') or {}).get('delivery_ready')) and not failure
            write('acceptance.json', {'target': args.target, 'project_id': project.id,
                'status': 'passed' if ready else 'paused' if project.status == 'paused' else 'failed',
                'workflow_status': project.status,
                'elapsed_seconds': round(time.monotonic() - started, 2), 'counts': counts,
                'source_records': len(project.sources), 'report_metadata': metadata,
                'exception': failure, 'manual_page_inspection': 'pending',
                'limitations': '自动门禁结果与逐页人工验收分别记录；人工验收前不宣称报告可交付。'})
    print(json.dumps({'target': args.target, 'delivery_ready': ready, 'failure': bool(failure)}, ensure_ascii=False))
    return 0 if ready else 1


if __name__ == '__main__':
    raise SystemExit(main())
