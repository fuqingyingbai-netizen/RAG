"""Offline state-equivalence regressions, not live model results."""
import copy,json,pytest
from person_material_accounting import diagnose_material
from person_replay_state import restore_chapter_state


def fixture(target='陈安'):
    base={'subject':target,'subject_scope':'person','claim_type':'attributed_statement','analysis_allowed':True,'temporal_conflict':False}
    facts=[{**base,'evidence_id':'E-PSTATEA','fact':target+'于2018年主持会议。','source_url':'https://fixture.invalid/a'},
           {**base,'evidence_id':'E-PSTATEB','fact':target+'于2018年主持会议。','source_url':'https://fixture.invalid/b'},
           {**base,'evidence_id':'E-PSTATEC','fact':target+'于2019年监督项目。','source_url':'https://fixture.invalid/c'}]
    claims=[{'analysis':facts[0]['fact'],'evidence_ids':['E-PSTATEB','E-PSTATEA']}]
    p={'chapter':5,'title':'治理','task':'核对治理行为。','facts':facts,'research_facts':facts,
       'required_source_displays':[{'evidence_id':'E-PSTATEC','quote':facts[2]['fact']}],
       'literal_material_display_proposed':True}
    seen=[]
    def model(role,prompt,*args):
        d=json.loads(prompt.splitlines()[-1]);seen.extend(f['evidence_id'] for f in d['facts'])
        return json.dumps({'material_reviews':[{'evidence_id':f['evidence_id'],
            'disposition':'source_display' if f['evidence_id']=='E-PSTATEC' else 'analysis',
            'matched_claim_indices':[] if f['evidence_id']=='E-PSTATEC' else [0],
            'reason':'实际逐字片段保留监督日期与行为。' if f['evidence_id']=='E-PSTATEC' else '正文保留主持日期与行为并引用本条。'} for f in d['facts']]})
    initial=diagnose_material(p,claims,model,None)
    assert initial['status']=='passed'
    previous=copy.deepcopy(p);previous.pop('literal_material_display_proposed')
    published=[{**claims[0],'evidence_ids':sorted(claims[0]['evidence_ids'])}]
    current=copy.deepcopy(previous);diagnostic={'content_acceptance':{'last_validated_candidate':claims,'material_diagnosis':initial}}
    restore_chapter_state(current,previous,diagnostic,published,current['facts'])
    seen.clear()
    return current,published,model,seen,initial


@pytest.mark.parametrize('target',['陈安','欧阳清和','Alex Morgan'])
def test_citation_order_and_lost_literal_flag_preserve_the_actual_bound_review(target):
    p,claims,model,seen,original=fixture(target)
    result=diagnose_material(p,claims,model,None,p['material_diagnosis_checkpoint'])
    assert p['literal_material_display_proposed'] is True
    assert result['status']=='passed' and not seen and result['requests']==0
    assert result['citation_order_context_reused']
    assert result['rows']==original['rows']


@pytest.mark.parametrize('change',['task','draft','source_text','source_url','source_actor','source_scope','citation_set'])
def test_a_changed_meaningful_context_never_reuses_a_completed_review(change):
    p,claims,model,seen,_=fixture()
    if change=='task':p['task']='核对另一项责任。'
    elif change=='draft':claims[0]['analysis']='陈安于2019年主持会议。'
    elif change=='citation_set':claims[0]['evidence_ids']=['E-PSTATEA']
    else:
        field={'source_text':'fact','source_url':'source_url','source_actor':'subject','source_scope':'subject_scope'}[change]
        p['research_facts'][0][field]={'fact':'另一条原文。','source_url':'https://fixture.invalid/new','subject':'另一个人','subject_scope':'affiliated_company'}[field]
    result=diagnose_material(p,claims,model,None,p['material_diagnosis_checkpoint'])
    assert seen and not result['citation_order_context_reused']


def test_pending_row_is_still_reviewed_after_order_only_restoration():
    p,claims,model,seen,_=fixture();prior=p['material_diagnosis_checkpoint']
    prior['rows']=[{**r,'disposition':'pending'} if r['evidence_id']=='E-PSTATEC' else r for r in prior['rows']]
    result=diagnose_material(p,claims,model,None,prior)
    assert seen==['E-PSTATEC'] and result['status']=='passed'


def test_changed_literal_is_reviewed_instead_of_inheriting_old_coverage():
    p,claims,model,seen,_=fixture();p['required_source_displays'][0]['quote']='监督项目'
    diagnose_material(p,claims,model,None,p['material_diagnosis_checkpoint'])
    assert seen==['E-PSTATEC']
