import json
from types import SimpleNamespace

import pytest

from industry_research import (annotate_fact, extract_industry_source_facts, summary_length,
                               delivery_errors, validate_docx_package)
from research_workflow import ResearchWorkflow
from research_strategies.industry import IndustryResearchStrategy
from report_agents.industry_report_agent import IndustryReportAgent
from docx_exporter import markdown_to_docx_bytes


SCOPE = {'industry_name': '机器人', 'segments': ['机器人'], 'geography': '中国大陆',
         'as_of_date': '2026-10-14', 'capital_market': 'none'}


def source(content='', summary='', module='市场规模与增长', scope='industry_level'):
    return SimpleNamespace(content=content, summary=summary, title='机器人行业研究',
        url='https://stats.gov.cn/robot', credibility_score=85,
        source_type='government',
        source_metadata={'module': module, 'evidence_scope': scope})


def cards(src):
    return [annotate_fact(f, SCOPE) for f in extract_industry_source_facts([src], SCOPE)]


def test_native_numeric_cards_survive_without_models_and_keep_verbatim_quote():
    original = '2025年我国机器人核心产业规模超过1.2万亿元。'
    rows = cards(source(original))
    assert len(rows) == 1 and rows[0]['is_structured_evidence']
    assert rows[0]['numeric_validation']['passed']
    assert rows[0]['evidence_quote'] in original
    assert rows[0]['numeric_context']['definition'].endswith('我国机器人核心产业规模')


def test_search_summary_is_never_promoted_to_native_numeric_fact():
    assert cards(source('', '2025年我国机器人市场规模100亿元。')) == []
    assert cards(source('机器人产业动态正在发布。', '2025年我国机器人市场规模100亿元。')) == []


@pytest.mark.parametrize('text', ['我国机器人市场规模100亿元。', '2025年机器人市场规模100亿元。',
                                '2025年中国与美国机器人市场规模100亿元。'])
def test_missing_or_ambiguous_context_remains_pending(text):
    rows = cards(source(text))
    assert rows and not rows[0]['numeric_validation']['passed']
    assert rows[0]['eligible_for_risk_scoring'] is False


def test_multiple_metrics_on_one_sentence_keep_distinct_cards_and_ids():
    rows = cards(source('2025年我国机器人市场规模100亿元，机器人毛利率20%。'))
    assert len(rows) == 2
    assert len({f['evidence_id'] for f in rows}) == 2
    w = ResearchWorkflow.__new__(ResearchWorkflow)
    assert len(w._dedupe_facts(rows)) == 2
    assert all(f['numeric_validation']['passed'] for f in rows)


def test_company_sample_cannot_be_promoted_to_industry_risk():
    rows = cards(source('2025年我国机器人订阅收入规模100亿元。', module='商业模式与盈利逻辑',
                        scope='representative_company'))
    assert rows and rows[0]['eligible_for_risk_scoring'] is False


def test_business_sentence_does_not_inherit_unrelated_page_numbers():
    rows = cards(source('2025年毛利率20%。机器人行业采用订阅和按量计费商业模式。',
                        module='商业模式与盈利逻辑'))
    assert len(rows) == 1 and rows[0].get('numeric_validation') is None
    assert rows[0].get('eligible_for_risk_scoring') is not False


def test_native_business_card_is_not_dropped_as_identical_source_excerpt():
    src = source('机器人行业采用订阅和按量计费商业模式。', module='商业模式与盈利逻辑')
    native = cards(src)[0]
    excerpt = annotate_fact({**native, 'claim_type':'source_excerpt','cleaning_method':'',
                              'is_structured_evidence':False}, SCOPE)
    w = ResearchWorkflow.__new__(ResearchWorkflow)
    assert len(w._dedupe_facts([excerpt,native]))==2
    assert excerpt['evidence_id'] != native['evidence_id']


def test_filing_retrieved_with_macro_query_remains_company_sample():
    src = source('2025年我国机器人订阅收入规模100亿元。', module='商业模式与盈利逻辑')
    src.source_type='filing'
    row = cards(src)[0]
    assert row['evidence_scope']=='representative_company' and row['eligible_for_risk_scoring'] is False


def test_llm_industry_cards_require_native_quote_and_set_structured_flag():
    src = source('机器人行业采用订阅商业模式。')
    p = SimpleNamespace(target_type='industry', target_name='机器人', sources=[src])
    w = ResearchWorkflow.__new__(ResearchWorkflow)
    raw = {'fact': '机器人采用订阅', 'source_url': src.url, 'evidence_quote': src.content,
           'claim_type': 'fact', 'scope_match': 'in_scope'}
    assert w._sanitize_structured_facts([raw], p)[0]['is_structured_evidence'] is True
    assert w._sanitize_structured_facts([{**raw, 'evidence_quote': '机器人营收500亿元'}], p) == []


def test_repeated_failures_stop_queued_cleaning_and_reset_on_next_run(monkeypatch):
    monkeypatch.setenv('CLEANING_MAX_WORKERS', '1')
    monkeypatch.setenv('INDUSTRY_CLEANING_FAILURE_LIMIT', '2')
    w = ResearchWorkflow.__new__(ResearchWorkflow); w._cleaning_brief = lambda *a: ''
    calls = []; events = []
    w._invoke_industry_cleaning = lambda *a, **k: (calls.append(a) or '')
    p = SimpleNamespace(target_type='industry')
    result = w._clean_batches_with_llm(p, {}, {}, ['a\n\n---\n\nb']*10, emit=events.append)
    assert len(calls) == 2 and result['cleaning_diagnostic']['circuit_open']
    assert result['cleaning_diagnostic']['batches'][-1]['model_calls'] == 0
    assert sum(e['label']=='行业精洗连续失败，停止追加模型请求' for e in events) == 1
    w._clean_batches_with_llm(p, {}, {}, ['a'])
    assert len(calls) == 3


def test_industry_prompt_omits_unrelated_identity_fields():
    w = ResearchWorkflow.__new__(ResearchWorkflow); w._cleaning_brief = lambda *a: ''
    prompts = []
    w._invoke_industry_cleaning = lambda role, prompt, **kw: (prompts.append(prompt) or '{"facts":[]}')
    w._clean_batches_with_llm(SimpleNamespace(target_type='industry'), {}, {}, ['材料'])
    assert 'numeric_context' in prompts[0] and '最多3条' in prompts[0]
    assert 'privacy_sensitivity' not in prompts[0] and 'identity_match' not in prompts[0]


def test_business_queries_separate_industry_evidence_from_company_samples():
    rows = IndustryResearchStrategy().expand_search_queries({'modules': []},
        {'target_name': '机器人', 'industry': '机器人', 'industry_scope': SCOPE})
    business = [r for r in rows if r['module']=='商业模式与盈利逻辑']
    assert any(r['evidence_scope']=='industry_level' and '收入结构' in r['query'] for r in business)
    assert any(r['evidence_scope']=='representative_company' and '年报' in r['query'] for r in business)
    assert any(r['search_tier']=='authority_first' and r['evidence_scope']=='industry_level' for r in business)


def test_overlong_summary_repairs_once_and_falls_back_under_visible_limit():
    agent = IndustryReportAgent(); rows = cards(source('2025年我国机器人市场规模100亿元。'))
    f = rows[0]; section = '## 1. 摘要\n' + ('机器人研究结论。'*200) + f['evidence_id']
    calls = []; notes = []
    result = agent._validate_section(section, {'facts': rows}, 1, '摘要',
        lambda *a: (calls.append(a) or section), lambda *a,**kw: None, None, notes)
    assert len(calls) == 1 and notes
    assert summary_length(result) <= 600 and f['evidence_id'] in result


def test_summary_length_excludes_source_identifiers_and_link_destinations():
    assert summary_length('## 1. 摘要\n机器人事实 [E-0123456789AB](https://example.org/'+'x'*1000+')') == 5


def test_market_gate_rejects_all_pending_numeric_cards():
    f = cards(source('我国机器人市场规模100亿元。'))[0]
    diagnostic = {'evidence_ids':[f['evidence_id']], 'chapter_evidence_ids':{4:[f['evidence_id']]},
        'numeric_evidence':{f['evidence_id']:{'fact':f['fact'],'validation':f['numeric_validation']}}}
    errors = delivery_errors(f'## 4. 市场规模与增长预测\n100亿元 {f["evidence_id"]} 待核验',diagnostic,SCOPE)
    assert any('市场规模章节尚无口径完整' in e for e in errors)


def test_docx_integrity_checks_actual_package_and_rejects_corruption():
    result = validate_docx_package(markdown_to_docx_bytes('## 1. 行业研究\n\n机器人研究正文。',title='行业报告'))
    assert result['docx_integrity_status']=='passed' and result['docx_paragraph_count']>0
    with pytest.raises(Exception):
        validate_docx_package(b'not-a-word-document')
