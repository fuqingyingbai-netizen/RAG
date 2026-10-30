"""Staged generation preserves good answers without broadening evidence rights."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from industry_question_generation import compile_jobs, parse_answers, generate_questions, job_prompt
from industry_research_stages import plan_questions, select_evidence, review_in_groups
from industry_model_output import IndustryModelOutputError, remaining_request_timeout, response_text
from test_industry_chapter_batches import rich_package
from test_industry_briefing import card, SCOPE


def answer(qid, ref):
    return {'question_id': qid, 'status': 'answered', 'refs': [ref], 'kind': 'conditional',
            'conclusion': '在所引分工适用于当前业务的条件下，选型需要考虑供给、集成与应用环节之间的衔接。',
            'analysis': '上游供给、中游集成与下游应用分别承担不同职责，因此可以沿着这些分工核对方案的依赖条件和接口要求。这是对所引材料的条件分析，不据此认定各类企业已经获利，也不能据此判断整个行业的市场份额。'}


def public(prompt):
    return json.loads(prompt.split('\n', 1)[1])


def keep_editorial(data):
    return json.dumps({'reviews': [
        {'draft_id': row['draft_id'], 'fingerprint': row['fingerprint'],
         'decision': 'keep', 'issues': []} for row in data['drafts']]})


def test_compiler_has_small_complete_cards_no_diagnostics_and_preserves_sources():
    p=rich_package(); old=deepcopy(p)
    jobs, d=compile_jobs(p, 2)
    assert len(jobs)==2 and p==old
    for packet in jobs:
        body=public(job_prompt(packet))
        assert len(body['questions'])<=2 and len(body['cards'])<=8
        assert len(job_prompt(packet))<=10000
        assert '_facts' not in body and 'fact_contract' not in json.dumps(body)
        for row in body['cards']:
            assert row['statement']==packet['_facts'][packet['_refs'][row['ref']]]['fact_contract']['statement']
    assert sum(q['status']=='scheduled' for q in d['questions'])==4


def test_independent_answer_commit_rejects_bad_sibling_and_keeps_valid_finding():
    packet=compile_jobs(rich_package(), 2)[0][0]
    first, second=packet['questions']
    good=answer(first['id'], first['allowed_refs'][0])
    bad=answer(second['id'], 'F999')
    valid, rejected, states=parse_answers(json.dumps({'answers':[good,bad]}), packet)
    assert len(valid)==1 and valid[0]['conclusion']==good['conclusion']
    assert rejected and states[second['id']]['status']=='invalid_answer'
    assert valid[0]['premises'][0]['quote']==packet['_facts'][valid[0]['evidence_ids'][0]]['fact_contract']['statement']
    assert valid[0]['entailment_status']=='not_evaluated'


def test_reference_in_another_question_is_not_authorized_by_shared_packet():
    packet=compile_jobs(rich_package(), 2)[0][0]
    first, second=packet['questions']
    foreign=next(ref for ref in second['allowed_refs'] if ref not in first['allowed_refs'])
    valid,rejected,_=parse_answers(json.dumps({'answers':[answer(first['id'],foreign)]}),packet)
    assert not valid and rejected


@pytest.mark.parametrize('mutate',[
    lambda a:a.update(conclusion='该行业市场规模已经达到99999亿元，企业经营表现因此显著改善。'),
    lambda a:a.update(conclusion=''),
    lambda a:a.update(refs=['F999']),
    lambda a:a.update(question_id='Q999'),
    lambda a:a.update(question_id=[]),
])
def test_bad_answer_never_upgrades_to_a_draft(mutate):
    packet=compile_jobs(rich_package(),2)[0][0]
    q=packet['questions'][0]; a=answer(q['id'],q['allowed_refs'][0]); mutate(a)
    valid,_,_=parse_answers(json.dumps({'answers':[a]}),packet)
    assert not valid


def test_duplicate_question_and_abstention_are_not_successful_analysis():
    packet=compile_jobs(rich_package(),2)[0][0]
    q=packet['questions'][0]; a=answer(q['id'],q['allowed_refs'][0])
    valid,_,states=parse_answers(json.dumps({'answers':[a,a]}),packet)
    assert not valid and states[q['id']]['status']=='duplicate_answer'
    valid,_,states=parse_answers(json.dumps({'answers':[{'question_id':q['id'],'status':'insufficient','reason':'缺少范围说明。'}]}),packet)
    assert not valid and states[q['id']]['status']=='model_abstained'


def test_source_agenda_is_not_a_bottleneck_answer_and_relevant_chain_is_preserved():
    p=rich_package()
    agenda=card('以全球及中国产业运营数据为基础，系统阐述定义边界、市场规模、技术体系、产业链结构、应用商业化、瓶颈挑战与战略建议。',
                'E-ABCDEF123456',module='细分赛道与产业链')
    p['facts'].append(agenda)
    jobs,d=compile_jobs(p,2)
    assert agenda['evidence_id'] in d['excluded_outline_ids']
    assert all(agenda['evidence_id'] not in j['_facts'] for j in jobs)
    assert any('产业链主体和分层关系'==q['question'] for j in jobs for q in j['questions'])


def test_planning_and_selection_roles_cannot_invent_questions_or_promote_foreign_cards():
    p=rich_package(); calls=[]
    def invoke(role,prompt,trace):
        calls.append(role); assert remaining_request_timeout() is not None
        if '规划' in role:
            return json.dumps({'priorities':[{'chapter':2,'questions':['Q2','Q1']},{'chapter':999,'questions':['Q1']}]})
        body=public(prompt); q=body['questions'][0]
        return json.dumps({'selections':[{'question_id':q['id'],'refs':[q['candidate_refs'][-1]],'reason':'保留具体分工原文。'},
                                         {'question_id':'Q999','refs':['F1'],'reason':'不允许新建问题。'}]})
    order,planning=plan_questions({2:p},SimpleNamespace(industry_scope=SCOPE),invoke,lambda *a,**k:None,None)
    selected,diag=select_evidence(p,2,order[2],invoke,lambda *a,**k:None,None)
    assert order=={2:['Q2','Q1']} and 'Q999' not in selected
    jobs,_=compile_jobs(p,2,question_order=order[2],evidence_selection=selected)
    assert jobs[0]['questions'][0]['id']=='Q2'
    assert planning['attempts']==diag['attempts']==1 and len(calls)==2
    assert remaining_request_timeout() is None


def test_selection_failure_falls_back_and_one_writer_timeout_preserves_other_answer(monkeypatch):
    # Exercise the explicit editor after a successful sibling writer request.
    monkeypatch.setenv('INDUSTRY_EDITORIAL_ENABLED', '1')
    calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        if '筛选' in role or len(calls)==2:
            raise IndustryModelOutputError('model_request_timeout')
        if '质量编辑' in role:
            return keep_editorial(public(prompt))
        body=public(prompt); q=body['questions'][0]
        return json.dumps({'answers':[answer(q['id'],q['allowed_refs'][0])]})
    r=generate_questions(rich_package(),2,'产业链',invoke,lambda *a,**k:None,None)
    assert len(calls)==4 and r['attempts']==2 and len(r['analyses'])==1
    assert sum('质量编辑' in role for role in calls)==1
    assert r['diagnostic']['editorial']['calls']==1
    assert r['diagnostic']['evidence_selection']['status']=='fallback_rule_selection'
    assert r['diagnostic']['partial_failure'] and remaining_request_timeout() is None


def test_writer_shared_deadline_never_starts_another_request_after_expiry(monkeypatch):
    monkeypatch.setenv('INDUSTRY_EDITORIAL_ENABLED', '0')
    now=[0.0]; calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        if '筛选' in role:
            return json.dumps({'selections':[]})
        q=public(prompt)['questions'][0]
        from industry_model_output import stage_timeout
        now[0]=2*stage_timeout('writer')+1
        return json.dumps({'answers':[answer(q['id'],q['allowed_refs'][0])]})
    result=generate_questions(rich_package(),2,'产业链',invoke,lambda *a,**k:None,None,clock=lambda:now[0])
    assert len(calls)==2 and result['attempts']==1 and len(result['analyses'])==1
    assert result['diagnostic']['requests'][1]['code']=='chapter_generation_budget_exhausted'
    assert result['diagnostic']['partial_failure']


def test_new_section_path_records_roles_without_hidden_analysis_repair(monkeypatch):
    monkeypatch.setenv('INDUSTRY_EDITORIAL_ENABLED', '1')
    from report_agents.industry_report_agent import IndustryReportAgent
    calls=[]
    def invoke(role,prompt,trace):
        calls.append(role); data=public(prompt)
        if '筛选' in role:return json.dumps({'selections':[]})
        if '质量编辑' in role:return keep_editorial(data)
        return json.dumps({'answers':[answer(q['id'],q['allowed_refs'][0]) for q in data['questions']]})
    p=SimpleNamespace(industry_question_jobs_enabled=True,industry_statement_plans={},industry_report_degradations=[])
    text=IndustryReportAgent()._write_statement_section(p,rich_package(),2,'产业链',invoke,lambda *a,**k:None,None)
    plan=p.industry_statement_plans[2]
    assert len(plan['analysis_claims'])==4 and '本章初步结论' in text
    assert len(calls)==5 and all('修复' not in role for role in calls)
    assert sum('质量编辑' in role for role in calls)==2
    assert plan['generation_batches']['editorial']['calls']==2
    assert plan['analysis_repair']['attempted'] is False
    assert plan['generation_batches']['version']=='industry-question-jobs-v6-editorial-protocol-and-budget'


def test_failure_usage_is_preserved_without_text_or_credentials():
    result=SimpleNamespace(content='PRIVATE_BODY',response_metadata={'finish_reason':'length'},
        usage_metadata={'output_tokens':3000,'output_token_details':{'reasoning':2900,'private':'SECRET'}})
    with pytest.raises(IndustryModelOutputError) as exc:
        response_text(result)
    assert exc.value.diagnostics['token_usage']['reasoning_tokens']==2900
    assert 'PRIVATE' not in json.dumps(exc.value.diagnostics) and 'SECRET' not in json.dumps(exc.value.diagnostics)


def test_review_groups_keep_success_when_other_group_times_out():
    from industry_reasoning import claim_id
    facts=rich_package()['facts']
    claims=[]
    for i,f in enumerate(facts[:6]):
        c={'chapter':2,'question':f'问题{i}', 'text':f['fact_contract']['statement'], 'evidence_ids':[f['evidence_id']]}
        c['claim_id']=claim_id(c,2); claims.append(c)
    calls=[]
    def invoke(prompt):
        calls.append(prompt)
        if len(calls)==2:raise IndustryModelOutputError('model_request_timeout')
        packet=json.loads(prompt.split('\n',1)[1].split('\n本组',1)[0])
        return json.dumps({'packet_fingerprint':packet['packet_fingerprint'],'reviews':[
            {'claim_id':c['claim_id'],'status':'supported','reason':'所引原文与本条判断的主体和内容一致。',
             'quotes':[{'evidence_id':eid,'quote':packet['cards'][eid]['statement'][:35]} for eid in c['evidence_ids']]}
            for c in packet['claims']]})
    r=review_in_groups(claims,facts,invoke)
    assert len(calls)==r['attempts']==3 and r['supported_claim_count']==6 and r['pending_claim_count']==0
    assert r['groups'][2]['submitted_claim_ids']==r['groups'][1]['submitted_claim_ids']
    assert set(r['groups'][0]['submitted_claim_ids']).isdisjoint(r['groups'][2]['submitted_claim_ids'])
    assert remaining_request_timeout() is None


@pytest.mark.parametrize('role,key,cap,timeout',[
    ('行业问题规划 Agent','INDUSTRY_PLANNER_MODEL',1500,120),
    ('行业证据筛选 Agent - 2','INDUSTRY_SELECTOR_MODEL',1500,120),
    ('行业问题结论 Agent - 产业链 - 1','INDUSTRY_WRITER_MODEL',None,360),
    ('行业问题结论重试 Agent - 产业链 - 1','INDUSTRY_WRITER_MODEL',None,360),
    ('行业分组支持复核 Agent','INDUSTRY_REVIEW_MODEL',None,240),
])
def test_role_specific_models_have_independent_budgets(monkeypatch,role,key,cap,timeout):
    import research_workflow
    monkeypatch.delenv('INDUSTRY_CONCLUSION_MAX_OUTPUT_TOKENS', raising=False)
    monkeypatch.setenv('ARK_API_KEY','synthetic'); monkeypatch.setenv('MODEL','qwen3.8-max')
    monkeypatch.setenv(key,'synthetic-stage-model'); configured=[]
    def create(**kwargs):
        configured.append(kwargs); return SimpleNamespace(invoke=lambda *a,**k:SimpleNamespace(content='{}'))
    monkeypatch.setattr(research_workflow,'init_chat_model',create)
    w=research_workflow.ResearchWorkflow.__new__(research_workflow.ResearchWorkflow)
    w._invoke_industry_report(role,'test')
    assert configured[0]['model']=='synthetic-stage-model'
    assert configured[0].get('max_tokens')==cap and configured[0]['timeout']==timeout and configured[0]['max_retries']==0
    if cap is None:
        assert 'max_tokens' not in configured[0]
