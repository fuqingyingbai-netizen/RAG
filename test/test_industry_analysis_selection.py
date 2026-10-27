"""Recover formatting-only failures without relaxing evidence or selection caps."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from industry_analysis import complete_plan
from industry_analysis_repair import repair_analyses
from industry_fact_contracts import normalize_analysis, validate_analyses, chapter_coverage
from report_agents.industry_report_agent import IndustryReportAgent
from test_industry_template_analysis import ANALYSIS, EID, SCOPE, chain, claim


@pytest.mark.parametrize('marker', [
    EID, '('+EID+')', '（'+EID+'）', '['+EID+']', '【'+EID+'】', '`'+EID+'`',
    '('+EID+'、'+EID+')', EID+'，'+EID,
])
def test_authorized_prose_citation_is_not_a_reason_to_lose_valid_analysis(marker):
    f = chain(); before = deepcopy(f)
    original = claim(ANALYSIS + ' ' + marker)
    accepted, rejected = validate_analyses([original], {'facts': [f]}, 2, [EID])
    assert len(accepted) == 1 and not rejected
    assert accepted[0]['text'] == ANALYSIS
    assert accepted[0]['evidence_ids'] == [EID]
    assert accepted[0]['entailment_status'] == 'not_evaluated'
    assert 'authorized_inline_citation_removed' in accepted[0]['format_normalization']
    assert original['text'].endswith(marker) and f == before


@pytest.mark.parametrize('marker', [
    'E-FFFFFFFFFFFF', '(E-FFFFFFFFFFFF)', EID+'_other', 'prefix_'+EID,
    'https://source.example/'+EID, 'https://source.example/?id='+EID,
    '/archive/'+EID, 'document:'+EID,
])
def test_unknown_ids_identifier_fragments_and_urls_cannot_be_hidden_by_normalization(marker):
    original = claim(ANALYSIS + ' ' + marker)
    checked, _ = normalize_analysis(original, [EID])
    assert marker in checked['text']
    accepted, rejected = validate_analyses([original], {'facts': [chain()]}, 2, [EID])
    assert not accepted and rejected[0]['original_analysis'] == original


def test_only_the_reference_field_and_the_actual_packet_can_authorize_a_marker():
    other = 'E-222222222222'
    # An ID in the text cannot silently add itself to the separate reference list.
    accepted, rejected = validate_analyses([claim(ANALYSIS+' '+other)], {'facts': [chain()]}, 2, [EID])
    assert not accepted and 'invalid_analysis_text' in rejected[0]['issues']
    # Nor can an explicit reference authorize a card absent from this packet.
    checked, _ = normalize_analysis(claim(ANALYSIS+' '+other, evidence_ids=[other]), [EID])
    assert other in checked['text']


def test_citation_formatting_does_not_remove_an_unlicensed_value():
    original = claim(ANALYSIS+' '+EID+'。市场规模达到999亿元。')
    accepted, rejected = validate_analyses([original], {'facts': [chain()]}, 2, [EID])
    assert not accepted and 'analysis_unauthorized_number' in rejected[0]['issues']
    assert '999亿元' in rejected[0]['normalized_analysis']['text']
    assert rejected[0]['original_analysis'] == original


def selection_case():
    preferred = chain(); preferred['quality_score'] = 10
    others = []
    for i in range(8):
        f = deepcopy(preferred)
        f['evidence_id'] = 'E-'+f'{i+2:012X}'
        f['quality_score'] = 100+i
        others.append(f)
    package = {'facts': others + [preferred], 'industry_scope': SCOPE}
    # The ninth card is a coverage candidate, but is not needed to preserve
    # coverage of the same question. Old ordering displaced a valid premise.
    ids = [f['evidence_id'] for f in others[:7]] + [EID]
    return package, ids


def test_selection_preserves_valid_premises_and_still_reserves_question_coverage():
    package, ids = selection_case(); before = deepcopy(package)
    valid, errors = validate_analyses([claim()], package, 2, ids)
    assert valid and not errors
    assert EID not in complete_plan(package, 2, ids)  # Reproduce the saved failure mechanism.
    selected = complete_plan(package, 2, ids, valid)
    assert len(selected) <= 8 and EID in selected
    assert validate_analyses([claim()], package, 2, selected)[0]
    old_covered = {q['question'] for q in chapter_coverage(package, 2, complete_plan(package, 2, ids)) if q['evidence_ids']}
    new_covered = {q['question'] for q in chapter_coverage(package, 2, selected) if q['evidence_ids']}
    assert old_covered <= new_covered and package == before


@pytest.mark.parametrize('bad_number', [False, True])
def test_writer_only_prioritizes_already_rule_checked_premises(monkeypatch, bad_number):
    monkeypatch.setenv('INDUSTRY_ANALYSIS_REPAIR_MAX_CALLS', '0')
    package, ids = selection_case()
    proposed = claim(ANALYSIS+('市场规模达到999亿元。' if bad_number else ' '+EID))
    project = SimpleNamespace(industry_statement_plans={}, industry_report_degradations=[])
    calls = []
    def invoke(role, prompt, trace):
        calls.append(role)
        return json.dumps({'evidence_ids': ids, 'analyses': [proposed]}, ensure_ascii=False)
    report = IndustryReportAgent()._write_statement_section(project, package, 2, '产业链', invoke, lambda *a, **k: None, None)
    plan = project.industry_statement_plans[2]
    assert len(calls) == 1 and len(plan['evidence_ids']) <= 8
    if bad_number:
        assert not plan['analysis_claims'] and not plan['selection_alignment']['rule_checked_premise_ids']
        assert '999' not in report
    else:
        assert plan['analysis_claims'] and EID in plan['evidence_ids'] and ANALYSIS in report
        assert plan['selection_alignment']['rule_checked_premise_ids'] == [EID]
        assert not plan['selection_alignment']['premise_ids_not_retained']


class SyntheticTransportTimeout(TimeoutError):
    pass


@pytest.mark.parametrize('role', ['章节分析局部修复 Agent - 产业链', '行业阶段性综合 Agent'])
def test_bounded_caller_sees_transport_timeout_instead_of_empty_json(monkeypatch, role):
    import research_workflow
    monkeypatch.setenv('ARK_API_KEY', 'synthetic-test-key')
    monkeypatch.setenv('MODEL', 'synthetic-test-model')
    calls = []
    def invoke(messages):
        calls.append(messages)
        raise SyntheticTransportTimeout('synthetic timeout')
    monkeypatch.setattr(research_workflow, 'init_chat_model', lambda **kwargs: SimpleNamespace(invoke=invoke))
    workflow = research_workflow.ResearchWorkflow.__new__(research_workflow.ResearchWorkflow)
    with pytest.raises(SyntheticTransportTimeout):
        workflow._invoke_industry_report(role, 'synthetic input')
    assert len(calls) == 1


def test_repair_keeps_real_failure_type_and_does_not_repeat_the_request():
    package = {'facts': [chain()]}
    proposed = claim(ANALYSIS+'市场规模达到999亿元。')
    valid, rejected = validate_analyses([claim(), proposed], package, 2, [EID])
    before = deepcopy(valid)
    calls = []
    def invoke(*args):
        calls.append(args)
        raise SyntheticTransportTimeout('synthetic timeout')
    project = SimpleNamespace()
    accepted, failures, diagnostic = repair_analyses(project, package, 2, [EID], valid, rejected,
        invoke, lambda *a, **k: None, None, '章节分析局部修复 Agent - 产业链')
    assert accepted == before and failures == rejected
    assert diagnostic['error_type'] == 'SyntheticTransportTimeout' and diagnostic['attempts'] == 1
    assert len(calls) == 1
