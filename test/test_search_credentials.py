"""Credential fallback is not a retry for rate limits or request failures."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
import requests

from web_search import WebSearchProvider


def response(status=200,body=None):
    r=requests.Response();r.status_code=status;r.url='https://api.tavily.com/search'
    r._content=json.dumps(body or {'results':[{'title':'Source','url':'https://example.org','content':'saved excerpt'}]}).encode()
    return r


@pytest.fixture
def pool(monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEY','synthetic-primary')
    monkeypatch.setenv('TAVILY_API_KEYS','synthetic-primary,synthetic-backup;synthetic-third')
    return WebSearchProvider()


def test_pool_deduplicates_and_keeps_legacy_key_first(pool):
    assert pool._tavily_api_keys()==['synthetic-primary','synthetic-backup','synthetic-third']


@pytest.mark.parametrize('code',[401,403,432])
def test_bad_credential_is_skipped_later_and_not_logged(monkeypatch,pool,code,capsys):
    calls=[]
    def post(url,**kw):
        key=kw['json']['api_key'];calls.append(key)
        return response(code,{'error':'invalid_api_key'}) if key=='synthetic-primary' else response()
    monkeypatch.setattr(requests,'post',post)
    result=pool._search_tavily('offline query',1)
    assert calls==['synthetic-primary','synthetic-backup'] and len(result)==1
    assert result.audit=={'http_attempts':2,'credential_switches':1}
    pool._search_tavily('second offline query',1)
    assert calls[-1]=='synthetic-backup' and calls.count('synthetic-primary')==1
    public=json.dumps(result.audit)+capsys.readouterr().out
    assert 'synthetic-primary' not in public and 'synthetic-backup' not in public


@pytest.mark.parametrize('code',[400,429,500])
def test_request_and_rate_errors_do_not_rotate(monkeypatch,pool,code):
    calls=[]
    def post(*a,**k):calls.append(1);return response(code,{'error':'ordinary request failure'})
    monkeypatch.setattr(requests,'post',post)
    with pytest.raises(requests.HTTPError):pool._search_tavily('offline query',1)
    assert len(calls)==1 and not pool._unavailable_tavily_keys


def test_timeout_does_not_rotate_and_success_is_one_request(monkeypatch,pool):
    calls=[]
    def post(*a,**k):calls.append(1);raise requests.Timeout('synthetic timeout')
    monkeypatch.setattr(requests,'post',post)
    with pytest.raises(requests.Timeout):pool._search_tavily('offline query',1)
    assert len(calls)==1 and not pool._unavailable_tavily_keys
    monkeypatch.setattr(requests,'post',lambda *a,**k:response())
    assert pool._search_tavily('offline query',1).audit['http_attempts']==1


def test_all_exhausted_keys_keep_quota_failure_without_more_requests(monkeypatch,pool):
    calls=[]
    def post(*a,**k):calls.append(1);return response(432,{'error':'quota_exceeded'})
    monkeypatch.setattr(requests,'post',post)
    for _ in range(2):
        with pytest.raises(Exception) as exc:pool._search_tavily('offline query',1)
        assert pool._search_failure_reason(exc.value)=='quota_exceeded'
    assert len(calls)==3
    assert all('synthetic-' not in signature for signature in pool._unavailable_tavily_keys)


def test_plural_only_credentials_work_for_single_and_multi_search(monkeypatch,pool):
    monkeypatch.delenv('TAVILY_API_KEY')
    monkeypatch.setenv('WEB_SEARCH_PROVIDER','multi')
    monkeypatch.setattr(requests,'post',lambda *a,**k:response())
    assert pool.search_single('tavily','offline query',1)
    pool.engines=[('tavily',pool._search_tavily)]
    assert pool.search('offline query',1).audit['engine_states']['tavily']['status']=='returned'


def test_concurrent_searches_keep_results_and_pool_state_consistent(monkeypatch,pool):
    def post(*a,**kw):
        return response(432,{'error':'quota_exceeded'}) if kw['json']['api_key']=='synthetic-primary' else response()
    monkeypatch.setattr(requests,'post',post)
    with ThreadPoolExecutor(max_workers=4) as workers:
        results=list(workers.map(lambda i:pool._search_tavily('offline query',1),range(8)))
    assert all(len(r)==1 for r in results) and len(pool._unavailable_tavily_keys)==1
