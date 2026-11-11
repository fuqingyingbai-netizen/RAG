"""Context routing regressions; model semantics are checked separately with real calls."""
import asyncio
import json
from copy import deepcopy

import pytest
import company_knowledge  # Register knowledge routes before the memory module.
import company_memory as memory


CASES = [
    ('请分析Meshy的产品定位和目标用户。', False),
    ('换个问题，Tripo的客户规模是多少？', False),
    ('请总结《甲公司年报》的营业收入。', False),
    ('比较Meshy和Tripo的定位。', False),
    ('乙公司的收入是多少？', False),
    ('请把所选资料中的收入整理成表格。', False),
    ('请把选中的文件中明确披露的数据整理成表格，不要推算。', False),
    ('请根据所选文档整理成指标表，每行注明来源。', False),
    ('那它的商业化情况呢？', True),
    ('请继续', True),
    ('整理成表格', True),
    ('请把回答整理成表格', True),
    ('请把所选资料中上一个问题的指标整理成表格', True),
    ('上一个问题的依据在哪？', True),
    ('之前的答案有数据支持吗？', True),
    ('收费方式呢？', True),
    ('客户数呢？', True),
    ('那Tripo呢？', True),
    ('同样比较Rodin', True),
    ('再展开一点', True),
    ('还有哪些限制？', True),
    ('为什么？', True),
    ('可以展开吗？', True),
    ('有哪些风险？', True),
    ('怎么收费？', True),
    ('它的目标用户是谁？', True),
]


@pytest.mark.parametrize('question,rewrite', CASES)
def test_mixed_questions_route_only_context_dependent_turns_to_model(monkeypatch, question, rewrite):
    calls=[]
    async def complete(cfg,instruction,data,**kwargs):
        calls.append(data)
        assert '[id_1]' not in json.dumps(data,ensure_ascii=False)
        return '{"query":"独立检索问题"}'
    monkeypatch.setattr(memory,'complete',complete)
    context={'summary':'','recent':[{'role':'user','content':'分析Meshy的定位。'},
        {'role':'assistant','content':'需核对资料[id_1]。'}]}
    snapshot=deepcopy(context)
    result=asyncio.run(memory.retrieval_question({'explicit_document_scope':True},question,context))
    assert bool(calls)==rewrite
    assert result==('独立检索问题' if rewrite else question)
    assert context==snapshot


def test_repeated_topic_switches_use_only_the_current_server_history(monkeypatch):
    async def run():
        context={'summary':'','recent':[]};calls=0
        async def complete(cfg,instruction,data,**kwargs):
            nonlocal calls
            calls+=1
            assert data['近期对话'][-1]['content']=='刚切换到乙公司。'
            assert data['最近用户问题']=='分析乙公司的客户。'
            return '{"query":"乙公司的客户数量"}'
        monkeypatch.setattr(memory,'complete',complete)
        for _ in range(20):
            context['recent']=[{'role':'user','content':'分析乙公司的客户。'},
                {'role':'assistant','content':'刚切换到乙公司。'}]
            assert await memory.retrieval_question({},'甲公司的收入是多少？',context)=='甲公司的收入是多少？'
            assert await memory.retrieval_question({},'客户数呢？',context)=='乙公司的客户数量'
        assert calls==20
    asyncio.run(run())
