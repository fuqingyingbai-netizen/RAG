import json
import re
from copy import deepcopy
from types import SimpleNamespace

import pytest
from industry_chapters import CHAPTERS, VERSION, apply_selection, public_config, report_chapters, validate_selection
from industry_research import normalize_scope, scope_fingerprint
from report_agents.industry_template import INDUSTRY_REPORT_OUTLINE, validate_report_template


def normalize(ids=None, **extra):
    raw = {'target_name': '机器人行业', 'as_of_date': '2026-11-17', **extra}
    if ids is not None:
        raw['industry_chapter_ids'] = ids
    result = dict(raw, focus_modules=['市场规模与增长'])
    result['industry_scope'] = normalize_scope(SimpleNamespace(target_name='机器人行业'), result, raw)
    apply_selection(result, raw)
    return result


def test_public_config_matches_runtime_outline_and_questions():
    from industry_fact_contracts import CHAPTER_QUESTIONS
    config = public_config()
    assert config['version'] == VERSION
    assert len(config['chapters']) == 16
    assert len([c for c in config['chapters'] if c['selectable']]) == 12
    assert len(config['automatic']) == 4
    assert len(config['defaults']) == 9
    assert INDUSTRY_REPORT_OUTLINE == [(c['title'], c['requirements']) for c in CHAPTERS]
    assert sum(map(len, CHAPTER_QUESTIONS.values())) == 41
    for c in CHAPTERS:
        assert [q for q, _ in CHAPTER_QUESTIONS.get(c['chapter'], [])] == [q['question'] for q in c['questions']]


@pytest.mark.parametrize('ids', [[], ['unknown'], ['industry.ch01'], ['industry.ch14'], [4], 'industry.ch04'])
def test_rejects_invalid_or_empty_explicit_selection(ids):
    with pytest.raises(ValueError):
        validate_selection(ids)


def test_selected_output_and_shared_research_dependencies_are_separate():
    result = normalize(['industry.ch11'])
    assert report_chapters(result['industry_scope']) == [1, 11, 14, 15, 16]
    assert result['focus_modules'] == ['市场规模与增长', '技术演进与平台生态', '政策与监管']
    assert normalize(['industry.ch07', 'industry.ch07'])['industry_chapter_ids'] == ['industry.ch07']


def test_legacy_saved_modules_retain_full_outline():
    result = normalize()
    assert 'selected_chapters' not in result['industry_scope']
    assert report_chapters(result['industry_scope']) == list(range(1, 17))
    assert result['focus_modules'] == ['市场规模与增长']


def test_resume_preserves_selection_and_fingerprints_only_delivery_change():
    first = normalize(['industry.ch08'], include_capital_markets=True)
    second = normalize(['industry.ch09'], include_capital_markets=True)
    assert first['focus_modules'] == second['focus_modules']
    assert scope_fingerprint(first) != scope_fingerprint(second)
    assert scope_fingerprint(first, source_only=True) == scope_fingerprint(second, source_only=True)
    resumed = normalize(industry_scope=deepcopy(first['industry_scope']))
    assert resumed['industry_chapter_ids'] == first['industry_chapter_ids']


def test_scope_constraints_are_explicit():
    with pytest.raises(ValueError, match='资本市场'):
        normalize(['industry.ch08'], include_capital_markets=False)
    with pytest.raises(ValueError, match='核心企业'):
        normalize(['industry.ch12'])
    assert normalize(['industry.ch12'], focus_entities='示例公司')['focus_modules'] == ['核心企业尽调']


def test_template_rejects_unselected_chapters_and_ignores_their_old_gaps():
    scope = normalize(['industry.ch04'])['industry_scope']
    report = '\n\n'.join(f"## {n}. {INDUSTRY_REPORT_OUTLINE[n-1][0]}\n正文" for n in report_chapters(scope))
    stale = {6: {'content_coverage': [{'question': '份额', 'status': 'missing'}]}}
    check = validate_report_template(report, stale, scope)
    assert check['structure_passed'] and not check['content_gaps']
    assert not validate_report_template(report + '\n## 6. 竞争格局\n正文', {}, scope)['structure_passed']


def test_actual_agent_schedules_only_selected_body_and_auto_sections(monkeypatch):
    import report_agents.industry_report_agent as module
    from industry_conclusion_recovery import recovery_plan
    from industry_chapter_research import prepare_chapter_packages
    scope = normalize(['industry.ch04'])['industry_scope']
    project = SimpleNamespace(target_name='机器人行业', title='测试', industry='', target_type='industry', industry_scope=scope)
    calls = []
    monkeypatch.setattr(module, '_focused_cleaned_json', lambda *a: json.dumps({'facts': [{'evidence_id':'E-12345678','fact':'2025年公开样本数据','scope_match':'in_scope'}]}))
    monkeypatch.setattr(module.IndustryReportAgent, '_write_section', lambda self, project, package, risk, index, title, *a, **k: calls.append(index) or f'## {index}. {title}\n\n本章示例 [E-12345678]。')
    agent = module.IndustryReportAgent()
    text = agent.generate(project, '{"facts":[]}', '{"dimensions":[]}', lambda *a: '{}', lambda text,n:text[:n], lambda *a,**k:None)
    assert calls == [4, 15, 1]
    assert [int(n) for n in re.findall(r'^## (\d+)\.', text, re.M)] == [1,4,14,15,16]
    assert set(project.industry_section_packages) == {1,4,14,15,16}
    packages = {}
    prepare_chapter_packages({'facts': []}, packages, project)
    assert set(packages) == {4}
    old = {6: {'generation_batches': {'questions': [{'question':'份额及集中度','status':'material_gap'}]}}}
    assert not recovery_plan(old, {6: {'facts':[]}}, scope)['tasks']


def test_api_preserves_selection_and_rejects_unknown_ids():
    from fastapi import HTTPException
    from research_api import _locked_run_intake, industry_chapter_config
    from research_schemas import ResearchRunRequest
    assert industry_chapter_config() == public_config()
    request = ResearchRunRequest(target_type='industry', industry_chapter_ids=['industry.ch04'], industry_template_version=VERSION)
    assert _locked_run_intake(request)['industry_chapter_ids'] == ['industry.ch04']
    with pytest.raises(HTTPException) as error:
        _locked_run_intake(ResearchRunRequest(target_type='industry', industry_chapter_ids=[]))
    assert error.value.status_code == 422
    with pytest.raises(HTTPException) as error:
        _locked_run_intake(ResearchRunRequest(target_type='industry', industry_template_version='stale'))
    assert error.value.status_code == 409


def test_scope_normalization_reuses_sources_but_does_not_force_company_research():
    from research_workflow import research_workflow
    project = SimpleNamespace(target_name='机器人行业', title='研究', target_type='industry', industry='', description='')
    raw={'target_type':'industry', 'industry_chapter_ids':['industry.ch04'], 'focus_entities':'示例公司'}
    normalized=research_workflow._normalize_intake(project,raw,[],[])
    assert normalized['focus_modules'] == ['市场规模与增长']
    assert normalized['industry_scope']['selected_chapters'] == [4]


def test_fact_contract_chapter_phase_and_finalization_keep_selection():
    from report_agents.industry_report_agent import IndustryReportAgent
    from industry_conclusion_recovery import snapshot
    scope=normalize(['industry.ch04'])['industry_scope']
    project=SimpleNamespace(target_name='机器人行业',title='研究',industry='',target_type='industry',
                            industry_scope=scope,industry_chapter_phase=True)
    payload=json.dumps({'fact_contract_version':'test','facts':[],'industry_scope':scope})
    agent=IndustryReportAgent()
    args=(project,payload,'{"dimensions":[]}',lambda *a:'{}',lambda text,n:text[:n],lambda *a,**k:None)
    agent.generate(*args)
    assert set(project.industry_chapter_research_plan['chapters']) == {'4'}
    assert set(project.industry_generated_sections) <= {1,4,15}
    project.industry_chapter_phase=False
    project.industry_recovery_seed=snapshot(project)
    project.industry_recovery_plan={'chapters':[],'finalize_synthesis':True}
    report=agent.generate(*args)
    assert validate_report_template(report,project.industry_statement_plans,scope)['structure_passed']
    assert set(project.industry_statement_plans) <= {1,4,14,15,16}
