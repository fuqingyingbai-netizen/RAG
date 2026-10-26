"""Synthetic contracts for questions, exact premises and bounded model review."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from industry_reasoning import (apply_risk_support, claim_id, completion_criteria, fingerprint,
    premise_issues, prioritize_questions, question_ledger, reasoning_snapshot,
    review_packet, run_support_review, validate_reviews)
from industry_fact_contracts import attach_contract, validate_analyses
from industry_delivery import verification_tasks, verification_task_table
from industry_research import normalize_risk
from report_agents.industry_report_agent import IndustryReportAgent
from test_industry_template_analysis import chain, fact, claim, EID, SCOPE, ANALYSIS


def review_claim(f=None, **updates):
    f = f or chain()
    c = {**claim(), 'chapter': 2, 'claim_kind': 'conditional',
         'premises': [{'evidence_id': EID, 'quote': f['fact_contract']['statement']}],
         'reasoning': '材料只支持产业链分层；盈利差异仍需另外核对。', **updates}
    return {**c, 'claim_id': claim_id(c, c['chapter'])}


def verdict(c, f, status='supported', **updates):
    return {'claim_id': c['claim_id'], 'status': status,
        'reason': '材料说明分层，分析保留了价值分配尚缺证的限制。',
        'quotes': [{'evidence_id': f['evidence_id'], 'quote': f['fact_contract']['statement']}], **updates}


def response(packet, reviews):
    return json.dumps({'packet_fingerprint': packet['packet_fingerprint'], 'reviews': reviews})


def test_questions_distinguish_no_material_from_a_selection_gap():
    f = chain(); payload = {'facts': [f], 'industry_scope': SCOPE}; before = deepcopy(payload)
    rows = {r['question']: r for r in question_ledger(payload, 2, [])['questions']}
    assert rows['产业链主体和分层关系']['evidence_state'] == 'selection_gap'
    assert rows['产业链主体和分层关系']['next_action'] == 'review_selection'
    assert rows['核心瓶颈']['evidence_state'] == 'missing'
    assert not any(r['answer_verified'] for r in rows.values())
    assert payload == before


def test_question_slots_survive_character_budget_preselection():
    f = chain(); general, body = fact('机器人行业是指相关产品及应用场景组成的行业分类。', evidence_id='E-222222222222')
    general = attach_contract(general, SCOPE, body)
    payload = {'facts': [general]*20+[f]}
    ordered = prioritize_questions(payload, 2)
    assert f in ordered['facts'][:2]
    assert len(ordered['facts']) <= len(payload['facts'])
    assert prioritize_questions({'facts': [{'fact': 'historical legacy'}]}, 2)['facts'][0]['fact'] == 'historical legacy'


def test_exact_whole_premises_are_required_and_source_objects_unchanged():
    f = chain(); c = review_claim(f); before = deepcopy(f)
    valid = {k: v for k,v in c.items() if k not in {'chapter', 'claim_id'}}
    assert validate_analyses([valid], {'facts': [f]}, 2, [EID])[0]
    valid['premises'][0]['quote'] = '上游提供控制器'
    assert 'invalid_claim_premises' in validate_analyses([valid], {'facts': [f]}, 2, [EID])[1][0]['issues']
    assert f == before


def test_cause_is_not_invented_from_a_descriptive_chain():
    f = chain(); c = review_claim(f, text='产业链已经分层，因此证明行业不存在竞争压力，各环节必然长期实现稳定盈利。')
    assert 'causal_link_not_supported' in premise_issues(c, [f])
    c['text'] = '产业链分层可能影响协作方式，但现有材料不足以判断盈利，仍需核对交易和成本。'
    assert premise_issues(c, [f]) == []
    c['text'] = '材料不能证明行业盈利；因此证明进入门槛必然下降。'
    assert premise_issues(c, [f]) == ['causal_link_not_supported']
    c['text'] = '材料并不必然证明行业盈利，不能据此认定核心瓶颈。'
    assert premise_issues(c, [f]) == []


def test_review_packet_contains_only_complete_licensed_records():
    f = chain(); f['original_model_fact'] = 'PRIVATE_DIAGNOSTIC'
    c = review_claim(f)
    packet, excluded = review_packet([c], [f])
    assert not excluded and packet['cards'][EID]['statement'] == f['fact_contract']['statement']
    assert 'PRIVATE_DIAGNOSTIC' not in json.dumps(packet)
    limited, excluded = review_packet([c], [f], max_chars=200)
    assert not limited['claims'] and excluded == [c['claim_id']]
    assert len(json.dumps(limited, ensure_ascii=False)) <= 200


@pytest.mark.parametrize('field,value', [('eligible_for_report', False), ('provenance', {'locator': {'status': 'unlocated'}})])
def test_unapproved_or_unlocated_fact_never_enters_review_packet(field, value):
    f = chain(); c = review_claim(f); f[field] = value
    packet, excluded = review_packet([c], [f])
    assert not packet['claims'] and excluded


@pytest.mark.parametrize('status', ['supported', 'partial', 'unsupported', 'contradicted', 'uncertain'])
def test_all_review_states_require_exact_material_and_never_prove_entailment(status):
    f = chain(); c = review_claim(f); packet, _ = review_packet([c], [f])
    result = validate_reviews(response(packet, [verdict(c, f, status)]), packet)[c['claim_id']]
    assert result['status'] == status and result['human_review_required']
    assert result['entailment_proven'] is False
    assert result['packet_fingerprint'] == packet['packet_fingerprint']


@pytest.mark.parametrize('bad', [
    {'quotes': []}, {'quotes': [{'evidence_id': EID, 'quote': 'invented quotation'}]},
    {'claim_id': 'C-UNKNOWN'}, {'status': {}}, {'reason': 'yes'},
    {'quotes': [{'evidence_id': 'E-222222222222', 'quote': 'other card'}]},
])
def test_invalid_review_cannot_upgrade_a_claim(bad):
    f = chain(); c = review_claim(f); packet, _ = review_packet([c], [f])
    assert validate_reviews(response(packet, [verdict(c, f, **bad)]), packet)[c['claim_id']]['status'] == 'not_evaluated'


def test_duplicates_and_omissions_do_not_silently_pass():
    f = chain(); c = review_claim(f); packet, _ = review_packet([c], [f])
    v = verdict(c, f)
    assert validate_reviews(response(packet, [v, v]), packet)[c['claim_id']]['status'] == 'not_evaluated'
    assert validate_reviews(response(packet, []), packet)[c['claim_id']]['status'] == 'not_evaluated'


def test_bounded_review_calls_once_and_failure_preserves_pending_state():
    f = chain(); c = review_claim(f); calls = []
    def timeout(prompt):
        calls.append(prompt); raise TimeoutError('SECRET_MUST_NOT_BE_LOGGED')
    result = run_support_review([c], [f], timeout)
    assert len(calls) == result['attempts'] == 1
    assert result['error_type'] == 'TimeoutError' and 'SECRET' not in json.dumps(result)
    assert result['reviews'][c['claim_id']]['status'] == 'not_evaluated'


def test_new_reasoning_cannot_change_ids_or_approve_a_stale_claim():
    f = chain(); c = review_claim(f); v = verdict(c, f)
    changed = review_claim(f, text=ANALYSIS+'本次仅讨论应用分工。')
    packet, _ = review_packet([changed], [f])
    assert changed['claim_id'] != c['claim_id']
    assert validate_reviews(response(packet, [v]), packet)[changed['claim_id']]['status'] == 'not_evaluated'


def test_review_fingerprint_binds_the_actual_evidence_not_only_claim_text():
    f = chain(); c = review_claim(f); packet, _ = review_packet([c], [f])
    old_response = response(packet, [verdict(c, f)])
    changed = deepcopy(f)
    changed['fact_contract']['statement'] += '该观察仅限本地区。'
    new_packet, _ = review_packet([c], [changed])
    assert packet['packet_fingerprint'] != new_packet['packet_fingerprint']
    assert validate_reviews(old_response, new_packet)[c['claim_id']]['status'] == 'not_evaluated'


def test_existing_material_omitted_before_budget_is_a_selection_gap():
    payload = {'facts': [], 'question_material_candidates': [{'question': '产业链主体和分层关系',
        'evidence_ids': [EID], 'evidence_count': 5}]}
    row = next(r for r in question_ledger(payload, 2, [])['questions'] if r['question'] == '产业链主体和分层关系')
    assert row['evidence_state'] == 'selection_gap' and row['available_evidence_count'] == 5
    assert row['candidate_basis'] == 'pre_budget_chapter_candidates' and not row['answer_verified']


def test_risk_review_can_remove_a_score_but_never_fill_an_unknown():
    f, body = fact('《机器人服务管理办法》第三条规定，机器人服务提供者应当记录数据来源。', module='政策与监管',
        source_url='https://www.gov.cn/rule', source_title='机器人服务管理办法', source_type='government')
    f = attach_contract(f, SCOPE, body)
    risk = normalize_risk({'dimensions': [{'name': '政策与监管风险', 'score': 30, 'level': 'low',
        'reason': '法规规定了数据记录义务。', 'evidence_ids': [EID]}]}, [f], SCOPE)
    row = next(d for d in risk['dimensions'] if d['name'] == '政策与监管风险')
    assert row['score'] == 30, row
    cid = claim_id({'question': row['name'], 'text': row['reason'], 'evidence_ids': row['evidence_ids']}, 14)
    review = {'attempts': 1, 'reviews': {cid: {'status': 'unsupported'}}}
    original = deepcopy(risk)
    checked = apply_risk_support(risk, review, [f], SCOPE)
    current = next(d for d in checked['dimensions'] if d['name'] == row['name'])
    assert current['score'] is None and current['unknown_cause'] == 'claim_support_rejected'
    assert current['validation_diagnostic']['support_rejected_score'] == 30
    assert current['candidate_evidence_count'] == 1
    assert current['validation_diagnostic']['supplied_evidence_ids'] == [EID]
    assert checked['overall_score'] is None and checked['assessed_dimension_count'] == 0
    assert all(d['score'] is None for d in checked['risk_transparency']['dimensions'])
    assert risk == original
    supported = apply_risk_support(checked, {'reviews': {cid: {'status': 'supported'}}}, [f], SCOPE)
    assert all(d['score'] is None for d in supported['dimensions'])


def test_report_review_retains_source_but_removes_only_rejected_analysis():
    f = chain(); a = claim(); c = review_claim(f)
    project = SimpleNamespace(industry_statement_plans={2: {'evidence_ids': [EID],
        'analysis_claims': [a], 'analysis_rejections': []}}, industry_report_degradations=[
            {'chapter': 2, 'review_type': 'statement_synthesis_review', 'evidence_ids': [EID]}])
    calls = []
    def invoke(role, prompt, trace):
        calls.append(role)
        packet = json.loads(prompt.split('\n', 1)[1]); submitted = packet['claims'][0]
        return response(packet, [verdict(submitted, f, 'unsupported')])
    sections = {}
    IndustryReportAgent()._review_statement_claims(project, {'facts': [f]}, {2: json.dumps({'facts': [f]})}, sections,
        invoke, lambda *a,**kw: None, None)
    assert len(calls) == 1 and ANALYSIS not in sections[2] and f['fact_contract']['statement'] in sections[2]
    plan = project.industry_statement_plans[2]
    assert not plan['analysis_claims'] and plan['analysis_rejections']
    rows = plan['content_coverage']
    assert next(r for r in rows if r['question'] == a['question'])['claim_support_states'] == ['unsupported']
    assert '所引材料不足以支持' in sections[2]
    tasks = verification_tasks({'facts': [f]}, {}, project.industry_report_degradations, SCOPE)
    assert any(s.get('status') == 'unsupported' for task in tasks for s in task.get('subtasks', []))
    assert '结论支持复核' in verification_task_table(tasks)
    snapshot = reasoning_snapshot(project)
    assert snapshot['human_review_required'] and snapshot['analysis_rejections']


def test_criteria_are_question_specific_not_a_generic_statistics_checklist():
    assert '硬件及测试负载' in completion_criteria('同条件测试配置')
    assert '市场分母及厂商分子' in completion_criteria('份额及集中度')
    assert '研究总体及样本' in completion_criteria('盈利及收入成本材料')
