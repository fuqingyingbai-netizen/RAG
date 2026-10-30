from person_risk_evidence import build_register
from person_evidence import normalize_person_risk
from types import SimpleNamespace


def fact(scope='person', **extra):
    return {'evidence_id': 'E-ONE', 'subject': '陈明', 'subject_scope': scope,
            'source_url': 'https://issuer.invalid/notice', 'fact': '来源记录',
            'observation': {'relations': ['legal']}, **extra}


def test_company_legal_statement_and_provider_failure_never_become_personal_severity():
    result = build_register([fact('affiliated_company')], platform_attempts=[
        {'provider': 'qcc', 'status': 'failed', 'reason': 'quota_exceeded'}])
    item = result['items'][0]
    assert item['subject_scope'] == 'affiliated_company'
    assert item['risk_severity'] == 'not_assessed' and item['risk_score'] is None
    assert item['responsibility'] == 'not_determined'
    assert result['overall_score'] is None
    assert result['collection_outcomes'][0]['reason'] == 'quota_exceeded'


def test_other_people_and_peer_litigation_do_not_enter_target_risk_register():
    assert not build_register([fact('other_person'), fact('comparison_person')])['items']


def test_named_negative_evaluation_is_an_opinion_even_if_reliable_source_is_present():
    result = build_register([fact(opinion_only=True, source_grade='A',
        feedback_record={'kind': 'attributed_opinion', 'evaluator': '顾海'},
        observation={'relations': []})])
    item = result['items'][0]
    assert item['domain'] == 'named_or_attributed_evaluation_not_fact'
    assert item['evidence_reliability']['source_grade'] == 'A'
    assert item['evidence_reliability']['independent_verification'] == 'pending'
    assert item['risk_severity'] == 'not_assessed'


def test_no_material_does_not_generate_zero_risk_or_a_fabricated_credit_score():
    result = build_register([], platform_attempts=[{'status': 'no_citable_record'}])
    assert result['overall_severity'] == 'not_assessed' and result['overall_score'] is None
    assert result['items'] == []
    assert result['policy']['weights'] is None and result['policy']['score_formula'] is None


def test_multiple_source_conflict_keeps_both_evidence_chains_without_selecting_a_winner():
    result = build_register([fact(), {**fact(), 'evidence_id': 'E-TWO'}], conflicts=[
        {'claim_key': 'same_field', 'evidence_ids': ['E-ONE', 'E-TWO'], 'status': 'unresolved'}])
    item = result['items'][-1]
    assert item['evidence_ids'] == ['E-ONE', 'E-TWO']
    assert item['source_conflict']['status'] == 'unresolved'
    assert item['responsibility'] == 'not_determined'


def test_production_risk_admission_rechecks_source_identity_instead_of_trusting_cleaned_label():
    text = '陈明的同名人物涉及诉讼，机构与目标不符。'
    src = SimpleNamespace(url='https://issuer.invalid/namesake', content=text,
                           source_metadata={'identity_status': 'quarantined'})
    result = normalize_person_risk({'facts': [{'fact': text, 'source_url': src.url,
        'identity_match': 'confirmed', 'identity_confidence': 'high'}]}, target='陈明', sources=[src])
    assert not result['source_signals']
    assert result['rejected_risk_leads'][0]['reason'] == 'identity_quarantine'
    assert result['overall_score'] is None
