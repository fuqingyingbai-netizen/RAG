import pytest
import threading
from concurrent.futures import ThreadPoolExecutor

from report_agents.company_transport import bounded_company_invoke, CompanyModelUnavailable


def test_transient_retries_have_one_owner_and_no_phantom_calls():
    calls=[];waits=[]
    def provider(*args):
        calls.append(args)
        raise TimeoutError('sensitive request body must not be logged')
    invoke=bounded_company_invoke(provider,sleep=waits.append)
    assert bounded_company_invoke(invoke) is invoke
    with pytest.raises(CompanyModelUnavailable) as caught:invoke('review','proofs')
    assert caught.value.attempts==len(calls)==3
    assert waits==[1,2]
    assert caught.value.diagnostic['category']=='timeout'
    assert caught.value.diagnostic['request_sent'] is None
    for _ in range(10):
        with pytest.raises(CompanyModelUnavailable) as blocked:invoke('review','proofs')
        assert blocked.value.attempts==0 and not blocked.value.attempted
    assert len(calls)==3


def test_resume_is_a_fresh_finite_observation_and_keeps_provider_response():
    calls=[]
    def provider(*args):
        calls.append(args)
        if len(calls)<3:raise ConnectionError('connection unavailable')
        return ' 原文不变 '
    invoke=bounded_company_invoke(provider,sleep=lambda _:None)
    assert invoke('read','input')==' 原文不变 '
    assert len(calls)==3


@pytest.mark.parametrize('status,category,retryable',[(401,'authentication',False),(402,'balance',False),
    (403,'permission',False),(429,'rate_limit',True),(500,'temporary_server',True),(503,'temporary_server',True),
    (413,'context_limit',False),(422,'configuration',False)])
def test_provider_categories_preserve_safe_http_evidence(status,category,retryable):
    from types import SimpleNamespace as NS
    from report_agents.company_transport import failure_diagnostic
    exc=RuntimeError('Authorization Bearer secret sk-not-for-output; sensitive entire request')
    exc.status_code=status;exc.request_id='req-123'
    exc.response=NS(headers={'retry-after':'3','authorization':'never-output'})
    value=failure_diagnostic(exc,stage='audit',input_hash='bound-input')
    assert value['category']==category and value['retryable'] is retryable
    assert value['http_status']==status and value['provider_request_id']=='req-123'
    assert value['retry_after_seconds']==3 and value['request_sent'] is True
    assert 'secret' not in str(value) and 'Authorization' not in str(value)


def test_auth_failure_is_not_blindly_retried_and_other_batches_are_deferred():
    calls=[]
    def provider(*args):
        calls.append(args);exc=RuntimeError('bad credential');exc.status_code=401;raise exc
    invoke=bounded_company_invoke(provider)
    with pytest.raises(CompanyModelUnavailable) as caught:invoke('write','input')
    assert caught.value.attempts==1
    with pytest.raises(CompanyModelUnavailable) as caught:invoke('read','different')
    assert caught.value.attempts==0
    assert calls==[('write','input')]


def test_rate_limit_respects_retry_after_without_nested_retry_amplification():
    from types import SimpleNamespace as NS
    calls=[];waits=[]
    def provider(*args):
        calls.append(args)
        if len(calls)==1:
            exc=RuntimeError('rate');exc.status_code=429;exc.response=NS(headers={'Retry-After':'7'});raise exc
        return 'ok'
    invoke=bounded_company_invoke(provider,sleep=waits.append)
    assert invoke('review','input')=='ok' and waits==[7] and len(calls)==2


def test_long_retry_after_is_resumable_and_never_busy_waited():
    from types import SimpleNamespace as NS
    exc=RuntimeError('rate');exc.status_code=429;exc.response=NS(headers={'Retry-After':'120'})
    def provider():raise exc
    with pytest.raises(CompanyModelUnavailable) as caught:
        bounded_company_invoke(provider,sleep=lambda _:pytest.fail('must not sleep'))()
    assert caught.value.diagnostic['deferred_until'] and caught.value.attempts==1


def test_budget_limit_propagates_without_turning_into_provider_error():
    from company_flow_state import CompanyFlowLimit
    def provider():raise CompanyFlowLimit('budget')
    with pytest.raises(CompanyFlowLimit):bounded_company_invoke(provider)()


def test_invalid_model_output_is_local_and_does_not_open_global_outage_circuit():
    def provider(role,prompt):
        if role=='invalid':raise ValueError('invalid model JSON')
        return 'valid independent batch'
    invoke=bounded_company_invoke(provider)
    for i in range(4):
        with pytest.raises(CompanyModelUnavailable) as caught:invoke('invalid',str(i))
        assert caught.value.diagnostic['category']=='output_format'
    assert invoke('other','proofs')=='valid independent batch'


def test_different_trace_callbacks_cannot_reset_same_input_attempt_budget():
    calls=[]
    def provider(*args):calls.append(1);raise ValueError('invalid format')
    invoke=bounded_company_invoke(provider)
    for i in range(3):
        with pytest.raises(CompanyModelUnavailable):invoke('same-stage','same-input',lambda *a:None)
    with pytest.raises(CompanyModelUnavailable) as caught:invoke('same-stage','same-input',lambda *a:None)
    assert caught.value.attempts==0 and len(calls)==3


def test_incomplete_native_review_cannot_pass_as_completed_delivery():
    from types import SimpleNamespace
    from research_workflow import ResearchWorkflow
    from test_evidence_ledger_and_section_packages import _sparse_traceable_company_report
    project = SimpleNamespace(target_type='company', company_source_review_package={
        'version': 'company-corpus-v2-native-guard-and-literal-reuse',
        'diagnostic': {'all_candidate_windows_reviewed': False}})
    with pytest.raises(RuntimeError, match='全量既有材料分析尚未完成'):
        ResearchWorkflow.__new__(ResearchWorkflow)._validate_delivery_report(
            project, _sparse_traceable_company_report('https://registry.test/company'))


def test_deferred_synthesis_cannot_pass_as_no_evidence():
    from types import SimpleNamespace
    from research_workflow import ResearchWorkflow
    from test_evidence_ledger_and_section_packages import _sparse_traceable_company_report
    project=SimpleNamespace(target_type='company',company_corpus_digest_package={
        'diagnostic':{'provider_deferred_synthesis_batches':1}})
    with pytest.raises(RuntimeError,match='归纳模型调用尚未完成'):
        ResearchWorkflow.__new__(ResearchWorkflow)._validate_delivery_report(
            project,_sparse_traceable_company_report('https://registry.test/company'))
