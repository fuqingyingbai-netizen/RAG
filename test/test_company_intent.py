import asyncio
from copy import deepcopy
import json

import pytest

import company_knowledge as kb
import company_memory as memory
import company_intent as intent
import company_observability as obs
from company_chat_task import fresh
from company_catalog import CompanyDocument
from test_company_memory import env, create, call, upstream


def context(question='甲公司的收入是多少？'):
    return {'summary': '', 'recent': [], 'task': fresh(question)}


@pytest.mark.parametrize('question,expected', [
    ('你好？', 'smalltalk'), ('在吗', 'smalltalk'), ('谢谢你！', 'smalltalk'),
    ('早上好，谢谢你！', 'smalltalk'), ('Thank you!', 'smalltalk'), ('聊聊天', 'smalltalk'),
    ('怎么上传文件？', 'assistant'), ('我该怎么修改密码？', 'assistant'),
    ('这个页面上传按钮在哪里？', 'assistant'), ('文件上传失败了，我该去哪里重试？', 'assistant'),
    ('你好，帮我查A项目预算。', 'knowledge'), ('谢谢，乙公司的收入是多少？', 'knowledge'),
    ('甲公司的收入是多少？', 'knowledge'),
    ('Summarize', 'knowledge'),
    ('整理成表格', 'transform'), ('它怎么收费？', 'knowledge'),
])
def test_fast_routes_do_not_call_model_or_replace_business_state(monkeypatch, question, expected):
    async def fail(*args, **kwargs):
        pytest.fail('explicit route should not call a model')
    monkeypatch.setattr(memory, 'complete', fail)
    ctx = context()
    before = deepcopy(ctx)
    cfg = {}
    # A document-scoped procedural question is business evidence, not a system guide request.
    cfg['explicit_document_scope'] = True
    route = asyncio.run(memory.route_question(cfg, question, ctx))
    assert route['intent'] == expected
    assert ctx == before
    if expected in {'smalltalk', 'assistant'}:
        assert '_task_update' not in cfg and route['query'] is None


def test_procedural_question_in_documents_stays_evidence_bound(monkeypatch):
    async def complete(*args, **kwargs):
        return '{"intent":"knowledge","query":"根据资料回答：怎么上传文件？"}'
    monkeypatch.setattr(memory, 'complete', complete)
    route = asyncio.run(memory.route_question({}, '根据资料回答：怎么上传文件？', context()))
    assert route['intent'] == 'knowledge' and route['query']


def test_complex_social_turn_is_classified_once_without_updating_business_task(monkeypatch):
    calls = []
    async def complete(cfg, instruction, data, **kwargs):
        calls.append(data)
        assert 'intent' in instruction and kwargs['json_output']
        return '{"intent":"smalltalk","query":null}'
    monkeypatch.setattr(memory, 'complete', complete)
    cfg = {}
    route = asyncio.run(memory.route_question(cfg, '最近工作压力好大，想放松一下。', context()))
    assert route['intent'] == 'smalltalk' and len(calls) == 1
    assert '_task_update' not in cfg


def test_model_routing_and_followup_rewriting_share_one_request(monkeypatch):
    calls = []
    async def complete(cfg, instruction, data, **kwargs):
        calls.append(data)
        return '{"intent":"knowledge","query":"乙公司的收入是多少？","subjects":["乙公司"],"topic":"收入"}'
    monkeypatch.setattr(memory, 'complete', complete)
    cfg = {}
    route = asyncio.run(memory.route_question(cfg, '那乙公司呢？', context()))
    assert len(calls) == 1 and '乙公司' in route['query']
    assert cfg['_task_update']['subjects'] == ['乙公司']


@pytest.mark.parametrize('bad', [
    {'intent': 'smalltalk', 'query': None}, {'intent': 'unrestricted', 'query': '乙公司的收入'},
    {'intent': 'knowledge', 'query': None}, {'intent': [], 'query': '乙公司的收入'},
])
def test_invalid_or_business_suppressing_route_gets_one_schema_repair(monkeypatch, bad):
    calls = []
    async def complete(*args, **kwargs):
        calls.append(args)
        return json.dumps(bad if len(calls) == 1 else {'intent': 'knowledge', 'query': '乙公司的收入是多少？'})
    monkeypatch.setattr(memory, 'complete', complete)
    route = asyncio.run(memory.route_question({}, '那乙公司呢？', context()))
    assert route['intent'] == 'knowledge' and len(calls) == 2


def test_provider_failure_falls_back_only_for_independent_query(monkeypatch):
    calls = []
    async def fail(*args, **kwargs):
        calls.append(1)
        raise kb.KnowledgeError('synthetic 429', 429)
    monkeypatch.setattr(memory, 'complete', fail)
    cfg = {}
    question = '说说量子纠缠的定义。'
    route = asyncio.run(memory.route_question(cfg, question, context()))
    assert route == {'intent': 'knowledge', 'query': question} and len(calls) == 1
    with pytest.raises(kb.KnowledgeError):
        asyncio.run(memory.route_question({}, '那乙公司呢？', context()))
    assert len(calls) == 2


@pytest.mark.parametrize('question', ['它的客户数量是多少？', '它怎么收费？', '那它的风险呢？'])
def test_parallel_objects_still_require_clarification_without_model(monkeypatch, question):
    async def fail(*args, **kwargs):
        pytest.fail('ambiguity is locally resolved')
    monkeypatch.setattr(memory, 'complete', fail)
    route = asyncio.run(memory.route_question({}, question, context('比较甲公司和乙公司的收费方式。')))
    assert route == {'intent': 'clarify', 'query': None}


def test_stateless_social_and_redirect_never_retrieve_or_invoke_model(env, monkeypatch):
    async def fail(*args, **kwargs):
        pytest.fail('non-business turn must not use retrieval or model')
    monkeypatch.setattr(memory, 'complete', fail)
    monkeypatch.setattr(kb, 'cloud_rpc', fail)
    for question in ('你好？', '在吗', '谢谢你', '怎么上传文件？'):
        response = env.client.post('/company-knowledge/chat/stream', json={'message': question})
        assert response.status_code == 200 and '"type": "done"' in response.text
        assert '"type": "citations"' not in response.text
        if '上传' in question:
            assert 'AI 助手' in response.text


def test_social_and_system_turns_preserve_task_and_topic_switch_survives(env, monkeypatch):
    requests = upstream(monkeypatch)
    sid = create(env)
    sequence = ['甲公司的收入是多少？', '谢谢你', '怎么上传文件？', '客户数呢？',
                '乙公司的收入是多少？', '在吗', '它怎么收费？', '整理成表格']
    previous = None
    for number, question in enumerate(sequence):
        count = len(requests)
        response = call(env, sid, question, str(number))
        assert '"type": "saved"' in response.text and '"type": "error"' not in response.text
        with env.db() as db:
            task = db.get(memory.KnowledgeChatTask, sid).state
        if intent.local_route(question):
            assert task == previous and len(requests) == count
        elif number >= 4:
            assert '乙公司' in task['request'] and '甲公司' not in task['request']
        previous = task
    assert not env.client.get('/company-knowledge/conversations/' + sid).json()['busy']


def test_three_parallel_conversations_keep_their_own_subject_through_60_turns(env, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    upstream(monkeypatch)
    sessions = [create(env) for _ in range(3)]
    def run(index):
        name = ('甲公司', '乙公司', '丙公司')[index]
        sid = sessions[index]
        for number, question in enumerate(([name + '的收入是多少？', '谢谢', '客户数呢？', '整理成表格', '在吗'] * 4)):
            response = call(env, sid, question, f'{index}-{number}')
            assert response.status_code == 200 and '"type": "saved"' in response.text
            assert '"type": "error"' not in response.text
        with env.db() as db:
            assert name in db.get(memory.KnowledgeChatTask, sid).state['request']
            assert not db.get(memory.KnowledgeChatThread, sid).busy_token
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(run, range(3)))


def test_social_turn_does_not_trigger_summary_compression(env, monkeypatch):
    sid = create(env)
    with env.db() as db:
        db.add_all(memory.KnowledgeChatMessage(thread_id=sid, request_id=str(i), role='user',
            content='甲公司资料' * 500, status='completed') for i in range(45))
        db.commit()
    async def fail(*args, **kwargs):
        pytest.fail('social turn must not compress history')
    monkeypatch.setattr(memory, 'complete', fail)
    assert '"type": "saved"' in call(env, sid, '谢谢你').text


def test_routing_does_not_bypass_session_ownership_or_document_acl(env):
    sid = create(env)
    env.user.id, env.user.username = 3, 'charlie'
    assert call(env, sid, '你好').status_code == 404
    env.user.id, env.user.username = 2, 'bob'
    with env.db() as db:
        db.get(CompanyDocument, 'doc-a').readers = []
        db.commit()
    assert call(env, sid, '你好').status_code == 403
    env.client.app.dependency_overrides.clear()
    assert call(env, sid, '你好').status_code == 401


def test_intent_and_actual_retrieval_logs_contain_metadata_only(monkeypatch, tmp_path):
    monkeypatch.setenv('COMPANY_KNOWLEDGE_LOG_DIR', str(tmp_path))
    trace = obs.Trace()
    token = obs._current.set(trace)
    try:
        asyncio.run(memory.route_question({}, '你好', context()))
        assert trace.stats['intent'] == 'smalltalk' and trace.stats['retrieval_attempted'] is False
        obs.observe_retrieval()
        assert trace.stats['retrieval_attempted'] is True
    finally:
        obs._current.reset(token)
    records = [json.loads(line) for p in tmp_path.glob('*.jsonl') for line in p.read_text(encoding='utf-8').splitlines()]
    assert all(record['request_id'] == trace.id for record in records)
    assert {record['event'] for record in records} == {'intent', 'retrieval'}
    assert '甲公司' not in json.dumps(records, ensure_ascii=False) and '你好' not in json.dumps(records, ensure_ascii=False)
