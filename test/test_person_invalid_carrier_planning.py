"""Offline repair-planning regressions; no live model calls."""
import json
import pytest
import person_material_accounting as module


def package(allowed=True):
    fact={'evidence_id':'E-PCARRIERONE','fact':'来源载陈安拟在未来12个月增持不少于一亿港元股份。',
        'source_url':'https://fixture.invalid/plan','subject':'陈安','subject_scope':'person','analysis_allowed':allowed}
    return {'chapter':10,'title':'专项调研','facts':[fact],'research_facts':[fact]}


def answer(state='analysis',indices=None,eid='E-PCARRIERONE'):
    return json.dumps({'material_reviews':[{'evidence_id':eid,'disposition':state,
        'matched_claim_indices':[0] if indices is None else indices,'reason':'增持计划属于本章投资行为材料。'}]},ensure_ascii=False)


@pytest.mark.parametrize('state',['analysis','corroborating_appendix'])
def test_repeated_nonexistent_carrier_becomes_missing_not_passed(state):
    p=package();before=p['facts'][0]['fact'];result=module.diagnose_material(p,[],lambda *a:answer(state),None)
    assert result['status']=='missing' and result['counts']=={'missing':1}
    row=result['rows'][0];assert row['planning_only_not_evidence'] and row['material_evidence_ids']==['E-PCARRIERONE']
    assert row['invalid_carrier_diagnosis']['reported_disposition']==state
    assert p['facts'][0]['fact']==before and result['requirements']==[]


@pytest.mark.parametrize('kind',['forbidden','unknown','malformed'])
def test_no_permission_no_record_or_no_response_stays_pending(kind):
    p=package(allowed=kind!='forbidden')
    response=answer(eid='E-PUNKNOWN') if kind=='unknown' else '{bad' if kind=='malformed' else answer()
    result=module.diagnose_material(p,[],lambda *a:response,None)
    assert result['status']=='pending' and result['counts']=={'pending':1}


def test_valid_analysis_is_still_accepted():
    p=package();claims=[{'analysis':p['facts'][0]['fact'],'evidence_ids':['E-PCARRIERONE']}]
    result=module.diagnose_material(p,claims,lambda *a:answer(),None)
    assert result['status']=='passed' and result['counts']=={'analysis':1}


def test_corrected_real_disposition_is_preferred_over_conservative_planning():
    replies=iter([answer(),answer('appendix',indices=[])])
    result=module.diagnose_material(package(),[],lambda *a:next(replies),None)
    assert result['status']=='passed' and result['counts']=={'appendix':1}


def test_transport_failure_cannot_become_a_missing_content_finding():
    def unavailable(*args):raise ConnectionError('Offline transport fixture')
    result=module.diagnose_material(package(),[],unavailable,None)
    assert result['status']=='pending' and result['counts']=={'pending':1}
