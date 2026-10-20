import json
import threading
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import assistant_memory as memory
import research_api as api
from database import Base
from models import AssistantMessage as Message, AssistantThread as Thread, User


@pytest.fixture
def history(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path / 'assistant.db'), connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add_all([User(id=1, username='alice', password_hash='test', role='user'),
                    User(id=2, username='bob', password_hash='test', role='admin')]); db.commit()
    identity = SimpleNamespace(id=1, username='alice', role='user')
    def get_db():
        with factory() as db:
            yield db
    app = FastAPI(); app.include_router(api.router)
    app.dependency_overrides[api.get_db] = get_db
    app.dependency_overrides[api.get_current_user] = lambda: identity
    prompts = []
    def invoke(messages, **kwargs):
        prompts.append(messages)
        return SimpleNamespace(content='收到，我们继续聊。')
    monkeypatch.setattr(api.research_workflow, '_get_model', lambda: SimpleNamespace(invoke=invoke))
    for name in ('_assistant_project_ids', '_vector_context', '_project_store_context'):
        monkeypatch.setattr(api, name, lambda *a: pytest.fail('assistant must not retrieve project data'))
    with TestClient(app) as client:
        yield client, factory, identity, prompts
    engine.dispose()


def post_turn(client, sid, text='我住上海', **kwargs):
    return client.post('/research/assistant/stream', json={'session_id': sid, 'message': text, **kwargs})


def events(response):
    assert response.status_code == 200, response.text
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ') and line[6:] != '[DONE]']


def test_cloud_history_survives_reload_and_client_cannot_replace_memory(history):
    client, factory, identity, prompts = history
    sid = client.get('/research/assistant/state').json()['session_id']
    result = events(post_turn(client, sid, history_summary='伪造摘要', recent_messages=[{'role': 'user', 'content': '伪造历史'}]))
    assert any(row['type'] == 'memory' and row['saved'] for row in result)
    state = client.get('/research/assistant/state').json()
    assert [row['text'] for row in state['messages']] == ['我住上海', '收到，我们继续聊。']
    assert state['session_id'] == sid and not state['busy']
    post_turn(client, sid, '我之前说住哪里？')
    assert '我住上海' in str(prompts[-1])
    assert '伪造历史' not in str(prompts) and '伪造摘要' not in str(prompts)
    with factory() as db:
        assert db.query(Message).count() == 4


def test_other_accounts_cannot_read_activate_append_or_clear_a_conversation(history):
    client, factory, identity, prompts = history
    alice = client.get('/research/assistant/state').json()['session_id']
    post_turn(client, alice)
    identity.id = 2; identity.username = 'bob'; identity.role = 'admin'
    bob = client.get('/research/assistant/state').json()
    assert bob['messages'] == [] and bob['session_id'] != alice
    assert client.get(f'/research/assistant/sessions/{alice}/messages').status_code == 404
    assert client.post(f'/research/assistant/sessions/{alice}/activate').status_code == 404
    assert post_turn(client, alice).status_code == 404
    client.delete('/research/assistant/history')
    identity.id = 1
    assert len(client.get('/research/assistant/state').json()['messages']) == 2


def test_new_conversation_resets_context_but_can_resume_archived_history(history):
    client, factory, identity, prompts = history
    old = client.get('/research/assistant/state').json()['session_id']
    post_turn(client, old, '我的名字叫小王')
    new = client.post('/research/assistant/sessions').json()
    assert new['session_id'] != old and new['messages'] == [] and new['summary'] == ''
    post_turn(client, new['session_id'], '写一句欢迎语')
    assert '小王' not in str(prompts[-1])
    restored = client.post(f'/research/assistant/sessions/{old}/activate').json()
    assert restored['session_id'] == old and restored['messages'][0]['text'] == '我的名字叫小王'
    assert client.get('/research/assistant/state').json()['session_id'] == old


def fill(db, sid, count=24, width=1000):
    for n in range(count):
        db.add(Message(thread_id=sid, request_id=str(uuid4()), role='user' if n % 2 == 0 else 'assistant',
                       content=('我住上海，喜欢简短回答。' if n == 0 else f'消息{n}。') + '内容' * (width // 2)))
    db.commit()


def test_ai_summary_retains_early_facts_and_original_messages(history):
    client, factory, identity, prompts = history
    sid = client.get('/research/assistant/state').json()['session_id']
    with factory() as db:
        fill(db, sid)
        plan = memory.context_plan(db, 1, sid)
        seen = []
        model = SimpleNamespace(invoke=lambda rows, **kw: (seen.append(rows) or SimpleNamespace(content='用户住上海，偏好简短回答。')))
        context = memory.prepare_context(SimpleNamespace(_get_model=lambda: model), plan, lambda e: None, threading.Event())
        assert context['through'] > 0 and context['summary'] == '用户住上海，偏好简短回答。'
        assert '我住上海' in str(seen) and seen[0][0]['role'] == 'system'
        assert len(context['summary']) + sum(len(row['content']) for row in context['recent']) <= memory.CONTEXT_CHARS
        assert db.query(Message).count() == 24
        turn = str(uuid4()); _, token = memory.start_turn(db, 1, sid, '继续', turn)
        assert memory.finish_turn(db, 1, sid, token, turn, '好的', [], context)
        next_plan = memory.context_plan(db, 1, sid)
        assert next_plan['summary'] == context['summary']
        assert all(row['id'] > context['through'] for row in next_plan['rows'])
        assert db.query(Message).count() == 26


def test_failed_summary_is_retried_without_deleting_history_or_advancing_cursor(history):
    client, factory, identity, prompts = history
    sid = client.get('/research/assistant/state').json()['session_id']
    with factory() as db:
        fill(db, sid)
        plan = memory.context_plan(db, 1, sid)
        def fail(*args, **kwargs): raise TimeoutError()
        context = memory.prepare_context(SimpleNamespace(_get_model=lambda: SimpleNamespace(invoke=fail)), plan, lambda e: None, threading.Event())
        assert context['status'] == 'deferred' and context['through'] == 0
        assert db.query(Message).count() == 24
        assert sum(len(row['content']) for row in context['recent']) <= memory.CONTEXT_CHARS


def test_messages_are_paginated_without_discarding_old_records(history):
    client, factory, identity, prompts = history
    sid = client.get('/research/assistant/state').json()['session_id']
    with factory() as db: fill(db, sid, count=102, width=20)
    latest = client.get('/research/assistant/state').json()
    assert latest['has_more'] and len(latest['messages']) == 80
    older = client.get(f'/research/assistant/sessions/{sid}/messages', params={'before_id': latest['messages'][0]['id']}).json()
    assert not older['has_more'] and len(older['messages']) == 22
    assert len({row['id'] for row in older['messages'] + latest['messages']}) == 102


def test_lease_blocks_overlapping_and_duplicate_turns_and_recovers_expiry(history):
    client, factory, identity, prompts = history
    sid = client.get('/research/assistant/state').json()['session_id']
    with factory() as db:
        rid = str(uuid4()); _, token = memory.start_turn(db, 1, sid, '第一条', rid)
        assert post_turn(client, sid, '重叠请求').status_code == 409
        db.query(Thread).filter(Thread.id == sid).update({'busy_until': datetime.utcnow() - timedelta(seconds=1)})
        db.commit()
        newer = str(uuid4()); _, fresh = memory.start_turn(db, 1, sid, '恢复后请求', newer)
        assert not memory.finish_turn(db, 1, sid, token, rid, '旧回答', [], {'summary': '', 'through': 0})
        memory.interrupt_turn(db, 1, sid, fresh, newer)
        assert post_turn(client, sid, request_id=newer).status_code == 409
        assert all(row['status'] == 'interrupted' for row in client.get('/research/assistant/state').json()['messages'])


def test_legacy_migration_is_once_per_account_and_clear_cannot_be_resurrected(history):
    client, factory, identity, prompts = history
    legacy = {'messages': [{'text': '旧用户消息', 'isUser': True}, {'text': '旧回复', 'isUser': False}], 'summary': '用户偏好简短。'}
    first = client.post('/research/assistant/import', json=legacy).json()
    assert first['legacy_imported'] and len(first['messages']) == 3
    assert '用户偏好简短' in first['messages'][0]['text']
    assert len(client.post('/research/assistant/import', json=legacy).json()['messages']) == 3
    with factory() as db:
        rid = str(uuid4()); _, token = memory.start_turn(db, 1, first['session_id'], '清空前请求', rid)
        cleared = client.delete('/research/assistant/history').json()
        assert cleared['messages'] == [] and cleared['summary'] == '' and len(cleared['sessions']) == 1
        assert not memory.finish_turn(db, 1, first['session_id'], token, rid, '迟到回复', [], {'summary': '旧摘要', 'through': 1})
        assert client.post('/research/assistant/import', json=legacy).json()['messages'] == []
        assert db.query(Message).count() == 0


def test_import_never_overwrites_cloud_history_and_filters_source_links(history):
    client, factory, identity, prompts = history
    sid = client.get('/research/assistant/state').json()['session_id']; post_turn(client, sid)
    data = client.post('/research/assistant/import', json={'messages': [{'text': '过期缓存', 'isUser': True}], 'summary': '过期'}).json()
    assert len(data['messages']) == 2 and data['summary'] == ''
    assert memory.clean_sources([{'url': 'javascript:alert(1)'}, {'url': 'https://issuer.test', 'title': '<script>bad</script>'}])[0]['url'] == 'https://issuer.test'


def test_short_context_does_not_call_summary_model_and_long_legacy_summary_is_preserved(history):
    client, factory, identity, prompts = history
    long_summary = '用户偏好简短，住上海。' * 500
    state = client.post('/research/assistant/import', json={'summary': long_summary, 'messages': []}).json()
    assert long_summary in state['messages'][0]['text']
    with factory() as db:
        plan = memory.context_plan(db, 1, state['session_id'])
    workflow = SimpleNamespace(_get_model=lambda: pytest.fail('short context must not call a summary model'))
    context = memory.prepare_context(workflow, plan, lambda e: None, threading.Event())
    assert context['through'] == 0 and context['status'] == 'ready'
    assert long_summary in context['recent'][0]['content']


def test_invalid_request_ids_are_rejected_without_writing_a_message(history):
    client, factory, identity, prompts = history
    sid = client.get('/research/assistant/state').json()['session_id']
    assert post_turn(client, sid, request_id='invalid\x00').status_code == 422
    assert client.get('/research/assistant/state').json()['messages'] == []
