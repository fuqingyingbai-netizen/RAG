"""Relevance routing cannot pre-judge main-report materiality."""
from copy import deepcopy
import json
import pytest

from report_agents.company_presentation import (
    VERSION, placement_payload, placement_prompt, build_presentation,
    package_errors, batch_input, render_annex, annex_errors,
)
from test_company_presentation import record, placements as answer_for, TARGET, SCOPE


def test_prior_model_rationale_is_hidden_but_native_evidence_and_coordinates_remain():
    row = record(text='股东大会是公司的权力机构，应依法召开会议。')
    row['decision'].update(relevance='前置分类器称这是决定性的核心事实，必须全部放main。',
                           voice='前置分类器自行撰写的归因', other='未经核对的附加字段')
    before = deepcopy(row); payload = placement_payload(row)
    assert payload['decision'] == {k: row['decision'][k] for k in ('chapter', 'aspect')}
    assert payload['text'] == row['text'] and payload['context'] == row['context']
    assert '前置分类器' not in json.dumps(payload, ensure_ascii=False)
    assert row == before and '必须全部放main' in render_annex({'records': [row]}, {}, TARGET)


def test_independent_reader_gets_complete_originals_and_scope_without_the_candidate():
    rows = [record(text='年报披露利润增长主要来自投资收益，经营现金流下降。')]
    candidate = answer_for(rows); candidate['records'][0]['reason'] = '候选暗示应服从此结论'
    prompt = placement_prompt(rows, TARGET, candidate, scope=SCOPE)
    assert '候选暗示应服从此结论' not in prompt
    assert json.dumps(SCOPE, ensure_ascii=False) in prompt
    assert rows[0]['text'] in prompt
    assert '不能仅以' in prompt and '未解决或影响关键判断' in prompt


def test_both_fresh_reads_receive_scope_while_disagreement_and_core_protections_remain():
    rows = [record('I-routine', text='章程规定一般会议召集程序。'),
            record('I-capital', text='注册资本变更金额及其尚未满足的生效条件。', kind='registry')]
    calls = []
    def invoke(role, prompt, trace):
        calls.append((role, prompt))
        actual = json.loads(prompt.split('资料：\n', 1)[1])
        answer = answer_for(actual, 'evidence')
        if role.endswith('独立审稿'):
            next(r for r in answer['records'] if r['information_id']=='I-routine')['surface'] = 'main'
        return json.dumps(answer, ensure_ascii=False)
    package = build_presentation({'records': rows}, TARGET, SCOPE, invoke, workers=1)
    assert len(calls) == 2 and all(json.dumps(SCOPE, ensure_ascii=False) in p for _, p in calls)
    assert set(package['main_information_ids']) == {'I-routine', 'I-capital'}
    assert package['placements']['I-capital']['structured_core_required'] is True
    assert not package_errors(package, {'records': rows}, TARGET, SCOPE)
    assert not annex_errors({'records': rows}, render_annex({'records': rows}, package, TARGET))


def test_old_contract_cannot_reuse_prejudged_main_decisions():
    rows = [record()]; old = {'version': 'company-presentation-v1-reviewed-main-and-lossless-evidence',
        'target_name': TARGET, 'scope': SCOPE, 'batches': [
            {'accepted': True, 'input_sha256': batch_input(rows, TARGET, SCOPE),
             'information_ids': [rows[0]['information_id']], 'proposal': answer_for(rows), 'review': answer_for(rows)}]}
    calls = []
    def invoke(role, prompt, trace):
        calls.append(role); return json.dumps(answer_for(rows, 'evidence'), ensure_ascii=False)
    package = build_presentation({'records': rows}, TARGET, SCOPE, invoke, previous=old, workers=1)
    assert VERSION != old['version'] and len(calls) == 2
    assert not package['main_information_ids']


@pytest.mark.parametrize('kind', ['regulatory_order','regulatory_notice','correction_recommendation','external_impersonation'])
def test_checked_primary_actions_and_company_harm_cannot_be_hidden_as_routine(kind):
    rows = [record(text='原文明示具体措施、第三方责任或目标公司的受损情况及未知状态。', kind=kind)]
    def invoke(role, prompt, trace):
        assert '不能凭一审判决或申请撤诉' in prompt
        return json.dumps(answer_for(rows, 'evidence'), ensure_ascii=False)
    package = build_presentation({'records': rows}, TARGET, SCOPE, invoke, workers=1)
    assert package['main_information_ids'] == [rows[0]['information_id']]
    assert package['placements'][rows[0]['information_id']]['structured_core_required'] is True
