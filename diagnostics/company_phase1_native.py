"""Resume a frozen real run with bounded calls and a read-only object fallback.

No model answers are transplanted. The ordinary production checkpoint readers
revalidate native receipts. Every new write goes into this checkout's runtime.
"""
from __future__ import annotations
import argparse
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'work/company-phase1-20261028'


class BoundedCheckpoint(BaseException):
    """Unwind nested SDK/validator Exception handlers without a fake response."""


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', choices=['haitian', 'kingsoft'])
    parser.add_argument('--max-model-calls', type=int, default=12)
    parser.add_argument('--max-http-calls', type=int, default=24)
    parser.add_argument('--stage', choices=['native', 'frozen-report'], default='native',
                        help='frozen-report uses the existing production ai_search_enabled=False intake for writing replay; not new collection acceptance.')
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    baseline = RUN / 'baseline' / args.case
    manifest = json.loads((baseline / 'manifest.json').read_text(encoding='utf-8'))
    output = RUN / 'native' / args.case
    output.mkdir(parents=True, exist_ok=True)
    def write(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, default=str, indent=2), encoding='utf-8')
    database = output / 'acceptance.sqlite'
    if not database.exists():
        shutil.copyfile(baseline / 'acceptance.sqlite', database)
        assert sha(database) == manifest['database']['sha256']
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
            assert db.execute('SELECT COUNT(*) FROM research_sources').fetchone()[0] == manifest['source_count']
        write('database-copy-proof.json', {'sha256': sha(database), 'source_quick_check': 'ok',
              'byte_identical_to_verified_baseline': True, 'source_records': manifest['source_count']})
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
        target_name = db.execute('SELECT target_name FROM research_projects WHERE id=1').fetchone()[0]
    import zipfile
    checkpoint_root = output / 'objects/projects/1/company_generation_checkpoint'
    restored = output / 'native-restore-proof.json'
    if not restored.exists():
        with zipfile.ZipFile(baseline / 'native-checkpoints.zip') as archive:
            for name in archive.namelist():
                if name.startswith('whole-'):
                    name_out = name[6:]
                    raw = archive.read(name)
                    assert hashlib.sha256(raw).hexdigest() == name_out[:-5]
                else:
                    name_out = name
                    raw = archive.read(name)
                destination = (checkpoint_root / name_out).resolve()
                if not destination.is_relative_to(checkpoint_root.resolve()):
                    raise ValueError('Invalid archived object path')
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(raw)
            write('native-restore-proof.json', {'archive_sha256': sha(baseline / 'native-checkpoints.zip'),
                  'restored_entries': len(archive.namelist()), 'restored_before_first_model_call': True})
    write('object-fallback-index.json', {'readonly_root': str(baseline / 'objects'),
          'baseline_manifest_sha256': sha(baseline / 'manifest.json'),
          'write_root': str(output / 'objects'), 'native_journal_version_gate_unchanged': True})
    if args.prepare_only:
        print(json.dumps({'case': args.case, 'state': 'prepared', 'model_calls': 0, 'http_calls': 0}))
        return 0
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=True)
    overrides = {
        'PYTHON_DOTENV_DISABLED': '1', 'DATABASE_URL': 'sqlite:///' + database.as_posix(),
        'RESEARCH_OBJECT_STORE': 'local', 'RESEARCH_LOCAL_STORE': str(output / 'objects'),
        'COMPANY_KNOWLEDGE_OBJECT_STORE': 'local', 'COMPANY_KNOWLEDGE_LOCAL_STORE': str(output / 'knowledge-outbox'),
        'BM25_STATE_PATH': str(output / 'bm25.json'), 'DOCX_RENDER_QA_WORKDIR': str(output / 'render-work'),
        'REDIS_KEY_PREFIX': 'company-phase1-01a18168-' + args.case,
        'MILVUS_COLLECTION': 'company_phase1_01a18168_' + args.case,
        'REPORT_SECTION_MAX_WORKERS': '1', 'COMPANY_EDITORIAL_WORKERS': '1',
        'COMPANY_CORPUS_REVIEW_WORKERS': '1', 'COMPANY_CORPUS_WRITE_WORKERS': '1',
        'COMPANY_SOURCE_REVIEW_WORKERS': '1', 'CLEANING_MAX_WORKERS': '1',
        'WEB_SEARCH_QUERY_CONCURRENCY': '2', 'RESEARCH_LEGACY_RAG_ENABLED': 'false',
    }
    os.environ.update(overrides)
    isolated_env = output / '.env'
    with isolated_env.open('w', encoding='utf-8') as stream:
        stream.write((ROOT/'.env').read_text(encoding='utf-8-sig'))
        for key, value in overrides.items():
            stream.write('\n' + key + '=' + json.dumps(value, ensure_ascii=False))
    sys.path.insert(0, str(ROOT / 'backend'))
    import research_store
    store = research_store.research_store
    own_get = store.get_bytes
    def get_bytes(key):
        try:
            return own_get(key)
        except FileNotFoundError:
            fallback = (baseline / 'objects' / key.replace('\\', '/').lstrip('/')).resolve()
            if not fallback.is_relative_to((baseline / 'objects').resolve()):
                raise ValueError('Invalid fallback object path')
            return fallback.read_bytes()
    store.get_bytes = get_bytes
    store.get_text = lambda key: get_bytes(key).decode('utf-8')
    import research_workflow as runtime
    if args.stage == 'frozen-report':
        run_project = runtime.ResearchWorkflow.run_project
        def frozen_report(self, *positional, **keywords):
            keywords['intake'] = {**(keywords.get('intake') or {}), 'ai_search_enabled': False}
            return run_project(self, *positional, **keywords)
        runtime.ResearchWorkflow.run_project = frozen_report
    factory = runtime.init_chat_model
    model_lock = threading.Semaphore(1)
    http_lock = threading.Semaphore(2)
    ledger_lock = threading.Lock()
    counts = {'model_calls': 0, 'model_failures': 0, 'http_calls': 0, 'http_failures': 0}
    tag = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    ledger = output / ('bounded-calls-' + tag + '.jsonl')
    def record(value):
        with ledger_lock:
            with ledger.open('a', encoding='utf-8') as f:
                f.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(), **value}, ensure_ascii=False, default=str) + '\n')
    class Model:
        def __init__(self, delegate, settings):
            self.delegate, self.settings = delegate, settings
        def __getattr__(self, name):
            return getattr(self.delegate, name)
        def invoke(self, messages, *positional, **keywords):
            with model_lock:
                if counts['model_calls'] >= args.max_model_calls:
                    raise BoundedCheckpoint('model_call_budget_exhausted')
                counts['model_calls'] += 1
                number = counts['model_calls']
                request = hashlib.sha256(json.dumps(messages, ensure_ascii=False, default=str, sort_keys=True).encode()).hexdigest()
                started = time.monotonic()
                record({'kind': 'model_started', 'number': number, 'model': self.settings.get('model'),
                        'input_sha256': request, 'sdk_max_retries': self.settings.get('max_retries')})
                try:
                    result = self.delegate.invoke(messages, *positional, **keywords)
                    record({'kind': 'model_returned', 'number': number,
                        'elapsed_seconds': round(time.monotonic()-started, 3),
                        'finish_reason': (getattr(result, 'response_metadata', {}) or {}).get('finish_reason'),
                        'usage': getattr(result, 'usage_metadata', None)})
                    return result
                except Exception as exc:
                    counts['model_failures'] += 1
                    record({'kind': 'model_failed', 'number': number, 'error_type': type(exc).__name__,
                            'elapsed_seconds': round(time.monotonic()-started, 3)})
                    raise
    def model_factory(*positional, **settings):
        return Model(factory(*positional, **settings), settings)
    runtime.init_chat_model = model_factory
    import requests
    request = requests.Session.request
    def bounded_request(session, method, url, *positional, **keywords):
        parsed = urlsplit(url)
        is_model = parsed.path.rstrip('/').endswith(('/chat/completions', '/responses'))
        with http_lock, (model_lock if is_model else nullcontext()):
            with ledger_lock:
                if counts['http_calls'] >= args.max_http_calls:
                    raise BoundedCheckpoint('http_call_budget_exhausted')
                if is_model:
                    if counts['model_calls'] >= args.max_model_calls:
                        raise BoundedCheckpoint('model_call_budget_exhausted')
                    counts['model_calls'] += 1
                counts['http_calls'] += 1
                number = counts['http_calls']
            started = time.monotonic()
            try:
                response = request(session, method, url, *positional, **keywords)
                record({'kind': 'http_returned', 'number': number, 'host': parsed.hostname,
                        'path': parsed.path, 'http_status': response.status_code,
                        'elapsed_seconds': round(time.monotonic()-started, 3)})
                return response
            except Exception as exc:
                counts['http_failures'] += 1
                record({'kind': 'http_failed', 'number': number, 'host': parsed.hostname,
                        'error_type': type(exc).__name__, 'elapsed_seconds': round(time.monotonic()-started, 3)})
                raise
    requests.Session.request = bounded_request
    version = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    code_files = [*sorted((ROOT/'backend').rglob('*.py')), ROOT/'diagnostics/accept_company_live.py', Path(__file__).resolve()]
    code_hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in code_files}
    write('bounded-plan-' + tag + '.json', {'case': args.case, 'code_commit': version,
          'stage': args.stage, 'new_collection_acceptance': args.stage == 'native',
          'model_logical_request_limit': args.max_model_calls, 'requests_http_limit': args.max_http_calls,
          'model_concurrency_enforced_by_semaphore': 1, 'requests_concurrency_enforced_by_semaphore': 2,
          'code_sha256': code_hashes, 'settings_overrides': overrides,
          'sdk_retries_remain_configured': True, 'original_model_responses_modified': False})
    spec = importlib.util.spec_from_file_location('phase1_native_entry', ROOT/'diagnostics/accept_company_live.py')
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    sys.argv = ['accept_company_live.py', '--target', target_name,
                '--env-file', str(isolated_env), '--output', str(output), '--as-of', '2026-10-24', '--resume']
    status = 'not_started'
    result_code = 1
    try:
        result_code = entry.main()
        status = 'native_entry_completed'
    except BoundedCheckpoint as exc:
        status = str(exc)
        result_code = 3
        # The ordinary runner's finally snapshots may observe old artifacts.
        # A budget boundary cannot authorize those artifacts for delivery.
        acceptance = output / 'acceptance.json'
        if acceptance.exists():
            value = json.loads(acceptance.read_text(encoding='utf-8'))
            value.update(status='bounded_checkpoint', delivery_ready=False, bounded_reason=status)
            write('acceptance.json', value)
    finally:
        unchanged = all(sha(ROOT / path) == value for path, value in code_hashes.items())
        write('bounded-result-' + tag + '.json', {'state': status, 'counts': counts,
              'stage': args.stage, 'new_collection_acceptance': False,
              'runtime_code_unchanged': unchanged, 'delivery_accepted': False,
              'manual_review': 'pending', 'actual_cost': None})
        print(json.dumps({'case': args.case, 'state': status, 'counts': counts,
                          'runtime_code_unchanged': unchanged}, ensure_ascii=False), flush=True)
    return result_code


if __name__ == '__main__':
    raise SystemExit(main())
