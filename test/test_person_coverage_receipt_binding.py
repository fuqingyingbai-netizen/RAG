"""Offline regressions for observed receipt failures, not live acceptance."""
import copy
import json
import pytest
import person_content_acceptance as acceptance
from test_person_content_acceptance import fixture


@pytest.mark.parametrize('correct_second',[False,True])
def test_covered_with_incomplete_selected_carriers_gets_specific_feedback(correct_second):
    p,old,current=fixture()
    current.append(copy.deepcopy(old[0]))
    calls=[]
    def invoke(role,prompt,*args):
        packet=json.loads(prompt.splitlines()[-1]);calls.append(packet)
        if len(calls)==2:
            feedback=packet['previous_carrier_validation'][0]
            assert feedback['previously_selected_claim_indices']==[0]
            assert len(feedback['missing_tenures'])==2
            assert feedback['planning_only_not_evidence'] is True
            assert packet['draft']==calls[0]['draft'] and packet['sources']==calls[0]['sources']
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered',
            'matched_claim_indices':[2] if len(calls)==2 and correct_second else [0],
            'gaps':[],'reason':'选择实际承接位置'}]},ensure_ascii=False)
    result=acceptance._check_one(p,current,old,invoke,None)
    assert len(calls)==2
    assert result['items'][0]['status']==('covered' if correct_second else 'missing')
    assert result['status']==('passed' if correct_second else 'pending_review')


def test_complete_first_carrier_receipt_needs_no_feedback_or_extra_call():
    p,old,current=fixture();calls=[]
    def invoke(role,prompt,*args):
        calls.append(json.loads(prompt.splitlines()[-1]))
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered',
            'matched_claim_indices':[0],'gaps':[],'reason':'原文逐字保留'}]})
    result=acceptance._check_one(p,old,old,invoke,None)
    assert result['status']=='passed' and len(calls)==1
    assert 'previous_carrier_validation' not in calls[0]


@pytest.mark.parametrize('failure',['pending_repair_validation','pending_repair_semantics','pending_repair_call'])
def test_failed_repair_does_not_commit_compaction_against_stale_receipt(monkeypatch,failure):
    a={'analysis':'原始要求A','evidence_ids':['E-PA']}
    b={'analysis':'中间要求B','evidence_ids':['E-PB']}
    c={'analysis':'当前实际正文C','evidence_ids':['E-PC']}
    prior=[a,b];review={'status':'pending_review','items':[{'prior_index':1,'status':'missing'}],
        'issues':['content_coverage_missing']}
    seen=[]
    def step(package,current,requirements,writing,invoke,emit,validate,prechecked,missing,protected):
        seen.append((copy.deepcopy(requirements),prechecked))
        if len(seen)==2:
            assert requirements==prior and prechecked==review
            assert requirements[prechecked['items'][0]['prior_index']]==b
            return current,[],{'status':'passed','requests':0}
        return current,['content_repair_not_valid'],{'status':failure,'requests':0,
            'conserved_requirements':[a,c],'initial_review':review,
            'semantic_rejections':['semantic_support_missing'],'exception_type':'APIConnectionError',
            'failure_kind':'connection_error','validation_rejections':['unsupported_analysis']}
    monkeypatch.setattr(acceptance,'_accept_once',step)
    result,errors,audit=acceptance.accept_content({'chapter':3},[c],prior,{},lambda *a:None,None,lambda *a:None)
    assert len(seen)==2 and not errors and result==[c]
