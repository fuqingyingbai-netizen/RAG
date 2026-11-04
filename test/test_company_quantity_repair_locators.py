"""Focused producer feedback preserves the full factual and audit gates."""
from copy import deepcopy
import json

import pytest

from report_agents.company_editorial import (
    build_editorial_package, parse_proposal, quantity_repair_locators,
)
from test_company_editorial import OUTLINE, audit, record,assert_semantic_rejected


def finding(row, text):
    return {'finding_id': 'p1', 'text': text, 'information_ids': [row['information_id']]}


def test_corrupted_scale_is_visible_and_native_offsets_stay_verbatim():
    row = record(text='公司披露有息借款為人民幣351.4百萬元，均按固定利率计息。')
    proposal = {'findings': [finding(row, row['text'].replace('百萬元', '百萟元'))]}
    before = deepcopy((proposal, row))
    hints = quantity_repair_locators(proposal, [row])
    assert '百萟元' in hints[0]['output_locators'][0]['quote']
    for loc in hints[0]['source_locators']:
        assert loc['quote'] == row['text'][loc['start']:loc['end']]
        assert '百萬元' in loc['quote']
    assert (proposal, row) == before
    assert_semantic_rejected(proposal,[row])


def test_equal_numbers_in_uncited_records_cannot_supply_a_unit():
    own = record('I-own', '公司披露本项原值351.4，单位未明确。')
    other = record('I-other', '其他主体披露收入351.4百万元。')
    proposal = {'findings': [finding(own, '公司披露本项原值351.4百万元。')]}
    hints = quantity_repair_locators(proposal, [own, other])
    assert {loc['information_id'] for loc in hints[0]['source_locators']} == {'I-own'}
    assert all('百万元' not in loc['quote'] for loc in hints[0]['source_locators'])
    assert parse_proposal(proposal, [own, other], 6, OUTLINE[5][1][0])[1]


def test_locators_never_round_or_change_a_scalar_to_find_support():
    row = record(text='公司借款为35.14百万元，计划金额为-351.4百万元。')
    hints = quantity_repair_locators({'findings': [finding(row, '公司借款为351.4百萟元。')]}, [row])
    assert hints[0]['source_locators'] == []


@pytest.mark.parametrize('repairs', [True, False])
def test_normal_retry_needs_new_correct_prose_and_full_independent_audit(repairs):
    row = record(text='公司披露有息借款為人民幣351.4百萬元，均按固定利率计息。')
    roles = []; producer_prompts = []

    def invoke(role, prompt, trace):
        roles.append(role)
        if role == '公司交付正文独立审稿':
            data = json.loads(prompt.split('资料：\n', 1)[1])
            qa=audit([row],data['findings'])
            if '百萟元' in data['findings'][0]['text']:
                qa['criteria']['factual_support']=False;qa['findings'][0]['status']='unsupported'
                qa['issues']=['原件为百萬元，正文误写百萟元。']
            return json.dumps(qa,ensure_ascii=False)
        assert role == '公司交付正文编写'
        producer_prompts.append(prompt)
        text = row['text'] if repairs and len(producer_prompts) > 1 else row['text'].replace('百萬元', '百萟元')
        return json.dumps({'findings': [finding(row, text)]}, ensure_ascii=False)

    package = build_editorial_package({'records': [row]}, OUTLINE, '公司', invoke, workers=1)
    assert '原件为百萬元' in producer_prompts[1]
    assert '百萟元' in producer_prompts[1] and '百萬元' in producer_prompts[1]
    if repairs:
        assert not package['diagnostic']['pending_information_ids']
        assert roles.count('公司交付正文独立审稿') == 2
        assert package['findings'][0]['text'] == row['text']
        assert package['batches'][0]['attempts'][0]['errors']
    else:
        assert package['diagnostic']['pending_information_ids'] == [row['information_id']]
        assert roles.count('公司交付正文独立审稿')==3
        assert package['batches'][0]['accepted'] is False
