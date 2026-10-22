"""Synthetic holdouts for the v17 document review; no services or model calls."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from industry_delivery import verification_tasks, review_reason_summary
from industry_fact_contracts import attach_contract, chapter_admitted
from industry_research import claim_semantic_issues, normalize_risk, risk_repair_package
from test_industry_fact_contracts import card, SCOPE


def codes(text, facts):
    return {i['code'] for i in claim_semantic_issues(text, facts)}


@pytest.mark.parametrize('quote', [
    '研究机构发布两份市场报告，星海云在此两报告中均位列前五，且均是唯一上榜的央企。',
    '平台被列入企业榜单，充分彰显了其在机器人领域的综合实力与市场领先地位。',
    '相关报告已经发布，卓远云在上述报告中排名第一。',
])
def test_embedded_company_rankings_remain_readable_samples_not_summary_or_risk(quote):
    f = attach_contract(card(quote, module='竞争格局与代表企业'), SCOPE)
    assert f['fact_contract']['report_admitted']
    assert f['fact_contract']['sample_boundary']
    assert not f['fact_contract']['risk_admitted']
    assert not chapter_admitted(f, 1)
    stale = deepcopy(f)
    stale['fact_contract'].update(sample_boundary='', risk_admitted=True)
    assert not chapter_admitted(stale, 1)


@pytest.mark.parametrize('quote', [
    '机器人产业链上游提供控制器，中游进行整机集成，下游服务工业客户。',
    '研究机构发布机器人市场报告，行业采用按量计费模式，用户按实际调用量支付费用。',
])
def test_generic_industry_statements_are_not_rejected_as_company_publicity(quote):
    f = attach_contract(card(quote), SCOPE)
    assert f['fact_contract']['report_admitted'] and chapter_admitted(f, 1)


@pytest.mark.parametrize('quote', [
    '随着全球晶圆厂扩产，国产硅片企业市场份额有望持续提升。',
    '服务中心不得对同一科技活动同时提供审查和复核服务。',
    '细分领域中，基础层企业营收波动最大，应用层现金流表现更为平稳。',
])
def test_a_broad_collection_title_does_not_establish_the_summary_subject(quote):
    f = attach_contract(card(quote, source_title='机器人行业资料合集'), SCOPE)
    assert f['fact_contract']['report_admitted']
    assert not chapter_admitted(f, 1)


def test_qualitative_forecasts_remain_attributed_and_unscored():
    f = attach_contract(card('机器人行业市场份额有望持续提升。'), SCOPE)
    assert f['fact_contract']['source_role'] == 'commentary'
    assert not f['fact_contract']['risk_admitted'] and not chapter_admitted(f, 1)


@pytest.mark.parametrize('quote', [
    '近日，研究机构发布《机器人市场份额，2024》报告。',
    '行业协会发布了《中国机器人发展白皮书》。',
])
def test_publishing_a_report_is_not_itself_an_industry_summary_finding(quote):
    f = attach_contract(card(quote), SCOPE)
    assert f['fact_contract']['report_admitted'] and not chapter_admitted(f, 1)


def test_review_body_procedure_is_readable_policy_but_not_industry_impact():
    f = attach_contract(card('第二条 服务中心不得对同一机器人科技活动同时提供审查和复核服务。',
        module='政策与监管',source_title='机器人科技伦理审查办法',source_url='https://www.gov.cn/robot'), SCOPE)
    assert f['fact_contract']['source_role'] == 'policy_primary'
    assert f['fact_contract']['report_admitted'] and chapter_admitted(f, 3)
    assert not chapter_admitted(f, 1) and not f['fact_contract']['risk_admitted']
    provider = attach_contract(card('第三条 机器人服务提供者应当建立安全管理制度。',module='政策与监管',
        source_title='机器人服务管理办法',source_url='https://www.gov.cn/robot'),SCOPE)
    assert provider['fact_contract']['risk_admitted'] and chapter_admitted(provider,1)


@pytest.mark.parametrize('quote', [
    '行业参与者可以分为头部平台、融合企业和技术层代表...行业主要上市公司：星海科技(123456)。',
    '机器人市场由集成商和控制器厂商组成…后续内容未展示。',
    '行业主要上市公司：星海科技、卓远系统；资料仅列主体清单。',
])
def test_search_elisions_and_stock_lists_do_not_become_assertions(quote):
    assert not attach_contract(card(quote), SCOPE)['fact_contract']['report_admitted']


@pytest.mark.parametrize('absence', ['无证据显示', '无证据证明', '尚未发现'])
def test_absence_of_penalty_is_not_proof_of_controllable_impact(absence):
    f = card('机器人服务提供者应当建立安全管理制度。', module='政策与监管')
    reason = absence + '已发生大规模处罚或准入限制，影响范围尚属可控。'
    row = {'name':'政策与监管风险', 'score':35, 'reason':reason, 'evidence_ids':[f['evidence_id']]}
    checked = normalize_risk({'dimensions':[row]}, [f], SCOPE)
    rejected = checked['dimensions'][0]
    assert rejected['score'] is None and rejected['unknown_cause'] == 'absence_as_low_risk'
    assert rejected['validation_diagnostic']['original_reason'] == reason
    assert 'absence_as_low_risk' not in codes('未见处罚材料，不能据此判断影响可控，仍需核验。', [f])
    package = risk_repair_package({'facts':[f], 'dimension_evidence_ids':{row['name']:[f['evidence_id']]}}, checked)
    assert len(package['dimensions_to_repair']) == 1


def observation(index, **context):
    f = card(f'资料{index}披露：2024年中国机器人市场规模达到120亿元。', '市场规模', '120', '亿元',
             evidence_id=f'E-{index:012X}', source_url=f'https://publisher{index}.example/report')
    f['numeric_context'].update(context)
    return f


@pytest.mark.parametrize('change', [
    {'period':'2025'}, {'definition':'机器人算力市场规模'}, {'geography':'全球'},
    {'metric':'算力市场规模'}, {'is_forecast':True}, {'value':'130'},
    {'comparator':'>'},
])
def test_different_hosts_do_not_make_incomparable_numeric_cards_agree(change):
    fs = [observation(1), observation(2, **change)]
    assert 'numeric_corroboration_not_comparable' in codes('多源数据一致。', fs)


def test_comparable_observations_pass_minimum_checks_without_certifying_semantics():
    assert not codes('多源数据一致。', [observation(1), observation(2)])
    fs = [observation(1), observation(2, definition='机器人算力市场规模')]
    assert not codes('不同来源口径不能相互印证，须先核对。', fs)


def test_unrelated_publisher_cannot_pad_a_same_publisher_comparison_group():
    fs = [observation(1), observation(2), observation(3, period='2025')]
    fs[1]['source_url'] = 'https://news.publisher1.example/other'
    assert 'numeric_corroboration_not_comparable' in codes('多源数据一致。', fs)


def test_single_year_growth_and_forecasts_do_not_prove_realized_persistent_growth():
    fs = [observation(1, metric='同比增长', value='24', unit='%', definition='机器人产业规模同比增长'),
          observation(2, period='2025', value='1.2', unit='万亿元'),
          observation(3, period='2026', value='515', unit='亿美元', is_forecast=True, definition='机器人算力市场规模')]
    reason = '2024年同比增长24%，2025年规模1.2万亿元，2026年算力市场预测515亿美元，增长持续性获证据支持。'
    assert 'growth_trend_not_comparable' in codes(reason, fs)
    assert not codes('这些数值不能拼成持续增长结论，需先核对口径。', fs)
    assert not codes('列示数值支持持续增长。', [observation(1, period='2023', value='100'), observation(2)])


@pytest.mark.parametrize('cause,expected', [
    ('source_corroboration_overstated','转载'),
    ('numeric_corroboration_not_comparable','指标定义'),
    ('absence_as_low_risk','未见处罚'),
    ('growth_trend_not_comparable','时间序列'),
])
def test_report_and_proposal_share_cause_specific_correction_tasks(cause, expected):
    from report_agents.industry_proposal import build_industry_proposal
    risk = {'dimensions':[{'name':'数据口径与证据可靠性风险', 'score':None, 'unknown_cause':cause,
                          'validation_diagnostic':{'original_score':40}}]}
    tasks = verification_tasks({}, risk, [], SCOPE)
    t = next(t for t in tasks if t['key'].startswith('risk:'))
    assert t['task_type'] == 'assessment_validation' and t['validation_cause'] == cause
    assert expected in t['action']
    project = SimpleNamespace(title='机器人研究', target_name='机器人', industry_scope=SCOPE, industry_verification_tasks=tasks)
    proposal = build_industry_proposal(project, risk_json=json.dumps(risk, ensure_ascii=False))
    assert t['action'] in proposal and t['completion'] in proposal


def test_front_notice_groups_chapters_and_preserves_full_reason_data():
    reasons = [{'code':'chapter_analysis_pending_review', 'chapter':c, 'message':'原始完整原因'} for c in [7,3,2,7]]
    reasons += [{'code':'risk_assessment_incomplete','dimension':'竞争格局与集中度风险'},
                {'code':'evidence_gate_failed','message':'原始闸门错误'}]
    original = deepcopy(reasons)
    text = review_reason_summary(reasons)
    assert '第2、3、7章' in text and text.count('分析结论待语义复核') == 1
    assert '竞争格局与集中度风险' in text and '另有1项' in text
    assert len(text) < 200 and reasons == original


def test_rejected_corroboration_explanation_is_not_a_new_positive_claim():
    assert not codes('评分理由声称多源印证，但引用来源不足或来自同一发布方，暂不评分。', [])
    assert 'source_corroboration_overstated' in codes('多源印证，证据充分。', [])
    assert 'source_corroboration_overstated' in codes(
        '评分理由声称多源印证，但引用来源不足，暂不评分。多源数据一致，结论已经证实。', [])
