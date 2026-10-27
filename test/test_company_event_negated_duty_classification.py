"""Negating a personal duty must not hide a separate affirmative duty."""
import json
import pytest

from report_agents.company_event_evidence import actor_obligation_errors,validate_event,review_primary_events
from test_company_event_actor_obligations import case
from test_company_event_impact_and_dates import TARGET,AS_OF,check


@pytest.mark.parametrize('negative',['不是','并不是','並不是'])
@pytest.mark.parametrize('role',['股东','股東','董事','员工','法定代表人','实际控制人','母公司','子公司','关联公司'])
def test_negated_duty_classification_is_not_a_positive_order(negative,role):
    source,row=case()
    row['summary']='关联身份和行为评价'+negative+role+'承担赔偿的判项。'
    assert not actor_obligation_errors(row,source['content'])
    assert not validate_event(row,source,TARGET,AS_OF)


def test_actual_native_negative_shareholder_classification():
    source,row=case()
    row['summary']='股东的行业经历及被认定的攀附恶意不是股东个人赔偿或连带责任判项。'
    assert not actor_obligation_errors(row,source['content'])
    assert not validate_event(row,source,TARGET,AS_OF)


@pytest.mark.parametrize('negative',['不是','并不是','並不是'])
@pytest.mark.parametrize('connector',['，但','；然而','而是','，'])
def test_later_positive_duty_does_not_borrow_an_earlier_negation(negative,connector):
    source,row=case()
    row['summary']='行为评价'+negative+'股东个人赔偿判项'+connector+'股东承担连带赔偿责任。'
    assert actor_obligation_errors(row,source['content'])
    assert any(error.startswith('unproven_actor_payment_obligation:') for error in validate_event(row,source,TARGET,AS_OF))


def test_negation_of_an_unrelated_phrase_cannot_hide_a_positive_duty():
    source,row=case()
    row['summary']='这不是一般性介绍，股东个人承担赔偿责任。'
    assert actor_obligation_errors(row,source['content'])


def test_negative_classification_still_needs_fresh_complete_independent_review():
    source,row=case()
    row['summary']='股东的行业经历及被认定的攀附恶意不是股东个人赔偿或连带责任判项。'
    row.pop('independent_check')
    assert not validate_event(row,source,TARGET,AS_OF,require_independent=False)
    assert 'independent_check_missing' in validate_event(row,source,TARGET,AS_OF)
    calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        if role=='公司监管原件提取':return json.dumps({'event':row},ensure_ascii=False)
        assert role=='公司监管原件独立核对'
        assert 'actors_and_obligations' in prompt and '完整原文：' in prompt
        return json.dumps(check(),ensure_ascii=False)
    result=review_primary_events([source],TARGET,AS_OF,invoke)
    assert calls==['公司监管原件提取','公司监管原件独立核对']
    assert result['receipts'][0]['state']=='accepted'
    assert result['events'][0]['summary']==row['summary']
