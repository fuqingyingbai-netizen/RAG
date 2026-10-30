"""Conclusions are useful draft judgments, never upgrades of evidence or scores."""
from copy import deepcopy
import hashlib
import io
import json
import re
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from industry_briefing import (synthesis_package, bind_plan, current_conclusions,
    comparison_table, reuse_chapter_judgments)
from industry_delivery import finalize_synthesis, risk_state_issues
from industry_fact_contracts import attach_contract, render_plan, validate_analyses, plan_prompt
from industry_research import summary_length
from docx_exporter import markdown_to_docx_bytes
from report_agents.industry_report_agent import IndustryReportAgent

SCOPE = {'industry_name': '机器人', 'segments': ['机器人'], 'capital_market': 'none',
    'named_companies': [], 'geography': '中国大陆', 'as_of_date': '2030-10-01'}
EID = 'E-111111111111'
TEXT = ('现有材料支持把云端、端侧与边缘端分别作为部署方案比较，而不是只按单项性能作统一排序。'
        '实际选择需要结合应用负载与部署条件；所引材料尚不足以认定其中一种方案在所有场景占优。')


def card(quote='机器人云端采用吞吐量优化架构，端侧采用低功耗架构，边缘侧面向低时延部署场景。', eid=EID, **fields):
    f = {'evidence_id': eid, 'fact': quote, 'evidence_quote': quote,
        'scope_match': 'in_scope', 'source_title': '机器人技术研究',
        'source_url': 'https://research.example/robot', 'evidence_scope': 'industry_level',
        'module': '技术路线对比', 'provenance': {'locator': {'status': 'verified',
            'start': 0, 'end': len(quote), 'quote': quote,
            'body_sha256': hashlib.sha256(quote.encode()).hexdigest()}}}
    f.update(fields)
    return attach_contract(f, SCOPE, quote)


def setup_claim():
    f = card()
    section = render_plan({'facts': [f]}, 7, '技术路线对比', [EID])
    package = synthesis_package({7: {'facts': [f]}}, {7: section}, SCOPE)
    claim = {'question': '技术及落地条件', 'text': TEXT, 'evidence_ids': [EID],
        'claim_kind': 'inference', 'premises': [{'evidence_id': EID, 'quote': f['fact_contract']['statement']}],
        'reasoning': '从不同部署方式的适用场景出发，提出分别比较方案的初步判断，未推定优胜路线。'}
    claims, failures = validate_analyses([claim], package, 14, [EID])
    assert len(claims) == 1 and not failures
    plan = {'evidence_ids': [EID], 'analysis_claims': claims}
    bind_plan(plan, package)
    report = '## 1. 摘要\n\n原摘要。\n\n'+section+'\n\n## 14. 综合评估\n旧状态。\n\n## 15. 信息来源\n索引。\n\n## 16. 后续研究点\n旧任务。'
    return f, package, plan, report


def test_synthesis_can_state_a_bounded_positive_judgment_without_inventing_a_score():
    f, package, plan, report = setup_claim()
    result, _ = finalize_synthesis(report, {'facts': [f]}, {}, [], SCOPE, {14: plan})
    assert result.count(TEXT) == 2  # Whole conclusion in body and summary.
    assert result.index('阶段性综合结论') < result.index('### 风险评估状态')
    assert '模型风险总分' not in result and not risk_state_issues(result, {}, SCOPE)
    assert current_conclusions(result, {'facts': [f]}, {14: plan}, SCOPE)[0]['entailment_status'] == 'not_evaluated'
    summary = re.search(r'(?ms)^## 1\..*?(?=^## 7\.)', result)[0]
    assert summary_length(summary) <= 600
    assert finalize_synthesis(result, {'facts': [f]}, {}, [], SCOPE, {'14': plan})[0] == result


@pytest.mark.parametrize('change', ['source', 'body', 'scope', 'rejected', 'unlocated'])
def test_changed_dependencies_remove_old_conclusion_and_its_summary(change):
    f, _, plan, report = setup_claim()
    result, _ = finalize_synthesis(report, {'facts': [f]}, {}, [], SCOPE, {14: plan})
    scope = deepcopy(SCOPE)
    if change == 'source':
        f['fact_contract']['statement'] = '新的原文陈述。'
    elif change == 'body':
        result = result.replace(f['fact_contract']['statement'], '人工移除了原文依据。')
    elif change == 'scope':
        scope['geography'] = '全球'
    elif change == 'rejected':
        plan['analysis_claims'][0]['support_review'] = {'status': 'unsupported'}
    else:
        f['provenance']['locator']['status'] = 'not_found'
    refreshed, _ = finalize_synthesis(result, {'facts': [f]}, {}, [], scope, {14: plan})
    assert TEXT not in refreshed and '阶段性综合结论' not in refreshed
    assert '综合结论的依据已变化' in refreshed


def test_bare_citation_cannot_authorize_synthesis_and_samples_stay_excluded():
    f = card()
    assert not synthesis_package({7: {'facts': [f]}}, {7: '这里只写编号 ['+EID+']'}, SCOPE)['facts']
    sample = card('机器人供应商测试样本采用统一硬件配置。', evidence_scope='representative_company')
    section = render_plan({'facts': [sample]}, 7, '技术路线对比', [EID])
    assert not synthesis_package({7: {'facts': [sample]}}, {7: section}, SCOPE)['facts']
    hidden_company = deepcopy(f)
    hidden_company['fact_contract']['summary_subject_present'] = False
    assert not synthesis_package({7: {'facts': [hidden_company]}}, {7: render_plan({'facts': [hidden_company]}, 7, '技术', [EID])}, SCOPE)['facts']


def test_duplicate_statements_keep_all_original_ids_in_comparison():
    a = card()
    b = deepcopy(a); b['evidence_id'] = 'E-222222222222'
    c = card('机器人技术路线采用不同部署方案，需要分别记录测试负载、软件版本与硬件配置。', 'E-333333333333')
    text = render_plan({'facts': [a, b, c]}, 7, '技术路线', [a['evidence_id'], b['evidence_id'], c['evidence_id']])
    assert text.count(a['fact_contract']['statement']) == 1
    assert all('['+f['evidence_id']+']('+f['source_url']+')' in text for f in (a, b, c))


def test_synthesis_rejects_new_numbers_even_when_the_text_is_fluent():
    _, package, plan, _ = setup_claim()
    bad = {k: v for k, v in plan['analysis_claims'][0].items()
        if k in {'question', 'text', 'evidence_ids', 'claim_kind', 'premises', 'reasoning'}}
    bad['text'] += '预计市场规模达到999亿元。'
    kept, errors = validate_analyses([bad], package, 14, [EID])
    assert not kept and 'analysis_unauthorized_number' in errors[0]['issues']


def test_synthesis_failure_reuses_a_current_chapter_judgment_and_makes_only_one_request():
    f, package, plan, _ = setup_claim()
    previous = {**plan['analysis_claims'][0], 'question': '路线及适用场景'}
    project = SimpleNamespace(industry_statement_plans={7: {'analysis_claims': [previous]}}, industry_report_degradations=[])
    packages = {7: json.dumps({'facts': [f]})}
    sections = {7: render_plan({'facts': [f]}, 7, '技术路线对比', [EID], [previous])}
    calls = []
    def invoke(role, prompt, trace):
        calls.append(role)
        raise TimeoutError('synthetic')
    IndustryReportAgent()._write_synthesis(project, {'facts': [f]}, packages, sections, SCOPE, invoke, lambda *a, **k: None, None)
    assert calls == ['行业阶段性综合 Agent']
    assert project.industry_statement_plans[14]['analysis_method'] == 'chapter_analysis_reuse'
    assert TEXT in sections[14]
    previous['support_review'] = {'status': 'unsupported'}
    assert not reuse_chapter_judgments({7: {'analysis_claims': [previous]}}, package)


def test_synthesis_integrates_current_material_from_different_chapters():
    a = card()
    b = card('机器人服务采用订阅和按量计费，用户按实际调用支付费用。',
        'E-222222222222', module='商业模式与盈利逻辑')
    packages = {7: {'facts': [a]}, 10: {'facts': [b]}}
    sections = {n: render_plan(p, n, '技术路线' if n == 7 else '商业模式', [f['evidence_id'] for f in p['facts']]) for n, p in packages.items()}
    text = ('现有材料支持将部署方案与收费方式结合考察：不同场景采用不同架构，订阅和按量计费则提供了不同的收费入口。'
            '初步判断是按场景分别考察技术与变现条件，不能由模式存在直接认定行业已经实现盈利。')
    claim = {'question': '总体判断及成立条件', 'text': text,
        'claim_kind': 'inference', 'evidence_ids': [EID, b['evidence_id']],
        'premises': [{'evidence_id': f['evidence_id'], 'quote': f['fact_contract']['statement']} for f in (a, b)],
        'reasoning': '并列比较不同部署场景与收费模式，提出初步研究判断，不将计费方式作为盈利实绩。'}
    project = SimpleNamespace(industry_statement_plans={}, industry_report_degradations=[])
    calls = []
    def invoke(role, prompt, trace):
        calls.append(role)
        assert '不能整段只列缺口' in prompt
        return json.dumps({'evidence_ids': [EID, b['evidence_id']], 'analyses': [claim]}, ensure_ascii=False)
    IndustryReportAgent()._write_synthesis(project, {'facts': [a, b]}, packages, sections, SCOPE, invoke, lambda *a, **k: None, None)
    assert calls == ['行业阶段性综合 Agent']
    assert text in sections[14]
    report = '\n\n'.join(sections[n] for n in sorted(sections))
    assert len(current_conclusions(report, {'facts': [a, b]}, project.industry_statement_plans, SCOPE)) == 1


def test_native_comparison_keeps_canonical_text_and_links_and_analysis_comes_first():
    f, _, plan, _ = setup_claim()
    b = card('机器人技术路线采用不同部署方案，需要分别记录测试负载、软件版本与硬件配置。', 'E-222222222222')
    text = render_plan({'facts': [f, b]}, 7, '技术路线对比', [EID, b['evidence_id']], plan['analysis_claims'])
    assert text.index('### 研究分析') < text.index('### 关键依据') < text.index('### 技术对照速览')
    assert f['fact_contract']['statement'] in text and f['source_url'] in text
    table, ids = comparison_table([f, b], 7)
    assert len(ids) == 2 and '实测领先' not in table
    chain = card('机器人产业链上游提供控制器，中游完成整机集成，下游服务制造场景。', module='细分赛道与产业链')
    flow, ids = comparison_table([chain], 2)
    assert '| 上游 | 中游 | 下游 |' in flow and '整机集成' in flow
    assert not ids  # The canonical full statement remains below the diagram.


def test_word_findings_have_native_emphasis_and_heading_stays_with_content():
    doc = markdown_to_docx_bytes('## 14. 综合评估\n\n### 阶段性综合结论\n\n> 有依据的阶段性判断。\n\n'
        '| 比较方向 | 原文信息 | 适用边界 |\n| --- | --- | --- |\n| 路线 | 来源信息。 | 所述场景 |', document_kind='industry_report')
    w = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    with ZipFile(io.BytesIO(doc)) as z:
        xml = ET.fromstring(z.read('word/document.xml'))
        styles = ET.fromstring(z.read('word/styles.xml'))
    finding = [p for p in xml.iter(w+'p') if p.find(w+'pPr/'+w+'pStyle') is not None
        and p.find(w+'pPr/'+w+'pStyle').get(w+'val') == 'IndustryFinding']
    assert len(finding) == 1 and finding[0].find(w+'pPr/'+w+'keepLines') is not None
    assert styles.find('.//'+w+"style[@"+w+"styleId='IndustryFinding']/"+w+'pPr/'+w+'shd') is not None
    grid = [int(n.get(w+'w')) for n in xml.find('.//'+w+'tblGrid')]
    assert sum(grid) == 9026 and grid[1] > 2*grid[0]
    for p in xml.iter(w+'p'):
        if '阶段性综合结论' in ''.join(n.text or '' for n in p.iter(w+'t')):
            assert p.find(w+'pPr/'+w+'keepNext') is not None


def test_runtime_synthesis_uses_writer_budget_without_sdk_retries(monkeypatch):
    import research_workflow
    monkeypatch.setenv('ARK_API_KEY', 'synthetic')
    monkeypatch.setenv('MODEL', 'synthetic')
    monkeypatch.delenv('INDUSTRY_CONCLUSION_MAX_OUTPUT_TOKENS',raising=False)
    monkeypatch.delenv('INDUSTRY_WRITER_TIMEOUT_SECONDS',raising=False)
    configured = []
    def model(**kwargs):
        configured.append(kwargs)
        return SimpleNamespace(invoke=lambda messages: SimpleNamespace(content='{}'))
    monkeypatch.setattr(research_workflow, 'init_chat_model', model)
    workflow = research_workflow.ResearchWorkflow.__new__(research_workflow.ResearchWorkflow)
    workflow._invoke_industry_report('行业阶段性综合 Agent', 'synthetic')
    assert configured[0]['timeout'] == 360 and configured[0]['max_retries'] == 0
    assert 'max_tokens' not in configured[0]


def test_unreviewed_risk_is_labelled_preliminary_without_deleting_its_score():
    from industry_delivery import risk_status_section
    from industry_research import delivery_review_reasons, active_risk_dimensions
    dimensions = [{'name': name, 'score': 40, 'level': 'medium', 'reason': '原始模型理由。',
        'evidence_ids': [EID], 'claim_support_review': {'status': 'not_evaluated'}} for name in active_risk_dimensions(SCOPE)]
    risk = {'dimensions': dimensions, 'overall_score': 40}
    original = deepcopy(risk)
    text = risk_status_section(risk, SCOPE)
    assert '6项形成模型初评' in text and '6项判断支持关系尚待复核' in text
    assert '模型风险初评总分：40' in text and text.count('初评待复核') == 6
    assert risk == original
    reasons = delivery_review_reasons(SCOPE, risk, [])
    assert len(reasons) == 6 and all(r['code'] == 'risk_claim_support_pending' for r in reasons)
