from copy import deepcopy
import pytest

from industry_stage_cache import stage_cache_issue


def test_all_failed_cleaning_is_retained_but_not_reused():
    payload={'facts':[{'cleaning_method':'industry_rule','fact':'原文仍然保留'}],
             'cleaning_diagnostic':{'circuit_open':True}}
    before=deepcopy(payload)
    assert stage_cache_issue(payload,'cleaned_facts') == 'previous_cleaning_model_failed'
    assert payload == before


def test_partial_model_success_is_not_discarded_or_forced_to_repeat():
    payload={'facts':[{'cleaning_method':'llm'}],'cleaning_diagnostic':{'circuit_open':True}}
    assert not stage_cache_issue(payload,'cleaned_facts')
    assert not stage_cache_issue({'facts':[]},'cleaned_facts')


@pytest.mark.parametrize('status',['empty_or_invalid_json','request_failed','connection_failed'])
def test_failed_risk_requests_are_not_a_cache_hit(status):
    assert stage_cache_issue({'validation_diagnostics':{'primary_status':status}},'risk_assessment')


def test_legitimate_evidence_unknown_is_reusable_without_inventing_a_score():
    payload={'dimensions':[{'score':None,'unknown_cause':'insufficient_applicable_evidence'}]}
    before=deepcopy(payload)
    assert not stage_cache_issue(payload,'risk_assessment') and payload == before


def test_workflow_errors_and_corrupt_payloads_cannot_pass_reuse():
    assert stage_cache_issue({'workflow_error':{'stage':'risk'}},'risk_assessment')
    assert stage_cache_issue(None,'cleaned_facts')
