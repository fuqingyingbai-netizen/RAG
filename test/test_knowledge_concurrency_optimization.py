"""Pool lifecycle, admission and streaming regressions with isolated synthetic data."""
import asyncio
import anyio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.orm import sessionmaker

import auth
import company_capacity as capacity
import company_chat_task as task
import company_knowledge as kb
import company_memory as memory
import company_observability as obs
from models import User
from test_company_workspace import setup, project, upload
from test_company_memory import env, create


def test_knowledge_auth_returns_its_only_connection_before_streaming(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path / 'auth.db'), pool_size=1, max_overflow=0, pool_timeout=.1,
                           connect_args={'check_same_thread': False})
    User.__table__.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(auth, 'SessionLocal', factory)
    with factory() as db:
        db.add(User(username='alice', password_hash='synthetic'))
        db.commit()
    app = FastAPI()
    @app.get('/stream')
    async def stream(user=Depends(auth.get_knowledge_current_user)):
        assert inspect(user).detached
        assert engine.pool.checkedout() == 0
        async def events():
            for _ in range(3):
                with factory() as db:
                    assert db.scalar(text('SELECT 1')) == 1
                yield user.username
                await asyncio.sleep(0)
        return StreamingResponse(events())
    client = TestClient(app)
    token = auth.create_access_token('alice', 'user')
    try:
        assert client.get('/stream', headers={'Authorization': 'Bearer ' + token}).text == 'alice' * 3
        for change in ({'is_active': False}, {'archived_at': __import__('datetime').datetime.utcnow()},
                       {'token_version': 1}, {'must_change_password': True}):
            with factory() as db:
                user = db.query(User).one()
                user.is_active, user.archived_at, user.token_version, user.must_change_password = True, None, 0, False
                for key, value in change.items():
                    setattr(user, key, value)
                db.commit()
            response = client.get('/stream', headers={'Authorization': 'Bearer ' + token})
            assert response.status_code == (403 if 'must_change_password' in change else 401)
            assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


def test_bounded_queue_cancellation_timeout_and_failure_return_all_permits():
    async def run():
        gate = capacity.Capacity(1, queue=1)
        async with gate.slot('model'):
            async def blocked():
                async with gate.slot('model', wait=.2):
                    pytest.fail('must remain queued')
            waiting = asyncio.create_task(blocked())
            await asyncio.sleep(.01)
            with pytest.raises(capacity.CapacityBusy):
                async with gate.slot('model', wait=.2):
                    pass
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            assert gate.active == 1 and gate.waiting == 0
            with pytest.raises(capacity.CapacityBusy):
                async with gate.slot('model', wait=.01):
                    pass
            assert gate.waiting == 0
        with pytest.raises(ValueError):
            async with gate.slot('model'):
                raise ValueError('synthetic failure')
        assert gate.active == gate.waiting == 0
    asyncio.run(run())


def test_ten_model_requests_are_limited_and_waiting_is_visible(monkeypatch):
    async def run():
        gate = capacity.Capacity(3, queue=7)
        monkeypatch.setattr(kb, 'model_slots', gate)
        active, maximum, attempts, notifications = 0, 0, 0, []
        async def report(event):
            notifications.append(event)
        async def transport(request):
            nonlocal active, maximum, attempts
            attempts += 1
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(.05)
            active -= 1
            return httpx.Response(200, json={'ok': True})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            async def call():
                async with kb.model_response(client, {'base_url': 'https://model.invalid', 'api_key': 'synthetic',
                                                     'provider': 'mock'}, {'stream': True}) as response:
                    await response.aread()
            token = capacity.waiting_reporter.set(report)
            try:
                await asyncio.gather(*(call() for _ in range(10)))
            finally:
                capacity.waiting_reporter.reset(token)
        assert maximum == 3 and attempts == 10 and len(notifications) == 14
        assert sum(bool(row.get('finished')) for row in notifications) == 7
        assert all(row['stage'] == 'queued' for row in notifications)
        assert gate.active == gate.waiting == 0
    asyncio.run(run())


def test_busy_upload_is_rejected_before_reading_body_and_browse_still_works(monkeypatch):
    async def run():
        gate = capacity.Capacity(1)
        monkeypatch.setattr(capacity, 'upload_slots', gate)
        app = FastAPI()
        app.add_middleware(capacity.KnowledgeCapacityMiddleware)
        @app.get('/company-knowledge/projects')
        def browse():
            return {'projects': []}
        consumed = False
        async def receive():
            nonlocal consumed
            consumed = True
            raise AssertionError('rejected upload body must not be read')
        sent = []
        async def send(message):
            sent.append(message)
        async with gate.slot('upload'):
            await app({'type': 'http', 'path': '/company-knowledge/uploads', 'method': 'POST',
                       'headers': [], 'query_string': b''}, receive, send)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
                assert (await client.get('/company-knowledge/projects')).status_code == 200
        assert not consumed and sent[0]['status'] == 503
        assert (b'retry-after', b'2') in sent[0]['headers']
        assert gate.active == 0
    asyncio.run(run())


@pytest.mark.parametrize('path', ['/company-knowledge/projects', '/company-knowledge/conversations',
                                 '/company-knowledge/documents'])
def test_pool_exhaustion_has_consistent_retryable_response(path):
    app = FastAPI()
    app.add_middleware(capacity.KnowledgeCapacityMiddleware)
    @app.get(path)
    def exhausted():
        raise PoolTimeout('must not disclose pool configuration')
    response = TestClient(app).get(path)
    assert response.status_code == 503 and response.headers['retry-after'] == '2'
    assert 'pool' not in response.text


def test_busy_during_sse_is_an_error_without_done_or_retry(monkeypatch):
    async def answer(*_):
        yield {'type': 'answer_delta', 'text': 'partial'}
        raise capacity.CapacityBusy()
    monkeypatch.setattr(kb, 'cloud_answer', answer)
    async def run():
        events = [event async for event in kb.stream_events({}, None)]
        assert [e['type'] for e in events] == ['progress', 'answer_delta', 'error']
        assert events[-1]['status_code'] == 503 and events[-1]['retry_after'] == 2
    asyncio.run(run())


def test_browsing_and_selected_scope_do_not_repeat_legacy_backfill(setup, monkeypatch):
    import company_projects as projects
    import company_workspace as ws
    p = project(setup)
    row = upload(setup, project_id=p['id']).json()
    def forbidden(*args):
        raise AssertionError('legacy migration is not a request operation')
    monkeypatch.setattr(projects, 'backfill_company_projects', forbidden)
    monkeypatch.setattr(ws, 'backfill_company_projects', forbidden)
    assert setup.client.get('/company-knowledge/projects').status_code == 200
    with setup.db() as db:
        doc = db.get(__import__('company_catalog').CompanyDocument, row['id'])
        doc.state, doc.cloud_id = 'ready', 'cloud'
        db.commit()
    cfg = {'index_id': 'test-index'}
    assert 'cloud' in asyncio.run(ws.prepare_scope(cfg, setup.user, [row['id']]))


def test_literal_project_followup_skips_model_without_losing_year(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError('literal subject and field need no rewrite model')
    monkeypatch.setattr(memory, 'complete', forbidden)
    state = task.fresh('海岚项目2025年的批准预算是多少？')
    context = {'task': state, 'recent': [], 'summary': ''}
    query = asyncio.run(memory.retrieval_question({}, '客户数量呢？', context))
    assert query == '海岚项目的客户数量？；2025年'
    assert not task.fresh('海岚项目和北星项目的预算是多少？')['structured']
    assert not task.fresh('这个项目的预算是多少？')['structured']
    state = task.fresh('海岚合成项目2025年度试验预算是多少万元？保留预算口径并引用，仅用两句话回答，800字以内。')
    query = asyncio.run(memory.retrieval_question({}, '它的负责人是谁？仅回答姓名并引用。',
                                                 {'task': state, 'recent': [], 'summary': ''}))
    assert '海岚合成项目' in query and '负责人是谁' in query and '2025年度' in query
    assert '仅回答姓名并引用' in query and '800字以内' in query


def test_first_answer_and_connection_hold_are_logged_without_content(tmp_path):
    engine = create_engine('sqlite://')
    obs.instrument_engine(engine)
    trace = obs.Trace()
    token = obs._current.set(trace)
    try:
        with engine.connect() as connection:
            connection.execute(text('SELECT 1'))
        obs.observe_sse({'type': 'answer_delta', 'text': 'PRIVATE'})
        first = trace.stats['first_answer_delta_ms']
        obs.observe_sse({'type': 'answer_delta', 'text': 'PRIVATE'})
        assert trace.stats['first_answer_delta_ms'] == first
        assert trace.stats['db_checkouts'] == 1 and trace.stats['db_connection_hold_ms'] > 0
    finally:
        obs._current.reset(token)
        engine.dispose()


def test_disconnect_releases_model_slot_and_marks_turn_interrupted(env, monkeypatch):
    import company_workspace as ws
    gate = capacity.Capacity(1)
    async def interrupted(*args):
        async with gate.slot('model'):
            yield {'type': 'answer_delta', 'text': 'partial answer'}
            await asyncio.Event().wait()
    monkeypatch.setattr(ws, 'grounded_answer', interrupted)
    session_id = create(env)
    cfg = kb.settings()
    cfg['allowed_documents'] = {'cloud-a': {'id': 'doc-a'}}
    question = kb.KnowledgeQuestion(message='明确问题', document_ids=['doc-a'], session_id=session_id, request_id='cancelled')
    token, plan, deps = memory.begin_turn(env.user, cfg, session_id, question.request_id, question.message)
    cfg['_conversation'] = (env.user, cfg, question, token, plan, deps)
    async def run():
        stream = kb.stream_events(cfg, question)
        async for event in stream:
            if event['type'] == 'answer_delta':
                assert gate.active == 1
                break
        await stream.aclose()
        assert gate.active == gate.waiting == 0
    asyncio.run(run())
    with env.db() as db:
        assert not db.get(memory.KnowledgeChatThread, session_id).busy_token
        assert {row.status for row in db.query(memory.KnowledgeChatMessage)} == {'interrupted'}


def test_rewrite_queue_rejection_does_not_revive_a_previous_subject(env, monkeypatch):
    session_id = create(env)
    cfg = kb.settings()
    cfg['allowed_documents'] = {'cloud-a': {'id': 'doc-a'}}
    question = kb.KnowledgeQuestion(message='那新公司呢？', document_ids=['doc-a'], session_id=session_id, request_id='queue-rejected')
    token, plan, deps = memory.begin_turn(env.user, cfg, session_id, question.request_id, question.message)
    plan['task'] = task.fresh('甲公司的客户数是多少？')
    async def rejected(*args):
        raise capacity.CapacityBusy('synthetic queue full')
    monkeypatch.setattr(memory, 'retrieval_question', rejected)
    cfg['_conversation'] = (env.user, cfg, question, token, plan, deps)
    async def run():
        return [event async for event in kb.stream_events(cfg, question)]
    events = asyncio.run(run())
    assert events[-1]['type'] == 'error' and events[-1]['status_code'] == 503
    with env.db() as db:
        state = db.get(memory.KnowledgeChatTask, session_id).state
        assert state['rewrite_failed'] and state['needs_clarification']
        assert state['unresolved_question'] == question.message
        assert task.local_followup('它的客户数呢？', state)[1] is None


def test_starlette_cancel_scope_cannot_skip_interrupted_turn_cleanup(env, monkeypatch):
    import company_workspace as ws
    async def answer(*args):
        yield {'type': 'answer_delta', 'text': 'partial'}
        await anyio.sleep_forever()
    monkeypatch.setattr(ws, 'grounded_answer', answer)
    session_id = create(env)
    cfg = kb.settings()
    cfg['allowed_documents'] = {'cloud-a': {'id': 'doc-a'}}
    question = kb.KnowledgeQuestion(message='明确问题', document_ids=['doc-a'], session_id=session_id, request_id='scope-cancelled')
    token, plan, deps = memory.begin_turn(env.user, cfg, session_id, question.request_id, question.message)
    async def run():
        with anyio.CancelScope() as scope:
            async for event in memory.conversation_stream(env.user, cfg, question, token, plan, deps):
                if event['type'] == 'answer_delta':
                    scope.cancel()
        with env.db() as db:
            assert not db.get(memory.KnowledgeChatThread, session_id).busy_token
            assert {row.status for row in db.query(memory.KnowledgeChatMessage)} == {'interrupted'}
    anyio.run(run)


def test_failed_asgi_send_explicitly_closes_the_suspended_body_iterator():
    from starlette.requests import ClientDisconnect
    async def run():
        closed = False
        async def body():
            nonlocal closed
            try:
                yield b'partial'
                await asyncio.Event().wait()
            finally:
                closed = True
        async def receive():
            return {'type': 'http.disconnect'}
        async def send(message):
            if message['type'] == 'http.response.body':
                raise OSError('synthetic closed TCP connection')
        response = kb.KnowledgeStreamingResponse(body(), media_type='text/event-stream')
        with pytest.raises(ClientDisconnect):
            await response({'type': 'http', 'asgi': {'spec_version': '2.4'}}, receive, send)
        assert closed
    asyncio.run(run())
