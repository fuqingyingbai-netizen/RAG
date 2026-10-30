"""Green review flags cannot authorize altered inputs or invented amounts."""
from copy import deepcopy
import json
import pytest

from report_agents.company_event_evidence import (
    validate_event, reviewed_event_records, review_primary_events, independent_check_witness,
)
from test_company_event_impact_and_dates import TARGET,AS_OF,source,selection,check,package


@pytest.mark.parametrize('mutation', ['summary','scope','reason','missing_witness','witness'])
def test_review_receipt_invalidates_even_when_changed_text_still_has_literal_support(mutation):
    s=source();row=selection(s)
    assert not validate_event(row,s,TARGET,AS_OF)
    if mutation=='summary':row['summary']+='目标公司为原告。'
    elif mutation=='scope':row['subject_scope']+='原文未说明实际收款。'
    elif mutation=='reason':row['independent_check']['reason']+='补充理由。'
    elif mutation=='missing_witness':row.pop('independent_check_witness')
    else:row['independent_check_witness']['input_sha256']='0'*64
    assert 'independent_check_input_or_response_changed' in validate_event(row,s,TARGET,AS_OF)
    assert not reviewed_event_records(package(row),[s],TARGET,AS_OF)


@pytest.mark.parametrize('extra',['','另案判赔657万元。'])
def test_a_bound_green_review_with_its_own_unsupported_award_still_fails(extra):
    s=source(extra);row=selection(s)
    row['independent_check']['reason']='判赔657万元，三部分为350万元、300万元、5万元，核对通过。'
    row['independent_check_witness']=independent_check_witness(row,row['independent_check'],TARGET,AS_OF)
    assert 'independent_reason_unsupported_quantity:657万元' in validate_event(row,s,TARGET,AS_OF)


@pytest.mark.parametrize('verdict',['supported',[],{'status':'supported','criteria':[]}])
def test_malformed_cached_review_is_pending_instead_of_crashing_the_report(verdict):
    s=source();row=selection(s);row['independent_check']=verdict
    row['independent_check_witness']=independent_check_witness(row,verdict,TARGET,AS_OF)
    assert validate_event(row,s,TARGET,AS_OF)
    assert not reviewed_event_records(package(row),[s],TARGET,AS_OF)


def test_bad_review_amount_gets_a_fresh_blind_review_without_rewriting_supported_extraction():
    s=source();candidate=selection(s);calls=[];review_inputs=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        if role=='公司监管原件提取':return json.dumps({'event':deepcopy(candidate)},ensure_ascii=False)
        assert role=='公司监管原件独立核对'
        payload=json.loads(prompt.split('\n提取：',1)[1]);review_inputs.append(payload)
        assert 'independent_check' not in payload and 'independent_check_witness' not in payload
        verdict=check();verdict['reason']='判赔657万元，核对通过。' if len(review_inputs)==1 else '判赔655万元，核对通过。'
        return json.dumps(verdict,ensure_ascii=False)
    result=review_primary_events([s],TARGET,AS_OF,invoke)
    assert calls==['公司监管原件提取','公司监管原件独立核对','公司监管原件独立核对']
    assert review_inputs[0]==review_inputs[1]
    assert result['events'][0]['summary']==candidate['summary']
    assert result['receipts'][0]['semantic_attempts'][0]['errors']
    assert not validate_event(result['events'][0],s,TARGET,AS_OF)
