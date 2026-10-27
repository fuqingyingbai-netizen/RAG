"""Synthetic regressions for fixed content requirements and flexible analysis."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from industry_fact_contracts import (attach_contract, chapter_coverage, chapter_admitted,
    parse_chapter_response, plan_prompt, render_plan, validate_analyses)
from industry_grounding import sample_boundary
from industry_delivery import task_criteria, verification_tasks, verification_task_table
from report_agents.industry_report_agent import IndustryReportAgent
from report_agents.industry_proposal import build_industry_proposal
from report_agents.industry_template import (INDUSTRY_REPORT_OUTLINE, TEMPLATE_VERSION,
    chapter_template_contract, validate_report_template)

SCOPE = {'industry_name':'机器人', 'segments':['机器人'], 'capital_market':'none',
         'named_companies':[], 'as_of_date':'2030-10-01', 'geography':'中国大陆'}
EID = 'E-111111111111'


def fact(quote, body=None, **updates):
    body = body if body is not None else quote
    start = body.index(quote)
    item = {'evidence_id':EID, 'fact':quote, 'evidence_quote':quote, 'scope_match':'in_scope',
        'source_title':'机器人研究', 'source_url':'https://research.example/report',
        'evidence_scope':'industry_level', 'module':'细分赛道与产业链',
        'provenance':{'locator':{'status':'verified','start':start,'end':start+len(quote),
            'quote':quote,'body_sha256':hashlib.sha256(body.encode()).hexdigest()}}}
    item.update(updates)
    return item, body


def chain():
    f, body = fact('机器人产业链上游提供控制器，中游完成整机集成，下游服务制造场景。')
    return attach_contract(f, SCOPE, body)


ANALYSIS = ('材料把产业链分为供给、系统集成和应用环节，可以作为梳理分工的起点。'
            '它没有给出各环节的价值占比和供需数据，因此还不足以比较盈利能力或认定核心瓶颈。')


def claim(text=ANALYSIS, **updates):
    return {'question':'产业链主体和分层关系', 'text':text, 'evidence_ids':[EID], **updates}


def test_source_population_is_inherited_without_rewriting_the_source():
    quote = '基础层企业营收波动较大，应用层企业现金流表现更为平稳。'
    body = '本文将行业指数成分股合并去重后加入发债企业，作为分析样本，共105家企业。\n'+quote
    f, _ = fact(quote, body, module='商业模式与盈利逻辑')
    original = deepcopy(f)
    checked = attach_contract(f, SCOPE, body)
    assert checked['fact_contract']['report_admitted']
    assert checked['fact_contract']['sample_boundary']
    assert not checked['fact_contract']['risk_admitted']
    assert checked['eligible_for_risk_scoring'] is False
    assert not chapter_admitted(checked, 1)
    assert '样本观察' in checked['fact_contract']['statement']
    assert f == original and checked['evidence_quote'] == quote


def test_unbound_body_cannot_supply_sample_qualifications():
    f, body = fact('机器人企业采用按量计费，用户按实际调用支付费用。')
    assert sample_boundary(f, '本文选取企业作为分析样本。'+body) == ''


def test_generic_industry_statement_remains_usable():
    f, body = fact('机器人企业采用按量计费，用户按实际调用支付费用。')
    c = attach_contract(f, SCOPE, body)['fact_contract']
    assert c['report_admitted'] and c['risk_admitted'] and not c['sample_boundary']


def test_named_company_comparison_and_methodological_opinion_keep_their_roles():
    f, body = fact('判断大模型公司商业健康度，毛利率的走向比单纯营收增速更有意义。',
        source_title='甲公司与Beta公司，谁更有盈利能力？', module='商业模式与盈利逻辑')
    c = attach_contract(f, SCOPE, body)['fact_contract']
    assert c['source_role'] == 'opinion' and c['sample_boundary'] and not c['risk_admitted']
    generic, body = fact('机器人云端和端侧采用不同架构，适用场景不同。', source_title='云端与端侧，谁更适合边缘部署？')
    assert not sample_boundary(generic, body)


def test_layering_analysis_and_coverage_share_a_rule_but_not_concentration_permission():
    f, body = fact('机器人市场参与者可以分为三个派系，分别是头部平台、融合产业企业和技术企业。', module='竞争格局与代表企业')
    f = attach_contract(f, SCOPE, body)
    rows = {r['question']:r for r in chapter_coverage({'facts':[f]}, 6, [EID])}
    assert rows['竞争机制与玩家分层']['evidence_ids'] == [EID]
    assert rows['份额及集中度']['status'] == 'missing'
    rendered = render_plan({'facts':[f]}, 6, '竞争格局', [EID])
    assert '提供了定性的玩家分层' in rendered


def test_historical_observation_is_labelled_without_changing_archived_quote():
    quote = '根据《机器人产业研究报告(2024)》，我国目前机器人市场参与者可以分为头部和初创企业。'
    f, body = fact(quote)
    checked = attach_contract(f, SCOPE, body)
    assert '历史来源观察（2024年口径）' in checked['fact_contract']['statement']
    assert checked['evidence_quote'] == quote and checked['fact_contract']['period'] == '2024'


def test_broken_display_title_uses_document_heading_and_preserves_original():
    quote = '机器人企业收入结构与毛利率存在差异。'
    body = '## 摘要\n作 者：张甲 机器人企业信用状况分析 邮 箱：a@example.test\n'+quote
    f, _ = fact(quote, body, source_title='1. 究》，2028.6.21')
    checked = attach_contract(f, SCOPE, body)
    assert checked['source_display_title'] == '机器人企业信用状况分析'
    assert checked['source_title'] == f['source_title'] and checked['evidence_quote'] == quote


def test_actual_prompt_contains_the_fixed_template_and_all_chapter_questions():
    f = chain(); package = {'facts':[f], 'industry_scope':SCOPE}
    data = json.loads(plan_prompt(package, 2).split('\n', 1)[1])
    assert data['template_contract']['version'] == TEMPLATE_VERSION
    assert data['template_contract']['required_content'] == INDUSTRY_REPORT_OUTLINE[1][1]
    assert '各环节价值分配及毛利率' in data['required_questions']
    assert data['template_contract']['scope_rules']['capital_enabled'] is False
    assert data['template_contract']['scope_rules']['company_diligence_enabled'] is False
    assert 'analyses' in plan_prompt(package, 2)


def test_free_analysis_is_rendered_separately_from_immutable_sources():
    f = chain(); package = {'facts':[f]}
    ids, proposed = parse_chapter_response(json.dumps({'evidence_ids':[EID],'analyses':[claim()]}, ensure_ascii=False), package, 2)
    accepted, errors = validate_analyses(proposed, package, 2, ids)
    assert len(accepted) == 1 and not errors
    result = render_plan(package, 2, INDUSTRY_REPORT_OUTLINE[1][0], ids, accepted)
    assert ANALYSIS in result and f['fact_contract']['statement'] in result
    assert '### 研究分析' in result and accepted[0]['entailment_status'] == 'not_evaluated'


@pytest.mark.parametrize('bad,code', [
    (claim(ANALYSIS+'市场规模达到999亿元。'), 'analysis_unauthorized_number'),
    (claim(question='自行编造的模板问题'), 'unknown_template_question'),
    (claim(evidence_ids=['E-222222222222']), 'invalid_analysis_citations'),
    (claim(ANALYSIS+'按第九条规定，企业必须取得经营许可证。'), 'analysis_unauthorized_legal_statement'),
    (claim(ANALYSIS+'<script>bad()</script>'), 'invalid_analysis_text'),
])
def test_invalid_analysis_is_not_rendered(bad, code):
    accepted, errors = validate_analyses([bad], {'facts':[chain()]}, 2, [EID])
    assert not accepted and code in errors[0]['issues']


def test_unrelated_chapter_evidence_cannot_answer_a_different_requirement():
    accepted, errors = validate_analyses([claim(question='核心瓶颈')], {'facts':[chain()]}, 2, [EID])
    assert not accepted and 'analysis_question_evidence_mismatch' in errors[0]['issues']


def test_methodological_expression_is_not_mistaken_for_a_new_legal_obligation():
    body = ANALYSIS+'进一步比较成本必须先核对统计口径，这属于研究条件。'
    accepted, errors = validate_analyses([claim(body)], {'facts':[chain()]}, 2, [EID])
    assert accepted and not errors


def test_isolated_market_point_does_not_satisfy_historical_series_or_long_forecast():
    f, body = fact('2024年中国机器人市场规模达到120亿元。', module='市场规模与增长',
        numeric_context={'metric':'市场规模','value':'120','unit':'亿元','period':'2024','geography':'中国大陆',
                         'definition':'中国机器人市场规模','is_forecast':False}, numeric_validation={'passed':True})
    f = attach_contract(f, SCOPE, body)
    rows = {r['question']:r for r in chapter_coverage({'facts':[f],'industry_scope':SCOPE}, 4, [EID])}
    assert rows['规模、期间和统计口径']['evidence_ids'] == [EID]
    assert rows['近三至五年历史序列与CAGR']['status'] == 'background_only'
    assert rows['未来五至十年来源预测']['status'] == 'missing'


def test_failed_local_repair_keeps_good_statements_without_repeated_requests():
    project = SimpleNamespace(industry_statement_plans={}, industry_report_degradations=[])
    calls = []
    def invoke(*args):
        calls.append(args)
        return json.dumps({'evidence_ids':[EID], 'analyses':[claim(ANALYSIS+'市场规模达到999亿元。')]})
    f = chain()
    text = IndustryReportAgent()._write_statement_section(project, {'facts':[f]}, 2, INDUSTRY_REPORT_OUTLINE[1][0], invoke, lambda *a,**k:None, None)
    assert len(calls) == 2 and '999' not in text and f['fact_contract']['statement'] in text
    assert project.industry_statement_plans[2]['analysis_rejections']


def test_valid_analysis_is_used_by_the_live_writer_and_saved_as_a_draft_claim():
    project = SimpleNamespace(industry_statement_plans={}, industry_report_degradations=[])
    text = IndustryReportAgent()._write_statement_section(project, {'facts':[chain()], 'industry_scope':SCOPE}, 2,
        INDUSTRY_REPORT_OUTLINE[1][0], lambda *args:json.dumps({'evidence_ids':[EID],'analyses':[claim()]}), lambda *a,**k:None, None)
    assert ANALYSIS in text
    assert project.industry_statement_plans[2]['analysis_method'] == 'evidence_bounded_model_analysis'
    assert any(r['analysis_status'] == 'draft_analysis_present' for r in project.industry_statement_plans[2]['content_coverage'])
    assert project.industry_report_degradations  # Rule checks do not certify prose semantics.


def test_program_checks_template_order_titles_and_missing_content():
    report = '\n\n'.join(f'## {i}. {title}\n正文' for i,(title,_) in enumerate(INDUSTRY_REPORT_OUTLINE,1))
    plan = {7:{'content_coverage':[{'question':'可核验性能及单位成本','status':'missing','analysis_status':'analysis_not_completed'}]}}
    checked = validate_report_template(report, plan, SCOPE)
    assert checked['structure_passed'] and checked['content_gaps'][0]['chapter'] == 7
    assert not validate_report_template(report.replace('## 7. 技术路线对比','## 7. 自行更名'))['structure_passed']
    assert not validate_report_template(report.replace('## 7.','## 8.'))['structure_passed']


def test_task_completion_matches_the_evidence_kind():
    tech = task_criteria('可比技术成本及测试条件')
    profit = task_criteria('行业盈利质量及样本边界')
    assert all(s in tech[2] for s in ['环境','版本','负载','性能','单位成本'])
    assert '样本' in profit[2] and '实际收费' in profit[2] and tech[2] != profit[2]


def test_grouped_review_exposes_individual_questions_in_both_deliverables():
    f = chain()
    notes = [{'chapter':7,'review_type':'statement_synthesis_review','evidence_ids':[EID],
        'content_coverage':[{'question':'可核验性能及单位成本','status':'missing','evidence_ids':[]}]}]
    tasks = verification_tasks({'facts':[f]}, {}, notes, SCOPE)
    assert len(tasks) == 1 and tasks[0]['subtasks'][0]['chapter'] == 7
    table = verification_task_table(tasks)
    assert '可核验性能及单位成本' in table and '环境、版本、负载' in table
    proposal = build_industry_proposal(SimpleNamespace(title='合成研究',target_name='机器人',industry_scope=SCOPE,industry_verification_tasks=tasks))
    assert '第7章：可核验性能及单位成本' in proposal and '项目报价与保密条款' in proposal
