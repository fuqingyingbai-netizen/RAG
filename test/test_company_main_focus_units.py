"""Focusing changes required prose, never original evidence or scope."""
from copy import deepcopy

import pytest

from report_agents.company_main_focus import (
    CRITERIA, expanded_unit_ids, focus_prompt, mandatory_full_record, mandatory_unit_ids,
    source_focus, source_units, validate_focus_answers,
)
from test_company_presentation import record, TARGET, SCOPE


def answer(row,ids):
    return {'records':[{'information_id':row['information_id'],'main_proposition_ids':ids,
        'reason':'选取改变公司判断的事实并保留所有相关限定。','criteria':dict.fromkeys(CRITERIA,True)}]}


def test_units_are_exact_native_offsets_including_zero_unknown_and_short_values():
    row = record('I-a',text='2026年营业收入为100元。\n0\n无\n—\n来源时点未知。')
    before = deepcopy(row); units = source_units(row)
    assert all(row['text'][unit['start']:unit['end']] == unit['text'] for unit in units)
    for text in ('0','无','—'):
        unit = next(unit for unit in units if unit['text'] == text)
        assert not unit['presentation_only']
    assert row == before


def test_line_wrapped_fact_and_its_attached_pending_condition_stay_together():
    row = record('I-a',text='公司注册资本为100\n万元。\n该变更尚须履行登记程序。\n联系电话：12345678')
    units = source_units(row)
    selected = expanded_unit_ids(row,[units[0]['proposition_id']])
    assert all(unit['proposition_id'] in selected for unit in units[:3])
    assert units[3]['proposition_id'] not in selected


def test_separate_profile_fields_do_not_force_unrelated_contact_details_into_main():
    row = record('I-a',text='公司名称：青禾公司\n注册资本：100万元\n邮政编码：123456\n联系电话：12345678')
    units = source_units(row)
    assert expanded_unit_ids(row,[units[1]['proposition_id']]) == [units[1]['proposition_id']]


def test_flattened_provider_fields_remain_separately_selectable_without_changing_text():
    row = record('I-a',text='中文名称：青禾公司英文名称：Qinghe Inc.本次发行前注册资本：100万元法定代表人：甲住所：乙地经营范围：开发软件。')
    units = source_units(row)
    assert [unit['text'] for unit in units] == ['中文名称：青禾公司','英文名称：Qinghe Inc.',
        '本次发行前注册资本：100万元','法定代表人：甲','住所：乙地','经营范围：开发软件。']
    capital = units[2]['proposition_id']
    assert expanded_unit_ids(row,[capital]) == [capital]
    assert all(row['text'][unit['start']:unit['end']] == unit['text'] for unit in units)


def test_a_native_period_prefix_stays_with_the_field_it_governs():
    row = record('I-a',text='截至2022年12月31日，注册资本：100万元。')
    units = source_units(row)
    assert len(units) == 2
    assert expanded_unit_ids(row,[units[1]['proposition_id']]) == [unit['proposition_id'] for unit in units]


@pytest.mark.parametrize('ids',[None,['other-source-M1'],['I-a-M1','I-a-M1'],[{}]])
def test_invalid_or_ambiguous_source_choices_supply_no_main_fact(ids):
    row = record('I-a',text='公司资本为100万元，尚未完成登记。')
    checked, errors = validate_focus_answers([row],answer(row,ids))
    assert not checked and errors


def test_missing_or_empty_focus_does_not_silently_move_a_main_candidate_to_annex():
    row = record('I-a',text='公司资本为100万元，尚未完成登记。')
    assert validate_focus_answers([row],{'records':[]})[1]
    assert validate_focus_answers([row],answer(row,[]))[1]


@pytest.mark.parametrize('criterion',CRITERIA)
def test_every_focus_semantic_criterion_is_required(criterion):
    row = record('I-a',text='公司资本为100万元，尚未完成登记。')
    value = answer(row,[source_units(row)[0]['proposition_id']])
    value['records'][0]['criteria'][criterion] = False
    assert not validate_focus_answers([row],value)[0]


def test_source_focus_is_only_a_locator_and_never_a_fabricated_approval():
    row = record('I-a',text='公司资本为100万元，尚未完成登记。')
    focus = source_focus(row,[source_units(row)[0]['proposition_id']])
    assert focus['spans'][0]['text'] in row['text']
    assert not {'accepted','supported','independent_check','delivery_ready'} & set(focus)


def test_structured_core_and_conflicts_keep_the_whole_native_fact_record():
    row = record('I-a',text='本期经营现金流为0元，上一期为100元；口径待核。',kind='financial_metric')
    assert mandatory_full_record(row)
    assert len(mandatory_unit_ids(row)) == len(source_units(row))
    row['context']['kind'] = 'reviewed_original_statement'
    assert mandatory_full_record(row,{'conflict_promoted':'same-scope-conflict'})


def test_two_readers_receive_full_originals_without_the_other_focus_decision():
    row = record('I-a',text='公司资本为100万元。联系电话12345678。')
    prompt = focus_prompt([row],TARGET,SCOPE,independent=True)
    assert row['text'] in prompt and '不提供另一人的候选结论' in prompt
    assert '联系电话12345678' in prompt and 'native_propositions' in prompt


def test_generic_profile_heading_and_its_checkbox_do_not_become_a_business_fact():
    row=record('I-a',text='三、公司基本情况\n1 公司概况\n√适用 □不适用\n公司名称：青禾公司\n注册资本：100万元')
    units=source_units(row)
    assert all(unit['context_only'] for unit in units[:3])
    name=next(unit for unit in units if unit['text']=='公司名称：青禾公司')
    assert expanded_unit_ids(row,[name['proposition_id']])==[name['proposition_id']]
    assert validate_focus_answers([row],answer(row,[units[0]['proposition_id']]))[1]


def test_applicability_of_a_business_question_is_not_mistaken_for_generic_layout():
    row=record('I-a',text='研发投入资本化\n□适用 √不适用\n研发支出为100万元。')
    units=source_units(row)
    assert not units[1]['context_only'] and not units[1]['presentation_only']
    assert units[1]['proposition_id'] in expanded_unit_ids(row,[units[0]['proposition_id']])


def test_following_approval_condition_is_attached_to_the_selected_plan():
    row=record('I-a',text='公司拟增资100万元。仅在股东批准后生效。联系电话：12345678。')
    units=source_units(row)
    assert expanded_unit_ids(row,[units[0]['proposition_id']])==[u['proposition_id'] for u in units[:2]]
