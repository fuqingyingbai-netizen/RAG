import json

from person_evidence import build_packages, validate_model_claims
from person_claim_repair import repair_once
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE
from person_chapter_research import peer_excerpts, exact_span
from person_text import folded
from person_records import definition_errors, personal_inference_errors


def test_holdings_in_two_undated_sources_do_not_prove_simultaneous_ownership():
    rows = [{'fact': '林知远夫妇持有甲公司40%股权。', 'subject': '林知远'},
            {'fact': '林知远夫妇持有乙公司60%股权。', 'subject': '林知远'}]
    assert 'simultaneous_ownership_period_not_supported' in definition_errors('其夫妇同时持有两家公司股权。', rows)
    assert 'comparison_subject_or_entity_mismatch' in definition_errors('两则信息的主体不同。', rows)
    assert 'legal_obligation_definition_not_supported' in definition_errors('两家公司法律实体独立。', rows)
    assert not definition_errors('材料未说明是否同时持有，不能据此认定法律实体独立。', rows)


def test_retirement_remarks_cannot_establish_prudent_mindset():
    assert personal_inference_errors('退休发言反映其对继任机制的审慎考量。')
    assert not personal_inference_errors('退休发言不足以反映其对继任机制的审慎考量。')


def test_repair_preserves_good_analysis_and_corrects_conditional_event_only():
    rows = [{'fact': '董事会提请股东大会授权，并在取得批准之同时授权林知远全权办理发行。',
             'source_url': 'https://filing.invalid/a', 'identity_match': 'confirmed'},
            {'fact': '林知远负责公司产品研发管理，具体项目结果另见披露。',
             'source_url': 'https://filing.invalid/b', 'identity_match': 'confirmed'}]
    package = build_packages({'facts': rows}, '林知远', PERSON_REPORT_OUTLINE)['chapters'][5]
    package['writing_contract'] = 'evidence_selection_v2'
    a, b = next(f for f in package['facts'] if '提请' in f['fact']), next(f for f in package['facts'] if '研发' in f['fact'])
    answer = json.dumps({'claims': [{'evidence_ids': [a['evidence_id']], 'analysis': '其被董事会授权办理发行。'},
                                   {'evidence_ids': [b['evidence_id']], 'analysis': '来源载明其负责研发管理，未披露具体项目结果。'}]}, ensure_ascii=False)
    claims, reasons = validate_model_claims(answer, package)
    calls = []
    def invoke(role, prompt, emit):
        calls.append(prompt)
        assert 'previous_analysis' not in prompt
        return json.dumps({'claims': [{'evidence_ids': [a['evidence_id']], 'analysis': '议案提请对其授权，取得股东大会批准后方可生效。'}]}, ensure_ascii=False)
    final, reasons, audit = repair_once(answer, package, {'facts': package['facts']}, claims, reasons, invoke, None, validate_model_claims)
    assert len(calls) == 1 and not reasons
    assert final[0]['analysis'] == claims[1]['analysis']
    assert audit['status'] == 'corrected' and audit['preserved_accepted_claims'] == 1


def test_chinese_variants_match_but_literal_source_is_preserved_and_owner_is_not_subject():
    text = '李書福先生，現任吉利控股董事會主席，曾負責汽車業務，其具體任期仍須核對。'
    peer = {'name': '李书福', 'company': '吉利'}
    assert folded('蔚來／李書福') == folded('蔚来/李书福')
    assert exact_span(text, text) == text
    assert peer_excerpts(text, peer) == [text]
    assert not peer_excerpts('彼现时亦为吉利汽车集团有限公司之董事长，该公司由股东李书福先生及其联系人士拥有。', peer)
