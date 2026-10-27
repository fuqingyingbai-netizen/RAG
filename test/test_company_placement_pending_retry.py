"""Retry source locators without repeating passed answers or weakening review."""
from copy import deepcopy
import json

import pytest

from report_agents.company_presentation import (
    build_presentation, literal_excerpt_options, package_errors,
    placement_payload, validate_batch,
)
from test_company_presentation import record, placements, TARGET, SCOPE


def retry_hints(prompt):
    return json.JSONDecoder().raw_decode(prompt.split('本轮待补齐的ID及逐字定位辅助：\n', 1)[1])[0]


@pytest.mark.parametrize('text', [
    '原文乙规定本次回购实施期限不超过十二个月。',
    '根据原文满\n公司招股说明书\n1-1-208\n意度评价为 99.35%。',
    '公司董事會未按上述期限執行的，負有責任的董事依法承擔連帶責任。',
    'Revenue increased 6.01%; cash flow declined 18.52%.',
    '注册资本',
])
def test_locator_options_are_always_unchanged_native_contiguous_spans(text):
    options = literal_excerpt_options(text)
    assert 1 <= len(options) <= 3
    assert len(options) == len(set(options))
    assert all(option in text and min(8, len(text.strip())) <= len(option.strip()) <= 24 for option in options)
    if '負有' in text:
        assert all('负有' not in option for option in options)


@pytest.mark.parametrize('stage', ['proposal', 'review'])
def test_retry_only_requests_missing_ids_with_all_original_context_and_fresh_judgment(stage):
    rows = [record('I-a', text='原文甲是本条完整资料，独立审稿仍须阅读。'),
            record('I-b', text='根据原文满\n公司招股说明书\n1-1-208\n意度评价为 99.35%。')]
    rows[1]['context']['boundary'] = '只适用于历史年度，不能作为当前年度满意度。'
    before = deepcopy(rows)
    counts = {}; calls = []; genuine = []
    def invoke(role, prompt, trace):
        current = 'review' if role.endswith('独立审稿') else 'proposal'
        counts[current] = counts.get(current, 0) + 1
        calls.append((current, prompt))
        native = json.JSONDecoder().raw_decode(prompt.split('资料：\n', 1)[1])[0]
        assert native == [placement_payload(row) for row in rows]
        if current == 'review':
            assert '首轮独有候选理由不得泄漏' not in prompt
        answer = placements(rows)
        if current == 'proposal':
            for item in answer['records']:
                item['reason'] = '首轮独有候选理由不得泄漏给另一位审稿者。'
        if current == stage:
            if counts[current] == 1:
                answer['records'][1]['source_excerpt'] = '根据原文满意度评价为 99.35%。'
            else:
                hints = retry_hints(prompt)
                assert [item['information_id'] for item in hints] == ['I-b']
                assert all(set(item) == {'information_id', 'literal_excerpt_options'} for item in hints)
                assert '必须覆盖全部信息ID' not in prompt
                answer['records'] = [answer['records'][1]]
                answer['records'][0]['source_excerpt'] = hints[0]['literal_excerpt_options'][0]
        genuine.append(deepcopy(answer))
        return json.dumps(answer, ensure_ascii=False)
    result = build_presentation({'records': rows}, TARGET, SCOPE, invoke, workers=1)
    assert len(calls) == 3 and counts[stage] == 2
    assert rows == before and not package_errors(result, {'records': rows}, TARGET, SCOPE)
    batch = result['batches'][0]
    assert batch['accepted'] and [attempt['response'] for attempt in batch['attempts']] == genuine
    assert not validate_batch(rows, batch)[1]


@pytest.mark.parametrize('defect', ['wrong_glyph', 'omitted', 'malformed_json'])
def test_supplied_native_options_never_supply_a_missing_or_invalid_model_witness(defect):
    rows = [record('I-a', text='负有责任的董事依法承担连带责任，但本条是一般制度条件。')]
    calls = []
    def invoke(role, prompt, trace):
        calls.append(prompt)
        if len(calls) > 1:
            assert retry_hints(prompt)[0]['information_id'] == 'I-a'
        if defect == 'malformed_json':
            return '{"records":[]} {"records":[]}'
        answer = placements(rows)
        if defect == 'wrong_glyph':
            answer['records'][0]['source_excerpt'] = '負有責任的董事依法承擔連帶責任'
        else:
            answer['records'] = []
        return json.dumps(answer, ensure_ascii=False)
    result = build_presentation({'records': rows}, TARGET, SCOPE, invoke, workers=1)
    assert len(calls) == 3 and not result['batches'][0]['accepted']
    assert result['diagnostic']['pending_information_ids'] == ['I-a']
    assert not result['main_information_ids'] and not result['evidence_information_ids']


def test_retry_bound_main_judgment_and_financial_core_still_promote_main():
    rows = [record('I-a', text='本条近期利润与经营现金变化影响判断。', kind='financial_metric'),
            record('I-b', text='本条资本变更须满足生效条件，尚未核验。')]
    counts = {}
    def invoke(role, prompt, trace):
        current = 'review' if role.endswith('独立审稿') else 'proposal'
        counts[current] = counts.get(current, 0) + 1
        answer = placements(rows)
        if current == 'review':
            if counts[current] == 1:
                answer['records'].pop()
            else:
                answer['records'] = [answer['records'][1]]
                answer['records'][0]['surface'] = 'main'
                answer['records'][0]['reason'] = '资本变更生效尚未核验直接影响公司判断。'
                answer['records'][0]['source_excerpt'] = retry_hints(prompt)[0]['literal_excerpt_options'][0]
        return json.dumps(answer, ensure_ascii=False)
    result = build_presentation({'records': rows}, TARGET, SCOPE, invoke, workers=1)
    assert set(result['main_information_ids']) == {'I-a', 'I-b'}
    assert not package_errors(result, {'records': rows}, TARGET, SCOPE)
