import asyncio
import json

import pytest

import company_knowledge as kb
import company_memory as memory
import company_workspace as ws
from company_chat_task import fresh, local_followup
from company_catalog import CompanyDocument
from test_company_memory import env, create, call, upstream


def task(subjects=('乙公司',), **extra):
    return {**fresh('乙公司的收入，限2025年，不要推算'), 'subjects': list(subjects),
            'structured': True, 'topic': '收入', 'constraints': ['限2025年', '不要推算'], **extra}


@pytest.mark.parametrize('question', ['整理成表格', '请把回答整理成表格', '改成列表', '请将结果转成清单'])
def test_formatting_keeps_canonical_query_without_accumulation(question):
    state = task()
    for _ in range(40):
        handled, query, state = local_followup(question, state)
        assert handled and query == '乙公司的收入，限2025年，不要推算'
    assert state['format'] in ('表格', '列表', '清单')


@pytest.mark.parametrize('question', ['客户数呢？', '怎么收费？', '它的目标用户是谁？', '该公司的收入是多少？'])
def test_single_subject_and_user_constraints_survive_short_followups(question):
    handled, query, state = local_followup(question, task())
    assert handled and '乙公司' in query and '限2025年' in query and '不要推算' in query
    assert state['request'] == query


@pytest.mark.parametrize('question', ['那甲公司呢？', '同样比较Tripo', '它和甲公司有什么差异？', '它的第二个产品呢？',
    '它比甲公司贵多少？', '它的收入是多少？仅限2026年，不要推算'])
def test_complex_switches_and_ordinals_still_use_rewriter(question):
    assert not local_followup(question, task())[0]


def test_parallel_subjects_require_clarification_and_format_does_not_clear_it():
    handled, query, state = local_followup('它怎么收费？', task(('甲公司', '乙公司')))
    assert handled and query is None and state['needs_clarification']
    assert not local_followup('整理成表格', state)[0]
    assert not local_followup('它们分别怎么收费？', task(('甲公司', '乙公司')))[0]


@pytest.mark.parametrize('question', ['请比较甲公司和乙公司的收费方式。', '比较Meshy与Tripo的目标用户。'])
def test_explicit_comparison_does_not_depend_on_model_to_detect_plural_subjects(question):
    state = fresh(question)
    assert len(state['subjects']) == 2
    assert local_followup('它的客户数量是多少？', state)[:2] == (True, None)
    assert fresh('比较甲公司的收入和客户数量')['subjects'] == []


def test_complete_literal_company_question_resolves_next_field_even_after_failed_generation():
    state = fresh('请介绍丙公司2025年的营业收入。')
    handled, query, state = local_followup('它怎么收费？', state)
    assert handled and '丙公司' in query and '收费' in query and '2025年' in query
    assert '收入' not in query
    assert not fresh('该公司的收入是多少？')['structured']
    assert not fresh('乙公司的收入是多少？仅限2026年，不要推算')['structured']


def test_full_new_question_clears_previous_task_and_does_not_mutate_context(monkeypatch):
    async def fail(*a, **kw):
        pytest.fail('complete question must not call rewriter')
    monkeypatch.setattr(memory, 'complete', fail)
    context = {'summary': '', 'recent': [], 'task': task()}
    cfg = {}
    assert asyncio.run(memory.retrieval_question(cfg, '甲公司的产品定位是什么？', context)) == '甲公司的产品定位是什么？'
    assert cfg['_task_update'] == fresh('甲公司的产品定位是什么？')
    assert context['task'] == task()


def test_state_survives_history_trimming_and_ambiguous_correction(monkeypatch):
    calls = []
    async def complete(cfg, instruction, data, **kwargs):
        calls.append(data)
        assert data['当前任务']['needs_clarification']
        return json.dumps({'query': '乙公司的收入是多少？', 'subjects': ['乙公司'], 'topic': '收入'})
    monkeypatch.setattr(memory, 'complete', complete)
    cfg = {}
    context = {'summary': '', 'recent': [], 'task': task(('甲公司', '乙公司'), needs_clarification=True)}
    assert asyncio.run(memory.retrieval_question(cfg, '我指的是乙公司', context)) == '乙公司的收入是多少？'
    assert cfg['_task_update']['subjects'] == ['乙公司'] and len(calls) == 1
    context['task'] = cfg['_task_update']
    assert '乙公司' in asyncio.run(memory.retrieval_question(cfg, '客户数呢？', context))
    assert len(calls) == 1


def test_120_rapid_mixed_turns_never_keep_the_previous_company(monkeypatch):
    calls = []
    async def complete(cfg, instruction, data, **kwargs):
        calls.append(data)
        name = next(name for name in ('甲公司', '乙公司', '丙公司') if name in data['当前任务']['request'])
        return json.dumps({'query': name + '的客户数量', 'subjects': [name], 'topic': '客户数量'})
    monkeypatch.setattr(memory, 'complete', complete)
    async def run():
        context = {'summary': '', 'recent': [], 'task': {}}
        for number in range(30):
            name = ('甲公司', '乙公司', '丙公司')[number % 3]
            for question in (name + '的产品定位是什么？', '客户数呢？', '整理成表格', '它怎么收费？'):
                cfg = {}
                query = await memory.retrieval_question(cfg, question, context)
                assert name in query
                context['task'] = cfg['_task_update']
        assert len(calls) == 30
    asyncio.run(run())


@pytest.mark.parametrize('metadata', [
    {'subjects': ['助手虚构的公司']}, {'subjects': '乙公司'},
    {'subjects': ['乙公司'], 'constraints': ['虚构限制']},
    {'subjects': ['乙公司'], 'format': 'html'},
])
def test_untrusted_metadata_cannot_poison_checkpoint(monkeypatch, metadata):
    async def complete(*a, **kw):
        return json.dumps({'query': '乙公司的收入', **metadata})
    monkeypatch.setattr(memory, 'complete', complete)
    cfg = {}
    with pytest.raises(kb.KnowledgeError) as failure:
        asyncio.run(memory.retrieval_question(cfg, '那乙公司呢？', {'summary': '', 'recent': [], 'task': task()}))
    assert failure.value.status_code == 502 and '_task_update' not in cfg


def test_rich_rewrite_cannot_replace_new_pricing_field_with_old_revenue(monkeypatch):
    async def complete(*a, **kw):
        return json.dumps({'query': '乙公司的收入是多少？', 'subjects': ['乙公司'], 'topic': '收入'})
    monkeypatch.setattr(memory, 'complete', complete)
    with pytest.raises(kb.KnowledgeError) as failure:
        asyncio.run(memory.retrieval_question({}, '它怎么收费？',
            {'summary': '', 'recent': [], 'task': {**task(), 'structured': False}}))
    assert failure.value.status_code == 502


def test_checkpoint_is_restored_invalidated_and_deleted_with_owning_thread(env, monkeypatch):
    upstream(monkeypatch)
    sid = create(env)
    assert '"type": "saved"' in call(env, sid).text
    with env.db() as db:
        state = db.get(memory.KnowledgeChatTask, sid)
        assert state.state['request'] == '总结豆包业务布局'
        assert '广告' not in json.dumps(state.state, ensure_ascii=False)
    cfg = kb.settings(); cfg['allowed_documents'] = {'cloud-a': {'id': 'doc-a'}}
    token, plan, deps = memory.begin_turn(env.user, cfg, sid, 'two', '整理成表格')
    assert plan['task']['request'] == '总结豆包业务布局'
    memory.finish_turn(env.user, cfg, sid, token, 'two', '', [], {'summary': '', 'through': 0, 'summary_dependencies': {}}, deps, False)
    with env.db() as db:
        db.get(CompanyDocument, 'doc-a').version = 2
        db.commit()
    token, plan, deps = memory.begin_turn(env.user, cfg, sid, 'three', '它呢？')
    assert plan['task'] == {} and plan['invalidated']
    assert env.client.delete('/company-knowledge/conversations/' + sid).status_code == 200
    assert not memory.finish_turn(env.user, cfg, sid, token, 'three', '', [], {'task_update': task()}, deps, False)
    with env.db() as db:
        assert db.get(memory.KnowledgeChatTask, sid) is None


def test_failed_answer_checkpoints_new_intent_instead_of_old_subject(env, monkeypatch):
    upstream(monkeypatch)
    sid = create(env)
    assert '"type": "saved"' in call(env, sid).text
    async def failed_answer(*a, **kw):
        raise kb.KnowledgeError('模拟生成服务不可用', 503)
        yield
    monkeypatch.setattr(ws, 'grounded_answer', failed_answer)
    assert '模拟生成服务不可用' in call(env, sid, '乙公司的客户数量是多少？', 'two').text
    with env.db() as db:
        assert db.get(memory.KnowledgeChatTask, sid).state['request'] == '乙公司的客户数量是多少？'
    cfg = kb.settings(); cfg['allowed_documents'] = {'cloud-a': {'id': 'doc-a'}}
    token, plan, deps = memory.begin_turn(env.user, cfg, sid, 'three', '整理成表格')
    context = asyncio.run(memory.prepare_context(cfg, plan))
    assert asyncio.run(memory.retrieval_question(cfg, '整理成表格', context)) == '乙公司的客户数量是多少？'
    memory.finish_turn(env.user, cfg, sid, token, 'three', '', [], context, deps, False)


def test_failed_rewrite_blocks_stale_subject_followup_until_explicit_reset(env, monkeypatch):
    requests = upstream(monkeypatch)
    sid = create(env)
    call(env, sid, '甲公司的收入是多少？')
    async def fail(*args, **kwargs):
        raise kb.KnowledgeError('模拟切换时限流', 429)
    monkeypatch.setattr(memory, 'complete', fail)
    assert '模拟切换时限流' in call(env, sid, '那乙公司呢？', 'two').text
    with env.db() as db:
        checkpoint = db.get(memory.KnowledgeChatTask, sid).state
        assert checkpoint['rewrite_failed'] and checkpoint['unresolved_question'] == '那乙公司呢？'
    assert '请补充公司' in call(env, sid, '它怎么收费？', 'three').text
    assert len([path for path, _ in requests if path.endswith('/retrieve')]) == 1
    assert '"type": "saved"' in call(env, sid, '乙公司的收入是多少？', 'four').text
    with env.db() as db:
        assert 'rewrite_failed' not in db.get(memory.KnowledgeChatTask, sid).state
