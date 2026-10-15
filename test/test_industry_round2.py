import json
import re
from types import SimpleNamespace

from industry_research import (summary_package, industry_excerpt, industry_cleaning_sources,
                               balanced_risk_facts, number_key, mark_unverified_numbers)
from report_agents.industry_report_agent import IndustryReportAgent
from research_workflow import ResearchWorkflow


def card(index, module='市场规模与增长', **extra):
    return {'evidence_id': f'E-{index:012X}', 'fact': f'机器人事实{index}',
            'source_url': f'https://stats.gov.cn/report/{index}', 'source_title': '机器人报告',
            'module': module, 'claim_type': 'fact', 'scope_match': 'in_scope',
            'evidence_scope': 'industry_level', 'eligible_for_risk_scoring': True, **extra}


def project(kind='industry'):
    return SimpleNamespace(target_type=kind, target_name='机器人', title='测试', industry='机器人',
                           description='', industry_scope={'industry_name': '机器人', 'capital_market': 'none'})


def test_industry_cleaning_model_has_no_hidden_retries(monkeypatch):
    import research_workflow
    settings = []
    monkeypatch.setenv('ARK_API_KEY', 'fake-test-key')
    monkeypatch.setenv('MODEL', 'fake-test-model')
    monkeypatch.setattr(research_workflow, 'init_chat_model', lambda **kw:
        (settings.append(kw) or SimpleNamespace(invoke=lambda _: SimpleNamespace(content='{}'))))
    w = ResearchWorkflow.__new__(ResearchWorkflow)
    assert w._invoke_industry_cleaning('行业清洗', 'prompt', timeout_seconds=23) == '{}'
    assert settings[0]['timeout'] == 23 and settings[0]['max_retries'] == 0


def test_cleaning_budget_shared_across_splits_and_other_batches_survive(monkeypatch):
    import research_workflow
    monkeypatch.setenv('CLEANING_MAX_WORKERS', '1')
    monkeypatch.setenv('INDUSTRY_CLEANING_BATCH_BUDGET_SECONDS', '70')
    monkeypatch.setenv('INDUSTRY_CLEANING_TIMEOUT_SECONDS', '60')
    monkeypatch.setenv('INDUSTRY_CLEANING_MAX_CALLS_PER_BATCH', '3')
    monkeypatch.setenv('INDUSTRY_CLEANING_SPLIT_MAX_DEPTH', '1')
    clock = [0.0]
    monkeypatch.setattr(research_workflow.time, 'monotonic', lambda: clock[0])
    w = ResearchWorkflow.__new__(ResearchWorkflow)
    w._cleaning_brief = lambda *a: ''
    requests = []
    def invoke(role, prompt, emit=None, timeout_seconds=60):
        if '批次2' in role:
            return json.dumps({'facts': [card(2)]})
        requests.append(timeout_seconds)
        clock[0] += timeout_seconds
        return ''
    w._invoke_industry_cleaning = invoke
    w._invoke = lambda *a, **k: (_ for _ in ()).throw(AssertionError('shared model used'))
    result = w._clean_batches_with_llm(project(), {}, {}, ['第一来源\n\n---\n\n第二来源', '正常来源'])
    assert requests == [60, 10]
    assert result['facts'][0]['evidence_id'] == card(2)['evidence_id']
    first = result['cleaning_diagnostic']['batches'][0]
    assert first['budget_exhausted'] and first['model_calls'] == 2
    assert any('批次1' in gap for gap in result['information_gaps'])


def test_cleaning_max_calls_bounds_rejected_responses(monkeypatch):
    monkeypatch.setenv('INDUSTRY_CLEANING_MAX_CALLS_PER_BATCH', '1')
    w = ResearchWorkflow.__new__(ResearchWorkflow); w._cleaning_brief = lambda *a: ''
    calls = []
    w._invoke_industry_cleaning = lambda *a, **k: (calls.append(a) or '')
    result = w._clean_batches_with_llm(project(), {}, {}, ['一\n\n---\n\n二'])
    assert len(calls) == 1 and result['facts'] == []
    assert result['cleaning_diagnostic']['batches'][0]['budget_exhausted']


def test_company_cleaning_keeps_existing_route():
    w = ResearchWorkflow.__new__(ResearchWorkflow); w._cleaning_brief = lambda *a: ''
    calls = []
    w._invoke = lambda *a, **k: (calls.append(a) or '{"facts": []}')
    w._invoke_industry_cleaning = lambda *a, **k: (_ for _ in ()).throw(AssertionError('industry route used'))
    result = w._clean_batches_with_llm(project('company'), {}, {}, ['公司来源'])
    assert len(calls) == 1 and 'cleaning_diagnostic' not in result


def test_risk_json_budget_is_complete_and_retains_late_module():
    w = ResearchWorkflow.__new__(ResearchWorkflow)
    facts = [card(i, '政策与监管', fact='政策原文'*1500, claim_type='source_excerpt') for i in range(100)]
    facts += [card(500, '市场规模与增长'), card(501, '商业模式与盈利逻辑')]
    raw = w._risk_evidence_payload(json.dumps({'facts': facts, 'information_gaps': ['缺口'*10000]}), 'industry')
    assert len(raw) <= 28000
    payload = json.loads(raw)
    assert {'市场规模与增长', '商业模式与盈利逻辑'} <= {x['module'] for x in payload['facts']}
    assert 'gap_interpretation' in payload


def test_risk_module_prefers_fact_over_source_excerpt():
    excerpt = card(1, claim_type='source_excerpt', quality_score=99)
    structured = card(2, quality_score=50)
    assert balanced_risk_facts([excerpt, structured], limit=1) == [structured]


def test_summary_uses_cited_balanced_cards_and_deduplicates_claims():
    duplicate = card(3, fact='同一市场规模')
    packages = {4: {'facts': [card(1), duplicate]}, 3: {'facts': [card(2, '政策与监管'),
               card(4, fact='同一市场规模')]}, 6: {'facts': [card(5)]}}
    sections = {4: card(1)['evidence_id']+' '+duplicate['evidence_id'],
                3: card(2)['evidence_id']+' '+card(4)['evidence_id']}
    summary = summary_package(packages, sections, {})
    ids = [f['evidence_id'] for f in summary['facts']]
    assert ids[:2] == [card(1)['evidence_id'], card(2)['evidence_id']]
    assert card(5)['evidence_id'] not in ids
    assert sum(f['fact']=='同一市场规模' for f in summary['facts']) == 1


def test_summary_prompt_digest_contains_no_budget_excluded_ids(monkeypatch):
    import report_agents.industry_report_agent as report_module
    original = report_module.summary_package
    monkeypatch.setattr(report_module, 'summary_package', lambda packages, sections, scope:
                        original(packages, sections, scope, limit=1800))
    agent = IndustryReportAgent(); p = project(); prompts = []
    facts = [card(i, fact=f'机器人市场事实{i}'+('内容'*100)) for i in range(20)]
    def write(proj, raw, risk, index, title, requirements, count, invoke, clip, emit, trace, completed_sections=''):
        package = json.loads(raw)
        if index == 1:
            prompts.append((package, completed_sections))
        return f'## {index}. {title}\n' + ' '.join(f['evidence_id'] for f in package['facts'])
    monkeypatch.setattr(agent, '_write_section', write)
    agent.generate(p, json.dumps({'facts': facts}), '{}', lambda *a:'', lambda s,n:s[:n], lambda *a,**k:None)
    package, digest = prompts[0]
    assert set(re.findall(r'E-[A-F0-9]{12}', digest)) == {f['evidence_id'] for f in package['facts']}
    assert len(json.dumps(package, ensure_ascii=False)) <= 1800


def test_summary_fallback_is_short_deduplicated_and_records_degradation():
    agent = IndustryReportAgent(); notes = []
    facts = [card(i) for i in range(12)] + [dict(card(100), fact=card(0)['fact'])]
    section = agent._validate_section('## 1. 摘要\n伪造引用 E-FFFFFFFFFFFF', {'facts':facts}, 1, '摘要',
            lambda *a:'', lambda *a,**k:None, None, notes)
    assert section.count('\n- ') == 5 and section.count(card(0)['fact']) == 1
    assert '人工复核' in section and 'E-FFFFFFFFFFFF' not in section
    assert notes[0]['chapter'] == 1


def test_industry_excerpt_keeps_late_business_data_and_original_words():
    text = '机器人报告2025年\n' + '目录与导航内容。'*500 + '订阅商业模式的收入结构中，经常性收入占比达到65%，按量计费。' + '后文。'*200
    excerpt = industry_excerpt(text, '商业模式与盈利逻辑', 1200)
    assert len(excerpt) <= 1200 and '65%' in excerpt and '不连续原文片段' in excerpt
    assert all(part in text for part in excerpt.split('\n[不连续原文片段]\n'))


def test_business_cleaning_sources_prefer_relevant_content():
    def source(title, body, score):
        return SimpleNamespace(title=title, content=body, summary='', credibility_score=score,
                               source_metadata={'module':'商业模式与盈利逻辑'})
    annual = source('芯片年报', '芯片库存100亿元', 95)
    model = source('机器人订阅模式', '机器人按量计费，经常性收入占比65%', 85)
    assert industry_cleaning_sources([annual, model], per_module=1) == [model]


def test_trillion_unit_validation_cannot_escape_number_gate():
    assert number_key('1.2万亿元') == number_key('12000亿元')
    assert number_key('1.2万亿美元') != number_key('1.2万亿元')
    assert '待核验' in mark_unverified_numbers('2025年规模1.2万亿元 E-000000000001', [card(1)])


def test_wrong_chapter_title_triggers_repair_even_when_number_and_ids_match():
    notes = []
    section = IndustryReportAgent()._validate_section('## 4. 错误标题\n'+card(1)['evidence_id'],
        {'facts': [card(1)]}, 4, '市场规模与增长预测', lambda *a:'', lambda *a,**k:None, None, notes)
    assert section.startswith('## 4. 市场规模与增长预测\n') and notes
