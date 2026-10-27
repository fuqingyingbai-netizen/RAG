"""Separate observed inputs, intentions and legal purpose without losing prose."""
from copy import deepcopy

import pytest

from industry_analysis import observed_business
from industry_delivery import evaluation_inputs
from industry_fact_contracts import attach_contract, chapter_admitted, chapter_coverage, render_plan
from industry_passages import policy_purpose_or_principle
from test_industry_fact_contracts import card, SCOPE


def checked(text, eid='E-000000000001', module='商业模式与盈利逻辑', **kwargs):
    return attach_contract(card(text, evidence_id=eid, module=module, **kwargs), SCOPE)


@pytest.mark.parametrize('middle', [
    '推动机器人在经济、生活和城市治理等领域深度融合，完善相关应用环境，强化科技创新策源能力，促进人才交流和产业资源共享，推动产业服务体系建设，打造开放包容和可持续的创新生态，',
    '坚持以人为本，促进创新发展，完善创新生态，' * 7,
])
def test_long_legislative_purpose_remains_readable_but_not_an_obligation_or_score(middle):
    quote = '第一条 为了促进机器人产业发展，' + middle + '根据有关法律法规，结合本市实际，制定本条例。'
    assert len(quote) > 100
    fact = checked(quote, module='政策与监管', source_title='机器人服务条例', source_url='https://www.gov.cn/robot')
    assert fact['fact_contract']['report_admitted']
    assert policy_purpose_or_principle(quote)
    assert not fact['fact_contract']['risk_admitted'] and not chapter_admitted(fact, 1)
    rows = chapter_coverage({'facts': [fact]}, 3, [fact['evidence_id']])
    assert next(r for r in rows if r['question'] == '义务主体及具体要求')['status'] == 'missing'
    assert next(r for r in rows if r['question'] == '适用政策原文')['evidence_ids'] == [fact['evidence_id']]


def test_a_real_provider_obligation_is_not_lost_when_it_mentions_a_policy_purpose():
    quote = '第三条 机器人服务提供者应当制定本单位安全规则，保障用户权益。'
    fact = checked(quote, module='政策与监管', source_title='机器人服务条例', source_url='https://www.gov.cn/robot')
    assert not policy_purpose_or_principle(quote)
    assert fact['fact_contract']['risk_admitted']


@pytest.mark.parametrize('quote', [
    '在未来，机器人收费服务的竞争优势，在于能够持续满足个性化需求。',
    '未来，机器人采用收费服务的竞争优势，在于用户能够获得持续稳定服务。',
    '推动机器人应用行动，要充分发挥技术路线的比较优势，引导创新资源均衡布局。',
])
def test_intentions_are_attributed_and_not_current_evaluation_or_scoring_inputs(quote):
    original = card(quote, module='技术路线对比')
    fact = attach_contract(original, SCOPE)
    assert fact['fact_contract']['report_admitted']
    assert fact['fact_contract']['source_role'] in {'commentary','recommendation'}
    assert not chapter_admitted(fact, 1) and not fact['fact_contract']['risk_admitted']
    assert not observed_business(fact)
    assert fact['provenance'] == original['provenance']


@pytest.mark.parametrize('text', [
    '机器人服务已从免费转付费，面向订阅用户提供持续更新。',
    '机器人用户已经从免费转为付费，服务方记录实际交易。',
    '机器人服务已开始收费，客户按实际使用量支付费用。',
    '面向未来应用场景的机器人软件，当前已取得付费客户。',
])
def test_actual_payment_signals_are_preserved_as_operating_material(text):
    fact = checked(text)
    assert fact['fact_contract']['risk_admitted']
    assert observed_business(fact)
    coverage = chapter_coverage({'facts':[fact]}, 10, [fact['evidence_id']])
    assert coverage[0]['evidence_ids'] == [fact['evidence_id']]


@pytest.mark.parametrize('text', [
    '机器人用户尚未实际支付费用，付费状态仍待核对。',
    '机器人服务未披露实际收入和营收，仍待取得经营材料。',
    '机器人用户计划实际支付费用，当前尚无交易记录。',
    '机器人客户实际支付失败，交易尚未完成。',
    '机器人服务预计披露收入，具体数据还未取得。',
    '机器人服务提供者必须披露收入，具体披露文件仍未取得。',
    '机器人客户实际费用尚未支付，订单仍未完成。',
])
def test_negated_failed_or_planned_payment_is_not_an_observed_result(text):
    assert not observed_business(checked(text))


def test_evaluation_uses_actual_payment_and_specific_duty_instead_of_first_generic_card():
    future = checked('在未来，机器人收费服务的竞争优势，在于满足用户个性化需求。')
    general = checked('机器人服务采用订阅制和按量计费模式。', 'E-000000000002')
    actual = checked('机器人服务已从免费转付费，面向订阅用户提供持续更新。', 'E-000000000003')
    duty = checked('第三条 机器人服务提供者应当制定数据标注规则。', 'E-000000000004',
                   '政策与监管', source_title='机器人服务条例', source_url='https://www.gov.cn/robot')
    purpose = checked('第一条 为了促进机器人产业发展，制定本条例。', 'E-000000000005',
                      '政策与监管', source_title='机器人服务条例', source_url='https://www.gov.cn/robot')
    payload = {'facts':[future,general,actual,purpose,duty]}; original = deepcopy(payload)
    body = evaluation_inputs(payload)
    assert actual['evidence_id'] in body and duty['evidence_id'] in body
    assert all(f['evidence_id'] not in body for f in [future,general,purpose])
    assert payload == original


def test_numeric_forecast_remains_usable_as_a_labelled_forecast_not_an_intention():
    fact = attach_contract(card('预计2032年中国机器人市场规模将达到900亿元。',
        '市场规模','900','亿元'), SCOPE)
    assert fact['fact_contract']['report_admitted'] and chapter_admitted(fact, 11)
    assert '预测/目标值' in fact['fact_contract']['statement']


def test_an_earlier_negative_observation_does_not_hide_a_new_payment_result():
    fact = checked('机器人服务此前尚未完成定价调整；当前已取得付费客户，用户按实际调用量支付费用。')
    assert observed_business(fact)


def test_technical_evaluation_prefers_test_conditions_to_a_breakthrough_headline():
    headline = checked('机器人技术路线取得重要突破，引领行业升级。', module='技术路线对比')
    measured = checked('机器人采用统一硬件进行测试，测试条件限定为相同模型和量化精度。',
                       'E-000000000002', module='技术路线对比')
    assert headline['fact_contract']['report_admitted']
    body = evaluation_inputs({'facts':[headline,measured]})
    assert measured['evidence_id'] in body and headline['evidence_id'] not in body
    assert headline['evidence_id'] not in evaluation_inputs({'facts':[headline]})


def test_business_coverage_does_not_present_background_ids_as_payment_evidence():
    background = checked('机器人服务采用订阅和按量计费模式。')
    actual = checked('机器人用户已开始付费，服务方保留交易记录。', 'E-000000000002')
    package = {'facts':[background,actual]}
    rows = chapter_coverage(package,10,[background['evidence_id'],actual['evidence_id']])
    assert rows[0]['evidence_ids'] == [actual['evidence_id']]
    assert rows[0]['background_evidence_ids'] == [background['evidence_id']]
    body = render_plan(package,10,'商业化',[background['evidence_id'],actual['evidence_id']])
    coverage_line = next(line for line in body.splitlines() if line.startswith('| 实际收费与付费客户'))
    assert '对应材料：['+actual['evidence_id']+']' in coverage_line
    assert '背景材料（未回答本问题）：['+background['evidence_id']+']' in coverage_line


def test_evaluation_retains_source_date_without_rebasing_current_wording_to_report_cutoff():
    fact = checked('目前机器人服务已开始收费，客户按实际使用量支付费用。', published_date='2023-10-09')
    payload = {'facts':[fact], 'industry_scope':{**SCOPE,'as_of_date':'2026-10-21'}}
    original = deepcopy(payload)
    body = evaluation_inputs(payload)
    assert '来源发布：2023-10-09；目前' in body and '2026-10-21' not in body
    assert payload == original
    undated = deepcopy(fact); undated.pop('published_date')
    assert '来源发布：' not in evaluation_inputs({'facts':[undated],'industry_scope':payload['industry_scope']})
