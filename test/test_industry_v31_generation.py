"""Visible model output failures must not become spurious evidence rejections."""
import json
from types import SimpleNamespace

import pytest

from industry_model_output import (generation_options, generation_error_code,
    IndustryModelOutputError, response_text)
from report_agents.industry_report_agent import IndustryReportAgent
from test_industry_reasoning import chain, EID


@pytest.mark.parametrize('name,disabled', [('qwen3.8-max', True), ('router/Qwen3-235B', True),
    ('qwen-plus', False), ('gpt-synthetic', False)])
def test_thinking_option_is_limited_to_compatible_family(name, disabled):
    assert bool(generation_options(name)) == disabled
    if disabled:
        assert generation_options(name) == {'extra_body': {'enable_thinking': False}}


def project():
    return SimpleNamespace(industry_statement_plans={}, industry_report_degradations=[])


def test_sdk_length_failure_is_propagated_without_format_retry_or_secret_logging(monkeypatch):
    import research_workflow
    # The SDK throws before an AIMessage exists when thinking consumes the cap.
    LengthFinishReasonError = type('LengthFinishReasonError', (Exception,), {})
    configured, events, calls = [], [], []
    monkeypatch.setenv('ARK_API_KEY', 'synthetic')
    monkeypatch.setenv('MODEL', 'qwen3.8-max')
    def create(**kwargs):
        configured.append(kwargs)
        def invoke(messages):
            calls.append(messages)
            raise LengthFinishReasonError('PRIVATE_RESPONSE_AND_CONFIG')
        return SimpleNamespace(invoke=invoke)
    monkeypatch.setattr(research_workflow, 'init_chat_model', create)
    workflow = research_workflow.ResearchWorkflow.__new__(research_workflow.ResearchWorkflow)
    p, f = project(), chain()
    text = IndustryReportAgent()._write_statement_section(p, {'facts': [f]}, 2, '行业定义',
        lambda role, prompt, emit: workflow._invoke_industry_report(role, prompt, events.append),
        lambda *a, **k: None, None)
    plan = p.industry_statement_plans[2]
    assert len(calls) == plan['model_attempts'] == 1 and plan['fallback']
    assert configured[0]['extra_body'] == {'enable_thinking': False}
    assert plan['plan_validation_failures'] == [{'attempt': 1, 'code': 'truncated_model_output', 'kind': 'generation_failure'}]
    assert not plan['analysis_rejections'] and f['fact_contract']['statement'] in text
    assert 'PRIVATE' not in json.dumps(plan) + json.dumps(events)
    assert not any('invalid_statement_plan' in json.dumps(e) for e in p.industry_report_degradations)


def test_actual_format_failure_still_gets_one_format_repair():
    p, f, calls = project(), chain(), []
    def invoke(role, prompt, emit):
        calls.append(role)
        return 'not JSON' if len(calls) == 1 else json.dumps({'evidence_ids': [EID], 'analyses': []})
    IndustryReportAgent()._write_statement_section(p, {'facts': [f]}, 2, '行业定义', invoke, lambda *a, **k: None, None)
    plan = p.industry_statement_plans[2]
    assert len(calls) == plan['model_attempts'] == 2 and not plan['fallback']
    assert plan['plan_validation_failures'][0]['kind'] == 'format_failure'


@pytest.mark.parametrize('stage', ['report', 'support', 'risk', 'cleaning'])
def test_all_industry_stages_send_visible_output_option_without_more_budget(monkeypatch, stage):
    import research_workflow
    monkeypatch.setenv('ARK_API_KEY', 'synthetic')
    monkeypatch.setenv('MODEL', 'qwen3.8-max')
    configured = []
    def create(**kwargs):
        configured.append(kwargs)
        return SimpleNamespace(invoke=lambda messages: SimpleNamespace(content='{}'))
    monkeypatch.setattr(research_workflow, 'init_chat_model', create)
    w = research_workflow.ResearchWorkflow.__new__(research_workflow.ResearchWorkflow)
    if stage == 'report': w._invoke_industry_report('行业章节编排 Agent - 合成章', 'synthetic')
    elif stage == 'support': w._invoke_industry_support_review('synthetic')
    elif stage == 'risk': w._invoke_industry_risk('行业风险 Agent', 'synthetic')
    else: w._invoke_industry_cleaning('行业清洗 Agent', 'synthetic')
    options = configured[0]
    assert options['extra_body'] == {'enable_thinking': False}
    assert options['max_retries'] == 0
    assert options['max_tokens'] == {'report':6000, 'support':6000, 'risk':4000, 'cleaning':2000}[stage]


def test_safe_output_usage_distinguishes_thinking_tokens_without_exposing_prose():
    message = SimpleNamespace(content='{}', response_metadata={'finish_reason':'stop'},
        usage_metadata={'input_tokens':20,'output_tokens':30,'output_token_details':{'reasoning':0,'private':'PRIVATE'}})
    raw, diagnostic = response_text(message)
    assert raw == '{}' and diagnostic['token_usage']['reasoning_tokens'] == 0
    assert 'PRIVATE' not in json.dumps(diagnostic)


def test_unrelated_phone_car_margin_is_not_an_ai_chain_value_observation():
    from industry_fact_contracts import chapter_admitted
    from test_industry_briefing import card
    f = card('某手机厂商的情况较为复杂：内存价格上涨拖累了手机业务毛利率，而电动汽车业务利润率因规模效应有所扩张。',
             module='细分赛道与产业链', industry_name='人工智能')
    assert f['fact_contract']['report_admitted']
    assert not chapter_admitted(f, 2)


def test_report_research_scope_is_not_a_concrete_bottleneck_finding():
    from industry_fact_contracts import chapter_admitted
    from test_industry_briefing import card
    f = card('报告从技术路线、产业格局、现存技术瓶颈等多个维度展开系统性研究，梳理产业链上下游关系，为项目方提供研究参考。',
             module='细分赛道与产业链', industry_name='人工智能')
    assert f['fact_contract']['report_admitted']
    assert not chapter_admitted(f, 2)


def test_synthesis_also_budgets_actual_writer_text_instead_of_archive_metadata():
    from copy import deepcopy
    from industry_briefing import synthesis_package
    from industry_fact_contracts import plan_prompt, render_plan
    from test_industry_briefing import card, SCOPE
    a = card('机器人云端采用吞吐量优化架构，端侧采用低功耗架构，边缘侧面向低时延部署场景。')
    b = card('机器人服务采用订阅和按量计费，用户按实际调用支付费用。',
             'E-222222222222', module='商业模式与盈利逻辑')
    for f in (a, b):
        f['provenance']['archive_only'] = 'AUDIT_NOT_MODEL_INPUT' * 330
    originals = deepcopy([a, b])
    packages = {7: {'facts': [a]}, 10: {'facts': [b]}}
    sections = {ch: render_plan(p, ch, '合成章节', [f['evidence_id'] for f in p['facts']]) for ch,p in packages.items()}
    package = synthesis_package(packages, sections, SCOPE)
    assert len(package['facts']) == 2
    assert len(json.dumps(package, ensure_ascii=False)) > 14000
    assert len(plan_prompt(package, 14)) <= 14000
    assert 'AUDIT_NOT_MODEL_INPUT' not in plan_prompt(package, 14)
    assert package['synthesis_input_budget']['actual_prompt_chars'] == len(plan_prompt(package, 14))
    assert [a, b] == originals
