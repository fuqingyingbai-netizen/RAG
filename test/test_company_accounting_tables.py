from copy import deepcopy

from report_agents.company_assessment import METRICS, _financial_scores
from report_agents.company_accounting_tables import accounting_grid_rows


def example(adjusted=False, split=False):
    headers = [['主要会计数据', '2025年', '2024年', '本期比上年同期增减（%）', '2023年']]
    rows = [[name, str(a)+'.00', str(b)+'.00', '20.00', str(c)+'.00']
            for name, a, b, c in zip(METRICS, (120, 12, 24), (100, 10, 20), (90, 9, 18))]
    if adjusted:
        headers = [['主要会计数据', '2025年', '2024年', '', '本期比上年同期增减（%）', '2023年'],
                   ['', '', '调整后', '调整前', '', '']]
        rows = [[r[0], r[1], r[2], str(int(float(r[2]))*2)+'.00', r[3], r[4]] for r in rows]
    continuation = []
    if split:
        rows[-1][0] = '经营活动产生的现金'
        continuation = [{'page': 10, 'text': '远山制造股份有限公司2025年年度报告\n流量净额',
                         'tables': [[['流量净额'] + [''] * (len(rows[-1])-1)]]}]
    table = headers + rows
    text = '主要会计数据\n单位：元 币种：人民币\n' + '\n'.join(' '.join(row) for row in table)
    pages = [{'page': 9, 'text': text, 'tables': [table]}] + continuation
    raw = '\n\n'.join(f"--- PDF page {p['page']} ---\n{p['text']}" for p in pages)
    return pages, raw


def parse(pages, raw):
    return accounting_grid_rows(pages, '远山制造股份有限公司',
        {'evidence_id': 'E-123456ABCDEF', 'evidence_ids': ['E-123456ABCDEF']},
        '2025年年度报告', '2025-12-31', METRICS, raw)


def test_year_headers_and_global_currency_supply_all_three_metrics():
    pages, raw = example()
    rows = parse(pages, raw)
    assert len(rows) == 3
    assert {r['currency'] for r in rows} == {'人民币'}
    assert {r['unit'] for r in rows} == {'元'}
    assert rows[0]['value'] == '120.00' and rows[0]['previous_value'] == '100.00'
    assert all(r['evidence_quote'] in raw for r in rows)
    assert [r['score'] for r in _financial_scores(rows)] == [5, 5]


def test_interim_relative_year_header_takes_precedence_over_inherited_adjustment_year():
    pages,raw=example(adjusted=True)
    table=pages[0]['tables'][0]
    table[0]=['主要会计数据','本报告期（1－6月）','上年同期','','本报告期比上年同期增减(%)','']
    table[1]=['','','调整后','调整前','','']
    for row in table[2:]:row[-1]=''
    pages[0]['text']='主要会计数据\n单位：元 币种：人民币\n'+'\n'.join(' '.join(row) for row in table)
    raw=pages[0]['text']
    rows=accounting_grid_rows(pages,'远山制造股份有限公司',{'evidence_ids':['E-123456ABCDEF']},
        '2026年半年度报告','2026-06-30',METRICS,raw)
    assert len(rows)==3
    assert all(r['previous_value_basis']=='adjusted' for r in rows)
    assert rows[0]['previous_value']=='100.00' and rows[0]['previous_value_before_adjustment']=='200.00'
    assert [r['score'] for r in _financial_scores(rows)]==[4,4]


def test_adjusted_and_unadjusted_columns_survive_without_inferring_three_year_comparability():
    pages, raw = example(adjusted=True)
    rows = parse(pages, raw)
    assert len(rows) == 3
    assert rows[0]['previous_value'] == '100.00'
    assert rows[0]['previous_value_before_adjustment'] == '200.00'
    assert rows[0]['previous_value_basis'] == 'adjusted'
    assert rows[0]['third_value'] == '90.00' and rows[0]['third_value_comparable'] is False
    assert '200.00' in rows[0]['fact']
    assert [r['score'] for r in _financial_scores(rows)] == [4, 4]


def test_split_cash_flow_label_needs_adjacent_empty_cell_continuation_and_native_quote():
    pages, raw = example(split=True)
    rows = parse(pages, raw)
    assert len(rows) == 3
    cash = next(r for r in rows if r['metric'] == METRICS[2])
    assert cash['pages'] == [9, 10] and cash['evidence_quote'] in raw
    assert '流量净额' in cash['source_metric']
    changed = deepcopy(pages)
    changed[1]['tables'][0][0][1] = '另一个数值'
    assert METRICS[2] not in {r['metric'] for r in parse(changed, raw)}
    changed = deepcopy(pages); changed[1]['page'] = 11
    assert METRICS[2] not in {r['metric'] for r in parse(changed, raw)}


def test_ambiguous_duplicate_years_are_not_resolved_by_matching_yoy_numbers():
    pages, raw = example(adjusted=True)
    pages[0]['tables'][0][1] = ['', '', '', '', '', '']
    assert parse(pages, raw) == []


def test_quarter_columns_do_not_become_annual_values():
    pages, raw = example()
    pages[0]['tables'][0][0] = ['主要会计数据', '第一季度', '第二季度', '第三季度', '第四季度']
    assert parse(pages, raw) == []


def test_unknown_currency_is_kept_as_observation_without_a_score():
    pages, raw = example()
    pages[0]['text'] = pages[0]['text'].replace(' 币种：人民币', '')
    rows = parse(pages, raw.replace(' 币种：人民币', ''))
    assert len(rows) == 3 and all(r['currency'] == '未载' for r in rows)
    assert all(r['score'] is None for r in _financial_scores(rows))


def test_unit_or_adjustment_header_metadata_cannot_override_native_text():
    pages, raw = example(adjusted=True)
    pages[0]['text']=pages[0]['text'].replace('单位：元','单位：千元')
    assert parse(pages,raw)==[]
    pages, raw=example(adjusted=True)
    pages[0]['tables'][0][1][2:4]=['调整前','调整后']
    assert parse(pages,raw)==[]
