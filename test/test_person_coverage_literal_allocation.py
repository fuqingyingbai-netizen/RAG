"""Offline allocation regressions; selection is never an accepted verdict."""
import copy,json
import pytest
import person_content_acceptance as acceptance
from person_material_accounting import allocate_literal_displays
from test_person_content_acceptance import fixture


def setup():
    p,old,claims=fixture();eid=old[0]['evidence_ids'][0]
    p['required_source_displays']=[{'evidence_id':eid,'quote':'2018年担任'}]
    return p,old,claims,eid


def test_coverage_allocation_offers_complete_admitted_originals_beyond_old_snippets():
    p,old,claims,eid=setup();seen=[]
    feedback={'status':'pending_review','items':[{'prior_index':0,'status':'missing'}]}
    def invoke(role,prompt,*args):
        d=json.loads(prompt.splitlines()[-1]);seen.append(d)
        assert d['conserved_prior_questions_not_evidence']==old
        assert d['actual_coverage_feedback']==feedback
        card=next(r for r in d['sources'] if r['evidence_id']==eid)
        assert card['original']==next(r['fact'] for r in p['research_facts'] if r['evidence_id']==eid)
        span=next(r for r in card['segments'] if '董事长任期三年' in r['quote'])
        return json.dumps({'displays':[{'evidence_id':eid,'segment_ids':[span['segment_id']]}]})
    result=allocate_literal_displays(p,claims,invoke,None,conserved_prior=old,coverage_feedback=feedback)
    assert result['status']=='selected_for_material_review'
    assert '董事长任期三年' in p['required_source_displays'][0]['quote']
    assert sum(len(r['quote']) for r in p['required_source_displays'])<=1600


@pytest.mark.parametrize('reply',[
    {'displays':[{'evidence_id':'E-PUNKNOWN','segment_ids':[0]}]},
    {'displays':[{'evidence_id':'KNOWN','segment_ids':[999999]}]},
    {'displays':[]},
])
def test_invalid_allocation_cannot_mutate_actual_body_plan(reply):
    p,old,claims,eid=setup();before=copy.deepcopy(p['required_source_displays'])
    reply=json.loads(json.dumps(reply).replace('KNOWN',eid))
    result=allocate_literal_displays(p,claims,lambda *a:json.dumps(reply),None,conserved_prior=old)
    assert result['status']=='pending' and p['required_source_displays']==before


def test_default_allocator_does_not_expose_new_prior_fields_or_full_original_cards():
    p,old,claims,eid=setup();seen=[]
    def invoke(role,prompt,*args):
        d=json.loads(prompt.splitlines()[-1]);seen.append(d)
        assert 'conserved_prior_questions_not_evidence' not in d
        assert all('original' not in r for r in d['sources'])
        return json.dumps({'displays':[{'evidence_id':eid,'segment_ids':[0]}]})
    assert allocate_literal_displays(p,claims,invoke,None)['status']=='selected_for_material_review'
    assert len(seen)==1


def test_repeated_real_coverage_failure_reallocates_then_discards_stale_receipt(monkeypatch):
    p,old,claims,eid=setup();calls=[];steps=[]
    review={'status':'pending_review','requests':0,'items':[{'prior_index':0,'status':'missing'}],
        'issues':['content_coverage_missing']}
    def step(package,current,prior,writing,invoke,emit,validate,prechecked,*args):
        steps.append(prechecked)
        if len(steps)<3:
            candidate=[{**current[0],'analysis':current[0]['analysis']+'。'},*current[1:]]
            return current,['content_coverage_missing'],{'status':'pending_final_coverage','requests':0,
                'candidate_repair':candidate,'conserved_requirements':prior,'final_review':review}
        assert prechecked is None
        assert '董事长任期三年' in package['required_source_displays'][0]['quote']
        return current,[],{'status':'passed','requests':0}
    def invoke(role,prompt,*args):
        calls.append(role);d=json.loads(prompt.splitlines()[-1]);card=d['sources'][0]
        assert d['actual_coverage_feedback']==review and d['conserved_prior_questions_not_evidence']==old
        i=next(r['segment_id'] for r in card['segments'] if '董事长任期三年' in r['quote'])
        return json.dumps({'displays':[{'evidence_id':eid,'segment_ids':[i]}]})
    monkeypatch.setattr(acceptance,'_accept_once',step)
    result,errors,audit=acceptance.accept_content(p,claims,old,{},invoke,None,None)
    assert not errors and len(steps)==3 and len(calls)==1
    assert audit['material_display_repairs'][0]['coverage_driven_allocation']['status']=='selected_for_material_review'
