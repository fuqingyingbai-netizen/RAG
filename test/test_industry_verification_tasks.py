"""Document-pair regressions: follow-up actions must retain their cause and scope."""
import copy
import io
import json
import re
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest

from industry_delivery import (verification_tasks, verification_task_table, tasks_section,
                               evaluation_inputs, finalize_synthesis)
from industry_research import append_evidence_index, delivery_errors, normalize_risk
from report_agents.industry_proposal import build_industry_proposal

SCOPE = {'capital_market': 'none', 'named_companies': [], 'industry_name': '机器人'}
EID = 'E-111111111111'


def fact(**changes):
    return {'evidence_id': EID, 'fact': '行业收费方式包含按量计费。',
            'evidence_quote': '行业收费方式包含按量计费。', 'module': '商业模式与盈利逻辑',
            'source_url': 'https://research.example/report', 'source_title': '行业调研',
            'scope_match': 'in_scope', 'eligible_for_report': True, 'evidence_scope': 'industry_level',
            'provenance': {'locator': {'status': 'verified'}}, **changes}


def unknown(cause='unverified_reason_numbers', **changes):
    return {'name': '商业化与盈利模式风险', 'score': None, 'level': 'unknown',
            'unknown_cause': cause, 'candidate_evidence_count': 3,
            'validation_diagnostic': {'admissible_evidence_ids': [EID], 'original_score': 42,
                                      'original_reason': '错误旧结论：行业平均利润999亿元。'}, **changes}


@pytest.mark.parametrize('cause', ['unverified_reason_numbers', 'invalid_reason_citations', 'missing_model_citations'])
def test_rejected_scores_first_review_saved_input_without_reprinting_failed_reason(cause):
    payload = {'facts': [fact()]}
    risk = {'dimensions': [unknown(cause)]}
    original = copy.deepcopy((payload, risk))
    task, = verification_tasks(payload, risk, [], SCOPE)
    assert task['task_type'] == 'assessment_validation'
    assert '先对照已保存原文' in task['action'] and '再确认补采' in task['action']
    assert '999' not in json.dumps(task, ensure_ascii=False)
    assert task['review_evidence_ids'] == [EID] and task['candidate_evidence_count'] == 3
    assert task['priority'] == '高' and task['chapters'] == [10, 14]
    assert task['completion'] != '核对原文' and '未通过继续保留未知' in task['completion']
    assert (payload, risk) == original


def test_abstained_competition_is_not_fixed_by_adding_company_counts_or_forcing_a_score():
    row = unknown('model_abstained', name='竞争格局与集中度风险',
                  validation_diagnostic={'admissible_evidence_ids': [EID], 'original_score': None})
    task, = verification_tasks({'facts': [fact()]}, {'dimensions': [row]}, [], SCOPE)
    assert task['task_type'] == 'assessment_abstained'
    assert 'CR3/CR5' in task['action'] and '分母' in task['materials']
    assert '不能替代集中度' in task['action'] and '先核对现有候选' in task['action']
    assert task['chapters'] == [6, 14] and '继续保留未知' in task['completion']


def test_missing_industry_evidence_keeps_business_sample_boundary():
    row = unknown('no_applicable_evidence', candidate_evidence_count=0, validation_diagnostic={})
    task, = verification_tasks({}, {'dimensions': [row]}, [], SCOPE)
    assert task['task_type'] == 'evidence_gap'
    assert '企业样本' in task['action'] and '实际收费' in task['materials'] + task['action']
    assert task['review_evidence_ids'] == [] and task['priority'] == '高'


def test_network_execution_failure_is_not_evidence_of_a_data_gap():
    row = unknown('assessment_unavailable', validation_diagnostic={})
    risk = {'dimensions': [row], 'validation_diagnostics': {'primary_status': 'request_failed'}}
    task, = verification_tasks({}, risk, [], SCOPE)
    assert task['task_type'] == 'execution_failure'
    assert '不能据此判断资料不足' in task['reason']
    assert '由用户决定' in task['action'] and '不自动追加请求' in task['action']


@pytest.mark.parametrize('changes', [
    {'eligible_for_report': False}, {'scope_match': 'out_of_scope'},
    {'provenance': {'locator': {'status': 'unlocated'}}}, {'evidence_scope': 'capital_market'},
])
def test_task_references_never_authorize_quarantined_or_disabled_evidence(changes):
    row = unknown(validation_diagnostic={'admissible_evidence_ids': [EID, 'E-FAKE00000000']})
    task, = verification_tasks({'facts': [fact(**changes)]}, {'dimensions': [row]}, [], SCOPE)
    assert task['review_evidence_ids'] == []
    table = verification_task_table([task])
    assert EID not in table and 'E-FAKE' not in table
    assert '先核对本轮评分输入' in table


def test_metric_tasks_link_to_unresolved_risk_and_do_not_duplicate_its_requirements():
    coverage = {'requirements': [
        {'requirement_id': 'concentration', 'module': '竞争格局与代表企业',
         'question': '行业集中度', 'status': 'candidate', 'candidate_evidence_ids': [EID]},
        {'requirement_id': 'technology_cost', 'module': '技术路线对比',
         'question': '同条件技术成本', 'status': 'missing'}]}
    risk = {'dimensions': [unknown('model_abstained', name='竞争格局与集中度风险')]}
    tasks = verification_tasks({'facts': [fact()], 'evidence_coverage': coverage}, risk, [], SCOPE)
    assert [t['key'] for t in tasks] == ['risk:竞争格局与集中度风险', 'metric:technology_cost']
    assert tasks[0]['review_evidence_ids'] == [EID]
    assert tasks[1]['requirement_ids'] == ['technology_cost']
    # IDs follow the problem rather than its position in a generated table.
    another = verification_tasks({'evidence_coverage': coverage}, {}, [], SCOPE)
    assert tasks[1]['task_id'] == next(t['task_id'] for t in another if t['key'] == 'metric:technology_cost')


def test_compact_report_keeps_tasks_and_proposal_keeps_full_completion_details():
    tasks = verification_tasks({'facts': [fact()]}, {'dimensions': [unknown()]},
                               [{'chapter': 7, 'message': '技术章节失败'}], SCOPE)
    project = SimpleNamespace(title='机器人研究', target_name='机器人', industry_scope=SCOPE,
                              industry_verification_tasks=tasks)
    table = verification_task_table(tasks)
    report = tasks_section(tasks)
    proposal = build_industry_proposal(project)
    from industry_reader import task_brief
    assert task_brief(tasks) in report and table not in report
    assert all(task['task_id'] in report for task in tasks)
    assert verification_task_table(tasks, include_reference_index=False, reference_location='附录B候选来源索引') in proposal
    assert verification_task_table(tasks, reference_index_only=True) in proposal
    for task in tasks:
        assert task['task_id'] in proposal and task['completion'] in proposal
    assert re.findall(r'^## (\d+)\.', proposal, re.M) == [str(i) for i in range(1, 8)]
    main=table.split('\n\n候选核验编号清单：',1)[0]
    assert {len(line.split('|')) for line in main.splitlines()} == {8}
    assert '报价确认表' in proposal and '不生成未经报价确认的金额' in proposal


def test_closed_scope_and_resolved_scores_cannot_leave_stale_followups():
    old = verification_tasks({}, {'dimensions': [unknown()]}, [], SCOPE)
    current = {'dimensions': [unknown(score=42), unknown(name='资本热度与估值风险')]}
    _, tasks = finalize_synthesis('## 14. 综合评估\n旧\n## 16. 后续研究点\n旧', {}, current,
                                 [{'chapter': 8}, {'chapter': 12}], SCOPE)
    assert old and tasks == []
    proposal = build_industry_proposal(SimpleNamespace(title='研究', target_name='机器人',
                   industry_scope=SCOPE, industry_verification_tasks=tasks), risk_json=json.dumps(current))
    assert old[0]['task_id'] not in proposal and '尚无可定位候选' not in proposal


def test_deterministic_evaluation_does_not_restore_a_rejected_legal_claim():
    bad = fact(fact='欧盟AI Act对高风险系统违规最高罚7%全球营业额。',
               evidence_quote='欧盟AI Act对高风险系统违规最高罚7%全球营业额。', module='政策与监管',
               numeric_validation={'passed': True})
    safe = fact(evidence_id='E-222222222222', fact='机器人行业政策对适用主体提出标识要求。',
                evidence_quote='机器人行业政策对适用主体提出标识要求。', module='政策与监管')
    section = evaluation_inputs({'facts': [bad, safe]})
    assert EID not in section and safe['evidence_id'] in section
    assert '7%' not in section


def test_candidate_review_links_are_indexed_without_becoming_supporting_claims():
    task, = verification_tasks({'facts': [fact()]}, {'dimensions': [unknown()]}, [], SCOPE)
    report = '\n\n'.join(f'## {i}. 章节\n' for i in range(1, 16)) + tasks_section([task])
    indexed, diagnostic = append_evidence_index(report, {'facts': [fact()]}, [('章节', [])] * 16,
                                               {i: {'facts': []} for i in range(1, 17)})
    assert EID in diagnostic['chapter_evidence_ids'][16]
    assert 'https://research.example/report' in indexed and '不表示其已支持风险评分' in indexed
    assert not any('第16章引用了不属于本章' in issue for issue in delivery_errors(indexed, diagnostic, SCOPE))


def test_template_fallback_retains_current_risk_and_explicit_technical_gap():
    from research_workflow import ResearchWorkflow
    project = SimpleNamespace(title='机器人研究', target_name='机器人', target_type='industry',
                              industry_scope=SCOPE, industry_current_risk={'dimensions': [unknown()]})
    text = ResearchWorkflow.__new__(ResearchWorkflow)._fallback_proposal(project, '技术路线缺少同条件比较')
    assert '商业化与盈利模式风险' in text and '技术路线尚未形成同条件比较' in text
    assert '完成条件' in text and '999' not in text


def test_revalidation_preserves_the_rejected_attempt_and_never_restores_its_score():
    raw = {'dimensions': [{'name': '商业化与盈利模式风险', 'score': 42, 'level': 'medium',
                           'reason': '行业利润999亿元。', 'evidence_ids': [EID]}]}
    first = normalize_risk(raw, [fact()], SCOPE)
    second = normalize_risk(first, [fact()], SCOPE)
    a = next(r for r in first['dimensions'] if r['name'] == '商业化与盈利模式风险')
    b = next(r for r in second['dimensions'] if r['name'] == a['name'])
    assert a['unknown_cause'] == b['unknown_cause'] == 'unverified_reason_numbers'
    assert a['validation_diagnostic'] == b['validation_diagnostic']
    assert b['score'] is None and b['candidate_evidence_count'] == 1
    task = next(t for t in verification_tasks({'facts': [fact()]}, second, [], SCOPE) if t['topic'] == a['name'])
    assert task['task_type'] == 'assessment_validation'
    # Removing applicable material changes current support without erasing the
    # original failure; reintroducing it must not silently reinstate the score.
    no_facts = normalize_risk(second, [], SCOPE)
    lost = next(r for r in no_facts['dimensions'] if r['name'] == a['name'])
    assert lost['unknown_cause'] == 'no_applicable_evidence'
    assert lost['validation_diagnostic']['original_score'] == 42
    assert lost['validation_diagnostic']['admissible_evidence_ids'] == []
    restored = normalize_risk(no_facts, [fact()], SCOPE)
    restored_row = next(r for r in restored['dimensions'] if r['name'] == a['name'])
    assert restored['overall_score'] is None and restored_row['score'] is None
    assert restored_row['unknown_cause'] == 'reassessment_required'
    assert restored_row['validation_diagnostic']['rejection_cause'] == 'unverified_reason_numbers'


def test_many_review_links_keep_full_audit_and_disclose_a_bounded_reader_list():
    ids = ['E-'+f'{n:012X}' for n in range(24)]
    cards = [fact(evidence_id=eid) for eid in ids]
    risk = {'dimensions': [unknown(validation_diagnostic={'admissible_evidence_ids': ids})]}
    tasks = verification_tasks({'facts': cards}, risk, [], SCOPE)
    table = verification_task_table(tasks)
    assert tasks[0]['audit_review_evidence_ids'] == ids
    selected=tasks[0]['review_evidence_ids']
    assert len(selected)==6 and all(eid in table for eid in selected)
    assert '精选6/24' in table and '全量编号保留于关联审计' in table
    main, appendix = table.split('\n\n候选核验编号清单：', 1)
    assert {len(row.split('|')) for row in main.splitlines()} == {8}
    assert all(len(re.findall(r'E-[A-F0-9]{12}', row)) <= 8 for row in appendix.splitlines())
    from docx_exporter import markdown_to_docx_bytes
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    with ZipFile(io.BytesIO(markdown_to_docx_bytes(table, document_kind='industry_proposal'))) as package:
        assert package.testzip() is None
        body = ET.fromstring(package.read('word/document.xml'))
        tables = body.findall('.//w:tbl', ns)
        assert len(tables) == 2
        widths = [{len(row.findall('w:tc', ns)) for row in t.findall('w:tr', ns)} for t in tables]
        assert widths == [{6}, {2}]
        assert all(eid in ''.join(body.itertext()) for eid in selected)
