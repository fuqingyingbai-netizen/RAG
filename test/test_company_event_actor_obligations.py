"""A company order cannot turn conduct or affiliation into personal liability."""
from copy import deepcopy
import hashlib
import json

import pytest

from report_agents.company_event_evidence import (
    REVIEW_CRITERIA, VERSION, actor_obligation_errors, validate_event,
    review_primary_events, reviewed_event_records,
)
from test_company_event_impact_and_dates import TARGET, AS_OF, BODY, source, selection, check, package


def case(extra='两位股东具有攀附商誉的恶意，法院据此评价被告公司的行为。'):
    s=source(extra);row=selection(s)
    row['quote']=BODY+extra;row['quote_offset']=s['content'].find(row['quote'])
    return s,row


@pytest.mark.parametrize('role',['股东','股東','董事','员工','法定代表人','实际控制人','母公司','子公司','关联公司'])
def test_named_role_or_affiliation_does_not_add_payment_obligations_even_with_green_checker(role):
    s,row=case();row['summary']='侵权及赔偿责任主体为第三方公司及其'+role+'，不得归于目标公司。'
    assert row['independent_check']['criteria']==dict.fromkeys(REVIEW_CRITERIA,True)
    assert any(error.startswith('unproven_actor_payment_obligation:') for error in validate_event(row,s,TARGET,AS_OF))


@pytest.mark.parametrize('summary',[
    '法院评价股东具有攀附商誉恶意；法院判令第三方公司赔偿655万元。',
    '公司承担赔偿责任；原文未载明股东个人承担赔偿义务。',
    '股东恶意是法院判令公司赔偿的裁判理由，不能补出股东个人义务。',
    '公司被判赔偿655万元，与股东身份不构成个人赔偿依据。',
])
def test_conduct_judicial_reasoning_and_unknown_personal_duty_remain_distinct(summary):
    s,row=case();row['summary']=summary
    assert not actor_obligation_errors(row,s['content'])
    assert not validate_event(row,s,TARGET,AS_OF)


@pytest.mark.parametrize('disposition',[
    '法院判令公司及其股东承担连带赔偿责任。',
    '法院判令向阳公司及其股东承担连带赔偿责任。',
    '法院判令公司及其董事共同赔偿。',
])
def test_explicit_role_payment_order_is_preserved(disposition):
    s,row=case(disposition)
    role='董事' if '董事' in disposition else '股东'
    row['summary']='赔偿责任主体为第三方公司及其'+role+'；按原文明示保留。'
    assert not validate_event(row,s,TARGET,AS_OF)


@pytest.mark.parametrize('extra',[
    '原告请求法院判令公司及其股东共同赔偿。',
    '法院判令第三方公司向股东支付补偿款。',
    '法院判令公司赔偿，并明确股东无需承担赔偿义务。',
    '如果股东未履行职责，股东可能承担赔偿责任。',
])
def test_request_recipient_denial_or_conditional_rule_does_not_prove_payment_duty(extra):
    s,row=case(extra);row['summary']='赔偿责任主体为第三方公司及其股东。'
    assert actor_obligation_errors(row,s['content'])


def test_other_case_cannot_supply_the_role_payment_order():
    s,row=case();s['content']+='另案法院判令股东承担连带赔偿责任。'
    row['original_sha256']=hashlib.sha256(s['content'].encode()).hexdigest()
    row['summary']='赔偿责任主体为第三方公司及其股东。'
    assert actor_obligation_errors(row,s['content'])


def test_previous_five_point_verdict_and_old_cache_are_not_six_point_admission():
    s,row=case();row['independent_check']['criteria'].pop('actors_and_obligations')
    assert 'independent_criterion:actors_and_obligations' in validate_event(row,s,TARGET,AS_OF)
    assert not reviewed_event_records(package(row),[s],TARGET,AS_OF)
    old=package(selection(s));old['version']='company-event-evidence-v2-responsibility-and-date-roles'
    assert VERSION!='company-event-evidence-v2-responsibility-and-date-roles'
    assert not reviewed_event_records(old,[s],TARGET,AS_OF)


def test_actor_repair_requires_a_new_complete_independent_review():
    s,good=case();bad=deepcopy(good)
    bad['summary']='侵权及赔偿责任主体为第三方公司及其股东。'
    good['summary']='法院认定第三方公司侵权，股东恶意为行为评价；判令公司赔偿655万元，未载股东个人赔偿义务。'
    calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        if role=='公司监管原件提取':return json.dumps({'event':bad},ensure_ascii=False)
        if role=='公司监管原件提取修复':
            assert 'unproven_actor_payment_obligation:' in prompt
            return json.dumps({'event':good},ensure_ascii=False)
        assert role=='公司监管原件独立核对'
        assert 'actors_and_obligations' in prompt and '本案判项' in prompt
        return json.dumps(check(),ensure_ascii=False)
    result=review_primary_events([s],TARGET,AS_OF,invoke)
    assert calls==['公司监管原件提取','公司监管原件提取修复','公司监管原件独立核对']
    assert result['events'][0]['summary']==good['summary']
    assert result['events'][0]['independent_check']['criteria']['actors_and_obligations'] is True
    assert result['receipts'][0]['state']=='accepted'


@pytest.mark.parametrize('scope',[
    '原文未判令股东个人承担赔偿或其他义务。',
    '本介绍未判决股东个人承担连带赔偿责任。',
    '原件没有判令董事个人支付赔偿。',
    '原文未責令股東個人承擔賠償義務。',
])
def test_source_order_absence_qualification_is_not_a_positive_payment_claim(scope):
    s,row=case();row['subject_scope']+=scope
    assert not actor_obligation_errors(row,s['content'])
    assert not validate_event(row,s,TARGET,AS_OF)


def test_negative_order_qualification_cannot_hide_a_separate_affirmative_extension():
    s,row=case();row['summary']='原文未判令股东个人承担赔偿；但赔偿责任主体为公司及其股东。'
    assert actor_obligation_errors(row,s['content'])
