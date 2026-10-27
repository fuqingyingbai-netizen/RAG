"""A fuller admitted same-original card must survive the repair scope."""
import json
import pytest
from person_claim_repair import repair_once
from person_evidence import build_packages,validate_model_claims
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE


def fixture():
    rows=[{'fact':'林知远负责研发管理，具体任期未披露。','source_url':'https://fixture.invalid/a','identity_match':'confirmed'},
          {'fact':'林知远于2018年获聘为总裁，任期三年，负责公司研发管理。','source_url':'https://fixture.invalid/a','identity_match':'confirmed'},
          {'fact':'林知远于2020年参与业务管理。','source_url':'https://fixture.invalid/b','identity_match':'confirmed'}]
    p=build_packages({'facts':rows},'林知远',PERSON_REPORT_OUTLINE)['chapters'][5]
    p['writing_contract']='evidence_selection_v2'
    facts=p['research_facts'];short=next(f for f in facts if '未披露' in f['fact']);full=next(f for f in facts if '2018' in f['fact']);other=next(f for f in facts if '2020' in f['fact'])
    p['facts']=[short]
    answer=json.dumps({'claims':[{'analysis':'来源称其于2018年获聘为总裁，任期三年。','evidence_ids':[short['evidence_id']]}]},ensure_ascii=False)
    claims,reasons=validate_model_claims(answer,p)
    assert reasons
    return p,short,full,other,answer,claims,reasons


def test_same_original_full_card_is_available_and_validated():
    p,short,full,other,answer,claims,reasons=fixture();seen=[]
    def invoke(role,prompt,*args):
        packet=json.loads(prompt[prompt.index('{"material":'):]);cards=packet['material']['facts'];ids={f['evidence_id'] for f in cards}
        assert full['evidence_id'] in ids and other['evidence_id'] not in ids
        seen.append(packet)
        return json.dumps({'claims':[{'analysis':'来源载林知远于2018年获聘为总裁，任期三年。','evidence_ids':[full['evidence_id']]}]},ensure_ascii=False)
    final,errors,audit=repair_once(answer,p,{'facts':[short]},claims,reasons,invoke,None,validate_model_claims)
    assert seen and not errors and audit['status']=='corrected'
    assert final[0]['evidence_ids']==[full['evidence_id']]


def test_conserved_chapter_source_gets_original_card_even_with_other_url():
    p,short,full,other,answer,claims,reasons=fixture()
    prior={'analysis':'林知远于2020年参与业务管理。','evidence_ids':[other['evidence_id']]}
    def invoke(role,prompt,*args):
        cards=json.loads(prompt[prompt.index('{"material":'):])['material']['facts']
        assert next(f for f in cards if f['evidence_id']==other['evidence_id'])['fact']==other['fact']
        return json.dumps({'claims':[prior]},ensure_ascii=False)
    final,errors,audit=repair_once(answer,p,{'facts':[short],'prior_draft_analyses_not_evidence':[prior]},claims,reasons,invoke,None,validate_model_claims)
    assert not errors and final[0]['evidence_ids']==prior['evidence_ids']


def test_selected_full_card_reaches_fresh_semantic_review_without_passing_final_gate(monkeypatch):
    import person_content_acceptance as acceptance
    rows=[{'fact':'林知远负责研发管理，具体日期未披露。','source_url':'https://fixture.invalid/a','identity_match':'confirmed'},
          {'fact':'林知远于2018年开始负责公司研发管理。','source_url':'https://fixture.invalid/a','identity_match':'confirmed'}]
    p=build_packages({'facts':rows},'林知远',PERSON_REPORT_OUTLINE)['chapters'][5]
    p['writing_contract']='evidence_selection_v2'
    short=next(f for f in p['research_facts'] if '未披露' in f['fact']);full=next(f for f in p['research_facts'] if '2018' in f['fact'])
    p['facts']=[short]
    prior=[{'analysis':'林知远于2018年开始负责公司研发管理。','evidence_ids':[short['evidence_id']]}]
    answer=json.dumps({'claims':prior},ensure_ascii=False)
    current=[{'analysis':'来源载林知远负责研发管理。','evidence_ids':[short['evidence_id']]}]
    initial={'status':'pending_review','requests':1,'issues':['content_coverage_missing'],
        'items':[{'prior_index':0,'status':'missing','matched_claim_indices':[0],
                  'gaps':[{'prior_quote':prior[0]['analysis'],'evidence_ids':prior[0]['evidence_ids']}]}]}
    semantic=[]
    def invoke(role,prompt,*args):
        if '事项定向补写' in role:return answer
        if '核验修订' in role:return json.dumps({'claims':[{'analysis':full['fact'],'evidence_ids':[full['evidence_id']]}]},ensure_ascii=False)
        if '语义复核' in role:
            semantic.append(prompt)
            packet=json.loads(prompt.splitlines()[-1])
            source=packet['claims'][0]['sources'][0]
            assert source['evidence_id']==full['evidence_id'] and source['original']==full['fact']
            return json.dumps({'reviews':[{'claim_index':0,'verdict':'supported','issues':[],'reason':'具体任命与任期来自完整原文。','supporting_evidence_ids':[full['evidence_id']]}]},ensure_ascii=False)
        raise AssertionError(role)
    def final_review(*args):return {'status':'pending_review','requests':1,'items':[],'issues':['content_review_unavailable']}
    monkeypatch.setattr(acceptance,'check_coverage',final_review)
    result,errors,audit=acceptance._accept_once(p,current,prior,{'chapter':5,'facts':[short]},invoke,None,validate_model_claims,initial_review=initial)
    assert not audit.get('semantic_rejections'),audit.get('repair_semantic_review')
    assert semantic and errors and audit['status']=='pending_final_coverage'
    assert audit['selected_repair_sources_restored'][0]['evidence_id']==full['evidence_id']


@pytest.mark.parametrize('selection',['unknown','other_original','source_only'])
def test_scope_does_not_admit_unprovided_or_ineligible_cards(selection):
    p,short,full,other,answer,claims,reasons=fixture()
    if selection=='source_only':full['analysis_allowed']=False
    selected='E-NOT-PROVIDED' if selection=='unknown' else other['evidence_id'] if selection=='other_original' else full['evidence_id']
    def invoke(role,prompt,*args):
        cards=json.loads(prompt[prompt.index('{"material":'):])['material']['facts']
        assert selected not in {f['evidence_id'] for f in cards}
        return json.dumps({'claims':[{'analysis':'来源载林知远于2018年获聘为总裁，任期三年。','evidence_ids':[selected]}]},ensure_ascii=False)
    _,errors,audit=repair_once(answer,p,{'facts':[short]},claims,reasons,invoke,None,validate_model_claims)
    assert errors and audit['status']!='corrected'
