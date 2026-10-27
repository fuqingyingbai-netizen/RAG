import pytest
import threading
from concurrent.futures import ThreadPoolExecutor

from report_agents.company_transport import bounded_company_invoke, CompanyModelUnavailable


@pytest.mark.parametrize('raises', [False, True])
def test_failed_provider_does_not_retry_for_every_queued_batch(raises):
    calls = []
    def unavailable(*args):
        calls.append(args)
        if raises:
            raise RuntimeError('provider unavailable')
        return ''
    invoke = bounded_company_invoke(unavailable, cooldown_seconds=0)
    for _ in range(100):
        with pytest.raises(CompanyModelUnavailable):
            invoke('role', 'prompt', None)
    assert len(calls) == 5


def test_success_resets_consecutive_failures_and_wrapping_is_idempotent():
    answers = iter(['', 'ok', '', '', 'ok'])
    invoke = bounded_company_invoke(lambda: next(answers))
    assert bounded_company_invoke(invoke) is invoke
    for expected in ['', 'ok', '', '', 'ok']:
        if expected:
            assert invoke() == expected
        else:
            with pytest.raises(CompanyModelUnavailable):
                invoke()


@pytest.mark.parametrize('raises', [False, True])
def test_transient_outage_recovers_without_replacing_or_rewriting_response(raises):
    calls = []
    response = ' {"quoted_source": "原件：百萬元；申请撤回上诉"} '
    def provider(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) <= 3:
            if raises:
                raise RuntimeError('connection failed')
            return ''
        return response
    invoke = bounded_company_invoke(provider, cooldown_seconds=0)
    for _ in range(3):
        with pytest.raises(CompanyModelUnavailable) as exc:
            invoke('role', 'prompt', target='公司')
        assert exc.value.attempted is True
    assert invoke('role', 'prompt', target='公司') == response
    assert invoke('next', 'fresh') == response
    assert calls[3] == (('role', 'prompt'), {'target': '公司'})
    assert calls[4] == (('next', 'fresh'), {})


def test_only_one_recovery_request_runs_and_waiters_resume_after_its_success():
    probe_started = threading.Event()
    release_probe = threading.Event()
    lock = threading.Lock()
    calls = 0
    def provider():
        nonlocal calls
        with lock:
            calls += 1
            number = calls
        if number <= 3:
            raise RuntimeError('offline')
        if number == 4:
            probe_started.set()
            assert release_probe.wait(5)
        return 'ok'
    invoke = bounded_company_invoke(provider, cooldown_seconds=0)
    for _ in range(3):
        with pytest.raises(CompanyModelUnavailable):
            invoke()
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(invoke) for _ in range(6)]
        try:
            assert probe_started.wait(5)
            with lock:
                assert calls == 4
            assert all(not f.done() for f in futures)
        finally:
            release_probe.set()
        assert [f.result(timeout=5) for f in futures] == ['ok'] * 6
    assert calls == 9


def test_late_inflight_success_reopens_guard_after_failure_budget_exhausted():
    started = threading.Event()
    release = threading.Event()
    def provider(role):
        if role == 'slow':
            started.set()
            assert release.wait(5)
            return 'fresh actual response'
        if role == 'fail':
            raise RuntimeError('offline')
        return 'recovered'
    invoke = bounded_company_invoke(provider, cooldown_seconds=0)
    with ThreadPoolExecutor(max_workers=1) as pool:
        slow = pool.submit(invoke, 'slow')
        try:
            assert started.wait(5)
            for _ in range(5):
                with pytest.raises(CompanyModelUnavailable) as exc:
                    invoke('fail')
                assert exc.value.attempted is True
            with pytest.raises(CompanyModelUnavailable) as exc:
                invoke('not actually attempted')
            assert exc.value.attempted is False
        finally:
            release.set()
        assert slow.result(timeout=5) == 'fresh actual response'
    assert invoke('next') == 'recovered'


def test_recovery_waits_for_cooldown_and_success_resets_next_outage_budget(monkeypatch):
    import report_agents.company_transport as transport
    clock = [100.0]
    waits = []
    real_condition = threading.Condition
    class AdvancingCondition(real_condition):
        def wait(self, timeout=None):
            assert timeout is not None and timeout > 0
            waits.append(timeout)
            clock[0] += timeout
    monkeypatch.setattr(transport.threading, 'Condition', AdvancingCondition)
    monkeypatch.setattr(transport.time, 'monotonic', lambda: clock[0])
    answers = iter(['', '', '', 'ok', '', '', '', 'second recovery'])
    invoke = bounded_company_invoke(lambda: next(answers), cooldown_seconds=30)
    for expected in ['', '', '', 'ok', '', '', '', 'second recovery']:
        if expected:
            assert invoke() == expected
        else:
            with pytest.raises(CompanyModelUnavailable):
                invoke()
    assert waits == [30, 30]


def test_persistent_outage_has_one_probe_at_a_time_and_finite_provider_calls():
    calls = []
    def provider():
        calls.append(1)
        raise RuntimeError('still offline')
    invoke = bounded_company_invoke(provider, cooldown_seconds=0)
    def attempt():
        with pytest.raises(CompanyModelUnavailable) as exc:
            invoke()
        return exc.value.attempted
    with ThreadPoolExecutor(max_workers=6) as pool:
        attempted = list(pool.map(lambda _: attempt(), range(100)))
    assert len(calls) == sum(attempted) == 5
    assert attempted.count(False) == 95


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
