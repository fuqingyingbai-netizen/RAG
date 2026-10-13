import os

import web_search
from web_search import WebSearchProvider


def test_site_fallback_query_wraps_multiple_domains():
    query = WebSearchProvider._query_with_sites("马云 诉讼", ["court.gov.cn", "creditchina.gov.cn"])
    assert "site:court.gov.cn" in query
    assert "site:creditchina.gov.cn" in query
    assert query.startswith("马云 诉讼")


def test_site_fallback_does_not_change_open_web_query():
    assert WebSearchProvider._query_with_sites("测试查询", []) == "测试查询"


def test_tavily_receives_native_include_domains():
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [], "images": []}

    original_post = web_search.requests.post
    original_key = os.environ.get("TAVILY_API_KEY")
    try:
        os.environ["TAVILY_API_KEY"] = "test-key"
        web_search.requests.post = lambda *args, **kwargs: captured.update(kwargs.get("json") or {}) or Response()
        WebSearchProvider()._search_tavily("测试", 5, ["court.gov.cn"], ["example.com"])
    finally:
        web_search.requests.post = original_post
        if original_key is None:
            os.environ.pop("TAVILY_API_KEY", None)
        else:
            os.environ["TAVILY_API_KEY"] = original_key

    assert captured["include_domains"] == ["court.gov.cn"]
    assert captured["exclude_domains"] == ["example.com"]


def test_exa_receives_domain_filter_and_financial_category():
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": []}

    original_post = web_search.requests.post
    original_key = os.environ.get("EXA_API_KEY")
    original_wait = WebSearchProvider._wait_for_exa_slot
    try:
        os.environ["EXA_API_KEY"] = "test-key"
        web_search.requests.post = lambda *args, **kwargs: captured.update(kwargs.get("json") or {}) or Response()
        WebSearchProvider._wait_for_exa_slot = lambda self: None
        WebSearchProvider()._search_exa("测试", 5, ["sec.gov"], None, "financial report")
    finally:
        web_search.requests.post = original_post
        WebSearchProvider._wait_for_exa_slot = original_wait
        if original_key is None:
            os.environ.pop("EXA_API_KEY", None)
        else:
            os.environ["EXA_API_KEY"] = original_key

    assert captured["includeDomains"] == ["sec.gov"]
    assert captured["category"] == "financial report"
