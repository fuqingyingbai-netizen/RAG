"""Positive and negative controls for bounded analysis edits; no real model calls."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from industry_analysis_repair import MAX_INPUT_CHARS, repair_analyses, repair_packet
from industry_fact_contracts import attach_contract, chapter_coverage, validate_analyses
from industry_passages import passage_issues
from industry_reasoning import completion_criteria, question_ledger, reasoning_snapshot
from report_agents.industry_report_agent import IndustryReportAgent
from test_industry_template_analysis import ANALYSIS, EID, SCOPE, chain, claim, fact


@pytest.mark.parametrize('tail', [
    '现有材料没有说明成本口径是否包含服务费用，无法判断可比性。',
    '现有材料没有说明如何划分统计范围，因此不能直接比较。',
    '现有材料没有解释为什么分层，也没有对应的经营数据。'])
def test_embedded_interrogatives_in_declarative_analysis_are_not_questions(tail):
    accepted, rejected = validate_analyses([claim(ANALYSIS + tail)], {'facts': [chain()]}, 2, [EID])
    assert accepted and not rejected


@pytest.mark.parametrize('body', ['如何判断机器人市场规模？', '是否存在机器人行业的进入壁垒', '用户提问：如何比较技术？'])
def test_actual_questions_still_cannot_be_propositions(body):
    assert 'question_not_assertion' in passage_issues(body, analysis=True)
    assert 'question_not_assertion' in passage_issues(body)


def test_deterministic_format_edits_preserve_prose_values_and_source():
    f = chain(); original = deepcopy(f)
    raw = claim('\n' + ANALYSIS[:33] + '\n' + ANALYSIS[33:] + f' [{EID}] ', evidence_ids=[EID, EID])
    accepted, rejected = validate_analyses([raw], {'facts': [f]}, 2, [EID])
    assert accepted and not rejected
    assert set(accepted[0]['format_normalization']) == {
        'whitespace_normalized', 'authorized_inline_citation_removed', 'duplicate_reference_removed'}
    assert accepted[0]['text'].replace(' ', '') == ANALYSIS
    assert f == original and raw['text'].startswith('\n')


@pytest.mark.parametrize('text,detail', [
    ('材料' * 1300, 'text_length_out_of_range'),
    (ANALYSIS + ' [E-FFFFFFFFFFFF]', 'text_contains_inline_evidence_id'),
    (ANALYSIS + ' https://invalid.example', 'text_contains_url'),
    (ANALYSIS + '<script>bad</script>', 'text_contains_markup')],ids=['oversized','wrong_id','url','markup'])
def test_rejections_always_retain_original_and_specific_diagnostic(text, detail):
    raw = claim(text)
    accepted, rejected = validate_analyses([raw], {'facts': [chain()]}, 2, [EID])
    assert not accepted
    assert rejected[0]['original_analysis'] == raw
    assert detail in [d['code'] for d in rejected[0]['details']]


def test_samples_are_comparison_background_without_upgrading_coverage_or_risk():
    f, body = fact('机器人市场参与者可以分为头部平台和初创企业。',
                   evidence_scope='representative_company', module='竞争格局与代表企业')
    f = attach_contract(f, SCOPE, body)
    rows = {r['question']: r for r in chapter_coverage({'facts': [f]}, 6, [EID])}
    assert rows['竞争机制与玩家分层']['status'] == 'background_only'
    assert rows['竞争机制与玩家分层']['evidence_ids'] == []
    analysis = claim('所引企业样本说明存在不同的玩家分层，但不能外推行业整体，也不能据此认定市场份额或集中度。',
                     question='竞争机制与玩家分层', claim_kind='comparison')
    assert validate_analyses([analysis], {'facts': [f]}, 6, [EID])[0]
    assert f['fact_contract']['risk_admitted'] is False


def test_explicit_scoped_limitation_is_kept_without_answering_missing_question():
    raw = claim('本章所引材料仅说明产业链分工，未提供核心部件的供给与依赖关系，无法判断实际瓶颈，仍需人工补充核验。',
                question='核心瓶颈', claim_kind='limitation')
    f = chain(); accepted, rejected = validate_analyses([raw], {'facts': [f]}, 2, [EID])
    assert accepted and not rejected
    row = next(q for q in question_ledger({'facts': [f]}, 2, [EID], accepted)['questions'] if q['question'] == '核心瓶颈')
    assert row['evidence_state'] == 'missing' and row['analysis_status'] == 'limitations_only'
    assert row['answer_verified'] is False
    bad = {**raw, 'text': raw['text'] + '整个行业不存在核心瓶颈。'}
    assert not validate_analyses([bad], {'facts': [f]}, 2, [EID])[0]


def run_repair(invoke, *, project=None, originals=None):
    package = {'facts': [chain()]}
    originals = originals or [claim(), claim(ANALYSIS + '市场规模达到999亿元。')]
    accepted, rejected = validate_analyses(originals, package, 2, [EID])
    before = deepcopy(accepted)
    project = project or SimpleNamespace()
    result = repair_analyses(project, package, 2, [EID], accepted, rejected,
        invoke, lambda *a, **k: None, None, '章节分析局部修复 Agent')
    assert accepted == before  # Passed paragraphs must never be edited in place.
    return result, before, project


def response(prompt, *, analysis=None, index=None, fingerprint=None):
    packet = json.loads(prompt.split('\n', 1)[1]); failed = packet['failed_analyses_not_evidence'][0]
    assert all('failed_analysis' not in card for card in packet['cards'].values())
    analysis = analysis or claim()
    analysis = {**analysis, 'claim_kind': 'conditional',
        'premises': [{'evidence_id': EID, 'quote': packet['cards'][EID]['statement']}],
        'reasoning': '所引材料仅说明分工关系，盈利与瓶颈仍需人工核验。'}
    return json.dumps({'request_fingerprint': fingerprint or packet['request_fingerprint'],
        'repairs': [{'index': failed['index'] if index is None else index,
                     'analysis': analysis}]}, ensure_ascii=False)


def test_one_local_repair_preserves_passed_paragraph_and_initial_audit():
    calls = []
    def invoke(role, prompt, trace):
        calls.append(role)
        return response(prompt)
    (accepted, rejected, diagnostic), passed, project = run_repair(invoke)
    assert len(calls) == 1 and len(accepted) == 1 and not rejected
    assert accepted[0] == passed[0]
    assert diagnostic['duplicate_repairs_omitted'] == [1]
    assert diagnostic['repaired'] == [1] and diagnostic['remaining'] == []
    assert '999' in diagnostic['initial_rejections'][0]['original_analysis']['text']
    assert diagnostic['input_chars'] <= MAX_INPUT_CHARS
    project.industry_statement_plans = {2: {'analysis_repair': diagnostic}}
    assert reasoning_snapshot(project)['analysis_repairs']['2']['attempted']


@pytest.mark.parametrize('change', ['stale_fingerprint', 'passed_index', 'changed_question', 'unauthorized_number', 'foreign_id'])
def test_repair_cannot_bypass_original_constraints_or_edit_passed_claim(change):
    def invoke(role, prompt, trace):
        kwargs = {}
        if change == 'stale_fingerprint': kwargs['fingerprint'] = 'wrong'
        if change == 'passed_index': kwargs['index'] = 0
        if change == 'changed_question': kwargs['analysis'] = claim(question='核心瓶颈')
        if change == 'unauthorized_number': kwargs['analysis'] = claim(ANALYSIS + '市场规模达到999亿元。')
        if change == 'foreign_id': kwargs['analysis'] = claim(evidence_ids=['E-FFFFFFFFFFFF'])
        return response(prompt, **kwargs)
    (accepted, rejected, diagnostic), passed, _ = run_repair(invoke)
    assert accepted == passed and rejected and not diagnostic['repaired']
    assert diagnostic['attempts'] == 1


def test_timeout_keeps_original_material_and_never_retries():
    calls = []
    def invoke(*args):
        calls.append(args)
        raise TimeoutError('simulated')
    (accepted, rejected, diagnostic), passed, _ = run_repair(invoke)
    assert len(calls) == 1 and accepted == passed and rejected
    assert diagnostic['error_type'] == 'TimeoutError'


def test_repair_budget_is_shared_by_chapters_and_zero_disables_calls(monkeypatch):
    calls = []
    monkeypatch.setenv('INDUSTRY_ANALYSIS_REPAIR_MAX_CALLS', '1')
    def invoke(role, prompt, trace):
        calls.append(role)
        return response(prompt)
    _, _, project = run_repair(invoke)
    project.industry_analysis_repair_budget['chapters'] = [7]  # Another chapter spent the shared budget.
    result, _, _ = run_repair(invoke, project=project)
    assert len(calls) == 1 and result[2]['status'] == 'request_budget_exhausted'
    monkeypatch.setenv('INDUSTRY_ANALYSIS_REPAIR_MAX_CALLS', '0')
    result, _, _ = run_repair(invoke)
    assert len(calls) == 1 and not result[2]['attempted']


def test_oversized_packet_is_skipped_whole_not_truncated():
    original = claim('材料' * 12000)
    _, rejected = validate_analyses([original], {'facts': [chain()]}, 2, [EID])
    packet, requested = repair_packet({'facts': [chain()]}, 2, [EID], rejected)
    assert not requested and len(json.dumps(packet, ensure_ascii=False)) <= MAX_INPUT_CHARS


def test_live_writer_keeps_good_analysis_and_revalidates_local_repair():
    calls = []
    def invoke(role, prompt, trace):
        calls.append(role)
        if '局部修复' in role:
            return response(prompt)
        return json.dumps({'evidence_ids': [EID], 'analyses': [claim(), claim(ANALYSIS + '市场规模达到999亿元。')]})
    project = SimpleNamespace(industry_statement_plans={}, industry_report_degradations=[])
    text = IndustryReportAgent()._write_statement_section(project, {'facts': [chain()]}, 2, '产业链', invoke, lambda *a, **k: None, None)
    assert len(calls) == 2 and '999' not in text and ANALYSIS in text
    assert project.industry_statement_plans[2]['analysis_repair']['repaired'] == [1]
    assert project.industry_report_degradations  # Never silently upgrade to final.


def test_task_criteria_match_screening_and_risk_questions():
    assert '筛选指标及判断条件' in completion_criteria('细分赛道与筛选标准')
    assert '发布机关及原始条款' not in completion_criteria('细分赛道与筛选标准')
    assert '风险作用对象与机制' in completion_criteria('行业经营与技术研发风险')
    assert '硬件及测试负载' not in completion_criteria('行业经营与技术研发风险')
    assert '发布机关及原始条款' in completion_criteria('标准、补贴与准入')


def test_unmeasured_latency_stays_readable_but_cannot_enter_summary_or_scoring():
    from industry_fact_contracts import chapter_admitted
    quote = '机器人云服务按请求自动扩容，将响应延迟降 低至毫秒级，促进规模化落地。'
    f, body = fact(quote, module='技术路线对比')
    f = attach_contract(f, SCOPE, body)
    assert f['fact_contract']['report_admitted']
    assert f['fact_contract']['source_role'] == 'performance_claim'
    assert not f['fact_contract']['risk_admitted'] and not chapter_admitted(f, 1)
    control, body = fact('机器人云端与边缘端的适用场景不同，需要分别比较部署条件。', module='技术路线对比')
    assert attach_contract(control, SCOPE, body)['fact_contract']['source_role'] != 'performance_claim'


def test_listed_company_cashflow_cannot_score_whole_industry():
    f, body = fact('上市公司回款速度加快，现金流压力有所缓解。', module='商业模式与盈利逻辑')
    f = attach_contract(f, SCOPE, body)
    assert f['fact_contract']['report_admitted'] and f['fact_contract']['sample_boundary']
    assert f['fact_contract']['risk_admitted'] is False


def test_repair_runtime_uses_dedicated_timeout_and_no_sdk_retries(monkeypatch):
    import research_workflow
    from research_workflow import ResearchWorkflow
    configured = []
    monkeypatch.setenv('ARK_API_KEY', 'synthetic-test-key')
    monkeypatch.setenv('MODEL', 'synthetic-test-model')
    monkeypatch.setenv('INDUSTRY_ANALYSIS_REPAIR_TIMEOUT_SECONDS', '999')
    def model(**kwargs):
        configured.append(kwargs)
        return SimpleNamespace(invoke=lambda messages: SimpleNamespace(content='{}'))
    monkeypatch.setattr(research_workflow, 'init_chat_model', model)
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    workflow._invoke_industry_report('章节分析局部修复 Agent - 产业链', 'synthetic input')
    assert configured[0]['timeout'] == 45 and configured[0]['max_retries'] == 0
    assert configured[0]['max_tokens'] == 2500
