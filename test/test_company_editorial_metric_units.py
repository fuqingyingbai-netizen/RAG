"""A native metric's explicit unit can be written beside its scalar."""
from copy import deepcopy
import pytest

from report_agents.company_editorial import declared_metric_quantities,parse_proposal,validate_audit
from test_company_editorial import record,audit,OUTLINE


def metric_row():
    row=record(text='营业收入（人民币元）：本期1,000.00，上年同期900.00，同比11.11%。',
               metric='营业收入',value='1,000.00',previous_value='900.00',unit='元',currency='人民币')
    row['provenance'][0]['origin']='specialized_checked_record'
    return row


def parse(row,text):
    return parse_proposal({'findings':[{'finding_id':'p','text':text,'information_ids':[row['information_id']]}]},
                          [row],6,OUTLINE[5][1][0])


def test_checked_metric_header_binds_both_current_and_prior_scalar_without_editing_originals():
    row=metric_row();before=deepcopy(row)
    findings,errors=parse(row,'公司披露营业收入本期1,000.00元，上年同期900.00元，同比11.11%，币种为人民币。')
    assert not errors
    assert not validate_audit([row],findings,audit([row],findings))
    assert row==before


def test_original_header_style_remains_valid_without_repeating_unit_after_each_value():
    row=metric_row();findings,errors=parse(row,row['text'])
    assert not errors and not validate_audit([row],findings,audit([row],findings))


@pytest.mark.parametrize('text',[
    '公司披露营业收入本期1,000.00万元，上年同期900.00元，同比11.11%，币种人民币。',
    '公司披露营业收入本期1,000.0元，上年同期900.00元，同比11.11%，币种人民币。',
    '公司披露营业收入本期1,000.00美元，上年同期900.00元，同比11.11%。',
])
def test_declared_unit_cannot_change_scale_precision_or_currency(text):
    assert parse(metric_row(),text)[1]


def test_raw_mixed_tables_cannot_borrow_the_next_table_unit_even_if_context_is_mislabeled():
    row=metric_row();row['text']='合同负债 1,000.00 900.00\n股本\n单位：元 币种：人民币\n股份总数 1,100.00'
    assert declared_metric_quantities(row)==[]
    assert parse(row,'合同负债本期1,000.00元，上期900.00元。')[1]


def test_mismatched_prior_unit_is_not_overwritten_with_current_unit():
    row=metric_row();row['context']['previous_unit']='万元'
    assert declared_metric_quantities(row)==['1,000.00元']
    assert parse(row,'营业收入本期1,000.00元，上年同期900.00元。')[1]


def test_unchecked_or_missing_unit_context_does_not_create_a_quantity():
    row=metric_row();row['provenance'][0]['origin']='literal_original_statement'
    assert declared_metric_quantities(row)==[]
    row=metric_row();row['context']['unit']='原文未载'
    assert declared_metric_quantities(row)==[]


@pytest.mark.parametrize('native_unit',['万元','亿元','百万元'])
def test_context_unit_cannot_match_only_the_suffix_of_a_larger_header_scale(native_unit):
    row=metric_row();row['text']=row['text'].replace('人民币元','人民币'+native_unit)
    assert declared_metric_quantities(row)==[]
    assert parse(row,'营业收入本期1,000.00元，上年同期900.00元，同比11.11%，币种人民币。')[1]


def test_correct_complete_scaled_header_still_binds_its_own_amounts():
    row=metric_row();row['context']['unit']='万元';row['text']=row['text'].replace('人民币元','人民币万元')
    assert declared_metric_quantities(row)==['1,000.00万元','900.00万元']
    assert not parse(row,'营业收入本期1,000.00万元，上年同期900.00万元，同比11.11%，币种人民币。')[1]
