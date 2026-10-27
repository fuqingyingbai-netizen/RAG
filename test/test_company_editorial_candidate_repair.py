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


def test_quantity_repair_preserves_candidates_but_freshly_audits_every_record():
    rows=inputs();original=deepcopy(rows);writes=[];reviews=[]
    def invoke(role,prompt,trace):
        if role=='公司交付正文独立审稿':
            data=json.loads(prompt.split('资料：\n',1)[1]);reviews.append(data)
            return json.dumps(audit(rows,data['findings']))
        writes.append(prompt)
        if len(writes)==1:return json.dumps(draft(rows,bad_unit=True))
        assert '固定待审草稿：' in prompt and '尚未获独立语义审稿支持' in prompt
        assert '固定已审正文：' not in prompt
        return json.dumps({'findings':[{'finding_id':'ADD_fixed','text':rows[1]['text'],'information_ids':['I-b']}]})
    result=build_editorial_package({'records':rows},OUTLINE,'青禾食品公司',invoke,workers=1)
    assert rows==original and len(writes)==2 and len(reviews)==1
    assert {r['information_id'] for r in reviews[0]['records']}=={'I-a','I-b'}
    assert {f['finding_id'] for f in reviews[0]['findings']}=={'stable','ADD_fixed'}
    assert not result['diagnostic']['pending_information_ids']
    assert result['batches'][0]['attempts'][1]['repair_mode']=='native_quantity_repair'


def test_semantic_failure_of_a_preserved_candidate_releases_it_for_full_rewrite():
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
        if len(writes)==1:return json.dumps(draft(rows,bad_unit=True,unsupported=True))
        if len(writes)==2:return json.dumps({'findings':[{'finding_id':'ADD_fixed','text':rows[1]['text'],'information_ids':['I-b']}]})
        assert '固定待审草稿：' not in prompt and '固定已审正文：' not in prompt
        return json.dumps(draft(rows))
    result=build_editorial_package({'records':rows},OUTLINE,'青禾食品公司',invoke,workers=1)
    assert len(writes)==3 and reviews==2 and not result['diagnostic']['pending_information_ids']
    assert all('全部收款' not in f['text'] for f in result['findings'])


def test_candidate_tampering_is_rejected_before_any_semantic_acceptance():
    rows=inputs();writes=0;reviews=0
    def invoke(role,prompt,trace):
        nonlocal writes,reviews
        if role=='公司交付正文独立审稿':
            reviews+=1;data=json.loads(prompt.split('资料：\n',1)[1]);return json.dumps(audit(rows,data['findings']))
        writes+=1
        if writes==1:return json.dumps(draft(rows,bad_unit=True))
        if writes==2:
            proposal=draft(rows);proposal['findings'][0]['text']='公司披露本期收入999元。'
            return json.dumps(proposal)
        return json.dumps(draft(rows))
    result=build_editorial_package({'records':rows},OUTLINE,'青禾食品公司',invoke,workers=1)
    assert writes==3 and reviews==1 and not result['diagnostic']['pending_information_ids']
    assert result['batches'][0]['attempts'][1]['errors']==['editorial_call_failed:FrozenProseConflict']


def test_nonquantity_defects_never_authorize_candidate_freezing():
    rows=inputs();proposal=draft(rows,bad_unit=True);valid=proposal['findings'][:1]
    for error in ['unknown_or_repeated_information','editorial_criterion:factual_support',
                  'missing_or_duplicate_finding_id','bad:model_written_structure_or_citation']:
        assert quantity_repair_candidates(proposal,valid,[error,'unrepresented_information:I-b'])==([],[])
