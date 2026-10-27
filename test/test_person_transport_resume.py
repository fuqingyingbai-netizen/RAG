import copy
import json

from person_content_acceptance import accept_content
from person_evidence import validate_model_claims
from person_material_accounting import diagnose_material


def fixture():
    facts=[{'evidence_id':f'E-PTRANS{i:08d}','fact':fact,'analysis_allowed':True,
        'subject_scope':'person','subject':'林知远','source_url':f'https://fixture.invalid/{i}'}
        for i,fact in enumerate(['林知远于2018年任董事。','林知远于2019年任总裁。'])]
    current=[{'analysis':'来源记载林知远于2018年任董事。','evidence_ids':[facts[0]['evidence_id']]}]
    prior=[{'analysis':'来源记载林知远于2019年任总裁。','evidence_ids':[facts[1]['evidence_id']]}]
    return facts,current,prior


def test_compression_transport_retry_keeps_the_exact_candidate_without_rewriting():
    facts,current,prior=fixture();writes=[];compressions=[]
    def invoke(role,prompt,*args):
        data=json.loads(prompt.splitlines()[-1])
        if '事项覆盖验收' in role:
            covered=any('2019' in c['analysis'] for c in data['draft'])
            return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered' if covered else 'missing',
                'matched_claim_indices':[1] if covered else [],'matched_table_indices':[],
                'gaps':[] if covered else [{'prior_quote':prior[0]['analysis'],'evidence_ids':prior[0]['evidence_ids']}],
                'reason':'当前实际文字完整保留该历史事项。' if covered else '旧稿2019年总裁任职尚未出现。'}]})
        if '事项定向补写' in role:
            writes.append(prompt)
            return json.dumps({'claims':[{'analysis':prior[0]['analysis']*40,'evidence_ids':prior[0]['evidence_ids']}]})
        if '篇幅压缩' in role:
            compressions.append((role,prompt))
            if len(compressions)==1:raise TimeoutError('temporary response timeout')
            return json.dumps({'claims':prior})
        if '语义复核' in role:
            return json.dumps({'reviews':[{'claim_index':0,'verdict':'supported','supporting_evidence_ids':prior[0]['evidence_ids']}]})
        raise AssertionError(role)
    package={'chapter':5,'title':'管理','facts':facts,'writing_contract':'evidence_selection_v2'}
    result,errors,audit=accept_content(package,current,prior,{'chapter':5,'facts':facts},invoke,None,validate_model_claims)
    assert not errors and audit['status'].startswith('passed')
    assert len(writes)==1 and len(compressions)==2 and compressions[0]==compressions[1]
    assert len(audit['rounds'])==1
    assert any('2018' in c['analysis'] for c in result) and any('2019' in c['analysis'] for c in result)


def test_exhausted_compression_retry_does_not_restart_the_whole_writer():
    facts,current,prior=fixture();writes=[];compressions=[]
    def invoke(role,prompt,*args):
        if '事项覆盖验收' in role:
            return json.dumps({'reviews':[{'prior_index':0,'verdict':'missing','matched_claim_indices':[],
                'matched_table_indices':[],'gaps':[{'prior_quote':prior[0]['analysis'],'evidence_ids':prior[0]['evidence_ids']}],
                'reason':'缺少2019年任职事项。'}]})
        if '事项定向补写' in role:
            writes.append(prompt)
            return json.dumps({'claims':[{'analysis':prior[0]['analysis']*40,'evidence_ids':prior[0]['evidence_ids']}]})
        if '篇幅压缩' in role:
            compressions.append(prompt);raise TimeoutError('temporary response timeout')
        raise AssertionError(role)
    package={'chapter':5,'title':'管理','facts':facts,'writing_contract':'evidence_selection_v2'}
    result,errors,audit=accept_content(package,current,prior,{'chapter':5,'facts':facts},invoke,None,validate_model_claims)
    assert errors and audit['status']=='pending_delivery' and result==current
    assert len(writes)==1 and len(compressions)==2 and compressions[0]==compressions[1]
    assert audit['transport_retry_exhausted'] and len(audit['rounds'])==1


def test_restored_material_checkpoint_reuses_completed_rows_but_rechecks_changed_source():
    facts,current,prior=fixture();seen=[]
    p={'chapter':5,'title':'管理','task':'核对具体授权事项','facts':facts,'require_material_dispositions':True}
    def review(role,prompt,*args):
        data=json.loads(prompt.splitlines()[-1]);seen.extend(f['evidence_id'] for f in data['facts'])
        return json.dumps({'material_reviews':[{'evidence_id':f['evidence_id'],'disposition':'appendix',
            'reason':'本条仅记历史任职，未记具体授权范围或审批权限，留作本章职务背景。'} for f in data['facts']]})
    checkpoint=diagnose_material(p,[],review,None);assert checkpoint['status']=='passed'
    seen.clear();p['material_diagnosis_checkpoint']=copy.deepcopy(checkpoint)
    result,errors,audit=accept_content(p,[],[],{'chapter':5,'facts':facts},review,None,validate_model_claims)
    assert not errors and not seen and audit['material_diagnosis']['same_context_decisions_reused']==2
    changed=copy.deepcopy(p);changed['facts'][0]['fact']='林知远于2024年取得研发预算审批权。'
    changed['material_diagnosis_checkpoint']=copy.deepcopy(checkpoint);seen.clear()
    accept_content(changed,[],[],{'chapter':5,'facts':changed['facts']},review,None,validate_model_claims)
    assert set(seen)=={f['evidence_id'] for f in facts}


def test_quota_failure_does_not_trigger_the_transient_same_input_retry():
    from person_model_transport import invoke_same_input
    calls=[];audit={}
    def invoke(*args):calls.append(args);raise ConnectionError('HTTP 403 insufficient_user_quota')
    try:invoke_same_input(invoke,'writer','source-bound prompt',None,audit,'transport')
    except ConnectionError:pass
    else:raise AssertionError('quota errors must remain errors')
    assert len(calls)==1 and audit['transport']['exhausted']
