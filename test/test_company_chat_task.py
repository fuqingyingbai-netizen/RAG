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


@pytest.mark.parametrize('question', ['那甲公司呢？', '同样比较Tripo', '它和甲公司有什么差异？', '它的第二个产品呢？'])
def test_complex_switches_and_ordinals_still_use_rewriter(question):
    assert not local_followup(question, task())[0]


def test_parallel_subjects_require_clarification_and_format_does_not_clear_it():
    handled, query, state = local_followup('它怎么收费？', task(('甲公司', '乙公司')))
    assert handled and query is None and state['needs_clarification']
    assert not local_followup('整理成表格', state)[0]
    assert not local_followup('它们分别怎么收费？', task(('甲公司', '乙公司')))[0]


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
