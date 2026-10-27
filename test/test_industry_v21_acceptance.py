"""Context-loss holdouts over synthetic sources; no external calls or private data."""
from copy import deepcopy
import hashlib

import pytest

from industry_analysis import chapter_analysis
from industry_fact_contracts import attach_contract, chapter_admitted, chapter_coverage, risk_admitted
from industry_grounding import metric_period_region
from industry_passages import passage_issues, reader_proposition
from test_industry_fact_contracts import card, SCOPE


def located(quote, prefix='', suffix='', **kwargs):
    body = prefix + quote + suffix
    fact = card(quote, **kwargs)
    fact['provenance']['locator'].update(start=len(prefix), end=len(prefix)+len(quote),
        body_sha256=hashlib.sha256(body.encode()).hexdigest())
    return fact, body


@pytest.mark.parametrize('prefix', [
    '问：如何推动机器人普惠应用？\n\n答：需要把普惠转化为可运行的商业模式。\n\n一是实现轻量化应用。',
    '中小企业面临转型困难。为此建议：\n\n一、由公共平台整合资源。',
    '已完成试运行。下一步，将持续建设平台。\n\n未来，平台服务本地企业。\n\n一是拓展资源；',
])
def test_a_sentence_in_an_action_list_keeps_its_advisory_role(prefix):
    quote = '依托机器人即服务模式，通过订阅制和按量计费降低企业使用门槛。'
    f, body = located(quote, prefix, module='商业模式与盈利逻辑')
    original = deepcopy(f)
    result = attach_contract(f, SCOPE, body)
    assert f == original
    assert result['fact_contract']['source_role'] == 'recommendation'
    assert result['fact_contract']['report_admitted']
    assert '来源建议' in result['fact_contract']['statement']
    assert not chapter_admitted(result, 1)
    assert not risk_admitted(result, '商业化与盈利模式风险')
    assert result['provenance'] == original['provenance']


def test_an_earlier_proposal_does_not_change_a_new_realized_result():
    quote = '机器人平台已取得付费客户，客户按实际调用量支付费用。'
    f, body = located(quote, '下一步，计划探索订阅。\n\n调查显示，', module='商业模式与盈利逻辑')
    result = attach_contract(f, SCOPE, body)
    assert result['fact_contract']['source_role'] == 'source_statement'
    assert result['fact_contract']['risk_admitted']


def test_unbound_body_cannot_supply_a_suggestion_qualification():
    f, body = located('机器人平台采用订阅制和按量计费模式。', '下一步，将优化服务。')
    f['provenance']['locator']['start'] += 1
    result = attach_contract(f, SCOPE, body)
    assert result['fact_contract']['source_role'] != 'recommendation'


def test_a_mismatched_snapshot_hash_cannot_supply_advisory_context():
    f, body = located('机器人平台采用订阅制和按量计费模式。', '下一步，将优化服务。')
    f['provenance']['locator']['body_sha256'] = '0'*64
    result = attach_contract(f,SCOPE,body)
    assert result['fact_contract']['source_role'] != 'recommendation'


@pytest.mark.parametrize('text', [
    '机器人产业发展应当坚持以人为本、创新驱动的原则，建设开放产业体系。',
    '第一条 为了促进机器人产业发展，结合本市实际，制定本条例。',
])
def test_policy_principles_and_purpose_do_not_fill_the_specific_obligation_slot(text):
    f = attach_contract(card(text, module='政策与监管', source_title='机器人产业条例',
        source_url='https://www.gov.cn/rules'), SCOPE, '第一条\n' + text)
    assert f['fact_contract']['source_role'] == 'policy_primary'
    assert f['fact_contract']['report_admitted']
    assert not chapter_admitted(f, 1)
    assert not f['fact_contract']['risk_admitted']
    package = {'facts': [f]}
    coverage = chapter_coverage(package, 3, [f['evidence_id']])
    duty = next(row for row in coverage if row['question'] == '义务主体及具体要求')
    assert duty['status'] == 'missing'
    assert '义务对象及要求' not in chapter_analysis(package, 3, [f['evidence_id']])


def test_a_concrete_provider_duty_remains_a_policy_obligation():
    f = attach_contract(card('第三条 机器人服务提供者应当制定数据标注规则，并保存安全评估记录。',
        module='政策与监管', source_title='机器人服务条例', source_url='https://www.gov.cn/rules'), SCOPE)
    coverage = chapter_coverage({'facts':[f]}, 3, [f['evidence_id']])
    duty = next(row for row in coverage if row['question'] == '义务主体及具体要求')
    assert duty['evidence_ids'] == [f['evidence_id']]
    assert '义务对象及要求：机器人服务提供者应当制定数据标注规则' in chapter_analysis({'facts':[f]},3,[f['evidence_id']])
    assert f['fact_contract']['risk_admitted']


@pytest.mark.parametrize('value,year', [('240','2026'), ('680','2031')])
def test_a_two_endpoint_projection_does_not_give_one_amount_a_ten_year_period(value,year):
    quote = '研究人员表示，从2026年到2031年，中国机器人产业规模预计将从240亿元增长至680亿元。'
    f = card(quote, '产业规模', value, '亿元')
    original = deepcopy(f)
    checked = attach_contract(f, SCOPE)
    assert checked['fact_contract']['report_admitted'], checked['fact_contract']['issues']
    assert checked['numeric_context']['period'] == year
    assert checked['numeric_context']['is_forecast']
    assert year + ' 中国大陆' in checked['fact_contract']['statement']
    assert f == original


def test_an_interval_growth_rate_still_describes_the_whole_interval():
    f = attach_contract(card('2021—2024年中国机器人增长率维持在12%以上。', '增长率','12','%'),SCOPE)
    assert f['numeric_context']['period'] == '2021—2024'
    assert f['fact_contract']['report_admitted']


def test_a_different_metric_in_a_second_clause_cannot_supply_an_endpoint():
    quote = '从2026年到2031年，中国机器人产业规模预计将为240亿元；软件收入将增长至680亿元。'
    period, _ = metric_period_region(quote, '产业规模','680','亿元')
    assert not period


def test_a_merged_slide_catalogue_is_quarantined_even_if_it_contains_predicates():
    quote = '机器人竞争格局,Contents Page,目录页,全球市场分布,科技巨头占据主导地位，产业链包括上中下游。'
    f = attach_contract(card(quote, module='竞争格局与代表企业'), SCOPE)
    assert 'table_of_contents' in passage_issues(quote)
    assert not f['fact_contract']['report_admitted']


def test_repeated_issuing_bodies_are_removed_only_from_the_reader_view():
    header = '国家机器人管理委员会国家机器人管理委员会中华人民共和国教育部中华人民共和国教育部令令 第18号 '
    text = '《机器人服务办法》已经会议审议通过，现予公布，自2026年8月1日起施行。'
    f = card(header + text, module='政策与监管', source_title='机器人服务办法', source_url='https://www.gov.cn/rules')
    original = deepcopy(f)
    checked = attach_contract(f, SCOPE)
    assert checked['fact_contract']['report_admitted']
    assert checked['fact_contract']['statement'] == text
    assert reader_proposition('机器人管理委员会公布《机器人服务办法》，应当保存记录。').startswith('机器人管理委员会')
    assert f == original and checked['provenance'] == original['provenance']


def test_an_unmeasured_large_effect_is_background_not_score_or_summary():
    f = attach_contract(card('机器人服务通常提供订阅或租赁模式，极大地降低企业的初期投入门槛。',
        module='商业模式与盈利逻辑'), SCOPE)
    assert f['fact_contract']['source_role'] == 'performance_claim'
    assert f['fact_contract']['report_admitted']
    assert not chapter_admitted(f,1) and not f['fact_contract']['risk_admitted']


def test_a_named_deployment_on_the_previous_pdf_page_remains_a_sample():
    quote = '算集群采用机器人推理框架，提供低延迟服务。'
    prefix = '某地甲乙类脑智算集群已于2026年试运行，该智\n\n--- PDF page 18 ---\n机器人算力研究报告\n13\n'
    f, body = located(quote,prefix,module='技术路线对比')
    checked = attach_contract(f,SCOPE,body)
    assert checked['fact_contract']['sample_boundary']
    assert not checked['fact_contract']['risk_admitted']
    assert 'cross_page_fragment' in checked['fact_contract']['issues']
    assert not checked['fact_contract']['report_admitted']


def test_a_complete_paragraph_after_a_pdf_page_header_is_not_a_split_word():
    f,body = located('机器人产业链包括上游零部件、中游系统和下游应用。',
        '上一页已完整结束。\n\n--- PDF page 3 ---\n机器人产业报告\n2\n')
    result = attach_contract(f,SCOPE,body)
    assert result['fact_contract']['report_admitted']
    assert 'cross_page_fragment' not in result['fact_contract']['issues']
