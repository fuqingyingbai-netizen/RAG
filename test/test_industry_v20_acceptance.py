"""Independent holdouts: claim-specific support and neutral missing-data language."""
from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from industry_assertions import claims_observed_growth, required_source_count
from industry_evidence import evidence_requirements, fact_requirement_ids
from industry_fact_contracts import attach_contract
from industry_research import claim_semantic_issues, normalize_risk
from test_industry_fact_contracts import card, SCOPE
from test_industry_v17_acceptance import observation


def codes(text, facts):
    return {issue['code'] for issue in claim_semantic_issues(text,facts)}


@pytest.mark.parametrize('phrase', ['增长持续','增长势头持续','增长仍在持续','保持增长势头'])
def test_single_growth_rate_and_other_market_forecast_do_not_establish_continuity(phrase):
    facts=[observation(1,metric='同比增长',value='24',unit='%',definition='机器人产业规模同比增长'),
           observation(2,period='2025',value='1.2',unit='万亿元'),
           observation(3,period='2026',value='515',unit='亿美元',is_forecast=True,definition='机器人算力市场规模')]
    text='2024年同比增长24%，2025年规模超过1.2万亿元，2026年算力市场预测515亿美元，'+phrase+'；预测假设另行核对。'
    assert 'growth_trend_not_comparable' in codes(text,facts)


@pytest.mark.parametrize('text', ['不能据单期数字认定增长持续。','增长持续性待验证。',
    '预计未来仍将持续增长。','以持续增长为假设。','持续增长仍待验证。','增长持续性尚未得到验证。',
    '否则删除持续增长判断并保留未知。','避免增长持续的无依据判断。'])
def test_pending_negated_and_predicted_continuity_is_not_a_realized_claim(text):
    assert not claims_observed_growth(text)


def test_real_comparable_history_still_allows_a_cautious_continuity_claim():
    facts=[observation(1,period='2023',value='100'),observation(2,period='2024',value='120')]
    assert not codes('这些同口径历史记录显示增长持续。',facts)


@pytest.mark.parametrize('count', ['3份报告','三份报告','3篇研究报告'])
def test_parenthetical_source_count_does_not_count_a_republication_twice(count):
    facts=[observation(1),observation(2),observation(3)]
    facts[1]['evidence_quote']=facts[0]['evidence_quote']
    text='存在多源交叉验证（如2024年市场规模120亿元见于'+count+'）。'
    assert required_source_count(text)==3
    assert 'source_corroboration_overstated' in codes(text,facts)


def test_unrelated_agreement_cannot_validate_the_value_actually_claimed():
    facts=[observation(1,value='120'),observation(2,value='130'),observation(3,value='130')]
    assert 'numeric_corroboration_not_comparable' in codes('市场规模120亿元已经多源交叉验证。',facts)
    assert not codes('市场规模130亿元已有多源交叉验证。',facts)


def test_three_matching_distinct_sources_pass_minimum_count_without_certifying_independence():
    facts=[observation(1),observation(2),observation(3)]
    assert not codes('多源交叉验证：市场规模120亿元见于3份报告。',facts)


def test_neutral_absence_of_penalties_does_not_force_a_policy_score_to_unknown():
    fact=attach_contract(card('机器人服务提供者应当制定具体、可操作的数据标注规则。',
        module='政策与监管',source_url='https://www.cac.gov.cn/rules'),SCOPE)
    reason='原文明确服务提供者的数据标注合规义务；本轮无证据显示已发生大规模处罚或准入限制，执行材料仍需核验。'
    risk=normalize_risk({'dimensions':[{'name':'政策与监管风险','score':65,'reason':reason,'evidence_ids':[fact['evidence_id']]}]},[fact],SCOPE)
    assert next(d for d in risk['dimensions'] if d['name']=='政策与监管风险')['score']==65
    assert 'absence_as_low_risk' in codes('未见处罚，因此监管风险较低，影响可控。',[fact])


def test_a_market_size_card_cannot_lend_a_second_geographical_share_to_player_coverage():
    fact=attach_contract(card('2024年中国机器人市场规模为120亿元，北京市场份额占30%。',
        '市场规模','120','亿元',module='竞争格局与代表企业'),SCOPE)
    requirements=evidence_requirements(['竞争格局与代表企业'])
    original=deepcopy(fact)
    assert 'market_share' not in fact_requirement_ids(fact,requirements)
    assert fact==original
    share=card('2024年中国机器人市场份额为30%。','市场份额','30','%',module='竞争格局与代表企业')
    assert 'market_share' in fact_requirement_ids(share,requirements)


def test_original_rejection_stays_in_audit_until_a_fresh_assessment():
    fact=attach_contract(card('机器人服务提供者应当制定数据标注规则。',module='政策与监管'),SCOPE)
    row={'name':'政策与监管风险','score':None,'unknown_cause':'absence_as_low_risk',
         'validation_diagnostic':{'original_score':65,'original_reason':'存在标注义务，未取得处罚材料。',
                                  'rejection_cause':'absence_as_low_risk','supplied_evidence_ids':[fact['evidence_id']]}}
    checked=normalize_risk({'dimensions':[row]},[fact],SCOPE)
    result=next(d for d in checked['dimensions'] if d['name']==row['name'])
    assert result['score'] is None and result['validation_diagnostic']['original_score']==65


def test_new_rejections_feed_report_and_proposal_correction_tasks():
    from industry_delivery import verification_tasks
    from report_agents.industry_proposal import build_industry_proposal
    risk={'dimensions':[{'name':'市场增长与需求风险','score':None,'unknown_cause':'growth_trend_not_comparable',
        'validation_diagnostic':{'original_score':55}}]}
    tasks=verification_tasks({},risk,[],SCOPE)
    project=SimpleNamespace(title='机器人研究',target_name='机器人',industry_scope=SCOPE,industry_verification_tasks=tasks)
    proposal=build_industry_proposal(project,risk_json=json.dumps(risk,ensure_ascii=False))
    assert all(t['action'] in proposal and t['completion'] in proposal for t in tasks)
    assert '时间序列' in proposal


def test_a_source_headline_or_top_four_list_does_not_prove_first_place():
    source=attach_contract(card('研究机构近日发布《机器人云服务市场份额》报告。',
        module='竞争格局与代表企业',source_title='甲公司连续位居机器人云市场第一'),SCOPE)
    top_four=attach_contract(card('市场份额前四的厂商包括甲公司、乙公司、丙公司和丁公司。',
        module='竞争格局与代表企业',evidence_id='E-222222222222'),SCOPE)
    assert 'ranking_source_missing' in codes('甲公司居机器人云服务市场第一。',[source,top_four])
    ranked=attach_contract(card('甲公司在中国机器人云服务市场位居第一。',module='竞争格局与代表企业'),SCOPE)
    assert 'ranking_source_missing' not in codes('甲公司居中国机器人云服务市场第一。',[ranked])
    assert 'ranking_source_missing' not in codes('不能据报告标题认定甲公司位居第一。',[source])


def test_ranking_rejection_keeps_diagnostics_and_gets_a_specific_correction_task():
    from industry_delivery import verification_tasks
    fact=attach_contract(card('研究机构近日发布《机器人市场份额》报告。',module='竞争格局与代表企业'),SCOPE)
    checked=normalize_risk({'dimensions':[{'name':'竞争格局与集中度风险','score':60,
        'reason':'甲公司居机器人云市场第一。','evidence_ids':[fact['evidence_id']]}]},[fact],SCOPE)
    rejected=next(d for d in checked['dimensions'] if d['name']=='竞争格局与集中度风险')
    assert rejected['score'] is None and rejected['unknown_cause']=='ranking_source_missing'
    assert rejected['validation_diagnostic']['original_score']==60
    tasks=verification_tasks({'facts':[fact]},checked,[],SCOPE)
    assert any(t.get('validation_cause')=='ranking_source_missing' and '原始排名表' in t['materials'] for t in tasks)
