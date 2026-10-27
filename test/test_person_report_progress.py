import copy
import pytest
from person_replay_state import restore_chapter_state,restore_research_pool


def fixture():
    a={'evidence_id':'E-PSTATEONE','fact':'林知远介绍工程师文化。','source_url':'https://fixture.invalid/one',
        'subject':'林知远','subject_scope':'person','claim_type':'attributed_statement'}
    b={**a,'evidence_id':'E-PSTATETWO','fact':'林知远表示将继续研发。','source_url':'https://fixture.invalid/two'}
    claim={'analysis':a['fact'],'evidence_ids':[a['evidence_id']]}
    package={'facts':[a],'research_facts':[dict(a,analysis_allowed=True)]}
    previous={'facts':[a],'research_facts':[a,b],
        'required_source_displays':[{'evidence_id':b['evidence_id'],'quote':'继续研发'}]}
    diagnostic={'content_acceptance':{'last_validated_candidate':[claim],
        'material_diagnosis':{'status':'pending','rows':[{'evidence_id':b['evidence_id'],'disposition':'pending'}]}}}
    return package,previous,diagnostic,[claim],[a,b]


def test_full_report_progress_keeps_research_literals_and_pending_status():
    p,old,d,claims,facts=fixture();proof=restore_chapter_state(p,old,d,claims,facts)
    assert {f['evidence_id'] for f in p['research_facts']}=={f['evidence_id'] for f in facts}
    assert p['required_source_displays']==old['required_source_displays']
    assert p['material_diagnosis_checkpoint']['status']=='pending'
    assert proof['material_checkpoint_candidate_bound']


@pytest.mark.parametrize('field,value',[('fact','另一段原文'),('source_url','https://different.invalid'),('subject','其他人'),('subject_scope','company')])
def test_changed_original_record_is_not_restored(field,value):
    p,old,d,claims,facts=fixture();old=copy.deepcopy(old);old['research_facts'][1][field]=value
    with pytest.raises(ValueError,match='report_research_source_mismatch'):
        restore_chapter_state(p,old,d,claims,facts)


def test_changed_draft_cannot_inherit_material_review():
    p,old,d,claims,facts=fixture();claims=[{**claims[0],'analysis':'更改的正文。'}]
    proof=restore_chapter_state(p,old,d,claims,facts)
    assert not proof['material_checkpoint_candidate_bound'] and 'material_diagnosis_checkpoint' not in p


def test_old_permission_cannot_promote_affiliated_company_to_person():
    p,old,d,claims,facts=fixture();facts[1].update(subject='恒川公司',subject_scope='affiliated_company',claim_type='person_company_record')
    old['research_facts'][1]={**facts[1],'analysis_allowed':True}
    restore_research_pool(p,old['research_facts'],facts)
    assert not p['research_facts'][-1]['analysis_allowed']


def test_unknown_old_record_cannot_be_added_to_the_current_research_pool():
    p,old,d,claims,facts=fixture();old['research_facts'].append({**facts[1],'evidence_id':'E-PUNADMITTED'})
    with pytest.raises(ValueError,match='report_research_source_mismatch'):
        restore_research_pool(p,old['research_facts'],facts)
