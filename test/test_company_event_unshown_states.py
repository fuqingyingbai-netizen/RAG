"""Source-not-shown lists stay unknown; completed acts still need proof."""
from copy import deepcopy
import json

import pytest

from report_agents.company_event_evidence import (
    case_state_errors, review_candidate, review_primary_events, validate_event,
)
from test_company_event_impact_and_dates import TARGET, AS_OF, source, selection, check


@pytest.mark.parametrize('qualification', [
    '原文未显示二审法院已准许撤回、判决已生效或赔偿款已到账。',
    '原文未明示法院准许撤回上诉、判决生效或赔偿款已到账。',
    '本页未明确显示原判已经生效。',
    '原文未顯示法院已准許撤回上訴、判決已生效或賠償款已到賬。',
    '申请撤回上诉与法院准许撤回、判决生效、判赔义务履行或赔偿款到账为不同状态。',
])
def test_bounded_unknown_list_is_not_an_assertion_or_independent_verdict(qualification):
    row = selection(); row['summary'] += qualification; before = deepcopy(row)
    assert not case_state_errors(row, source()['content'])
    assert not validate_event(row, source(), TARGET, AS_OF, require_independent=False)
    assert 'independent_check_input_or_response_changed' in validate_event(row, source(), TARGET, AS_OF)
    assert row == before


@pytest.mark.parametrize('qualification,error', [
    ('原文未显示判决已生效，但赔偿款已到账。', 'unproven_compensation_receipt'),
    ('原文未显示赔偿款已到账，原判已经生效。', 'unproven_judgment_finality'),
    ('原文未显示判决已生效而赔偿款已到账。', 'unproven_compensation_receipt'),
    ('申请撤回上诉与判决已生效为不同状态。', 'unproven_judgment_finality'),
    ('原文未明示其他事项而是上诉已撤回。', 'unproven_withdrawal_completion'),
])
def test_negative_or_distinction_text_cannot_hide_a_separate_completed_act(qualification, error):
    row = selection(); row['summary'] = qualification
    assert error in case_state_errors(row, source()['content'])


@pytest.mark.parametrize('assertion,error', [
    ('原判已经生效。', 'unproven_judgment_finality'),
    ('赔偿款已经到账。', 'unproven_compensation_receipt'),
])
def test_source_not_shown_list_cannot_supply_proof_of_a_positive_claim(assertion, error):
    row = selection()
    row['quote'] += '原文未显示二审法院已准许撤回、原判已经生效或赔偿款已经到账。'
    row['summary'] = assertion
    assert error in case_state_errors(row, source()['content'])


def failed_native_cache():
    native = source(); good = review_candidate(selection(native))
    good['summary'] += '原文未显示二审法院已准许撤回、判决已生效或赔偿款已到账。'
    first = deepcopy(good); first['date_quote'] = None
    def invoke(role, prompt, trace):
        if role == '公司监管原件提取': return json.dumps({'event': first}, ensure_ascii=False)
        if role == '公司监管原件提取修复': return json.dumps({'event': good}, ensure_ascii=False)
        assert role == '公司监管原件独立核对'
        raise RuntimeError('review service temporarily unavailable')
    cache = review_primary_events([native], TARGET, AS_OF, invoke)
    assert not cache['events'] and cache['receipts'][0]['state'] == 'requires_review'
    cache['version'] = 'company-event-evidence-v6-qualified-state-scope'
    return native, good, cache


def test_actual_raw_repair_can_resume_only_through_fresh_independent_review():
    native, good, cache = failed_native_cache(); before = deepcopy(cache); calls = []
    def invoke(role, prompt, trace):
        calls.append(role)
        assert role == '公司监管原件独立核对'
        assert '"independent_check"' not in prompt
        return json.dumps(check(), ensure_ascii=False)
    result = review_primary_events([native], TARGET, AS_OF, invoke, cache=cache)
    assert calls == ['公司监管原件独立核对'] and cache == before
    assert result['receipts'][0]['proposal_reused_from_raw_cache'] is True
    assert result['receipts'][0]['cached_proposal_witness']['role'] == '公司监管原件提取修复'
    assert result['events'][0]['summary'] == good['summary']
    assert not validate_event(result['events'][0], native, TARGET, AS_OF)


@pytest.mark.parametrize('defect', ['body', 'request_hash', 'verdict_only', 'version', 'date', 'url'])
def test_stale_or_unbound_raw_proposal_requires_new_extraction(defect):
    native, good, cache = failed_native_cache()
    if defect == 'body': native['content'] += '\n新取得的资料。'
    if defect == 'request_hash':
        for attempt in cache['receipts'][0]['object_response_attempts']: attempt['input_sha256'] = '0' * 64
    if defect == 'verdict_only': cache['receipts'][0].pop('object_response_attempts')
    if defect == 'version': cache['version'] = 'unknown-event-contract'
    if defect == 'date': cache['as_of_date'] = '2026-10-23'
    if defect == 'url': cache['receipts'][0]['source_url'] += '?different-original=1'
    calls = []
    def invoke(role, prompt, trace):
        calls.append(role)
        if role == '公司监管原件提取': return json.dumps({'event': good}, ensure_ascii=False)
        assert role == '公司监管原件独立核对'
        return json.dumps(check(), ensure_ascii=False)
    result = review_primary_events([native], TARGET, AS_OF, invoke, cache=cache)
    assert calls == ['公司监管原件提取', '公司监管原件独立核对']
    assert result['events'] and not result['receipts'][0].get('proposal_reused_from_raw_cache')


def test_pending_fresh_review_does_not_drop_the_original_proposal_or_grant_approval():
    native, good, cache = failed_native_cache(); calls = []
    def unavailable(role, prompt, trace):
        calls.append(role); assert role == '公司监管原件独立核对'
        raise RuntimeError('still unavailable')
    pending = review_primary_events([native], TARGET, AS_OF, unavailable, cache=cache)
    assert not pending['events'] and calls == ['公司监管原件独立核对']
    assert pending['receipts'][0]['state'] == 'requires_review'
    calls.clear()
    def recovered(role, prompt, trace):
        calls.append(role); assert role == '公司监管原件独立核对'
        return json.dumps(check(), ensure_ascii=False)
    resumed = review_primary_events([native], TARGET, AS_OF, recovered, cache=pending)
    assert calls == ['公司监管原件独立核对'] and resumed['events']
    assert len(resumed['receipts'][0]['cached_proposal_receipt']['object_response_attempts']) == 2


def test_a_rejected_fresh_verdict_cannot_be_overridden_by_a_cached_proposal():
    native, good, cache = failed_native_cache(); calls = []
    def invoke(role, prompt, trace):
        calls.append(role)
        if role == '公司监管原件独立核对':
            return json.dumps(check(actors_and_obligations=False), ensure_ascii=False)
        assert role == '公司监管原件语义修复'
        return json.dumps({'event': None})
    result = review_primary_events([native], TARGET, AS_OF, invoke, cache=cache)
    assert calls == ['公司监管原件独立核对', '公司监管原件语义修复']
    assert not result['events'] and result['receipts'][0]['state'] == 'requires_review'
