import json

from person_citations import canonical_reference
from person_evidence import build_packages, validate_model_claims
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE


def test_only_unique_short_tail_omission_in_current_inputs_can_be_completed():
    key = 'E-PABC12345678901'
    assert canonical_reference(key[:-1], [key]) == key
    assert canonical_reference(key.lower(), [key]) == key
    assert canonical_reference(key[:-1], [key, key[:-1]+'9']) == key[:-1]
    assert canonical_reference(key[:-3], [key]) == key[:-3]
    assert canonical_reference('E-POUTSIDE123456', [key]) == 'E-POUTSIDE123456'


def test_corrected_id_remains_source_bound_and_is_auditable():
    package = build_packages({'facts': [{'fact': '林知远于2009年毕业于远山大学，获得硕士学位。', 'source_url': 'https://filing.invalid/a', 'identity_match': 'confirmed'}]}, '林知远', PERSON_REPORT_OUTLINE)['chapters'][2]
    package['writing_contract'] = 'evidence_selection_v2'
    key = package['facts'][0]['evidence_id']
    rows, errors = validate_model_claims(json.dumps({'claims': [{'evidence_ids': [key[:-1]], 'analysis': '来源列明教育经历，其他阶段资料仍待核对。'}]}, ensure_ascii=False), package)
    assert not errors and rows[0]['evidence_ids'] == [key]
    assert rows[0]['citation_identifier_corrections'] == [{'returned': key[:-1], 'canonical': key}]
    rows, errors = validate_model_claims(json.dumps({'claims': [{'evidence_ids': [], 'analysis': ''}]}), package)
    assert not rows and not errors
    assert validate_model_claims(json.dumps({'claims': [{'evidence_ids': [], 'analysis': '无来源的新判断'}]}), package)[1] == ['unknown_or_missing_evidence_id']
