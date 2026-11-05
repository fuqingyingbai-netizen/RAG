import json
from copy import deepcopy

from report_agents.company_editorial import build_editorial_package, quantity_repair_candidates
from test_company_editorial import record, audit, OUTLINE


def inputs():
    return [record('I-a',text='公司披露本期收入100元。'),
            record('I-b',text='平台返回次数栏原值为0，相关情况为不适用。')]


def draft(rows, *, bad_unit=False, unsupported=False):
    return {'findings':[
        {'finding_id':'stable','text':rows[0]['text']+('已全部收款。' if unsupported else ''),'information_ids':['I-a']},
        {'finding_id':'bad','text':'平台返回次数为0次，相关情况为不适用。' if bad_unit else rows[1]['text'],
         'information_ids':['I-b']}]}


def test_native_count_label_does_not_trigger_token_repair_or_candidate_freezing():
    rows=inputs();original=deepcopy(rows);writes=[];reviews=[]
    def invoke(role,prompt,trace):
        if role=='公司交付正文独立审稿':
            data=json.loads(prompt.split('资料：\n',1)[1]);reviews.append(data)
            return json.dumps(audit(rows,data['findings']))
        writes.append(prompt);return json.dumps(draft(rows,bad_unit=True))
    result=build_editorial_package({'records':rows},OUTLINE,'青禾食品公司',invoke,workers=1)
    assert rows==original and len(writes)==1 and len(reviews)==1
    assert {r['information_id'] for r in reviews[0]['records']}=={'I-a','I-b'}
    assert not result['diagnostic']['pending_information_ids']


def test_real_semantic_failure_requests_full_rewrite_and_fresh_audit():
    rows=inputs();writes=[];reviews=0
    def invoke(role,prompt,trace):
        nonlocal reviews
        if role=='公司交付正文独立审稿':
            data=json.loads(prompt.split('资料：\n',1)[1]);reviews+=1;answer=audit(rows,data['findings'])
            if reviews==1:
                answer['criteria']['factual_support']=False
                answer['findings'][0].update(status='unsupported',reason='收入不能证明全部收款。')
            return json.dumps(answer)
        writes.append(prompt)
        return json.dumps(draft(rows,unsupported=len(writes)==1))
    result=build_editorial_package({'records':rows},OUTLINE,'青禾食品公司',invoke,workers=1)
    assert len(writes)==2 and reviews==2 and not result['diagnostic']['pending_information_ids']
    assert all('全部收款' not in f['text'] for f in result['findings'])


def test_tampered_cached_prose_is_not_authorized_by_its_old_true_flags():
    from test_company_editorial import invoke_for
    rows=inputs();first=build_editorial_package({'records':rows},OUTLINE,'公司',invoke_for(rows),workers=1)
    corrupt=deepcopy(first);corrupt['batches'][0]['findings'][0]['text']='公司披露本期收入999元。'
    calls=[]
    result=build_editorial_package({'records':rows},OUTLINE,'公司',invoke_for(rows,calls),previous=corrupt,workers=1)
    assert len(calls)==2 and not result['batches'][0].get('reused')
    assert all('999' not in f['text'] for f in result['findings'])


def test_nonquantity_defects_never_authorize_candidate_freezing():
    rows=inputs();proposal=draft(rows,bad_unit=True);valid=proposal['findings'][:1]
    for error in ['unknown_or_repeated_information','editorial_criterion:factual_support',
                  'missing_or_duplicate_finding_id','bad:model_written_structure_or_citation']:
        assert quantity_repair_candidates(proposal,valid,[error,'unrepresented_information:I-b'])==([],[])
