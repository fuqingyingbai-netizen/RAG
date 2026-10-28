import json
from concurrent.futures import ThreadPoolExecutor

import pytest
import requests

import assistant_online
import tavily_keys
import web_search
from tavily_keys import TavilyKeyPool, TavilyKeysUnavailable, get_tavily_pool, tavily_api_keys
from web_search import WebSearchProvider


@pytest.fixture(autouse=True)
def isolated_pool(monkeypatch):
    monkeypatch.delenv('TAVILY_API_KEY', raising=False)
    monkeypatch.delenv('TAVILY_API_KEYS', raising=False)
    monkeypatch.setattr(tavily_keys, '_pool', None)


def reply(status=200, payload=None, headers=None):
    response = requests.Response()
    response.status_code = status
    response.url = 'https://api.tavily.com/search'
    response._content = json.dumps(payload if payload is not None else {'results': []}).encode()
    response.headers.update(headers or {})
    return response


def key_from(kwargs):
    return kwargs['headers']['Authorization'].removeprefix('Bearer ')


def test_pool_order_deduplication_and_legacy_compatibility(monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEY', 'legacy')
    assert tavily_api_keys() == ('legacy',)
    monkeypatch.setenv('TAVILY_API_KEYS', ' first,second;first\nthird ')
    assert tavily_api_keys() == ('first', 'second', 'third')
    monkeypatch.setenv('TAVILY_API_KEYS', '["second", "first", "second"]')
    assert tavily_api_keys() == ('second', 'first')


def test_bad_pool_configuration_does_not_echo_secret(monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEYS', '["private-credential",broken')
    with pytest.raises(ValueError) as failure:
        tavily_api_keys()
    assert 'private-credential' not in str(failure.value)


@pytest.mark.parametrize('status,message', [
    (401, 'invalid key'), (403, 'forbidden'), (402, 'payment required'),
    (432, 'key limit'), (433, 'monthly quota'),
    (429, 'This request exceeds your plan usage limit. Upgrade or wait for reset.'),
])
def test_credential_failure_retries_same_query_then_sticks_to_working_key(monkeypatch, status, message):
    monkeypatch.setenv('TAVILY_API_KEYS', 'first-secret,second-secret')
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs)
        return reply(status, {'detail': {'error': message}}) if key_from(kwargs) == 'first-secret' else reply()
    monkeypatch.setattr(web_search.requests, 'post', post)
    result = WebSearchProvider()._search_tavily('same query', 6, ['issuer.test'], ['other.test'])
    WebSearchProvider()._search_tavily('next query', 6)
    assert [key_from(call) for call in calls] == ['first-secret', 'second-secret', 'second-secret']
    assert calls[0]['json'] == calls[1]['json']
    assert calls[1]['json']['include_domains'] == ['issuer.test']
    assert calls[1]['json']['exclude_domains'] == ['other.test']
    assert result.audit['key_slot'] == 2
    assert result.audit['key_failovers'][0]['key_slot'] == 1
    assert 'first-secret' not in str(result.audit) and 'second-secret' not in str(result.audit)


@pytest.mark.parametrize('status', [400, 422, 500, 503])
def test_query_and_service_errors_do_not_try_every_credential(status):
    calls = []
    def post(url, **kwargs):
        calls.append(key_from(kwargs))
        return reply(status, {'detail': 'unavailable'})
    with pytest.raises(requests.HTTPError):
        TavilyKeyPool(('first', 'second')).search({'query': 'q'}, post=post)
    assert calls == ['first']


@pytest.mark.parametrize('error', [requests.Timeout, requests.ConnectionError])
def test_network_errors_do_not_rotate_or_quarantine_credentials(error):
    pool = TavilyKeyPool(('first', 'second'))
    calls = []
    def fail(url, **kwargs):
        calls.append(key_from(kwargs))
        raise error('connection failed')
    with pytest.raises(error):
        pool.search({'query': 'q'}, post=fail)
    pool.search({'query': 'q'}, post=lambda url, **kwargs: calls.append(key_from(kwargs)) or reply())
    assert calls == ['first', 'first']


def test_empty_results_are_successful_and_do_not_rotate():
    calls = []
    payload, audit = TavilyKeyPool(('first', 'second')).search(
        {'query': 'q'}, post=lambda url, **kwargs: calls.append(key_from(kwargs)) or reply())
    assert payload == {'results': []} and calls == ['first'] and audit['key_failovers'] == []


def test_research_and_assistant_share_quarantine_and_pool_only_config(monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEYS', 'first-secret,second-secret')
    monkeypatch.setenv('ASSISTANT_SEARCH_PROVIDER', 'tavily')
    calls = []
    def post(url, **kwargs):
        calls.append(key_from(kwargs))
        if calls[-1] == 'first-secret':
            return reply(433)
        return reply(payload={'results': [{'title': 'Source', 'url': 'https://issuer.test', 'content': 'snippet'}]})
    monkeypatch.setattr(web_search.requests, 'post', post)
    assert WebSearchProvider().search_single('tavily', 'research', 1)
    result = assistant_online.search_web('assistant')
    assert result['status'] == 'ok' and result['provider'] == 'tavily'
    assert calls == ['first-secret', 'second-secret', 'second-secret']
    assert 'secret' not in str(result)


def test_exhausted_pool_falls_back_without_permanently_disabling_tavily(monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEYS', 'first,second')
    monkeypatch.setenv('SERPER_API_KEY', 'configured')
    calls = []
    def post(url, **kwargs):
        calls.append(key_from(kwargs))
        return reply(433)
    monkeypatch.setattr(web_search.requests, 'post', post)
    provider = WebSearchProvider()
    provider.engines = [('tavily', provider._search_tavily), ('serper', lambda *a: [{'url': 'https://fallback.test'}])]
    first = provider.multi_engine_search('first', 1)
    second = provider.multi_engine_search('second', 1)
    assert first[0]['url'] == second[0]['url'] == 'https://fallback.test'
    assert calls == ['first', 'second', 'first']
    assert first.audit['engine_states']['tavily']['reason'] == 'quota_exceeded'
    assert first.audit['engine_request_audits']['tavily']['configured_key_count'] == 2
    assert 'tavily' not in provider._disabled_engines


def test_quota_cooldown_allows_recharge_or_monthly_reset_without_restart(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(tavily_keys.time, 'monotonic', lambda: now[0])
    monkeypatch.setenv('TAVILY_KEY_QUOTA_COOLDOWN_SECONDS', '10')
    pool = TavilyKeyPool(('single',))
    with pytest.raises(TavilyKeysUnavailable):
        pool.search({'query': 'q'}, post=lambda *a, **kw: reply(432))
    with pytest.raises(TavilyKeysUnavailable) as failure:
        pool.search({'query': 'q'}, post=lambda *a, **kw: pytest.fail('cooling key must be skipped'))
    assert failure.value.reason == 'quota_exceeded'
    now[0] += 11
    assert pool.search({'query': 'q'}, post=lambda *a, **kw: reply())[0] == {'results': []}


def test_plain_rate_limit_uses_retry_after_without_permanent_quarantine(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(tavily_keys.time, 'monotonic', lambda: now[0])
    pool = TavilyKeyPool(('single',))
    with pytest.raises(TavilyKeysUnavailable) as failure:
        pool.search({'query': 'q'}, post=lambda *a, **kw: reply(429, headers={'Retry-After': '120'}))
    assert failure.value.reason == 'rate_limited'
    now[0] += 61
    with pytest.raises(TavilyKeysUnavailable):
        pool.search({'query': 'q'}, post=lambda *a, **kw: pytest.fail('Retry-After still active'))
    now[0] += 60
    pool.search({'query': 'q'}, post=lambda *a, **kw: reply())


def test_changed_credentials_get_fresh_state(monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEYS', 'expired')
    original = get_tavily_pool()
    with pytest.raises(TavilyKeysUnavailable):
        original.search({'query': 'q'}, post=lambda *a, **kw: reply(401))
    assert get_tavily_pool() is original
    monkeypatch.setenv('TAVILY_API_KEYS', 'replacement')
    assert get_tavily_pool() is not original


def test_concurrent_callers_share_skipped_credentials():
    pool = TavilyKeyPool(('expired', 'healthy'))
    def post(url, **kwargs):
        return reply(433) if key_from(kwargs) == 'expired' else reply()
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(lambda _: pool.search({'query': 'q'}, post=post), range(20)))
    assert all(audit['key_slot'] == 2 for _, audit in results)
    _, audit = pool.search({'query': 'q'}, post=post)
    assert audit['attempted_key_slots'] == [2]


@pytest.mark.parametrize('first_failure', [401, 403, 433])
def test_tenth_key_failure_rechecks_first_key_and_keeps_recovered_key(first_failure):
    keys = tuple('key-' + str(slot) for slot in range(1, 11))
    pool = TavilyKeyPool(keys)
    calls = []
    def post(url, **kwargs):
        key = key_from(kwargs)
        calls.append(key)
        if key == keys[0] and calls.count(keys[0]) > 1:
            return reply(payload={'results': [{'url': 'https://recovered.test'}]})
        return reply(first_failure if key == keys[0] else 433)
    payload, audit = pool.search({'query': 'q'}, post=post)
    assert calls == list(keys) + [keys[0]]
    assert payload['results'][0]['url'] == 'https://recovered.test'
    assert audit['key_slot'] == 1 and audit['wrap_rechecked']
    assert audit['key_attempt_sequence'] == list(range(1, 11)) + [1]
    _, second_audit = pool.search({'query': 'next'}, post=post)
    assert second_audit['key_attempt_sequence'] == [1]


def test_wrap_rechecks_first_key_quarantined_during_previous_requests():
    keys = tuple('key-' + str(slot) for slot in range(1, 11))
    pool = TavilyKeyPool(keys)
    recovered = [False]
    calls = []
    def post(url, **kwargs):
        key = key_from(kwargs)
        calls.append(key)
        if (key == keys[-1] and not recovered[0]) or (key == keys[0] and recovered[0]):
            return reply()
        return reply(433)
    assert pool.search({'query': 'before recharge'}, post=post)[1]['key_slot'] == 10
    recovered[0] = True
    audit = pool.search({'query': 'after recharge'}, post=post)[1]
    assert calls == list(keys) + [keys[-1], keys[0]]
    assert audit['key_attempt_sequence'] == [10, 1] and audit['wrap_rechecked']


def test_failed_wrap_probe_is_bounded_and_recovers_after_shared_cooldown(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(tavily_keys.time, 'monotonic', lambda: now[0])
    pool = TavilyKeyPool(('first', 'last'))
    calls = []
    def fail(url, **kwargs):
        calls.append(key_from(kwargs))
        return reply(433)
    with pytest.raises(TavilyKeysUnavailable) as failure:
        pool.search({'query': 'q'}, post=fail)
    assert calls == ['first', 'last', 'first']
    assert failure.value.audit['key_attempt_sequence'] == [1, 2, 1]
    with ThreadPoolExecutor(max_workers=6) as executor:
        def during_cooldown(_):
            with pytest.raises(TavilyKeysUnavailable):
                pool.search({'query': 'q'}, post=fail)
        list(executor.map(during_cooldown, range(12)))
    assert calls == ['first', 'last', 'first']
    now[0] += 61
    _, audit = pool.search({'query': 'recharged'}, post=lambda *a, **kw: reply())
    assert audit['key_slot'] == 1 and audit['wrap_rechecked']


def test_wrap_does_not_bypass_first_key_rate_limit():
    pool = TavilyKeyPool(('rate-limited', 'exhausted'))
    calls = []
    def post(url, **kwargs):
        key = key_from(kwargs)
        calls.append(key)
        return reply(429 if key == 'rate-limited' else 433, headers={'Retry-After': '120'})
    with pytest.raises(TavilyKeysUnavailable):
        pool.search({'query': 'q'}, post=post)
    assert calls == ['rate-limited', 'exhausted']
