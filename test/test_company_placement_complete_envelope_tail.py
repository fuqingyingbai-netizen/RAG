"""A complete envelope never licenses record repair or extra data."""
from copy import deepcopy
import json

import pytest

from report_agents.company_presentation import build_presentation, package_errors, parse_placement_response
from test_company_presentation import TARGET, SCOPE, placements, record


@pytest.mark.parametrize('as_array', [False, True])
@pytest.mark.parametrize('tail', [']}', '"}', '}}'])
def test_complete_json_value_with_only_surplus_closing_tokens_keeps_every_record(as_array, tail):
    answer = placements([record()]); before = deepcopy(answer)
    raw = json.dumps(answer['records'] if as_array else answer, ensure_ascii=False)+tail
    assert parse_placement_response(raw) == before
    assert answer == before


@pytest.mark.parametrize('tail', [
    ' {"records":[]}', ' []', ' "extra"', ' ""', ' ""}',
    ' null', ' 655', ' explanation', ' 结论：已经到账', ']'*9,
])
def test_extra_values_text_or_unbounded_junk_are_never_discarded(tail):
    raw = json.dumps(placements([record()]), ensure_ascii=False)+tail
    with pytest.raises(ValueError):
        parse_placement_response(raw)


@pytest.mark.parametrize('raw', ['{"records":[{"information_id":"I-a"}', '{records:[]}'])
def test_incomplete_or_invalid_inner_structure_cannot_be_recovered(raw):
    with pytest.raises(ValueError):
        parse_placement_response(raw)


@pytest.mark.parametrize('defect', ['wrong_glyph', 'short_quote', 'missing_id'])
def test_complete_envelope_does_not_fill_an_invalid_or_missing_source_bound_answer(defect):
    rows = [record('I-a', text='原文规定票数不得计入有表决权的股份总数。')]
    answer = placements(rows)
    if defect == 'wrong_glyph':
        answer['records'][0]['source_excerpt'] = '票數不得計入有表決權的股份總數'
    elif defect == 'short_quote':
        answer['records'][0]['source_excerpt'] = '原文规定票数'
    else:
        answer['records'] = []
    calls = []
    def invoke(role, prompt, trace):
        calls.append(role)
        return json.dumps(answer, ensure_ascii=False)+']}'
    result = build_presentation({'records':rows}, TARGET, SCOPE, invoke, workers=1)
    assert len(calls) == 3 and not result['batches'][0]['accepted']
    assert result['diagnostic']['pending_information_ids'] == ['I-a']
    assert not result['main_information_ids'] and not result['evidence_information_ids']


def test_complete_envelope_still_needs_both_full_context_independent_reads():
    rows = [record('I-a', text='本条原文说明公司资本变更须先满足生效条件。')]
    before = deepcopy(rows); calls = []
    def invoke(role, prompt, trace):
        calls.append(role)
        assert rows[0]['text'] in prompt
        return json.dumps(placements(rows), ensure_ascii=False)+'"}'
    result = build_presentation({'records':rows}, TARGET, SCOPE, invoke, workers=1)
    assert calls == ['公司交付正文取舍','公司交付正文取舍独立审稿']
    assert not package_errors(result, {'records':rows}, TARGET, SCOPE)
    assert rows == before


def test_delimiters_inside_native_values_are_never_stripped_or_reinterpreted():
    rows = [record('I-a', text='原文的示例字符为 ]} 和 "}，金额仍为655万元。')]
    answer = placements(rows)
    assert parse_placement_response(json.dumps(answer, ensure_ascii=False)+'}}') == answer
