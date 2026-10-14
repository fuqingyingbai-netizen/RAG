import json
import threading
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from industry_research import (annotate_fact, select_chapter_evidence, normalize_risk,
                               package_risk_evidence, bounded_package, numeric_supported,
                               mark_unverified_numbers, delivery_errors, unique_search_queries)
from report_agents.industry_report_agent import IndustryReportAgent
from report_agents.report_prompts import build_section_prompt
from research_workflow import ResearchWorkflow
from json_utils import strip_nul




def test_industry_models_bound_timeout_and_disable_hidden_sdk_retries(monkeypatch):
    import research_workflow
    settings = []
    monkeypatch.setenv('ARK_API_KEY', 'test-only-key')
    monkeypatch.setenv('MODEL', 'test-only-model')
    monkeypatch.setattr(research_workflow, 'init_chat_model', lambda **kw: (settings.append(kw) or SimpleNamespace(invoke=lambda messages: SimpleNamespace(content='章节'))))
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    assert workflow._invoke_industry_report('行业章节 Agent', 'prompt') == '章节'
    assert workflow._invoke_industry_report('行业章节修复 Agent', 'prompt') == '章节'
    assert [row['max_retries'] for row in settings] == [0, 0]
    assert [row['timeout'] for row in settings] == [90, 45]


def numeric(value=100, text='2025年中国机器人核心产业规模100亿元。', url='https://stats.gov.cn/report'):
    return annotate_fact({'fact': text, 'source_url': url, 'module': '市场规模与增长',
        'claim_type': 'fact', 'evidence_scope': 'industry_level', 'numeric_context': {
            'metric': '核心产业规模', 'value': value, 'unit': '亿元', 'geography': '中国',
            'period': '2025', 'definition': '机器人核心产业销售额', 'is_forecast': False}},
        {'industry_name': '机器人', 'geography': '中国大陆', 'as_of_date': '2026-01-31'})


def test_validated_fact_wins_over_many_high_score_source_excerpts():
    verified = numeric()
    raw = [dict(verified, evidence_id=f'E-RAW{i:09d}', claim_type='source_excerpt',
                numeric_context={}, numeric_validation={'passed': False}, quality_score=99) for i in range(30)]
    cards = select_chapter_evidence({'facts': raw + [verified]}, '市场规模与增长预测', [])['facts']
    assert cards[0] == verified
    assert len(cards) == 12


def test_number_validation_checks_the_metric_not_other_numbers_in_quote():
    card = numeric(text='2025年中国机器人核心产业规模100亿元，同比增长30%。')
    diagnostic = {card['evidence_id']: {'context': card['numeric_context'], 'validation': card['numeric_validation']}}
    assert numeric_supported('100.0亿元', card['evidence_id'], diagnostic)
    assert numeric_supported('1,000,000万元', card['evidence_id'], diagnostic)
    assert not numeric_supported('30%', card['evidence_id'], diagnostic)
    section = mark_unverified_numbers(f'## 4. 规模\n100亿元 {card["evidence_id"]}\n增长30% {card["evidence_id"]}', [card])
    assert '待核验' not in section.splitlines()[1]
    assert '待核验' in section.splitlines()[2]


def test_numeric_context_cannot_invent_a_value_or_use_string_forecast_flag():
    inconsistent = numeric(value=999)
    assert 'value_not_in_evidence_quote' in inconsistent['numeric_validation']['missing_fields']
    card = numeric()
    raw = dict(card, numeric_context={**card['numeric_context'], 'period': '2030', 'is_forecast':'false'})
    checked = annotate_fact(raw, {'industry_name':'机器人', 'as_of_date':'2026-01-31'})
    assert 'is_forecast_boolean' in checked['numeric_validation']['missing_fields']
    assert 'period_after_cutoff' in checked['numeric_validation']['missing_fields']


def test_disabled_capital_dimension_and_followups_are_excluded():
    card = numeric()
    result = normalize_risk({'dimensions': [{'name': '资本热度与估值风险', 'score': 85, 'evidence_ids': []}],
                             'unknowns': ['估值数据缺失', '商业化资料待核验'],
                             'recommended_followups': ['采集投融资数据库', '补充盈利模式资料']}, [card], {'capital_market': 'none'})
    assert len(result['dimensions']) == 6
    assert '资本热度与估值风险' not in result['applicable_dimensions']
    assert result['recommended_followups'] == ['补充盈利模式资料']
    assert result['overall_score'] is None


def test_disabled_authority_module_does_not_create_false_gap():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    quality = {'authoritative_counts': {'政策与监管': 3, '市场规模与增长': 2, '竞争格局与代表企业': 2,
                                       '商业模式与盈利逻辑': 1}}
    result = workflow._apply_authority_coverage_requirements(quality, 'industry', {'capital_market': 'none'})
    assert result['authority_coverage_passed']
    assert '投融资与资本市场' not in result['authority_requirements']


def test_risk_cards_are_carried_only_into_synthesis_chapters():
    card = numeric()
    risk = {'dimensions': [{'name': '市场增长与需求风险', 'score': 30, 'evidence_ids': [card['evidence_id']]}]}
    package, scoped = package_risk_evidence({'facts': []}, {'facts': [card]}, risk, include_all=True)
    assert package['facts'] == [card] and scoped['dimensions'] == risk['dimensions']
    package, scoped = package_risk_evidence({'facts': []}, {'facts': [card]}, risk)
    assert package['facts'] == [] and scoped['dimensions'] == []


def test_preselected_prompt_keeps_exact_risk_cards_and_json_budget():
    card = numeric()
    package = bounded_package({'facts': [dict(card, fact=card['fact'] * 100)]}, 5000)
    assert len(package) <= 5000 and json.loads(package)['facts'][0]['evidence_id'] == card['evidence_id']
    project = SimpleNamespace(target_name='机器人', target_type='industry', industry='机器人', title='测试', description='', industry_scope={})
    prompt = build_section_prompt(report_kind='行业', outline=IndustryReportAgent.outline, project=project,
        cleaned_json=package, risk_json='{}', index=13, section_title='风险核查', requirements=[],
        clip=lambda v,n:v[:n], evidence_preselected=True)
    assert package in prompt


def test_search_deduplicates_across_rounds_but_preserves_distinct_domain_routes():
    seen = set()
    first = {'query': '机器人 市场规模', 'include_domains': ['stats.gov.cn']}
    assert unique_search_queries([first, first], seen) == [first]
    assert unique_search_queries([first], seen) == []
    assert len(unique_search_queries([{'query': first['query']}], seen)) == 1


def test_gate_reads_serialized_chapter_keys_and_deduplicates_errors():
    card = numeric()
    report = '\n\n'.join(f'## {i}. {title}\n' + (f'100亿元 {card["evidence_id"]}\n100亿元 {card["evidence_id"]}' if i==4 else '待核验')
                           for i,(title,_) in enumerate(IndustryReportAgent.outline,1))
    diagnostic = {'evidence_ids': [card['evidence_id']], 'chapter_evidence_ids': {'4': [card['evidence_id']]},
                  'numeric_evidence': {card['evidence_id']: {'context': card['numeric_context'], 'validation': card['numeric_validation']}}}
    errors = delivery_errors(report, diagnostic, {})
    assert not any('第4章' in e for e in errors)
    broken = report.replace('100亿元', '500亿元')
    assert sum('数值 500亿元' in e for e in delivery_errors(broken, diagnostic, {})) == 1


def test_failed_section_repair_preserves_only_auditable_facts():
    card = numeric()
    agent = IndustryReportAgent()
    section = agent._validate_section('## 4. 市场规模与增长预测\n伪造500亿元 E-FAKEFAKEFAKE', {'facts':[card]}, 4,
        '市场规模与增长预测', lambda *a:'## 4. 市场规模与增长预测\n仍引用 E-FAKEFAKEFAKE', lambda *a,**k:None, None)
    assert card['evidence_id'] in section and 'E-FAKEFAKEFAKE' not in section and '500亿元' not in section
