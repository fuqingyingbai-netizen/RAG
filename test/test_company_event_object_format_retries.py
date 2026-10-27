"""Malformed object syntax never supplies a semantic or approval witness."""
from copy import deepcopy
import json

import pytest

from report_agents.company_event_evidence import VERSION, _object_answer, reviewed_event_records, review_primary_events, validate_event
from test_company_event_impact_and_dates import TARGET, AS_OF, check, selection, source


@pytest.mark.parametrize('broken', [
    '<escape>{"status":"supported","criteria":{}}</escape>',
    '[{"status":"supported"}]', '```JSON\n{"status":"supported"}\n```',
])
def test_unreadable_checker_gets_fresh_full_context_retry_without_reextracting_facts(broken):
    native = source(); row = selection(native); row.pop('independent_check')
    before = deepcopy(row); calls = []; checker_prompts = []
    def invoke(role,prompt,trace):
        calls.append(role)
        assert native['content'] in prompt
        if role == '公司监管原件提取':return json.dumps({'event':row},ensure_ascii=False)
        assert role == '公司监管原件独立核对'
        candidate = json.JSONDecoder().raw_decode(prompt.rsplit('\n提取：',1)[1])[0]
        assert candidate['summary'] == before['summary'] and 'independent_check' not in candidate
        checker_prompts.append(prompt)
        return broken if len(checker_prompts) == 1 else json.dumps(check(),ensure_ascii=False)
    result = review_primary_events([native],TARGET,AS_OF,invoke)
    assert calls == ['公司监管原件提取','公司监管原件独立核对','公司监管原件独立核对']
    assert result['receipts'][0]['state'] == 'accepted'
    event = result['events'][0]
    assert event['summary'] == before['summary'] and not validate_event(event,native,TARGET,AS_OF)
    attempts = result['receipts'][0]['object_response_attempts']
    assert [attempt['json_object_parsed'] for attempt in attempts] == [True,False,True]
    assert attempts[1]['raw_response'] == broken
    assert len(result['receipts'][0]['semantic_attempts']) == 1
    assert '上次返回不是可解析的JSON对象' in checker_prompts[1]


def test_two_unreadable_green_looking_checks_stay_unfinished_and_supply_no_approval():
    native = source(); row = selection(native); row.pop('independent_check'); calls = []
    malformed = '<escape>'+json.dumps(check())+'</escape>'
    def invoke(role,prompt,trace):
        calls.append(role)
        return json.dumps({'event':row}) if role == '公司监管原件提取' else malformed
    result = review_primary_events([native],TARGET,AS_OF,invoke)
    assert calls == ['公司监管原件提取','公司监管原件独立核对','公司监管原件独立核对']
    assert not result['events'] and result['receipts'][0]['state'] == 'requires_review'
    assert 'independent_check' not in result['receipts'][0]
    assert [attempt['json_object_parsed'] for attempt in result['receipts'][0]['object_response_attempts']] == [True,False,False]


@pytest.mark.parametrize('broken_role', ['公司监管原件提取','公司监管原件提取修复','公司监管原件语义修复'])
def test_each_object_stage_retries_format_only_and_still_requires_source_and_fresh_checker(broken_role):
    native = source(); good = selection(native); good.pop('independent_check')
    initial = deepcopy(good)
    if broken_role == '公司监管原件提取修复':initial['source_date'] = None
    counts = {}; calls = []
    def invoke(role,prompt,trace):
        calls.append(role); counts[role] = counts.get(role,0)+1
        assert native['content'] in prompt
        if role == broken_role and counts[role] == 1:return 'unreadable object, not a verdict'
        if role == '公司监管原件提取':return json.dumps({'event':initial},ensure_ascii=False)
        if role == '公司监管原件独立核对':
            return json.dumps(check(factual_support=not (broken_role == '公司监管原件语义修复' and counts[role] == 1)))
        assert role in {'公司监管原件提取修复','公司监管原件语义修复'}
        return json.dumps({'event':good},ensure_ascii=False)
    result = review_primary_events([native],TARGET,AS_OF,invoke)
    assert counts[broken_role] == 2 and result['receipts'][0]['state'] == 'accepted'
    assert not validate_event(result['events'][0],native,TARGET,AS_OF)
    if broken_role == '公司监管原件语义修复':
        assert calls.count('公司监管原件独立核对') == 2
        assert result['receipts'][0]['semantic_attempts'][0]['check']['criteria']['factual_support'] is False


def test_valid_unsupported_check_requires_semantic_repair_instead_of_sampling_for_green():
    native = source(); row = selection(native); row.pop('independent_check'); calls = []
    def invoke(role,prompt,trace):
        calls.append(role)
        if role == '公司监管原件独立核对':
            return json.dumps(check(factual_support=calls.count(role)>1))
        assert role in {'公司监管原件提取','公司监管原件语义修复'}
        return json.dumps({'event':row},ensure_ascii=False)
    result = review_primary_events([native],TARGET,AS_OF,invoke)
    assert calls == ['公司监管原件提取','公司监管原件独立核对','公司监管原件语义修复','公司监管原件独立核对']
    assert result['receipts'][0]['state'] == 'accepted'
    assert all(attempt['json_object_parsed'] for attempt in result['receipts'][0]['object_response_attempts'])


@pytest.mark.parametrize('tail', [' {}',' []',' 但本案是否已经生效并未得到证明。',']}'])
def test_checker_does_not_drop_additional_data_after_a_supported_json_prefix(tail):
    with pytest.raises(ValueError):
        _object_answer(json.dumps(check(),ensure_ascii=False)+tail)


def test_one_complete_fenced_object_retains_all_original_values():
    answer = check()
    assert _object_answer('```json\n'+json.dumps(answer,ensure_ascii=False)+'\n```') == answer


def test_empty_checker_response_remains_a_transport_failure_and_supplies_no_verdict():
    native = source(); row = selection(native); row.pop('independent_check'); calls = []
    def invoke(role,prompt,trace):
        calls.append(role)
        return json.dumps({'event':row}) if role == '公司监管原件提取' else ''
    result = review_primary_events([native],TARGET,AS_OF,invoke)
    assert calls == ['公司监管原件提取','公司监管原件独立核对']
    assert not result['events'] and result['receipts'][0]['state'] == 'requires_review'
    assert result['receipts'][0]['error_type'] == 'CompanyModelUnavailable'
    assert 'independent_check' not in result['receipts'][0]


def test_old_parsed_prefix_contract_needs_a_fresh_complete_object_review():
    native = source(); row = selection(native)
    old = {'version':'company-event-evidence-v3-actor-obligation-boundaries',
           'target_name':TARGET,'as_of_date':AS_OF,'events':[row]}
    assert not reviewed_event_records(old,[native],TARGET,AS_OF)
    calls = []
    def invoke(role,prompt,trace):
        calls.append(role)
        return json.dumps({'event':row} if role == '公司监管原件提取' else check(),ensure_ascii=False)
    result = review_primary_events([native],TARGET,AS_OF,invoke,cache=old)
    assert calls == ['公司监管原件提取','公司监管原件独立核对']
    assert result['version'] == VERSION and result['receipts'][0]['state'] == 'accepted'
    assert not result['receipts'][0].get('reused')
