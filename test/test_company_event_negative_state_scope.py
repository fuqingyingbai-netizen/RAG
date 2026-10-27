"""Absence of a completed act is separate from an affirmative completion."""
from copy import deepcopy
import json

import pytest

from report_agents.company_event_evidence import case_state_errors, review_primary_events, validate_event
from test_company_event_impact_and_dates import TARGET, AS_OF, check, selection, source


@pytest.mark.parametrize('negative', [
    '未称', '未稱', '未说明', '未說明', '未披露', '未提及', '未表明',
    '未能确认', '未能確認', '未能证实', '未曾说明', '未见', '未見',
])
def test_explicit_absence_of_reported_completion_is_not_an_asserted_completion(negative):
    row = selection()
    row['summary'] += '原文'+negative+'法院准许撤回上诉、判决生效或赔偿款已到账。'
    before = deepcopy(row)
    assert not case_state_errors(row, source()['content'])
    assert not validate_event(row, source(), TARGET, AS_OF)
    assert row == before


@pytest.mark.parametrize('connector', ['但', '但是', '然而', '不过', '不過', '却', '卻'])
@pytest.mark.parametrize('affirmative,error', [
    ('上诉已撤回', 'unproven_withdrawal_completion'),
    ('原判已经生效', 'unproven_judgment_finality'),
    ('赔偿款已经到账', 'unproven_compensation_receipt'),
])
def test_contrasting_positive_act_cannot_borrow_an_earlier_negative_qualification(connector, affirmative, error):
    row = selection()
    row['summary'] = '原文未称另一个程序已完成'+connector+affirmative+'。'
    assert error in case_state_errors(row, source()['content'])


@pytest.mark.parametrize('affirmative,error', [
    ('上诉已撤回', 'unproven_withdrawal_completion'),
    ('原判已经生效', 'unproven_judgment_finality'),
    ('赔偿款已经到账', 'unproven_compensation_receipt'),
])
def test_negative_language_in_source_is_not_proof_of_a_positive_generated_act(affirmative, error):
    row = selection()
    row['quote'] += '原文未称法院准许撤回上诉、判决生效或赔偿款已经到账。'
    row['summary'] = affirmative+'。'
    assert error in case_state_errors(row, source()['content'])


def test_actual_negative_list_shape_still_requires_fresh_complete_independent_review():
    native = source(); row = selection(native); row.pop('independent_check')
    row['summary'] += '原文未称法院准许撤回、判决生效或赔偿款到账。'
    assert not validate_event(row, native, TARGET, AS_OF, require_independent=False)
    assert 'independent_check_missing' in validate_event(row, native, TARGET, AS_OF)
    calls = []
    def invoke(role, prompt, trace):
        calls.append(role)
        if role == '公司监管原件提取':
            return json.dumps({'event':row}, ensure_ascii=False)
        assert role == '公司监管原件独立核对'
        assert '"independent_check"' not in prompt
        return json.dumps(check(), ensure_ascii=False)
    package = review_primary_events([native], TARGET, AS_OF, invoke)
    assert calls == ['公司监管原件提取','公司监管原件独立核对']
    assert package['receipts'][0]['state'] == 'accepted'
    assert package['events'][0]['summary'] == row['summary']
