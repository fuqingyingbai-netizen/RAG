"""Neutral reconciled fiscal-segment fixtures, not live issuer evidence."""
from copy import deepcopy

import pytest

from report_agents.company_financial_statements import fiscal_segment_revenue_rows

TARGET='星河控股有限公司'
PERIOD='2026财年年度报告（截至2026-03-31）'


def pages():
    return [{'page':1,'text':TARGET+'\n截至2026年3月31日止財務年度的20-F表格年度報告'},
            {'page':12,'text':'所示期間內分部間抵消前我們的分部收入如下表：\n'
             '截至3月31日止年度\n2024 2025 2026\n人民幣 人民幣 人民幣 美元\n（百萬元）\n'
             '平台集團：\n　客戶管理 30 40 50 7\n　其他 10 10 10 1\n40 50 60 8\n'
             '平台集團合計 40 50 60 8\n雲集團 20 30 40 6\n所有其他\n(4) 10 20 30 4\n'
             '未分攤 1 2 3 1\n分部間抵消 (5) (6) (7) (1)\n合併收入 66 96 126 18\n'
             '1. 本期完成業務重組，以上報告已根據新的報告架構更新，不能與舊架構混用。\n2. 直營成本按總額法列示。'}]


def test_only_top_level_rmb_rows_reconcile_without_nested_or_usd_double_counting():
    rows=fiscal_segment_revenue_rows(pages(),TARGET,PERIOD)
    assert len(rows)==6
    assert [r['entity'] for r in rows]==['平台集团合计','云集团','所有其他','未分摊','分部间抵消','合并收入']
    assert rows[0]['value']=='60' and rows[0]['previous_value']=='50'
    assert rows[-2]['value']=='-7' and rows[-1]['value']=='126'
    assert all(r['currency']=='人民币' and r['page']==12 and r['reconciliation_verified'] for r in rows)
    assert all('新的報告架構' in r['reclassification_note'] for r in rows)
    assert '平台集團合計' in rows[0]['evidence_quote']


@pytest.mark.parametrize('change',['unreconciled','mixed_currency','wrong_month','no_elimination','different_target','no_fiscal_cover','adjusted_profit'])
def test_ambiguous_or_non_revenue_tables_do_not_create_segment_income(change):
    p=deepcopy(pages());target=TARGET
    if change=='unreconciled':p[-1]['text']=p[-1]['text'].replace('66 96 126','66 96 127')
    if change=='mixed_currency':p[-1]['text']=p[-1]['text'].replace('人民幣 人民幣 人民幣','人民幣 美元 人民幣')
    if change=='wrong_month':p[-1]['text']=p[-1]['text'].replace('截至3月31日','截至12月31日')
    if change=='no_elimination':p[-1]['text']=p[-1]['text'].replace('分部間抵消','其他調節')
    if change=='different_target':target='星河服務有限公司'
    if change=='no_fiscal_cover':p[0]['text']=TARGET+'\n證券發行公告'
    if change=='adjusted_profit':p[-1]['text']=p[-1]['text'].replace('分部收入如下表','分部經調整EBITA如下表')
    assert fiscal_segment_revenue_rows(p,target,PERIOD)==[]
