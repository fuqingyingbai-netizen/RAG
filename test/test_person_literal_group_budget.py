"""Offline layout proposals retain whole source groups and need final review."""
import copy,json
import pytest
from person_material_accounting import allocate_literal_displays,fit_literal_source_groups


def test_source_group_fitting_never_cuts_a_qualifier_or_half_a_selected_source_group():
    rows=[{'evidence_id':eid,'quote':str(i)*200} for eid,count in [('A',5),('B',4),('C',2)] for i in range(count)]
    before=copy.deepcopy(rows);selected,audit=fit_literal_source_groups(rows,1600)
    assert sum(len(r['quote']) for r in selected)==1400
    assert {r['evidence_id'] for r in selected}=={'A','C'}
    assert all(r in selected for r in rows if r['evidence_id'] in {'A','C'})
    assert audit['deferred_evidence_ids']==['B'] and rows==before


def fixture():
    facts=[{'evidence_id':f'E-PGROUP{i:04d}','fact':str(i%10)*160,'source_url':f'https://fixture.invalid/{i}'} for i in range(14)]
    plan=[{'evidence_id':r['evidence_id'],'quote':r['fact']} for r in facts]
    return {'chapter':3,'title':'离线素材','facts':facts,'required_source_displays':plan}


def test_two_valid_oversized_returns_become_only_a_bounded_layout_proposal():
    p=fixture();calls=[]
    def invoke(role,prompt,*args):
        packet=json.loads(prompt.splitlines()[-1]);calls.append(packet)
        return json.dumps({'displays':[{'evidence_id':r['evidence_id'],'segment_ids':[0]} for r in packet['sources']]})
    result=allocate_literal_displays(p,[],invoke,None)
    assert len(calls)==2 and result['status']=='selected_for_material_review'
    assert result['source_group_budget_selection']['model_plan_chars']==2240
    assert result['selected_chars']==1600 and len(p['required_source_displays'])==10
    assert all(r['quote']==next(f['fact'] for f in p['facts'] if f['evidence_id']==r['evidence_id']) for r in p['required_source_displays'])
    assert len(p['facts'])==14


@pytest.mark.parametrize('kind',['invalid_id','empty_reply','exception'])
def test_one_oversized_return_and_one_failure_cannot_apply_a_budget_proposal(kind):
    p=fixture();before=copy.deepcopy(p['required_source_displays']);calls=[]
    def invoke(role,prompt,*args):
        packet=json.loads(prompt.splitlines()[-1]);calls.append(packet)
        if len(calls)==1:return json.dumps({'displays':[{'evidence_id':r['evidence_id'],'segment_ids':[0]} for r in packet['sources']]})
        if kind=='exception':raise ConnectionError('offline fixture only')
        return '' if kind=='empty_reply' else json.dumps({'displays':[{'evidence_id':'E-PUNKNOWN','segment_ids':[0]}]})
    result=allocate_literal_displays(p,[],invoke,None)
    assert result['status']=='pending' and p['required_source_displays']==before


def test_no_complete_source_group_fits_means_pending_not_empty_success():
    rows=[{'evidence_id':'A','quote':'甲'*200} for _ in range(10)]
    # Distinct selected spans from one source are atomic together.
    rows=[{**r,'quote':str(i)+r['quote']} for i,r in enumerate(rows)]
    selected,audit=fit_literal_source_groups(rows,1600)
    assert selected==[] and audit['deferred_evidence_ids']==['A']
