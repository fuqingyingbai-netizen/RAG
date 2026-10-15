import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import company_knowledge as kb


@pytest.fixture
def client(monkeypatch):
    for key, value in {'API_KEY': 'test-secret', 'BASE_URL': 'https://test.cn-beijing.maas.aliyuncs.com',
                       'AGENT_ID': 'aid-test', 'INDEX_ID': 'test-index'}.items():
        monkeypatch.setenv('BAILIAN_KNOWLEDGE_' + key, value)
    monkeypatch.setenv('COMPANY_KNOWLEDGE_USERS', '')
    app = FastAPI()
    app.include_router(kb.router)
    return TestClient(app)


def log_in(client, role='admin', username='admin'):
    client.app.dependency_overrides[kb.get_current_user] = lambda: SimpleNamespace(role=role, username=username)


def test_anonymous_and_newly_registered_accounts_cannot_read_company_data(client):
    assert client.get('/company-knowledge/documents').status_code == 401
    assert client.post('/company-knowledge/chat/stream', json={'message': 'test'}).status_code == 401
    log_in(client, 'user', 'new-user')
    assert client.get('/company-knowledge/status').json()['access_allowed'] is False
    assert client.get('/company-knowledge/documents').status_code == 403
    assert client.post('/company-knowledge/chat/stream', json={'message': 'test'}).status_code == 403


def test_explicitly_allowed_employee_can_access_without_receiving_secret(client, monkeypatch):
    log_in(client, 'user', 'employee')
    monkeypatch.setenv('COMPANY_KNOWLEDGE_USERS', 'employee, another')
    response = client.get('/company-knowledge/status')
    assert response.status_code == 200 and response.json()['access_allowed']
    assert 'test-secret' not in response.text and 'api_key' not in response.text


@pytest.mark.parametrize('url', ['http://test.cn-beijing.maas.aliyuncs.com', 'https://example.com',
                                  'https://test.cn-beijing.maas.aliyuncs.com:bad'])
def test_credentials_are_not_sent_to_an_unapproved_or_invalid_endpoint(client, monkeypatch, url):
    monkeypatch.setenv('BAILIAN_KNOWLEDGE_BASE_URL', url)
    with pytest.raises(kb.KnowledgeError):
        kb.settings()


def test_planning_text_is_not_mixed_into_answer_and_citations_are_safe():
    def frame(step, content, **kwargs):
        return {'output': {'choices': [{'message': {'extra': {'step': step}, 'content': content, **kwargs}}]}}
    assert list(kb.frame_events(frame('planning', 'private planning'))) == []
    assert list(kb.frame_events(frame('generating', 'answer'))) == [{'type': 'answer_delta', 'text': 'answer'}]
    reference = kb.citation({'_citation_index': 2, 'doc_id': 'file-test', 'content': 'Evidence',
                             'doc_url': 'javascript:alert(1)', 'page_number': [0, 1]})
    assert reference['url'] == '' and reference['text'] == 'Evidence' and reference['id'] == '2'


def test_sse_parser_handles_comments_multiline_and_final_unterminated_record():
    async def lines():
        for line in [': heartbeat', 'data: {', 'data: "code": "200"}', '', 'data: {"code":"Success"}']:
            yield line
    async def run():
        return [frame async for frame in kb.sse_frames(lines())]
    assert asyncio.run(run()) == [{'code': '200'}, {'code': 'Success'}]


def test_real_document_schema_and_pagination(monkeypatch, client):
    cfg = kb.settings()
    original = httpx.AsyncClient
    def handler(request):
        assert request.url.params['index_id'] == 'test-index'
        assert request.url.params['page_number'] == '2'
        return httpx.Response(200, json={'success': True, 'code': 'Success', 'data': {'total_count': 101, 'rows': [
            {'doc_id': 'file-test', 'doc_name': 'Test.pdf', 'doc_type': 'pdf', 'status': 'FINISH'}]}})
    monkeypatch.setattr(kb.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    result = asyncio.run(kb.list_cloud_documents(cfg, 2))
    assert result['total_count'] == 101 and result['documents'][0]['format'] == 'PDF'


def test_upstream_auth_error_is_reported_without_leaking_headers(client, monkeypatch):
    log_in(client)
    original = httpx.AsyncClient
    monkeypatch.setattr(kb.httpx, 'AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(lambda request: httpx.Response(401, json={'secret': 'test-secret'})), **kwargs))
    response = client.post('/company-knowledge/chat/stream', json={'message': 'test'})
    assert '"type": "error"' in response.text and 'test-secret' not in response.text


def test_successful_stream_and_interrupted_stream_are_distinguished(client, monkeypatch):
    log_in(client)
    original = httpx.AsyncClient
    def frame(text, change=''):
        return {'code': '200', 'output': {'choices': [{'message': {'content': text,
                'extra': {'step': 'generating', 'step_change': change}}}]}}
    stream = ''.join('data: ' + json.dumps(value) + '\n\n' for value in [frame('Answer'), frame('', 'generation_end')])
    monkeypatch.setattr(kb.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text=stream, headers={'content-type': 'text/event-stream'})), **kwargs))
    response = client.post('/company-knowledge/chat/stream', json={'message': 'test'})
    assert '"type": "answer_delta"' in response.text and '"type": "done"' in response.text
    stream = 'data: ' + json.dumps(frame('Partial answer')) + '\n\n'
    response = client.post('/company-knowledge/chat/stream', json={'message': 'test'})
    assert '"type": "error"' in response.text and '"type": "done"' not in response.text


def test_empty_question_rejected_before_upstream_call(client):
    log_in(client)
    assert client.post('/company-knowledge/chat/stream', json={'message': '   '}).status_code == 422


def test_progress_reports_real_tool_query_and_distinct_document_count():
    def frame(change, **message):
        return {'output': {'choices': [{'message': {'extra': {'step': 'tool_calling', 'step_change': change}, **message}}]}}
    started = list(kb.frame_events(frame('tool_calling', tool_calls=[{'function': {
        'name': 'semantic_search', 'arguments': json.dumps({'query': '业务资料'})}}])))
    assert started[-1]['stage'] == 'retrieving' and '业务资料' in started[-1]['detail']
    returned = list(kb.frame_events(frame('tool_return', additional_kwargs={'extra_json': {'docs': [
        {'doc_id': 'a', '_citation_index': 1}, {'doc_id': 'a', '_citation_index': 2},
        {'doc_id': 'b', '_citation_index': 3}]}})))
    assert returned[0]['detail'] == '本次命中 2 份文件、3 个片段。'
    assert len(returned[1]['citations']) == 3


def test_planning_progress_is_a_summary_without_raw_reasoning():
    value = {'output': {'choices': [{'message': {'extra': {'step': 'planning', 'step_change': 'plan_start'},
                                              'content': 'private internal reasoning'}}]}}
    events = list(kb.frame_events(value))
    assert events[0]['stage'] == 'organizing'
    assert 'private internal reasoning' not in json.dumps(events)


def test_quiet_upstream_gets_heartbeat_and_stops_after_completion(monkeypatch):
    async def run():
        release = asyncio.Event()
        async def cloud(cfg, question):
            await release.wait()
            yield {'type': 'answer_delta', 'text': 'answer'}
            yield {'type': 'done'}
        monkeypatch.setattr(kb, 'cloud_answer', cloud)
        events = kb.stream_events({}, None, heartbeat_interval=.01)
        assert (await anext(events))['stage'] == 'connecting'
        assert (await anext(events))['type'] == 'heartbeat'
        release.set()
        tail = [value async for value in events]
        assert [value['type'] for value in tail if value['type'] != 'heartbeat'] == ['answer_delta', 'done']
        assert tail[-1]['type'] == 'done'
    asyncio.run(run())


def test_closing_stream_cancels_the_upstream_worker(monkeypatch):
    async def run():
        cancelled = asyncio.Event()
        async def cloud(cfg, question):
            try:
                await asyncio.Event().wait()
                yield {'type': 'done'}
            finally:
                cancelled.set()
        monkeypatch.setattr(kb, 'cloud_answer', cloud)
        events = kb.stream_events({}, None, heartbeat_interval=.01)
        await anext(events)
        await anext(events)
        await events.aclose()
        assert cancelled.is_set()
    asyncio.run(run())
