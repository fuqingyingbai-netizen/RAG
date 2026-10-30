"""Keep partial chapter success within two requests and shared time limits."""
from copy import deepcopy
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from industry_chapter_batches import plan_batches, generate_batches
from industry_fact_contracts import plan_prompt, chapter_coverage
from industry_model_output import IndustryModelOutputError, remaining_request_timeout, request_deadline
from report_agents.industry_report_agent import IndustryReportAgent
from test_industry_briefing import card, SCOPE


def rich_package():
    texts = ['机器人行业是指机器人技术研发和应用涉及的硬件产品与集成服务。',
        '机器人产业链上游提供控制器，中游完成整机集成，下游服务制造场景。',
        '机器人产业链各环节价值分配包括硬件供给、系统集成与应用服务等不同环节。',
        '机器人产业核心部件依赖是供应瓶颈的重要表现。']
    facts = [card(texts[i%4], f'E-{i+1:012X}', module='细分赛道与产业链') for i in range(16)]
    assert all(f['fact_contract']['report_admitted'] for f in facts)
    return {'facts': facts, 'industry_scope': SCOPE}


def answer(prompt, *, foreign=None):
    data = json.loads(prompt.split('\n', 1)[1])
    q = next(q for q in data['generation_targets'] if q['direct_evidence_ids'])
    eid = q['direct_evidence_ids'][0]
    claim = {'question':q['question'], 'claim_kind':'conditional',
        'text':'如果所引材料适用于当前业务，可以分别考察不同环节的职责与依赖关系；这属于有条件的分析，不能据此推定所有企业的盈利表现。',
        'reasoning':'依据所引材料的职责和分工讨论比较角度，不补充经营结果或行业评分。',
        'evidence_ids':[foreign or eid]}
    return json.dumps({'evidence_ids':[eid], 'analyses':[claim]}, ensure_ascii=False)


def test_batches_reserve_questions_and_keep_original_archive_unchanged():
    package = rich_package(); original = deepcopy(package)
    batches = plan_batches(package, 2)
    assert len(batches) == 2 and all(len(b['facts']) <= 12 for b in batches)
    groups = [set(b['analysis_batch']['questions']) for b in batches]
    expected = {q['question'] for q in chapter_coverage(package, 2, [f['evidence_id'] for f in package['facts']]) if q['evidence_ids']}
    assert not groups[0]&groups[1] and groups[0]|groups[1] == expected
    for batch in batches:
        prompt = plan_prompt(batch, 2)
        data = json.loads(prompt.split('\n', 1)[1])
        assert set(data['required_questions']) == set(batch['analysis_batch']['questions'])
        assert len(prompt) <= 12000 and '最多8条来源、3段分析' in prompt
    assert package == original
    assert not plan_batches({'facts':package['facts'][:4]},2)
    assert not plan_batches(package,14)


def test_two_answerable_questions_with_many_cards_also_split():
    package=rich_package()
    package['facts']=[f for i,f in enumerate(package['facts']) if i%4 in {0,1}]
    package['facts']+=deepcopy(package['facts'])
    for i,f in enumerate(package['facts']):
        f['evidence_id']=f'E-{i+1:012X}'
    batches=plan_batches(package,2)
    assert len(batches)==2
    assert all(len(b['analysis_batch']['questions'])==1 for b in batches)


@pytest.mark.parametrize('failed_batch', [1,2])
def test_either_timeout_keeps_the_other_success_without_a_third_request(monkeypatch, failed_batch):
    monkeypatch.setenv('INDUSTRY_ANALYSIS_REPAIR_MAX_CALLS','0')
    package=rich_package(); p=SimpleNamespace(industry_statement_plans={},industry_report_degradations=[])
    calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        assert remaining_request_timeout() is not None
        if len(calls)==failed_batch:
            raise IndustryModelOutputError('model_request_timeout')
        return answer(prompt)
    text=IndustryReportAgent()._write_statement_section(p,package,2,'行业定义',invoke,lambda *a,**k:None,None)
    plan=p.industry_statement_plans[2]
    assert len(calls)==plan['model_attempts']==2 and not plan['fallback']
    assert len(plan['analysis_claims'])==1 and plan['generation_batches']['partial_failure']
    assert plan['analysis_claims'][0]['text'] in text
    assert any('已保留' in d['message'] for d in p.industry_report_degradations)
    assert remaining_request_timeout() is None
    assert all(eid in plan['evidence_ids'] for c in plan['analysis_claims'] for eid in c['evidence_ids'])


def test_shared_deadline_skips_second_request_after_first_consumes_budget():
    batches=plan_batches(rich_package(),2); now=[0.0]; calls=[]
    def invoke(role,prompt,trace):
        calls.append(role); now[0]=91
        return answer(prompt)
    result=generate_batches(batches,2,'行业定义',invoke,lambda *a,**k:None,None,clock=lambda:now[0])
    assert len(calls)==result['attempts']==1 and len(result['analyses'])==1
    assert result['diagnostic']['batches'][1]['code']=='chapter_generation_budget_exhausted'
    assert result['diagnostic']['partial_failure']


def test_foreign_reference_cannot_be_authorized_by_other_batch_after_merge():
    batches=plan_batches(rich_package(),2)
    first_ids={f['evidence_id'] for f in batches[0]['facts']}
    foreign=next(f['evidence_id'] for f in batches[1]['facts'] if f['evidence_id'] not in first_ids)
    calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        return answer(prompt,foreign=foreign) if len(calls)==1 else answer(prompt)
    result=generate_batches(batches,2,'行业定义',invoke,lambda *a,**k:None,None)
    assert len(result['analyses'])==1 and result['rejections']
    assert 'invalid_analysis_citations' in result['rejections'][0]['issues']


@pytest.mark.parametrize('both_fail', [False, True])
def test_bad_json_does_not_erase_good_analysis_or_add_a_third_request(monkeypatch, both_fail):
    monkeypatch.setenv('INDUSTRY_ANALYSIS_REPAIR_MAX_CALLS','0')
    p=SimpleNamespace(industry_statement_plans={},industry_report_degradations=[])
    calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        return 'invalid JSON' if both_fail or len(calls)==1 else answer(prompt)
    IndustryReportAgent()._write_statement_section(p,rich_package(),2,'行业定义',invoke,lambda *a,**k:None,None)
    plan=p.industry_statement_plans[2]
    assert len(calls)==plan['model_attempts']==2
    assert plan['fallback'] is both_fail
    assert len(plan['analysis_claims']) == (0 if both_fail else 1)
    assert len(plan['plan_validation_failures']) == (2 if both_fail else 1)
    assert all(r['kind']=='format_failure' for r in plan['plan_validation_failures'])
    assert plan['evidence_ids'] and remaining_request_timeout() is None


def test_batch_question_boundary_is_independent_of_card_overlap():
    batches=plan_batches(rich_package(),2)
    other=batches[1]['analysis_batch']['questions'][0]
    calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        data=json.loads(answer(prompt))
        if len(calls)==1:
            data['analyses'][0]['question']=other
        return json.dumps(data,ensure_ascii=False)
    result=generate_batches(batches,2,'行业定义',invoke,lambda *a,**k:None,None)
    assert len(result['analyses'])==1
    assert result['rejections'][0]['issues']==['analysis_outside_requested_batch']


def test_more_than_eight_cross_batch_premises_are_preserved_in_final_selection():
    from industry_analysis import complete_plan
    package=rich_package()
    # Two batches may each select eight sources. Retaining their valid analyses
    # must not silently discard the latter batch's distinct premises.
    used=[f['evidence_id'] for f in package['facts'][:12]]
    claims=[{'evidence_ids':used[i:i+4]} for i in range(0,12,4)]
    ids=complete_plan(package,2,used,claims,max_facts=16,preserve_premises_first=True)
    assert set(used)<=set(ids) and len(ids)<=16
    short=complete_plan(package,2,[f['evidence_id'] for f in package['facts']],claims[:1],
                        max_facts=16,preserve_premises_first=True)
    assert len(short)<=8


def test_context_deadline_is_reset_on_exception_and_batch_model_uses_smaller_budget(monkeypatch):
    import research_workflow
    monkeypatch.setenv('ARK_API_KEY','synthetic')
    monkeypatch.setenv('MODEL','qwen3.8-max')
    configured, calls=[],[]
    def create(**kwargs):
        configured.append(kwargs)
        def invoke(messages,**options):
            calls.append(options); return SimpleNamespace(content='{}')
        return SimpleNamespace(invoke=invoke)
    monkeypatch.setattr(research_workflow,'init_chat_model',create)
    w=research_workflow.ResearchWorkflow.__new__(research_workflow.ResearchWorkflow)
    with request_deadline(time.monotonic()+12):
        w._invoke_industry_report('行业章节分段编排 Agent - 合成章','synthetic')
    assert 0<calls[0]['timeout']<=12
    assert configured[0]['max_tokens']==3000 and configured[0]['max_retries']==0
    assert configured[0]['timeout']==45 and remaining_request_timeout() is None
    with pytest.raises(IndustryModelOutputError):
        with request_deadline(time.monotonic()-1):
            w._invoke_industry_report('行业章节分段编排 Agent - 合成章','synthetic')
    assert len(calls)==1 and remaining_request_timeout() is None


def test_real_sdk_accepts_timeout_override_and_serializes_single_token_cap_offline():
    from langchain_openai import ChatOpenAI
    received=[]
    def handle(request):
        received.append((json.loads(request.content),request.extensions['timeout']))
        return httpx.Response(200,json={'id':'synthetic','object':'chat.completion','created':0,'model':'qwen3.8-max',
            'choices':[{'index':0,'message':{'role':'assistant','content':'{}'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        model=ChatOpenAI(model='qwen3.8-max',api_key='synthetic',base_url='https://unit.example/v1',
            http_client=client,timeout=45,max_tokens=3000,max_retries=0,
            model_kwargs={'response_format':{'type':'json_object'}},extra_body={'enable_thinking':False})
        result=model.invoke([{'role':'user','content':'Return JSON.'}],timeout=12.0)
    body,limits=received[0]
    assert result.content=='{}' and limits['read']==12
    assert body.get('max_completion_tokens',body.get('max_tokens'))==3000
    assert not ('max_tokens' in body and 'max_completion_tokens' in body)
    assert body['enable_thinking'] is False and body['response_format']=={'type':'json_object'}
