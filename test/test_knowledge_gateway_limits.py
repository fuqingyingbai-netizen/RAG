"""Observed HTTP200 embedded account limit: no false answer, retry or secret leak."""
import asyncio
import json

import httpx
import pytest

import company_knowledge as kb
import company_memory as memory
from test_company_workspace import setup, ready, transport, upload


@pytest.mark.parametrize('error,status', [({'type': 'rate_limit_error'}, 429),
    ({'code': 429}, 429), ({'type': 'upstream_error'}, 502), ('private error', 502)])
def test_embedded_error_classification_does_not_copy_vendor_body(error, status):
    exception = kb.model_body_error(error)
    assert exception.status_code == status
    assert 'private' not in str(exception) and 'rate_limit_error' not in str(exception)


def test_streamed_http200_limit_emits_429_without_answer_or_retry(setup, monkeypatch):
    monkeypatch.setenv('COMPANY_KNOWLEDGE_MODEL', 'glm-5.3-flash')
    monkeypatch.setenv('COMPANY_KNOWLEDGE_BASE_URL', 'https://model.invalid/v1')
    monkeypatch.setenv('COMPANY_KNOWLEDGE_API_KEY', 'private-key')
    document_id = upload(setup).json()['id']
    ready(setup, document_id)
    calls = []
    def handler(request):
        if request.url.path.endswith('/retrieve'):
            return httpx.Response(200, json={'data': {'nodes': [
                {'metadata': {'doc_id': 'cloud-a', 'content': 'Evidence'}}]}})
        calls.append(request)
        return httpx.Response(200, text='data: '+json.dumps({'error': {'type': 'rate_limit_error',
            'message': 'Concurrency limit exceeded for account; private-key'}})+'\n\n')
    transport(monkeypatch, handler)
    response = setup.client.post('/company-knowledge/chat/stream',
                                 json={'message': 'What does the source say?', 'document_ids': [document_id]})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert response.status_code == 200 and events[-1]['type'] == 'error' and events[-1]['status_code'] == 429
    assert not any(x['type'] in ('answer_delta', 'saved', 'done') for x in events)
    assert len(calls) == 1 and 'private-key' not in response.text


def test_non_streamed_memory_call_preserves_http200_rate_limit(monkeypatch):
    async def config(*_):
        return {'model': 'glm-5.3-flash', 'base_url': 'https://model.invalid/v1',
                'api_key': 'private-key', 'provider': 'mock'}
    monkeypatch.setattr(kb, 'model_settings', config)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'error': {'type': 'rate_limit_error', 'message': 'private-key'}})
    transport(monkeypatch, handler)
    with pytest.raises(kb.KnowledgeError) as caught:
        asyncio.run(memory.complete({}, 'summarize synthetic task', {'task': 'test'}))
    assert caught.value.status_code == 429 and len(calls) == 1
    assert 'private-key' not in str(caught.value)
