"""Isolated regressions for prelaunch findings 8–10; no real upstream calls."""
import asyncio
from datetime import datetime, timezone
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import company_knowledge as kb
import company_observability as obs
import company_ingestion as ingestion
from company_catalog import CompanyDocument
from test_company_workspace import setup, upload, project


@pytest.fixture
def logs(monkeypatch, tmp_path):
    root = tmp_path / 'traces'
    monkeypatch.setenv('COMPANY_KNOWLEDGE_LOG_DIR', str(root))
    return root


def records(root, kind='summary'):
    return [json.loads(line) for path in root.glob('kb-' + kind + '-*.jsonl')
            for line in path.read_text().splitlines()]


def test_all_knowledge_routes_document_business_rejections(setup):
    schema = setup.client.app.openapi()
    expected = {'400', '401', '403', '404', '409', '410', '413', '416', '422', '429', '502', '503'}
    for path, methods in schema['paths'].items():
        if path.startswith('/company-knowledge/'):
            for method, operation in methods.items():
                if method in {'get', 'post', 'put', 'patch', 'delete', 'head'}:
                    assert expected <= set(operation['responses']), (path, method)
                    assert '500' not in operation['responses']


def test_actual_permission_conflict_and_validation_errors_match_schema(setup):
    p = project(setup, 'contract')
    cases = [setup.client.post('/company-knowledge/projects', json={'name': 'contract'}),
             setup.client.post('/company-knowledge/chat/stream', json={'message': ''}),
             setup.client.get('/company-knowledge/documents/missing/preview')]
    setup.user.username, setup.user.id = 'bob', 2
    cases.append(setup.client.patch('/company-knowledge/projects/' + p['id'], json={'name': 'denied'}))
    assert [r.status_code for r in cases] == [409, 422, 404, 403]
    for response in cases:
        kb.KnowledgeValidationError.model_validate(response.json())


def test_preview_is_not_cacheable_and_revocation_is_rechecked(setup, monkeypatch):
    row = upload(setup, visibility='restricted', readers='["bob"]').json()
    url = '/company-knowledge/documents/' + row['id'] + '/preview'
    pending = setup.client.get(url)
    assert pending.status_code == 200
    assert pending.headers['cache-control'] == 'private, no-store'
    assert set(pending.headers['vary'].split(', ')) == {'Authorization', 'Cookie'}
    with setup.db() as db:
        doc = db.get(CompanyDocument, row['id'])
        doc.cloud_id, doc.state = 'cloud-visible', 'ready'
        db.commit()
    async def chunks(*args, **kwargs):
        return {'nodes': [{'text': 'PRIVATE EVIDENCE', 'metadata': {'doc_id': 'cloud-visible'}}], 'total': 1}
    monkeypatch.setattr(kb, 'cloud_rpc', chunks)
    setup.user.username, setup.user.id = 'bob', 2
    ready = setup.client.get(url)
    assert ready.status_code == 200 and 'PRIVATE EVIDENCE' in ready.text
    assert ready.headers['cache-control'] == 'private, no-store'
    with setup.db() as db:
        db.get(CompanyDocument, row['id']).readers = []
        db.commit()
    denied = setup.client.get(url, headers={'If-None-Match': 'old-value'})
    assert denied.status_code == 404 and 'PRIVATE EVIDENCE' not in denied.text


def test_preview_rejects_version_change_during_upstream_lookup(setup, monkeypatch):
    row = upload(setup).json()
    with setup.db() as db:
        doc = db.get(CompanyDocument, row['id'])
        doc.cloud_id, doc.state = 'old', 'ready'
        db.commit()
    async def changed(*args, **kwargs):
        with setup.db() as db:
            db.get(CompanyDocument, row['id']).cloud_id = 'new'
            db.commit()
        return {'nodes': [{'text': 'STALE TEXT', 'metadata': {'doc_id': 'old'}}]}
    monkeypatch.setattr(kb, 'cloud_rpc', changed)
    response = setup.client.get('/company-knowledge/documents/' + row['id'] + '/preview')
    assert response.status_code == 409 and 'STALE TEXT' not in response.text


@pytest.mark.parametrize('ending,outcome', [('done', 'success'), ('error', 'business_error'), ('none', 'incomplete')])
def test_http_200_is_not_automatically_sse_success(logs, monkeypatch, ending, outcome):
    app = FastAPI()
    app.add_middleware(obs.KnowledgeHTTPMiddleware)
    async def answer(cfg, question):
        yield {'type': 'answer_delta', 'text': 'SECRET ANSWER'}
        if ending != 'none':
            yield {'type': ending, 'message': 'SECRET ERROR', 'usage': {}}
    monkeypatch.setattr(kb, 'cloud_answer', answer)
    @app.get('/company-knowledge/chat/{session}')
    def stream(session: str):
        async def events():
            async for event in kb.stream_events({}, None):
                yield 'data: ' + json.dumps(event) + '\n\n'
        return StreamingResponse(events(), media_type='text/event-stream')
    response = TestClient(app).get('/company-knowledge/chat/SECRET-ID?question=SECRET-QUESTION',
                                   headers={'Authorization': 'Bearer SECRET-KEY', 'X-Request-ID': 'spoofed'})
    assert response.status_code == 200
    summary = records(logs)[0]
    assert summary['outcome'] == outcome and summary['response_complete']
    assert summary['route'] == '/company-knowledge/chat/{session}'
    assert summary['request_id'] == response.headers['x-request-id'] != 'spoofed'
    assert 'SECRET' not in json.dumps(records(logs) + records(logs, 'detail'))


def test_requests_are_isolated_and_nonknowledge_routes_untouched(logs):
    app = FastAPI()
    app.add_middleware(obs.KnowledgeHTTPMiddleware)
    @app.get('/company-knowledge/status')
    def status():
        obs.observe_sse({'type': 'done'})
        return {'ok': True}
    @app.get('/health')
    def health():
        return {'ok': True}
    client = TestClient(app)
    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(lambda _: client.get('/company-knowledge/status'), range(10)))
    assert len({r.headers['x-request-id'] for r in responses}) == 10
    assert len(records(logs)) == 10
    assert 'x-request-id' not in client.get('/health').headers
    assert len(records(logs)) == 10


def test_actual_upload_correlates_http_sql_and_confirmed_commit(setup, logs):
    setup.client.app.add_middleware(obs.KnowledgeHTTPMiddleware)
    obs.instrument_engine(setup.db.kw['bind'])
    response = upload(setup, payload=b'PRIVATE ORIGINAL BYTES')
    assert response.status_code == 202
    request_id = response.headers['x-request-id']
    summary = next(row for row in records(logs) if row['request_id'] == request_id)
    assert summary['route'] == '/company-knowledge/uploads' and summary['outcome'] == 'success'
    assert summary['sql_calls'] > 0 and summary['commits_confirmed'] > 0
    events = [row for row in records(logs, 'detail') if row['request_id'] == request_id]
    assert any(row['event'] == 'transaction' for row in events)
    assert 'PRIVATE ORIGINAL BYTES' not in json.dumps(events)


def test_permission_refusal_is_logged_as_http_error(setup, logs):
    setup.client.app.add_middleware(obs.KnowledgeHTTPMiddleware)
    p = project(setup)
    setup.user.username, setup.user.id = 'bob', 2
    response = setup.client.patch('/company-knowledge/projects/' + p['id'], json={'name': 'denied'})
    assert response.status_code == 403
    summary = next(row for row in records(logs) if row['request_id'] == response.headers['x-request-id'])
    assert summary['http_status'] == 403 and summary['outcome'] == 'http_error'


def test_middleware_does_not_buffer_first_sse_event(logs):
    from http_delivery import ResearchReadCompression
    async def run():
        first, release = asyncio.Event(), asyncio.Event()
        async def app(scope, receive, send):
            await send({'type':'http.response.start','status':200,
                        'headers':[(b'content-type',b'text/event-stream')]})
            await send({'type':'http.response.body','body':b'data: first\n\n','more_body':True})
            await release.wait()
            obs.observe_sse({'type':'done'})
            await send({'type':'http.response.body','body':b'data: done\n\n'})
        async def receive():
            return {'type':'http.request','body':b''}
        async def send(message):
            if message.get('body'):
                first.set()
        middleware = obs.KnowledgeHTTPMiddleware(ResearchReadCompression(app))
        task = asyncio.create_task(middleware({'type':'http','method':'GET','path':'/company-knowledge/chat',
            'headers':[(b'accept-encoding',b'gzip')]},receive,send))
        try:
            await asyncio.wait_for(first.wait(),5)
            assert not task.done()
        finally:
            release.set()
            await task
    asyncio.run(run())
    assert records(logs)[0]['outcome'] == 'success'


def test_cancelled_stream_records_interruption_and_resets_context(logs):
    async def app(scope, receive, send):
        await send({'type': 'http.response.start', 'status': 200,
                    'headers': [(b'content-type', b'text/event-stream')]})
        obs.observe_sse({'type': 'done'})
        raise asyncio.CancelledError()
    async def run():
        async def receive():
            return {'type': 'http.disconnect'}
        async def send(message):
            pass
        with pytest.raises(asyncio.CancelledError):
            await obs.KnowledgeHTTPMiddleware(app)({'type': 'http', 'path': '/company-knowledge/chat', 'method': 'POST'}, receive, send)
        assert obs._current.get() is None
    asyncio.run(run())
    summary = records(logs)[0]
    assert summary['outcome'] == 'interrupted' and not summary['response_complete']


def test_log_failure_cannot_fail_business_request(logs, monkeypatch):
    logs.write_text('not-a-directory')
    app = FastAPI()
    app.add_middleware(obs.KnowledgeHTTPMiddleware)
    @app.get('/company-knowledge/status')
    def status():
        with obs.phase('synthetic'):
            return {'ok': True}
    response = TestClient(app).get('/company-knowledge/status')
    assert response.status_code == 200 and response.json() == {'ok': True}


def test_sql_execution_commit_and_rollback_are_distinct_and_redacted(logs):
    engine = create_engine('sqlite://')
    obs.instrument_engine(engine)
    obs.instrument_engine(engine)
    trace = obs.Trace()
    token = obs._current.set(trace)
    try:
        with Session(engine) as db:
            db.execute(text('select :secret'), {'secret': 'SQL-SECRET'})
            assert trace.stats['sql_calls'] == 1 and trace.stats['commits_confirmed'] == 0
            db.rollback()
            db.execute(text('select 2'))
            db.commit()
            with pytest.raises(Exception):
                db.execute(text('select * from nonexistent_table'))
            db.rollback()
        assert trace.stats['sql_calls'] == 3 and trace.stats['sql_errors'] == 1
        assert trace.stats['commits_confirmed'] == 1 and trace.stats['rollbacks_confirmed'] == 2
        assert trace.stats['sql_execution_ms'] >= 0
        output = json.dumps(records(logs, 'detail'))
        assert 'SQL-SECRET' not in output and 'select ' not in output and 'nonexistent_table' not in output
    finally:
        obs._current.reset(token)
        engine.dispose()


def test_async_thread_sql_context_is_preserved(logs, tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'thread.db'))
    obs.instrument_engine(engine)
    trace = obs.Trace()
    async def run():
        token = obs._current.set(trace)
        def query():
            with Session(engine) as db:
                db.execute(text('select 1'))
                db.commit()
        try:
            await asyncio.to_thread(query)
        finally:
            obs._current.reset(token)
    asyncio.run(run())
    assert trace.stats['sql_calls'] == 1 and trace.stats['commits_confirmed'] == 1
    engine.dispose()


def test_savepoint_release_does_not_count_as_outer_transaction_commit(logs):
    engine = create_engine('sqlite://')
    obs.instrument_engine(engine)
    trace = obs.Trace()
    token = obs._current.set(trace)
    try:
        with Session(engine) as db:
            db.execute(text('select 1'))
            nested = db.begin_nested()
            db.execute(text('select 2'))
            nested.commit()
            assert trace.stats['commits_confirmed'] == 0
            db.rollback()
            assert trace.stats['rollbacks_confirmed'] == 1
            db.execute(text('select 1'))
            nested = db.begin_nested()
            db.execute(text('select 2'))
            nested.rollback()
            assert trace.stats['rollbacks_confirmed'] == 1
            db.commit()
            assert trace.stats['commits_confirmed'] == 1
    finally:
        obs._current.reset(token)
        engine.dispose()


def test_upstream_retries_and_business_errors_are_recorded_without_secrets(logs):
    async def run():
        trace = obs.Trace()
        token = obs._current.set(trace)
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(503 if len(calls) == 1 else 200, json={'success': False, 'message': 'UPSTREAM SECRET'})
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                cfg = {'base_url': 'https://model.invalid', 'api_key': 'KEY SECRET', 'provider': 'test'}
                async with kb.model_response(client, cfg, {'stream': False, 'content': 'QUESTION SECRET'}) as response:
                    await response.aread()
                with pytest.raises(kb.KnowledgeError):
                    await kb.cloud_rpc(client, cfg, '/api/v1/chunklist', {'secret': 'BODY SECRET'})
            assert trace.stats['upstream_calls'] == 3
            assert trace.stats['upstream_errors'] == 2
            assert trace.stats['model_retry_attempts'] == 1
            assert trace.stats['upstream_statuses'] == {'503': 1, '200': 2}
            assert trace.stats['upstream_error_types'] == {'KnowledgeError': 1}
        finally:
            obs._current.reset(token)
    asyncio.run(run())
    events = records(logs, 'detail')
    upstream = [r for r in events if r['event'] == 'upstream']
    assert [r['http_status'] for r in upstream] == [503, 200, 200]
    assert [r['attempt'] for r in upstream[:2]] == [1, 2]
    assert all(r['response_headers_ms'] >= 0 for r in upstream[:2])
    assert upstream[-1]['error_type'] == 'KnowledgeError'
    assert 'SECRET' not in json.dumps(events)


@pytest.mark.parametrize('state', ['ready', 'failed', 'archived'])
def test_background_context_outlives_request_and_records_persisted_result(logs, monkeypatch, state):
    parent = obs.Trace()
    parent.active = False
    token = obs._current.set(parent)
    async def process(doc_id):
        obs.observe_checkpoint(state)
    monkeypatch.setattr(ingestion, '_process_document', process)
    try:
        asyncio.run(ingestion.process_document('PRIVATE DOCUMENT ID'))
        assert obs._current.get() is parent
    finally:
        obs._current.reset(token)
    summary = records(logs)[0]
    assert summary['request_id'] != parent.id and summary['parent_request_id'] == parent.id
    assert summary['persisted_state'] == state and summary['task_scope_ms'] >= 0
    assert 'PRIVATE DOCUMENT ID' not in json.dumps(summary)


def test_failed_checkpoint_never_records_ready(setup, logs):
    row = upload(setup).json()
    with obs.ingestion_trace(row['id']):
        with pytest.raises(kb.KnowledgeError):
            ingestion.checkpoint(row['id'], 'wrong-worker', state='ready')
    assert 'persisted_state' not in records(logs)[0]


def test_committed_checkpoint_records_actual_database_state(setup, logs):
    row = upload(setup).json()
    with setup.db() as db:
        db.get(CompanyDocument, row['id']).worker_id = 'actual-worker'
        db.commit()
    with obs.ingestion_trace(row['id']):
        ingestion.checkpoint(row['id'], 'actual-worker', state='failed', status_message='PRIVATE MESSAGE')
    with setup.db() as db:
        assert db.get(CompanyDocument, row['id']).state == 'failed'
    assert records(logs)[0]['persisted_state'] == 'failed'
    assert 'PRIVATE MESSAGE' not in json.dumps(records(logs) + records(logs, 'detail'))


def test_background_cancellation_is_preserved(logs, monkeypatch):
    async def cancelled(doc_id):
        raise asyncio.CancelledError()
    monkeypatch.setattr(ingestion, '_process_document', cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ingestion.process_document('test'))
    assert records(logs)[0]['error_type'] == 'CancelledError'


def test_retention_boundaries_and_unrelated_files_are_preserved(logs, monkeypatch):
    logs.mkdir()
    monkeypatch.setattr(obs, 'now', lambda: datetime(2026, 11, 12, tzinfo=timezone.utc))
    files = {'kb-detail-2026-11-05-99.jsonl': False, 'kb-detail-2026-11-06-99.jsonl': True,
             'kb-summary-2026-10-13-99.jsonl': False, 'kb-summary-2026-10-14-99.jsonl': True,
             'kb-summary-2026-99-99-99.jsonl': True, 'original.txt': True}
    for name in files:
        (logs / name).write_text('preserve')
    assert obs.write('detail', {'event': 'test'})
    for name, kept in files.items():
        assert (logs / name).exists() is kept
        if kept:
            assert (logs / name).read_text() == 'preserve'


def test_capacity_cap_drops_new_logs_without_overwriting(logs, monkeypatch):
    monkeypatch.setattr(obs, 'LIMITS', {'detail': (7, 150), 'summary': (30, 150)})
    assert obs.write('detail', {'event': 'first'})
    original = next(logs.glob('*.jsonl')).read_bytes()
    assert not obs.write('detail', {'event': 'x' * 200})
    assert next(logs.glob('*.jsonl')).read_bytes() == original


def test_parallel_append_produces_complete_json_records(logs):
    with ThreadPoolExecutor(max_workers=5) as pool:
        assert all(pool.map(lambda n: obs.write('detail', {'sequence': n}), range(100)))
    assert {r['sequence'] for r in records(logs, 'detail')} == set(range(100))


def test_partial_os_write_is_completed(logs, monkeypatch):
    original = obs.os.write
    monkeypatch.setattr(obs.os, 'write', lambda fd, payload: original(fd, payload[:7]))
    assert obs.write('detail', {'event': 'complete'})
    assert records(logs, 'detail')[0]['event'] == 'complete'
