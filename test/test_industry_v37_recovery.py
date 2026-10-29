"""Saved-v37 failure classes, reproduced with synthetic cards and no network."""
from copy import deepcopy
import json

import pytest

from industry_fact_contracts import chapter_coverage, validate_analyses
from industry_model_output import IndustryModelOutputError
from industry_reasoning import completion_criteria, review_prompt, run_support_review
from industry_research import delivery_errors
from industry_research_stages import review_in_groups
from industry_question_generation import compile_jobs, job_prompt
from test_industry_template_analysis import chain, claim
from test_industry_v36_review import make_claims, complete


@pytest.mark.parametrize('title', ['中国市场规模、份额|成长[2032]', '标题含#与4000亿元及248%'])
def test_selected_source_title_is_attribution_before_format_and_number_checks(title):
    f = chain(); f['source_title'] = title
    text = '根据《'+title+'》，产业链按供给、集成与应用分工，有助于按业务环节梳理协作关系。'
    c = claim(text=text, conclusion=text)
    before = deepcopy([f,c])
    accepted, rejected = validate_analyses([c], {'facts':[f]}, 2, [f['evidence_id']])
    assert accepted and not rejected and accepted[0]['text'] == text
    assert [f,c] == before


def test_unknown_or_uncited_title_cannot_hide_markup_or_extra_claims():
    f = chain(); f['source_title'] = '真实|标题'
    extra = deepcopy(f); extra.update(evidence_id='E-222222222222', source_title='未引|标题')
    package = {'facts':[f,extra]}
    for body in ['根据《未引|标题》，产业链按供给、集成与应用分工形成协作关系。',
                 '根据《真实|标题》，产业链按供给、集成与应用分工。|新增栏目',
                 '根据《真实|标题》，产业链收入已增长248%，行业规模达到4000亿元。']:
        accepted, rejected = validate_analyses([claim(text=body)],package,2,[f['evidence_id'],extra['evidence_id']])
        assert not accepted and rejected


def test_delivery_masks_only_verified_cited_title_numbers():
    f = chain(); eid = f['evidence_id']
    f['source_title'] = '市值破4000亿元！智能体暴涨248%！某产品研究'
    diagnostic = {'evidence_ids':[eid], 'chapter_evidence_ids':{10:[eid]}, 'numeric_evidence':{
        eid:{'source_title':f['source_title'], 'fact':f['fact_contract']['statement']}}}
    line = '据《'+f['source_title']+'》，该来源讨论产品发展。 ['+eid+']'
    def report(text):
        return '\n'.join(f'## {i}. 章节\n'+(text if i==10 else '研究边界与口径。') for i in range(1,17))
    errors = delivery_errors(report(line),diagnostic,{})
    assert not any('4000亿元' in e or '248%' in e or '未授权数值' in e for e in errors)
    errors = delivery_errors(report(line+'行业收入增长248%。'),diagnostic,{})
    assert any('248%' in e for e in errors)
    # A title from a different, uncited card provides no exemption.
    errors = delivery_errors(report(line.replace(eid,'E-333333333333')),diagnostic,{})
    assert any('248%' in e for e in errors)


def test_connection_failure_retries_after_other_groups_and_keeps_success(monkeypatch):
    monkeypatch.setenv('INDUSTRY_REVIEW_MAX_REQUESTS','4')
    f, claims = make_claims(6); before = deepcopy(claims); calls=[]; delays=[]
    def invoke(prompt):
        calls.append(prompt)
        if len(calls)==1:
            raise IndustryModelOutputError('model_connection_failed',{'token_usage':{'output_tokens':0}})
        return complete(prompt)
    result = review_in_groups(claims,[f],invoke,sleeper=delays.append)
    assert len(calls)==3 and len(delays)==1 and delays[0]>0
    assert result['groups'][1]['submitted_claim_ids']==[claims[5]['claim_id']]
    assert result['groups'][2]['submitted_claim_ids']==result['groups'][0]['submitted_claim_ids']
    assert result['groups'][2]['retry_kind']=='execution'
    assert result['supported_claim_count']==6 and not result['pending_claim_count']
    assert result['groups'][0]['output_diagnostic']['token_usage']['output_tokens']==0
    assert claims==before


def test_truncated_review_splits_failed_group_without_replaying_completed_sibling(monkeypatch):
    monkeypatch.setenv('INDUSTRY_REVIEW_MAX_REQUESTS','4')
    f, claims = make_claims(6); calls=[]
    def invoke(prompt):
        calls.append(prompt)
        if len(calls)==1:
            raise IndustryModelOutputError('truncated_model_output')
        return complete(prompt)
    result = review_in_groups(claims,[f],invoke)
    assert len(calls)==4 and result['supported_claim_count']==6
    chunks=[g['submitted_claim_ids'] for g in result['groups'][2:]]
    assert list(map(len,chunks))==[3,2]
    assert set(chunks[0]).isdisjoint(chunks[1])
    assert set(chunks[0]+chunks[1])==set(result['groups'][0]['submitted_claim_ids'])
    assert all(g['retry_delay_seconds']==0 for g in result['groups'][2:])


def test_rate_limit_is_bounded_and_never_becomes_supported(monkeypatch):
    monkeypatch.setenv('INDUSTRY_REVIEW_MAX_REQUESTS','5')
    monkeypatch.setenv('INDUSTRY_REVIEW_EXECUTION_RETRIES','1')
    f,claims=make_claims(3); delays=[]; calls=[]
    def invoke(prompt):
        calls.append(prompt)
        raise IndustryModelOutputError('model_rate_limited')
    result=review_in_groups(claims,[f],invoke,sleeper=delays.append)
    assert len(calls)==2 and len(delays)==1 and delays[0]>=5
    assert result['pending_claim_count']==3 and result['supported_claim_count']==0
    assert all(v=={'execution':1} for v in result['retry_counts'].values())


def test_semantic_rejection_and_unknown_errors_are_not_transient_retries(monkeypatch):
    monkeypatch.setenv('INDUSTRY_REVIEW_MAX_REQUESTS','5')
    f,claims=make_claims(1); calls=[]
    def rejected(prompt):
        calls.append(prompt)
        return complete(prompt).replace('"supported"','"unsupported"')
    result=review_in_groups(claims,[f],rejected)
    assert len(calls)==1 and result['valid_review_count']==1 and not result['supported_claim_count']
    def failed(prompt):
        raise ValueError('synthetic unavailable credentials')
    result=review_in_groups(claims,[f],failed)
    assert result['attempts']==1 and result['pending_claim_count']==1
    assert 'credentials' not in json.dumps(result)


def test_duplicate_quote_recovery_preserves_valid_sibling(monkeypatch):
    monkeypatch.setenv('INDUSTRY_REVIEW_MAX_REQUESTS','3')
    f,claims=make_claims(2); calls=[]
    def invoke(prompt):
        calls.append(prompt); value=json.loads(complete(prompt))
        if len(calls)==1:
            value['reviews'][0]['quotes']*=2
        return json.dumps(value)
    result=review_in_groups(claims,[f],invoke)
    assert len(calls)==2 and result['supported_claim_count']==2
    assert result['groups'][1]['submitted_claim_ids']==[claims[0]['claim_id']]


def test_retry_respects_shared_deadline_including_backoff(monkeypatch):
    monkeypatch.setenv('INDUSTRY_REVIEW_MAX_REQUESTS','2')
    monkeypatch.setenv('INDUSTRY_REVIEW_TIMEOUT_SECONDS','10')
    f,claims=make_claims(1); now=[0]; delays=[]
    def invoke(prompt):
        now[0]=19
        raise IndustryModelOutputError('model_connection_failed')
    result=review_in_groups(claims,[f],invoke,clock=lambda:now[0],sleeper=delays.append)
    assert result['attempts']==1 and not delays and result['pending_claim_count']==1


def test_sdk_failure_class_is_preserved_without_provider_exception_text():
    f,claims=make_claims(1)
    class APIConnectionError(Exception): pass
    def invoke(prompt):raise APIConnectionError('sensitive provider body')
    result=run_support_review(claims,[f],invoke)
    assert result['output_error_code']=='model_connection_failed'
    assert 'sensitive' not in json.dumps(result)


def test_technical_scene_premise_gets_slot_without_claiming_test_performance():
    from test_industry_template_analysis import fact,SCOPE
    from industry_fact_contracts import attach_contract
    rows=[]
    for i in range(6):
        f,body=fact('该技术路线适用于云端推理场景，采用不同部署架构。',evidence_id=f'E-{i+1:012X}')
        rows.append(attach_contract(f,SCOPE,body))
    scene,body=fact('云端追求吞吐量，端侧追求能效与成本，边缘侧追求可靠性与低延迟。',evidence_id='E-ABCDEF123456')
    scene=attach_contract(scene,SCOPE,body);rows.append(scene)
    before=deepcopy(rows);package={'facts':rows}
    coverage=chapter_coverage(package,7,[f['evidence_id'] for f in rows])
    assert coverage[0]['evidence_ids'][0]==scene['evidence_id']
    packets,_=compile_jobs(package,7)
    assert any(scene['evidence_id'] in p['_facts'] for p in packets)
    q=next(q for p in packets for q in p['questions'] if q['question']=='路线及适用场景')
    assert '定性场景比较' in q['instruction']
    assert not next(r for r in coverage if r['question']=='可核验性能及单位成本')['evidence_ids']
    assert rows==before and '硬件及测试负载' not in completion_criteria('路线及适用场景')


def test_prompt_separates_observation_from_mechanism_and_metric_definition():
    prompt=job_prompt({'version':'test','chapter':4,'questions':[{'instruction':'同机构或相同数值不能推出口径一致'}],'cards':[]})
    reviewed=review_prompt({'claims':[],'cards':{}})
    assert '同机构或相同数值' in prompt
    assert '相同数值' in reviewed and '转换成本' in reviewed and '可比基准' in reviewed
