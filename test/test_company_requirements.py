"""Behavioral checks for question routing and domain isolation."""
from copy import deepcopy
from pathlib import Path
import re
from types import SimpleNamespace

from company_requirements import build_requirements, platform_requirement_ids, VERSION
from company_platform import CompanyPlatformAudit
from research_strategies import get_research_strategy
from research_workflow import ResearchWorkflow


def intake(**changes):
    return {'target_type': 'company', 'target_name': '示例制造股份有限公司',
            'official_identifier': 'IDENTIFIER-TEST', 'as_of_date': '2026-10-24',
            'industry': '制造业', **changes}


def checkbox_modules():
    text = (Path(__file__).parents[1] / 'frontend/script.js').read_text(encoding='utf-8')
    block = text.split('modulesByTarget: { company: [', 1)[1].split('], person:', 1)[0]
    return re.findall(r"value:\s*'([^']+)'", block)


def test_every_real_company_checkbox_has_a_specific_question_and_original_contract():
    modules = checkbox_modules()
    rows = build_requirements(modules, intake())
    assert len(rows) == len(modules) == len({r['requirement_id'] for r in rows})
    for row in rows:
        assert row['question'] != row['module']
        assert row['expected_original_fields'] and row['chapters'] and row['query_terms']
        assert row['budget_exhaustion_is_not_acceptance'] is True
        assert row['state'] == 'planned'
        assert all(route['availability'] == 'requires_live_verification' for route in row['routes'])


def test_scope_witness_is_order_stable_and_invalidates_for_entity_identifier_and_period():
    old = build_requirements(['收入情况'], intake())[0]
    reordered = dict(reversed(list(intake().items())))
    assert build_requirements(['收入情况'], reordered)[0] == old
    for changes in [{'target_name': '另一制造有限公司'}, {'official_identifier': 'OTHER'}, {'as_of_date': '2025-12-31'}]:
        new = build_requirements(['收入情况'], intake(**changes))[0]
        assert new['requirement_id'] == old['requirement_id']
        assert new['scope_sha256'] != old['scope_sha256']
        assert new['input_sha256'] != old['input_sha256']


def test_revenue_query_asks_for_accounting_scope_instead_of_the_checkbox_label():
    strategy = get_research_strategy('company')
    templates = strategy.templates_for_module('收入情况', intake()['target_name'], '制造业')
    assert all('收入情况' not in query for query in templates)
    questions = strategy.module_questions('收入情况', intake()['target_name'], '制造业')
    assert any('会计期间' in question and '调整口径' in question for question in questions)
    rows = strategy.expand_search_queries({'modules': [{'name': '收入情况'}]}, intake())
    selected = [row for row in rows if row['module'] == '收入情况']
    assert selected and all(row['company_requirement_ids'] and row['query_purpose'] for row in selected)


def test_platform_mapping_requires_the_actual_target_and_aspect():
    rows = build_requirements(['融资情报', '管理团队'], intake())
    args = {'firm_name': intake()['target_name'], 'aspect': '融资状况分析'}
    ids = platform_requirement_ids(rows, 'xiniu', 'get_company_info', args)
    assert ids == [rows[0]['requirement_id']]
    assert platform_requirement_ids(rows, 'xiniu', 'get_company_info', {**args, 'firm_name': '关联方有限公司'}) == []
    assert platform_requirement_ids(rows, 'xiniu', 'get_company_info', {**args, 'aspect': '风险评估'}) == []


def test_platform_quota_failure_remains_a_collection_gap_linked_to_the_question():
    project = SimpleNamespace(company_research_requirements=build_requirements(['诉讼/制裁'], intake()))
    audit = CompanyPlatformAudit(project, 'qcc', 'test-credential', {})
    audit.record('get_company_risk_scan', {'searchKey': intake()['target_name']}, 'failed', 'quota_exceeded')
    row = project.company_professional_platform_attempts[0]
    assert row['company_requirement_ids']
    assert row['status'] == 'failed' and row['reason'] == 'quota_exceeded'
    assert 'risk_score' not in row and 'severity' not in row


def test_unknown_choice_requires_a_real_question_instead_of_claiming_a_supported_route():
    row = build_requirements(['客户自定义专项'], intake())[0]
    assert row['state'] == 'requires_specific_question' and row['routes'] == []


def test_plan_persists_company_contract_but_other_target_plans_keep_their_semantics():
    workflow = ResearchWorkflow()
    project = SimpleNamespace(target_name=intake()['target_name'], title='研究', industry='制造业', target_type='company')
    plan = workflow.plan_research(project, intake(focus_modules=['收入情况', '诉讼/制裁']))
    assert plan['company_requirement_version'] == VERSION
    assert plan['company_requirements'] == project.company_research_requirements
    assert all(module['company_requirement_ids'] for module in plan['modules'])
    for kind in ('person', 'industry'):
        other = SimpleNamespace(target_name='示例对象', title='研究', industry='', target_type=kind)
        config = {'target_type': kind, 'target_name': '示例对象', 'focus_modules': ['公司背景']}
        before = deepcopy(config)
        other_plan = workflow.plan_research(other, config)
        assert 'company_requirements' not in other_plan
        assert not hasattr(other, 'company_research_requirements')
        assert config == before
