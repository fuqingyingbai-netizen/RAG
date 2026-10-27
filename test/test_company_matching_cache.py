from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from report_agents import company_text as matching


class Converter:
    def __init__(self,prefix=''):self.calls=[];self.prefix=prefix
    def convert(self,text):self.calls.append(text);return self.prefix+text


def test_only_identical_complete_text_reuses_a_conversion_within_one_report(monkeypatch):
    converter=Converter();monkeypatch.setattr(matching,'_CC',converter)
    with matching.company_matching_cache():
        for _ in range(3):assert matching.match_text('本期收入100.00萬元')=='本期收入100.00萬元'
        assert matching.match_text('本期收入100.00元')=='本期收入100.00元'
        assert matching.match_text('上期收入100.00萬元')=='上期收入100.00萬元'
    assert len(converter.calls)==3 and matching._MATCHING_CACHE.get() is None
    matching.match_text('本期收入100.00萬元')
    assert len(converter.calls)==4


def test_calls_without_a_generation_scope_do_not_retain_source_text(monkeypatch):
    converter=Converter();monkeypatch.setattr(matching,'_CC',converter)
    matching.match_text('原文');matching.match_text('原文')
    assert converter.calls==['原文','原文'] and matching._MATCHING_CACHE.get() is None


def test_nested_scopes_share_one_cache_and_exceptions_clear_every_retained_string(monkeypatch):
    converter=Converter();monkeypatch.setattr(matching,'_CC',converter)
    with pytest.raises(RuntimeError):
        with matching.company_matching_cache():
            cache=matching._MATCHING_CACHE.get();matching.match_text('私有资料')
            with matching.company_matching_cache():matching.match_text('私有资料')
            assert len(converter.calls)==1
            raise RuntimeError('generation failed')
    assert not cache.entries and cache.chars==0 and matching._MATCHING_CACHE.get() is None


def test_character_budget_uses_lru_and_never_caches_oversize_text(monkeypatch):
    converter=Converter();monkeypatch.setattr(matching,'_CC',converter)
    with matching.company_matching_cache(max_chars=8,max_entries=10):
        for text in ('甲乙','丙丁','甲乙','戊己','丙丁'):matching.match_text(text)
        assert converter.calls==['甲乙','丙丁','戊己','丙丁']
        cache=matching._MATCHING_CACHE.get();assert cache.chars<=8 and len(cache.entries)<=2
        matching.match_text('长原文超过预算');matching.match_text('长原文超过预算')
        assert converter.calls[-2:]==['长原文超过预算','长原文超过预算'] and cache.chars<=8


def test_entry_budget_is_independent_of_character_budget(monkeypatch):
    converter=Converter();monkeypatch.setattr(matching,'_CC',converter)
    with matching.company_matching_cache(max_chars=100,max_entries=1):
        for text in ('甲','乙','甲'):matching.match_text(text)
        assert len(matching._MATCHING_CACHE.get().entries)==1
    assert len(converter.calls)==3


def test_replacing_the_conversion_policy_cannot_reuse_an_earlier_result(monkeypatch):
    first=Converter('甲');second=Converter('乙');monkeypatch.setattr(matching,'_CC',first)
    with matching.company_matching_cache():
        assert matching.match_text('原文')=='甲原文'
        monkeypatch.setattr(matching,'_CC',second)
        assert matching.match_text('原文')=='乙原文'
    assert first.calls==second.calls==['原文']


def test_independent_threads_do_not_share_a_report_cache(monkeypatch):
    converter=Converter();monkeypatch.setattr(matching,'_CC',converter)
    def report(_):
        with matching.company_matching_cache():
            matching.match_text('同一原文');matching.match_text('同一原文')
        assert matching._MATCHING_CACHE.get() is None
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(report,range(2)))
    assert converter.calls==['同一原文','同一原文']


def test_original_traditional_quotes_and_offsets_are_identical_with_and_without_cache():
    raw='公司原文載明：臺灣業務收入100.00萬元；國際業務尚未完成，不代表已收款。'
    baseline=matching.OriginalTextView(raw);start=baseline.text.index('国际');end=start+len('国际业务尚未完成')
    quote=baseline.quote(start,end)
    with matching.company_matching_cache():
        for _ in range(3):
            view=matching.OriginalTextView(raw)
            assert view.original==raw and view.text==baseline.text and view.quote(start,end)==quote
    assert quote=='國際業務尚未完成'


def test_report_agent_installs_and_clears_the_scope_even_if_generation_fails():
    from report_agents.company_report_agent import CompanyReportAgent
    def emit(*args,**kwargs):
        assert matching._MATCHING_CACHE.get() is not None
        raise RuntimeError('stop before any model or source processing')
    with pytest.raises(RuntimeError):
        CompanyReportAgent().generate(SimpleNamespace(),'{}','{}',None,None,emit)
    assert matching._MATCHING_CACHE.get() is None
