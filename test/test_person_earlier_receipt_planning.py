"""Offline malformed-reply recovery preserves diagnosis, never coverage."""
import json
import pytest
import person_content_acceptance as acceptance
from test_person_content_acceptance import fixture


def earlier(old):
    return {'reviews':[{'prior_index':0,'verdict':'missing','matched_claim_indices':[999],
        'gaps':[{'prior_quote':old[0]['analysis'],'evidence_ids':old[0]['evidence_ids']}],
        'reason':'本轮具体职责与任期未获完整承接。'}]}


def test_later_broken_json_cannot_erase_a_real_earlier_edit_question():
    p,old,claims=fixture();first=json.dumps(earlier(old),ensure_ascii=False);calls=[]
    def invoke(*args):
        calls.append(args)
        return first if len(calls)==1 else '{"reviews":[{"reason":"原文见"董事长"，保留"}]}'
    result=acceptance._check_one(p,claims,old,invoke,None)
    item=result['items'][0];scope=item['unvalidated_review_repair_scope']
    assert result['status']=='pending_review' and item['status']=='pending_review' and item['reason']==''
    assert scope['reported_review']==earlier(old)['reviews'][0] and scope['earlier_structured_receipt_attempt']==1
    assert scope['planning_only_not_accepted_coverage']
    assert acceptance.coverage_repair_plans(result,old)[0]['gaps'][0]['prior_quote']==old[0]['analysis']


@pytest.mark.parametrize('case',['empty_later','failed_later','no_diagnosis','unsupported_verdict','duplicate_rows'])
def test_absent_reviews_or_ambiguous_earlier_receipts_do_not_request_prose(case):
    p,old,claims=fixture();row=earlier(old);calls=[]
    if case=='no_diagnosis':row['reviews'][0]['reason']=''
    if case=='unsupported_verdict':row['reviews'][0]['verdict']='invalid_prior'
    if case=='duplicate_rows':row['reviews']*=2
    def invoke(*args):
        calls.append(args)
        if len(calls)==1:return json.dumps(row,ensure_ascii=False)
        if case=='failed_later':raise ConnectionError('offline fixture only')
        return '' if case=='empty_later' else 'nonempty invalid JSON'
    result=acceptance._check_one(p,claims,old,invoke,None)
    assert result['status']=='pending_review'
    assert not any(r.get('unvalidated_review_repair_scope') for r in result['items'])
