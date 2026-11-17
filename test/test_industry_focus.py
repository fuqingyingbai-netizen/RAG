import json
from types import SimpleNamespace
import pytest
from industry_focus import MODULES, apply_focus, question_depth, module_enabled
from industry_fact_contracts import CHAPTER_QUESTIONS
from industry_conclusion_recovery import recovery_plan, targeted_queries
from industry_research import scope_fingerprint
from report_agents.industry_template import INDUSTRY_REPORT_OUTLINE
from research_workflow import ResearchWorkflow


def test_mapping_uses_real_questions_and_never_expands_related_chapters():
    for row in MODULES.values():
        for chapter, names in row['primary'].items():
            assert 1 <= int(chapter) <= len(INDUSTRY_REPORT_OUTLINE)
            assert set(names) <= dict(CHAPTER_QUESTIONS.get(int(chapter), [] )).keys()
    scope = apply_focus({}, ['市场规模与增长'])
    assert all(question_depth(scope, 4, q) == 'priority' for q, _ in CHAPTER_QUESTIONS[4])
    assert all(question_depth(scope, c, q) == 'basic' for c in (5, 10, 11) for q, _ in CHAPTER_QUESTIONS[c])
    assert len(INDUSTRY_REPORT_OUTLINE) == 16


def test_technology_modules_target_different_questions():
    scope = apply_focus({}, ['技术演进与平台生态'])
    assert question_depth(scope, 7, '落地难度与迭代成熟度') == 'priority'
    assert question_depth(scope, 7, '可核验性能及单位成本') == 'basic'
    scope = apply_focus({}, ['技术路线对比'])
    assert question_depth(scope, 7, '可核验性能及单位成本') == 'priority'
    assert question_depth(scope, 7, '落地难度与迭代成熟度') == 'basic'


@pytest.mark.parametrize('serialized', [False, True])
def test_recovery_only_collects_focus_gaps_but_keeps_basic_repairs(serialized):
    scope = apply_focus({}, ['行业定义与边界'])
    names = [q for q, _ in CHAPTER_QUESTIONS[2]]
    package = {'industry_scope': scope}
    plans = {2: {'generation_batches': {'questions': [
        {'question': names[0], 'status': 'material_gap'},
        {'question': names[1], 'status': 'material_gap'},
        {'question': names[2], 'status': 'generation_failed'}]}}}
    result = recovery_plan(plans, {2: json.dumps(package) if serialized else package})
    assert [(t['question'],t['action']) for t in result['tasks']] == [(names[0],'collect_evidence'),(names[2],'retry_generation')]
    assert result['deferred_research'][0]['question'] == names[1]
    assert result['deferred_research'][0]['status'] == 'unresolved'
    queries = targeted_queries(result,'机器人')
    assert len(queries) == 1 and queries[0]['question'] == names[0]
    assert targeted_queries(result,'机器人',[q['query'] for q in queries])[0]['query'] != queries[0]['query']


def test_focus_changes_checkpoint_not_source_ownership():
    old = {'target_name':'机器人','focus_modules':['市场规模与增长'],'industry_scope':{'capital_market':'none'}}
    new = {**old, 'industry_scope':apply_focus(old['industry_scope'],old['focus_modules'])}
    assert scope_fingerprint(old) != scope_fingerprint(new)
    assert scope_fingerprint(old,True) == scope_fingerprint(new,True)
    assert not module_enabled(apply_focus({'capital_market':'none'},['投融资与资本市场']),'投融资与资本市场')
    assert question_depth({},4,CHAPTER_QUESTIONS[4][0][0]) == 'priority'


@pytest.mark.parametrize('modules', [[], ['市场规模与增长']])
def test_normalization_planning_and_queries_preserve_focus_including_empty(modules):
    w = ResearchWorkflow.__new__(ResearchWorkflow)
    p = SimpleNamespace(title='机器人研究', target_name='机器人', target_type='industry', industry='机器人', description='')
    intake = w._normalize_intake(p, {'target_type':'industry','focus_modules':modules,'include_capital_markets':False,'as_of_date':'2026-11-17'}, [], [])
    assert intake['focus_modules'] == modules
    assert intake['industry_scope']['focus_modules'] == modules
    plan = w.plan_research(p,intake)
    assert [m['name'] for m in plan['modules']] == modules
    queries = w._expand_search_queries(plan,intake)
    assert all(q['module'] in modules for q in queries)
    assert bool(queries) == bool(modules)
    quality = w._apply_authority_coverage_requirements({},'industry',intake['industry_scope'])
    assert set(quality['authority_requirements']) <= set(modules)


def test_writer_prioritizes_focus_without_dropping_other_questions_or_cards():
    from copy import deepcopy
    from test_industry_chapter_batches import rich_package
    from industry_question_generation import compile_jobs
    package = rich_package()
    package['industry_scope'] = apply_focus(package.get('industry_scope', {}), ['细分赛道与产业链'])
    before = deepcopy(package)
    jobs, diagnostic = compile_jobs(package, 2, question_order=['Q1','Q2','Q3','Q4'])
    assert [q['id'] for job in jobs for q in job['questions']] == ['Q2','Q3','Q4','Q1']
    assert package == before
    assert len(diagnostic['questions']) == 4
    assert diagnostic['questions'][0]['research_depth'] == 'basic'


def test_supplement_query_uses_selected_owner_not_first_related_module():
    scope = apply_focus({}, ['商业模式与盈利逻辑'])
    result = recovery_plan({}, {10: {'industry_scope':scope}})
    queries = targeted_queries(result,'机器人')
    assert queries and all(q['module'] == '商业模式与盈利逻辑' for q in queries)
