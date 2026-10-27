"""Offline malformed-receipt regressions; no live acceptance is fabricated."""
import copy,json
import pytest
import person_content_acceptance as acceptance
from test_person_content_acceptance import fixture


def malformed(p,old,claims):
    row={'prior_index':0,'verdict':'missing','matched_claim_indices':[0],
         'gaps':[{'prior_quote':'不是旧稿逐字原文','evidence_ids':['E-PTYPONOTADMITTED']}],
         'reason':'当前正文遗漏旧稿实质事项，需回到来源修订。'}
    review=acceptance.check_coverage(p,claims,old,lambda *a:json.dumps({'reviews':[row]},ensure_ascii=False),None)
    return review,row


def test_invalid_receipt_stays_pending_and_only_actual_baseline_defines_edit_scope():
    p,old,claims=fixture();review,row=malformed(p,old,claims)
    before=copy.deepcopy(review)
    assert review['status']=='pending_review' and review['requests']==2
    item=review['items'][0];scope=item['unvalidated_review_repair_scope']
    assert item['status']=='pending_review' and scope['reported_review']==row
    assert scope['prior_quote']==old[0]['analysis'] and scope['evidence_ids']==old[0]['evidence_ids']
    plans=acceptance.coverage_repair_plans(review,old)
    assert plans[0]['gaps']==[{'prior_quote':old[0]['analysis'],'evidence_ids':old[0]['evidence_ids']}]
    assert plans[0]['planning_only_not_accepted_coverage'] is True and review==before


@pytest.mark.parametrize('change',[
    {'state':'covered'},{'state':'missing'},{'verdict':'invalid_prior'}, {'verdict':[]},
    {'reason':''},{'reason':None},{'analysis':''},{'evidence_ids':[]},
    {'evidence_ids':['E-PUNKNOWN']},{'attempts':[{'status':'returned','output_chars':40}]},
    {'attempts':[{'status':'returned','output_chars':40},{'status':'failed','output_chars':0}]},
    {'attempts':[{'status':'returned','output_chars':40},{'status':'returned','output_chars':0}]},
])
def test_failure_or_unknown_source_cannot_become_an_edit_plan(change):
    row={'verdict':'missing','reason':'具体缺项'};old={'analysis':'实际旧稿。','evidence_ids':['E-PKNOWN']}
    attempts=[{'status':'returned','output_chars':40}]*2;state=change.get('state','pending_review')
    for key in ('verdict','reason'):
        if key in change:row[key]=change[key]
    for key in ('analysis','evidence_ids'):
        if key in change:old[key]=change[key]
    assert acceptance.unvalidated_coverage_scope(state,row,old,{'E-PKNOWN'},change.get('attempts',attempts)) is None


@pytest.mark.parametrize('change',[{'status':'covered'},{'prior_index':True},{'prior_index':9},
    {'scope':{'prior_quote':'改过旧稿'}},{'scope':{'evidence_ids':['E-PUNKNOWN']}},
    {'scope':{'planning_only_not_accepted_coverage':False}}])
def test_edit_plan_requires_unchanged_exact_baseline_binding(change):
    p,old,claims=fixture();review,_=malformed(p,old,claims);item=review['items'][0]
    item.update({k:v for k,v in change.items() if k!='scope'})
    item['unvalidated_review_repair_scope'].update(change.get('scope',{}))
    assert acceptance.coverage_repair_plans(review,old)==[]


def test_duplicate_or_extra_receipts_cannot_certify_coverage():
    p,old,claims=fixture()
    row={'prior_index':0,'verdict':'covered','matched_claim_indices':[0],'gaps':[],'reason':'逐字保留'}
    review=acceptance._check_one(p,old,old,lambda *a:json.dumps({'reviews':[row,row]}),None)
    assert review['requests']==2 and review['status']=='pending_review'
    assert review['items'][0]['status']=='pending_review'


def test_bare_covered_receipt_is_format_retried():
    p,old,claims=fixture();calls=[]
    def invoke(*args):
        calls.append(args)
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[],
            'gaps':[],'reason':'没有真实承接位置'}]})
    result=acceptance._check_one(p,claims,old,invoke,None)
    assert len(calls)==2 and '格式补核' in calls[1][0] and result['status']=='pending_review'


@pytest.mark.parametrize('final_pass',[False,True])
def test_planning_reaches_writer_but_final_coverage_remains_mandatory(monkeypatch,final_pass):
    p,old,claims=fixture();initial,_=malformed(p,old,claims);calls=[]
    def invoke(role,prompt,*args):
        calls.append((role,json.loads(prompt.splitlines()[-1])))
        return json.dumps({'claims':old},ensure_ascii=False)
    monkeypatch.setattr(acceptance,'review_analyses',lambda chapter,title,facts,changes,*a,**k:(changes,[],{'requests':0}))
    monkeypatch.setattr(acceptance,'check_coverage',lambda *a,**k:{'status':'passed' if final_pass else 'pending_review',
        'requests':0,'items':[],'issues':[] if final_pass else ['content_review_incomplete']})
    validate=lambda answer,package:(json.loads(answer)['claims'],[])
    result,errors,audit=acceptance._accept_once(p,claims,old,{'chapter':5,'facts':p['facts']},invoke,None,validate,initial)
    assert calls and calls[0][1]['missing_items'][0]['planning_only_not_accepted_coverage']
    assert audit['initial_review']['items'][0]['status']=='pending_review'
    if final_pass:assert not errors and audit['status']=='passed_after_targeted_repair'
    else:assert errors and result==claims and audit['status']=='pending_final_coverage'
