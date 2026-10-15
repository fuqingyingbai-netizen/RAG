"""Scoring trust is not citation validity; fixtures require no network or database."""
import json
from types import SimpleNamespace

from industry_research import normalize_risk, unknown_risk, package_risk_evidence, risk_level
from industry_risk import scoring_rubric, risk_support_markdown
from research_workflow import ResearchWorkflow

SCOPE = {'capital_market': 'none'}


def card(eid='E-123456ABCDEF', **updates):
    return {'evidence_id': eid, 'module': '政策与监管', 'fact': '机器人行业监管准入规定已生效。',
            'scope_match': 'in_scope', 'evidence_scope': 'industry_level', 'claim_type': 'qualitative',
            'source_url': 'https://regulator.gov.cn/rule',
            'provenance': {'locator': {'status': 'verified'}}, **updates}


def score(f, **updates):
    return {'name': '政策与监管风险', 'score': 30, 'level': 'low',
            'reason': '已生效的规定带来合规义务。', 'evidence_ids': [f['evidence_id']], **updates}


def checked(facts=None, row=None):
    f = card()
    return normalize_risk({'dimensions': [row or score(f)]}, facts if facts is not None else [f], SCOPE)


def test_valid_reference_is_neither_calibration_nor_probability():
    result = checked()
    row = result['dimensions'][0]
    assert row['score'] == 30
    assert row['assessment_confidence']['status'] == 'not_calibrated'
    assert row['assessment_confidence']['probability'] is None
    assert row['evidence_support']['metric_coverage_ratio'] == 1
    assert result['overall_score'] is None  # Other enabled dimensions remain unknown.
    assert result['risk_transparency']['calibration_status'] == 'not_calibrated'


def test_duplicate_cards_do_not_inflate_coverage_or_documents():
    f = card()
    support = checked([f, f.copy()])['dimensions'][0]['evidence_support']
    assert support['applicable_fact_count'] == support['cited_fact_count'] == 1
    assert support['cited_document_count'] == 1


def test_source_quotes_and_samples_do_not_become_verified_metrics():
    excerpt = card(claim_type='source_excerpt')
    sample = card('E-AAAAAAAAAAAA', evidence_scope='representative_company')
    quarantined = card('E-BBBBBBBBBBBB', eligible_for_report=False)
    row = checked([excerpt, sample, quarantined])['dimensions'][0]
    assert row['score'] == 30
    support = row['evidence_support']
    assert support['applicable_fact_count'] == 1
    assert support['verified_metric_count'] == 0
    assert support['requirements'][0]['status'] == 'candidate'


def test_model_support_and_confidence_claims_are_overwritten():
    row = score(card(), evidence_support={'metric_coverage_ratio': 1},
                assessment_confidence={'status': 'high', 'probability': .99})
    result = checked([card(provenance={})], row)['dimensions'][0]
    assert result['evidence_support']['located_cited_fact_count'] == 0
    assert result['evidence_support']['metric_coverage_ratio'] == 0
    assert result['assessment_confidence']['probability'] is None


def test_abstention_can_have_coverage_without_having_a_score():
    result = checked(row=score(card(), score=None, level='unknown'))
    row = result['dimensions'][0]
    assert row['assessment_status'] == 'unknown'
    assert row['evidence_support']['verified_metric_count'] == 1
    assert row['evidence_support']['cited_fact_count'] == 0
    assert row['score'] is None


def test_capital_disabled_does_not_add_requirement_or_dimension():
    rubric = scoring_rubric(SCOPE)
    assert all('资本' not in row['name'] for row in rubric['dimensions'])
    result = checked([card(), card('E-AAAAAAAAAAAA', module='投融资与资本市场')])
    assert all(r['id'] != 'capital' for row in result['dimensions'] for r in row['evidence_support']['requirements'])


def test_multiple_cards_from_same_document_do_not_prove_corroboration():
    facts = [card(), card('E-AAAAAAAAAAAA')]
    result = checked(facts, score(card(), evidence_ids=[f['evidence_id'] for f in facts]))
    support = result['dimensions'][0]['evidence_support']
    assert support['cited_fact_count'] == 2 and support['cited_document_count'] == 1
    assert '独立' in support['limitations'][1]


def test_unknown_fallback_has_methodology_without_invented_support():
    result = unknown_risk(scope=SCOPE)
    assert result['risk_transparency']['overall_score'] is None
    assert all(r['evidence_support']['applicable_fact_count'] == 0 for r in result['dimensions'])
    assert '尚未' in result['risk_transparency']['notice']


def test_rubric_is_versioned_and_copy_safe():
    rubric = scoring_rubric(SCOPE)
    rubric['bands'][0]['range'][0] = 99
    assert scoring_rubric(SCOPE)['bands'][0]['range'][0] == 0
    assert rubric['calibration_status'] == 'not_calibrated'
    assert all(row['factors'] for row in rubric['dimensions'])


def test_rubric_boundaries_match_actual_decimal_score_levels():
    for value in (0, 39.9, 40, 69.9, 70, 84.9, 85, 100):
        band = next(b for b in scoring_rubric()['bands'] if b['range'][0] <= value
                    and (value <= b['range'][1] if b['upper_inclusive'] else value < b['range'][1]))
        assert risk_level(value) == band['level']


def test_verified_numeric_support_retains_forecast_nature_separately():
    f = card(module='市场规模与增长', fact='预计2027年机器人行业市场规模达到100亿元。',
             numeric_context={'metric':'市场规模', 'value':'100', 'unit':'亿元', 'geography':'中国',
                              'period':'2027', 'definition':'机器人行业市场规模', 'is_forecast':True},
             numeric_validation={'passed':True})
    row = score(f, name='市场增长与需求风险', reason='预测显示需求潜力，兑现仍有不确定性。')
    result = checked([f], row)['dimensions'][1]
    assert result['evidence_support']['validated_numeric_fact_count'] == 1
    assert result['evidence_support']['forecast_numeric_fact_count'] == 1
    assert result['assessment_confidence']['probability'] is None


def test_support_statistics_never_become_writer_evidence():
    result = checked()
    _, package = package_risk_evidence({'facts': [card()]}, {'facts': [card()]}, result, True)
    assert '尚未' in package['scoring_caveat']
    assert all('evidence_support' not in row and 'assessment_confidence' not in row for row in package['dimensions'])


def test_repair_refreshes_support_after_acceptance(monkeypatch):
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    f = card()
    initial = checked(row=score(f, reason='参考 E-AAAAAAAAAAAA'))
    monkeypatch.setattr(workflow, '_invoke_industry_risk', lambda *a, **k: json.dumps({'dimensions': [score(f)]}))
    payload = {'facts': [f], 'dimension_evidence_ids': {'政策与监管风险': [f['evidence_id']]}}
    result = workflow._repair_industry_risk(initial, payload, [f], SCOPE)
    assert result['risk_transparency']['dimensions'][0]['score'] == 30
    assert result['dimensions'][0]['evidence_support']['cited_fact_count'] == 1
    assert result['validation_diagnostics']['repair']['repaired_dimensions'] == ['政策与监管风险']


def test_invalid_primary_response_keeps_retained_support(monkeypatch):
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    f = card()
    prompts = []
    def invoke(*args, **kwargs):
        prompts.append(args[1])
        return 'bad json'
    monkeypatch.setattr(workflow, '_risk_evidence_payload', lambda *a, **k: json.dumps({'facts': [f]}))
    monkeypatch.setattr(workflow, '_invoke_industry_risk', invoke)
    project = SimpleNamespace(target_type='industry', title='测试', target_name='机器人', industry='机器人', industry_scope=SCOPE)
    result = json.loads(workflow.assess_risk(project, json.dumps({'facts': [f]})))
    assert result['dimensions'][0]['evidence_support']['applicable_fact_count'] == 1
    assert result['overall_score'] is None
    assert 'industry-risk-rubric-v1' in prompts[0]


def test_delivery_metadata_and_quality_diagnostic_use_current_risk(monkeypatch):
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = SimpleNamespace(target_type='industry', title='测试', target_name='机器人', industry_scope=SCOPE)
    monkeypatch.setattr(workflow, '_validate_delivery_report', lambda *a: None)
    report, meta = workflow._prepare_industry_delivery(project, '## 1. 摘要\n事实', json.dumps(checked()))
    assert meta['risk_transparency']['dimensions'][0]['score'] == 30
    assert '**风险评分说明**' in report and '尚未经过人工标注' in report
    reexported, _ = workflow._prepare_industry_delivery(project, report, json.dumps(checked()))
    assert reexported.count('**风险评分说明**') == 1
    assert reexported.count('**待人工复核稿**') == 1
    diagnostic = workflow._build_report_quality_diagnostic(project, '', '需要复核')
    assert '风险评分与证据支持' in diagnostic and '尚未校准' in diagnostic
    _, updated = workflow._prepare_industry_delivery(project, '', json.dumps(unknown_risk(scope=SCOPE)))
    assert updated['risk_transparency']['dimensions'][0]['score'] is None
    assert '| 政策与监管风险 | 未评估 |' in risk_support_markdown(updated['risk_transparency'])
