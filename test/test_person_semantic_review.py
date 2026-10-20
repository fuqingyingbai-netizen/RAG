import json

from person_semantic_review import review_analyses


def test_role_fact_does_not_license_final_control_even_with_real_citation():
    fact = {'evidence_id': 'E-PTEST123456', 'fact': '林知远负责审批本次项目预算，授权范围以具体议案为限。', 'source_url': 'https://filing.invalid/a'}
    claim = {'evidence_ids': [fact['evidence_id']], 'analysis': '该人物拥有公司最终决策权。'}
    def reviewer(*a):
        return json.dumps({'reviews': [{'claim_index': 0, 'verdict': 'unsupported', 'reason': '项目预算审批范围不能扩张为公司最终决策权。'}]}, ensure_ascii=False)
    result, reasons, audit = review_analyses(11, '治理', [fact], [claim], reviewer)
    assert not result[0]['analysis'] and reasons == ['semantic_support_missing']
    assert audit['claims'][0]['verdict'] == 'unsupported'


def test_positive_semantic_verdict_requires_literal_quotes_for_all_citations():
    facts = [{'evidence_id': 'E-PTEST123456', 'fact': '林知远任董事，任期以披露文件对应历史时期为限。', 'source_url': 'https://filing.invalid/a'},
             {'evidence_id': 'E-PTEST234567', 'fact': '林知远任总裁，历史职责为研发管理，尚缺当前任期。', 'source_url': 'https://filing.invalid/b'}]
    claims = [{'evidence_ids': [f['evidence_id'] for f in facts], 'analysis': '来源列出董事及总裁角色，尚缺当前任期依据。'}]
    def reviewer(*a):
        return json.dumps({'reviews': [{'claim_index': 0, 'verdict': 'supported', 'support_quotes': [
            {'evidence_id': facts[0]['evidence_id'], 'quote': facts[0]['fact']}]}]})
    result, reasons, _ = review_analyses(2, '履历', facts, claims, reviewer)
    assert reasons == ['semantic_review_incomplete'] and not result[0]['analysis']


def test_supported_review_keeps_source_bound_analysis_as_draft():
    fact = {'evidence_id': 'E-PTEST123456', 'fact': '林知远任董事，任期以披露文件对应历史时期为限。', 'source_url': 'https://filing.invalid/a'}
    claim = {'evidence_ids': [fact['evidence_id']], 'analysis': '来源列明历史董事角色，不能据此确认现任。'}
    review = {'reviews': [{'claim_index': 0, 'verdict': 'supported', 'support_quotes': [{'evidence_id': fact['evidence_id'], 'quote': fact['fact']}]}]}
    result, reasons, audit = review_analyses(2, '履历', [fact], [claim], lambda *a: json.dumps(review))
    assert not reasons and result[0]['analysis'] == claim['analysis']
    assert audit['status'] == 'reviewed_sources_not_independent_verification'


def test_review_source_selection_keeps_original_text_without_model_copying_it():
    fact = {'evidence_id': 'E-PTEST123456', 'fact': '林知远任董事，任期以披露文件对应历史时期为限。', 'source_url': 'https://filing.invalid/a'}
    claim = {'evidence_ids': [fact['evidence_id']], 'analysis': '来源披露的是历史董事角色，缺少当前任期依据。'}
    review = {'reviews': [{'claim_index': 0, 'verdict': 'supported', 'supporting_evidence_ids': [fact['evidence_id']]}]}
    result, reasons, audit = review_analyses(2, '履历', [fact], [claim], lambda *a: json.dumps(review))
    assert not reasons and result[0]['analysis']
    assert audit['claims'][0]['support_quotes'] == [{'evidence_id': fact['evidence_id'], 'quote': fact['fact']}]


def test_reviewer_cannot_override_cutoff_with_its_training_year():
    fact = {'evidence_id': 'E-PTEST123456', 'fact': '林知远于2026年6月公开说明产品计划，实际结果仍需核对。', 'source_url': 'https://filing.invalid/a'}
    claim = {'evidence_ids': [fact['evidence_id']], 'analysis': '来源记载一次公开说明，尚未披露结果。'}
    answer = {'reviews': [{'claim_index': 0, 'verdict': 'unsupported', 'reason': '当前为2024年，2026年日期不真实。'}]}
    result, reasons, audit = review_analyses(3, '观察', [fact], [claim], lambda *a: json.dumps(answer), as_of_date='2026-10-20')
    assert reasons == ['semantic_review_incomplete']
    assert audit['claims'][0]['verdict'] == 'invalid_time_context'
