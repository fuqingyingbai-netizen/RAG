"""Regression of actual provider envelopes, without spending API quota."""
import json
from types import SimpleNamespace

import pytest

from company_platform import CompanyPlatformAudit, failure_kind, restore_platform_audit
from research_workflow import ResearchWorkflow
from report_agents.company_judicial import build_judicial_package, render_judicial


QUOTA = {'error': {'code': 300008, 'message': '当前积分余额不足，无法完成本次调用。',
                    'data': {'error_type': 'credit_balance_insufficient', 'quota_status': 'insufficient',
                             'retry_allowed': True}}}


def project(name='目标科技股份有限公司', kind='company'):
    return SimpleNamespace(target_name=name, target_type=kind, title=name, industry='制造业', description='')


def workflow(monkeypatch, response):
    w = ResearchWorkflow.__new__(ResearchWorkflow)
    calls, events, saves = [], [], []
    for key in ('QCC_API_KEY', 'TYC_API_KEY', 'XINIU_API_KEY'):
        monkeypatch.setenv(key, 'test-credential')
    monkeypatch.delenv('QCC_ENABLE_IPR_TOOLS', raising=False)
    monkeypatch.setattr(w, '_mcp_initialize', lambda *a, **k: (None, True, ''))
    def call(url, headers, tool, args, **kw):
        calls.append((tool, args))
        return (response(tool, args) if callable(response) else response), None
    monkeypatch.setattr(w, '_mcp_call_tool', call)
    monkeypatch.setattr(w, '_save_structured_source', lambda *a, **k: saves.append(a) or False)
    return w, calls, events, saves


@pytest.mark.parametrize('provider,payload,first,unqueried', [
    ('qcc', QUOTA, 'get_company_registration_info', 6),
    ('tyc', {'error': {'code': 'http_error', 'message': 'HTTP 401: Unauthorized'}}, 'search_companies', 4),
    ('xiniu', {'error': {'code': 'tool_execution_error', 'message': '余额不足或配额已用完'}}, 'get_company_info:企业基本信息', 4),
])
def test_account_failure_stops_all_provider_calls_and_preserves_coverage(monkeypatch, provider, payload, first, unqueried):
    w, calls, events, saves = workflow(monkeypatch, payload)
    p = project()
    result = getattr(w, f'_collect_{provider}_sources')(None, p, p.target_name, {}, emit=events.append)
    assert result == 0 and len(calls) == 1 and not saves
    rows = p.company_professional_platform_attempts
    assert rows[0]['tool'] == first and rows[0]['status'] == 'failed'
    assert rows[0]['arguments']
    assert sum(r['status'] == 'not_queried' for r in rows) == unqueried
    assert not any('未命中' in e['label'] for e in events)
    assert 'test-credential' not in json.dumps(rows)
    if provider == 'qcc':
        text = render_judicial(build_judicial_package({'facts': []}, p.target_name,
                               query_attempts=p.company_judicial_query_attempts))
        assert '账户额度不足' in text and '尚未查询' in text
        assert 'get_company_risk_scan' in text


def test_account_block_applies_to_next_company_but_new_credentials_retry(monkeypatch):
    w, calls, events, _ = workflow(monkeypatch, QUOTA)
    for name in ('甲科技股份有限公司', '乙制造股份有限公司'):
        p = project(name)
        w._collect_qcc_sources(None, p, name, {}, emit=events.append)
    assert len(calls) == 1
    assert all(r['status'] == 'not_queried' for r in p.company_professional_platform_attempts)
    monkeypatch.setenv('QCC_API_KEY', 'new-credential')
    p = project('丙科技股份有限公司')
    w._collect_qcc_sources(None, p, p.target_name, {})
    assert len(calls) == 2


def test_block_expires_and_rate_limit_has_shorter_window(monkeypatch):
    now = [1000.]
    monkeypatch.setattr('company_platform.time.monotonic', lambda: now[0])
    cache = {}
    a = CompanyPlatformAudit(project(), 'qcc', 'credential', cache)
    a.planned(['search'])
    assert a.result('search', {}, {'error': {'message': 'HTTP 429 Too many requests'}})
    now[0] += 61
    b = CompanyPlatformAudit(project(), 'qcc', 'credential', cache)
    assert not b.cached_failure()


@pytest.mark.parametrize('payload,kind', [
    ({'result': {'total': 0, 'items': []}}, ''),
    ({'error': {'message': '本工具未开通'}}, 'tool_unavailable'),
    ({'error': {'message': 'HTTP 403 Forbidden'}}, 'access_denied'),
    ({'error': {'message': 'temporary gateway failure'}}, 'request_failed'),
])
def test_tool_failure_and_real_zero_are_not_account_failure(payload, kind):
    a = CompanyPlatformAudit(project(), 'qcc', 'credential', {})
    assert failure_kind(payload) == kind
    assert not a.result('tool', {}, payload)
    assert a.project.company_professional_platform_attempts[0]['status'] == ('failed' if kind else 'returned')


def test_temporary_errors_do_not_emit_false_no_hit_or_skip_other_tools(monkeypatch):
    w, calls, events, _ = workflow(monkeypatch, {'error': {'message': 'temporary failure'}})
    p = project()
    w._collect_qcc_sources(None, p, p.target_name, {}, emit=events.append)
    assert len(calls) == 7
    assert not any('未命中' in e['label'] for e in events)


def test_actual_zero_return_keeps_search_semantics(monkeypatch):
    w, calls, events, _ = workflow(monkeypatch, {'result': {'total': 0, 'items': []}})
    p = project()
    w._collect_qcc_sources(None, p, p.target_name, {}, emit=events.append)
    assert len(calls) == 7
    assert sum('未命中' in e['label'] for e in events) == 7
    assert all(r['status'] == 'returned' for r in p.company_professional_platform_attempts)


def test_partial_success_keeps_saved_count_when_later_account_failure(monkeypatch):
    w, calls, events, _ = workflow(monkeypatch, lambda tool, args:
        {'result': {'content': [{'text': '目标科技股份有限公司真实登记返回'}]}}
        if tool == 'get_company_registration_info' else QUOTA)
    monkeypatch.setattr(w, '_save_structured_source', lambda *a, **k: True)
    p = project()
    assert w._collect_qcc_sources(None, p, p.target_name, {}, emit=events.append) == 1
    assert len(calls) == 2


def test_initialization_auth_failure_skips_tools(monkeypatch):
    w, calls, events, _ = workflow(monkeypatch, {})
    monkeypatch.setattr(w, '_mcp_initialize', lambda *a, **k: (None, False, 'HTTP 401 Unauthorized'))
    p = project()
    assert w._collect_qcc_sources(None, p, p.target_name, {}, emit=events.append) == 0
    assert not calls
    assert len(p.company_judicial_query_attempts) == 2


def test_document_list_survives_detail_quota_failure(monkeypatch):
    from test_company_judicial import structured, SCAN, cases, case_row
    def response(tool, args):
        if tool == 'get_company_risk_scan':
            return {'text': structured(tool, SCAN)[1]['content']}
        if tool == 'get_judicial_documents':
            return {'text': structured(tool, cases([case_row(did='doc1')]))[1]['content']}
        if tool == 'get_judicial_document_detail':
            return QUOTA
        return {'text': 'valid response'}
    w, calls, events, _ = workflow(monkeypatch, response)
    monkeypatch.setattr(w, '_extract_mcp_text', lambda p, **kw: p.get('text', ''))
    saved = []
    monkeypatch.setattr(w, '_save_structured_source', lambda *a, **k: saved.append(a) or True)
    from test_company_judicial import NAME
    p = project(NAME)
    added = w._collect_qcc_sources(None, p, p.target_name, {})
    assert added == len(saved)
    assert any(a[4].startswith('企查查-get_judicial_documents') for a in saved)
    assert not any(a[4].startswith('企查查-get_judicial_document_detail') for a in saved)


def test_collection_persists_audit_and_restores_judicial_gaps(monkeypatch):
    w, calls, events, _ = workflow(monkeypatch, QUOTA)
    saved = []
    monkeypatch.setattr(w, 'save_artifact', lambda *a, **kw: saved.append(a))
    p = project()
    assert w.collect_structured_sources(None, p, {}, events.append) == 0
    assert len(calls) == 3 and len(saved) == 1
    assert saved[0][2] == 'professional_platform_audit'
    fresh = project()
    restore_platform_audit(fresh, json.loads(saved[0][4]))
    assert fresh.company_judicial_query_attempts == p.company_judicial_query_attempts
    assert len(fresh.company_professional_platform_attempts) == 17


def test_transport_timeout_keeps_attempt_and_unqueried_tools_in_durable_audit(monkeypatch):
    import requests
    w, calls, events, _ = workflow(monkeypatch, {})
    def timeout(*a, **k):
        raise requests.Timeout('provider transport timeout')
    monkeypatch.setattr(w, '_mcp_call_tool', timeout)
    saved = []
    monkeypatch.setattr(w, 'save_artifact', lambda *a, **kw: saved.append(a))
    p = project()
    assert w.collect_structured_sources(None, p, {}, events.append) == 0
    rows = json.loads(saved[0][4])['attempts']
    attempted = next(r for r in rows if r['tool'] == 'get_company_registration_info')
    assert attempted['status'] == 'failed' and attempted['arguments']['searchKey'] == p.target_name
    assert attempted['error_code'] == 'transport_error'
    risk = next(r for r in rows if r['tool'] == 'get_company_risk_scan')
    assert risk['status'] == 'not_queried' and risk['reason'] == 'transport_failed'


@pytest.mark.parametrize('error', [
    {'message':'HTTP 403 当前可用额度不足。'},
    {'code':'insufficient_user_quota','message':'HTTP 403'},
])
def test_relay_quota_failure_takes_priority_over_generic_403(error):
    assert failure_kind({'error':error}) == 'quota_exceeded'
