"""Reader-facing quality holdouts; no model, search, or business DB calls."""
from copy import deepcopy

import pytest

from industry_analysis import market_table, statement_lineage_present
from industry_delivery import finalize_synthesis, refresh_summary_readiness, verification_tasks
from industry_fact_contracts import attach_contract, render_plan
from industry_research import active_risk_dimensions, claim_semantic_issues, normalize_risk, summary_length
from test_industry_fact_contracts import card, SCOPE


@pytest.mark.parametrize('reason', [
    '本轮无证据显示已发生处罚或执行收紧，属制度建设期常规风险。',
    '未取得处罚记录，因此监管压力有限。',
    '尚未发现准入限制，暂归一般风险。',
    '评估尚待校准；未见处罚，政策影响可控。',
    '当前风险较低，因为未见处罚材料。',
])
def test_missing_execution_material_cannot_become_reassurance(reason):
    fact = attach_contract(card('第三条 机器人服务提供者应当制定数据标注规则。',
        module='政策与监管', source_title='机器人服务管理办法',
        source_url='https://www.cac.gov.cn/rules'), SCOPE)
    original = deepcopy(fact)
    result = normalize_risk({'dimensions': [{'name': '政策与监管风险', 'score': 52,
        'reason': reason, 'evidence_ids': [fact['evidence_id']]}]}, [fact], SCOPE)
    row = next(d for d in result['dimensions'] if d['name'] == '政策与监管风险')
    assert row['score'] is None and row['unknown_cause'] == 'absence_as_low_risk'
    assert row['validation_diagnostic']['original_reason'] == reason
    assert row['validation_diagnostic']['original_score'] == 52
    task = next(t for t in verification_tasks({'facts': [fact]}, result, [], SCOPE)
                if t['topic'] == '政策与监管风险')
    assert '未见处罚' in task['reason'] or '未见处罚' in task['action']
    assert fact == original


@pytest.mark.parametrize('reason', [
    '本轮无证据显示已发生处罚或执行收紧，执行情况需补充核验。',
    '未见处罚，不能据此认定政策影响有限。',
    '未见处罚，不代表属于常规风险。',
    '未见处罚，仍不能确认政策风险较低。',
    '未取得处罚材料。另有适用义务，应单独核对履行成本。',
    '删除由未见处罚推导低风险的理由；取得直接影响证据后独立评估，否则保持未知。',
    '服务提供者应当保存标注记录，违规情节轻微时按法定规则处理。',
])
def test_neutral_limit_and_negated_reassurance_are_not_rejected(reason):
    assert 'absence_as_low_risk' not in {i['code'] for i in claim_semantic_issues(reason, [])}


def forecast(eid, year='2032', value='900', definition='中国机器人市场规模', **updates):
    f = card(f'来源预计到{year}年中国机器人市场规模将达到{value}亿元。',
        '市场规模', value, '亿元', evidence_id=eid,
        source_url=f'https://source-{eid[-1]}.example/report', **updates)
    f['numeric_context'].update(period=year, definition=definition, is_forecast=True)
    return attach_contract(f, {**SCOPE, 'as_of_date': '2026-10-21'})


def test_forecasts_consolidate_equal_values_without_discarding_definitions_or_boundaries():
    facts = [forecast('E-000000000001'), forecast('E-000000000002', definition='机器人服务市场规模'),
             forecast('E-000000000003', claim_type='opinion')]
    package = {'facts': facts, 'industry_scope': {**SCOPE, 'as_of_date': '2026-10-21'}}
    original = deepcopy(package)
    body = render_plan(package, 11, '前景展望', [f['evidence_id'] for f in facts])
    value_rows = [line for line in body.splitlines() if line.startswith('| 2032')]
    assert len(value_rows) == 1
    assert all(f['evidence_id'] in value_rows[0] for f in facts)
    assert '中国机器人市场规模' in value_rows[0] and '机器人服务市场规模' in value_rows[0]
    assert '来源观点（未作事实认定）' in value_rows[0]
    assert '合列不表示口径已经统一或来源相互独立' in body
    assert package == original


def test_forecast_target_passed_is_not_promoted_to_actual_or_current_outlook():
    facts = [forecast('E-000000000001', '2025'), forecast('E-000000000002', '2032')]
    body, _ = market_table(facts, '2026-10-21')
    rows = [line for line in body.splitlines() if line.startswith('| 20')]
    assert '2025 历史预测（目标期已过且非实际值）' in rows[0]
    assert '2032 预测/目标值' in rows[1]
    # Without a known cutoff the source forecast nature is preserved.
    assert '历史预测' not in market_table(facts)[0]


def test_forecast_table_lineage_requires_exact_authorized_row_not_just_id():
    fact = forecast('E-000000000001', '2025')
    package = {'facts': [fact], 'industry_scope': {**SCOPE, 'as_of_date': '2026-10-21'}}
    body = render_plan(package, 11, '前景展望', [fact['evidence_id']])
    assert statement_lineage_present(fact, body, package, 11)
    assert not statement_lineage_present(fact, body.replace('900亿元', '950亿元'), package, 11)
    assert not statement_lineage_present(fact, body.replace('历史预测（目标期已过且非实际值）', '来源报告值'), package, 11)


def test_numeric_groups_keep_different_targets_comparators_and_samples_distinct():
    a = forecast('E-000000000001')
    b = forecast('E-000000000002', '2033')
    c = forecast('E-000000000003'); c['fact_contract']['comparator'] = '>'
    d = forecast('E-000000000004'); d['fact_contract']['sample_boundary'] = '供应商样本'
    body, ids = market_table([a, b, c, d])
    assert len([line for line in body.splitlines() if line.startswith('| 20')]) == 3
    assert '超过900亿元' in body and '样本观察（不能外推行业整体）' in body
    assert len(ids) == 4


def all_assessed():
    return {'dimensions': [{'name': name, 'score': 52, 'level': 'medium',
                           'evidence_ids': ['E-000000000001']} for name in active_risk_dimensions(SCOPE)],
            'overall_score': 52}


def test_summary_exposes_current_unknowns_and_refreshes_without_stale_state():
    risk = all_assessed()
    risk['dimensions'][2].update(score=None, reason='旧原因不能出现在摘要')
    report = '## 1. 摘要\n\n机器人市场规模已有来源列示。[E-000000000001]\n\n## 2. 产业链\n\n保留正文。'
    first = refresh_summary_readiness(report, risk, [], SCOPE)
    assert '未完成评估：竞争格局与集中度风险' in first and '总分暂不计算' in first
    assert '资本热度' not in first and '旧原因' not in first
    assert refresh_summary_readiness(first, risk, [], SCOPE) == first
    refreshed = refresh_summary_readiness(first, all_assessed(), [], SCOPE)
    assert '未完成评估' not in refreshed and '评估与使用边界' not in refreshed
    assert refreshed == report


def test_summary_reserves_status_space_and_removes_whole_statements_only():
    paragraphs = [f'- 第{n}条材料：' + '这是一个完整来源陈述，' * 8 + f'结束。[E-{n:012X}]' for n in range(1, 6)]
    report = '## 1. 摘要\n\n' + '\n\n'.join(paragraphs) + '\n\n## 2. 产业链\n\n第二章不改。'
    risk = all_assessed(); risk['dimensions'][1]['score'] = None
    result = refresh_summary_readiness(report, risk, [{'chapter': 7}], SCOPE)
    summary = result.split('## 2.', 1)[0]
    assert summary_length(summary) <= 600
    assert '市场增长与需求风险' in summary and '部分章节分析或生成结果待复核' in summary
    for paragraph in summary.split('\n\n'):
        if paragraph.startswith('- '):
            assert paragraph in paragraphs
    assert result.split('## 2.', 1)[1] == report.split('## 2.', 1)[1]


def test_disabled_capital_and_unspecified_company_do_not_add_summary_pending_notice():
    report = '## 1. 摘要\n\n原摘要。\n\n## 2. 产业链\n\n正文。'
    assert refresh_summary_readiness(report, all_assessed(), [{'chapter': 8}, {'chapter': 9}, {'chapter': 12}], SCOPE) == report


@pytest.mark.parametrize('risk', [{}, {'dimensions': None}, {'dimensions': []}])
def test_absent_assessment_is_visible_without_crashing_summary(risk):
    result = refresh_summary_readiness('## 1. 摘要\n\n来源陈述。\n\n## 2. 产业链\n\n正文。', risk, [], SCOPE)
    assert '总分暂不计算' in result and '未完成评估：政策与监管风险' in result
