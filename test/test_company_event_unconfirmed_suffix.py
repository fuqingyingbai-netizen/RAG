"""Unconfirmed state labels do not assert finality; separate assertions do."""
import json
import pytest
from report_agents.company_event_evidence import case_state_errors,validate_event,review_primary_events
from test_company_event_impact_and_dates import TARGET,AS_OF,source,selection,check


@pytest.mark.parametrize('scope',[
    '故判决生效及执行状态无法确认。',
    '判決生效及執行狀態無法確認。',
    '本案原判生效与否尚不能确认。',
    '判决生效情况无法核实。',
    '判决生效与赔偿款到账状态仍无法确定。',
])
def test_unknown_state_label_is_not_a_completed_judgment(scope):
    row=selection();row['subject_scope']=scope
    assert not case_state_errors(row,source()['content'])
    assert not validate_event(row,source(),TARGET,AS_OF,require_independent=False)
    assert 'independent_check_input_or_response_changed' in validate_event(row,source(),TARGET,AS_OF)


@pytest.mark.parametrize('scope',[
    '判决已生效及执行状态无法确认。',
    '判决生效且执行状态无法确认。',
    '判决生效，但执行状态无法确认。',
    '判决生效，执行状态无法确认。',
    '2025年判决生效及执行状态无法确认。',
])
def test_separate_or_explicit_finality_cannot_borrow_unknown_execution_state(scope):
    row=selection();row['subject_scope']=scope
    assert 'unproven_judgment_finality' in case_state_errors(row,source()['content'])


def test_qualified_unknown_state_still_gets_a_fresh_independent_review():
    s=source();row=selection(s);row['subject_scope']+='故判决生效及执行状态无法确认。';calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        if role=='公司监管原件提取':return json.dumps({'event':row},ensure_ascii=False)
        assert role=='公司监管原件独立核对'
        return json.dumps(check(),ensure_ascii=False)
    result=review_primary_events([s],TARGET,AS_OF,invoke)
    assert calls==['公司监管原件提取','公司监管原件独立核对']
    assert result['events'] and not validate_event(result['events'][0],s,TARGET,AS_OF)
