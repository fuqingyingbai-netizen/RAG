import json
from copy import deepcopy
from report_agents.company_editorial import build_editorial_package
from test_company_editorial import record,audit,OUTLINE


NATIVE='公司披露2025年收入100.00万元。计划新增产线尚未完成。'
FIRST='公司披露2025年收入100.00万元。'
MISSING='新增产线仍为计划，尚未完成。'


def initial():return {'finding_id':'stable','text':FIRST,'information_ids':['I-a']}


def first_review(row,findings):
    result=audit([row],findings);result['criteria']['semantic_retention']=False
    result['information'][0].update(status='lost',reason='遗漏新增产线仍为计划且尚未完成的独立事实。')
    result['issues']=['尚未完整表达计划状态。'];return result


def test_missing_information_is_added_without_rewriting_supported_prose_and_full_review_runs_again():
    row=record(text=NATIVE);writes=[];reviews=[]
    def invoke(role,prompt,trace):
        if role=='公司交付正文独立审稿':
            data=json.loads(prompt.split('资料：\n',1)[1]);reviews.append(data)
            return json.dumps(first_review(row,data['findings']) if len(reviews)==1 else audit([row],data['findings']))
        writes.append(prompt)
        return json.dumps({'findings':[initial()] if len(writes)==1 else
            [{'finding_id':'ADD_plan','text':MISSING,'information_ids':['I-a']}]})
    result=build_editorial_package({'records':[row]},OUTLINE,'青禾食品公司',invoke,workers=1)
    assert len(writes)==len(reviews)==2 and not result['diagnostic']['pending_information_ids']
    assert reviews[1]['findings'][0]['text']==FIRST and len(reviews[1]['findings'])==2
    assert '固定已审正文' in writes[1] and result['batches'][0]['attempts'][1]['repair_mode']=='supplement'
    assert row['text']==NATIVE


def test_an_unsupported_or_unreadable_first_draft_cannot_lock_its_prose():
    row=record(text=NATIVE);writes=[];reviews=0
    def invoke(role,prompt,trace):
        nonlocal reviews
        if role=='公司交付正文独立审稿':
            data=json.loads(prompt.split('资料：\n',1)[1]);reviews+=1
            result=first_review(row,data['findings']) if reviews==1 else audit([row],data['findings'])
            if reviews==1:
                result['criteria']['factual_support']=False;result['findings'][0].update(status='unsupported',reason='原文未证明全部收款。')
            return json.dumps(result)
        writes.append(prompt)
        return json.dumps({'findings':[{'finding_id':'stable','text':FIRST+'已全部收款。' if len(writes)==1 else NATIVE,'information_ids':['I-a']}]})
    result=build_editorial_package({'records':[row]},OUTLINE,'青禾食品公司',invoke,workers=1)
    assert not result['diagnostic']['pending_information_ids'] and '固定已审正文' not in writes[1]
    assert all(a['repair_mode']=='rewrite' for a in result['batches'][0]['attempts'])


def test_changing_protected_prose_is_rejected_and_requires_a_fresh_full_rewrite():
    row=record(text=NATIVE);writes=0;reviews=0
    def invoke(role,prompt,trace):
        nonlocal writes,reviews
        if role=='公司交付正文独立审稿':
            data=json.loads(prompt.split('资料：\n',1)[1]);reviews+=1
            return json.dumps(first_review(row,data['findings']) if reviews==1 else audit([row],data['findings']))
        writes+=1
        if writes==1:return json.dumps({'findings':[initial()]})
        if writes==2:return json.dumps({'findings':[{**initial(),'text':FIRST.replace('100.00','999.00')},
            {'finding_id':'ADD_plan','text':MISSING,'information_ids':['I-a']}]})
        assert '固定已审正文' not in prompt
        return json.dumps({'findings':[{**initial(),'text':NATIVE}]})
    result=build_editorial_package({'records':[row]},OUTLINE,'青禾食品公司',invoke,workers=1)
    assert not result['diagnostic']['pending_information_ids'] and writes==3 and reviews==2
    assert result['batches'][0]['attempts'][1]['errors']==['editorial_call_failed:FrozenProseConflict']
    assert all('999.00' not in f['text'] for f in result['findings'])


def test_new_full_audit_failure_cannot_be_overridden_by_the_original_supported_flags():
    row=record(text=NATIVE);writes=0;reviews=0
    def invoke(role,prompt,trace):
        nonlocal writes,reviews
        if role=='公司交付正文独立审稿':
            data=json.loads(prompt.split('资料：\n',1)[1]);reviews+=1
            if reviews==1:return json.dumps(first_review(row,data['findings']))
            result=audit([row],data['findings']);result['criteria']['factual_support']=False
            result['issues']=['本轮独立审稿仍未支持全部正文。'];return json.dumps(result)
        writes+=1
        if writes==1:return json.dumps({'findings':[initial()]})
        if writes==2:return json.dumps({'findings':[{'finding_id':'ADD_plan','text':MISSING,'information_ids':['I-a']}]})
        return json.dumps({'findings':[{**initial(),'text':NATIVE}]})
    result=build_editorial_package({'records':[row]},OUTLINE,'青禾食品公司',invoke,workers=1)
    assert reviews==3 and result['diagnostic']['pending_information_ids']==['I-a']
    assert result['diagnostic']['failed_batches']==1 and not result['findings']
