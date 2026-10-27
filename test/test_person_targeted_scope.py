import json
from person_content_acceptance import _accept_once,draft_rows
from person_evidence import validate_model_claims


def fixture():
    first={'evidence_id':'E-PSCOPEFIRST','fact':'林知远公开介绍口罩最高日产超过5000万只。','source_url':'https://fixture.invalid/first','subject':'林知远','subject_scope':'person','analysis_allowed':True}
    second={**first,'evidence_id':'E-PSCOPESECOND','fact':'来源称2020年林知远完成既定安排，属当时公开陈述。','source_url':'https://fixture.invalid/second'}
    target={'analysis':'来源引述林知远公开介绍口罩日产超过5000万只。','evidence_ids':[first['evidence_id']]}
    repaired={**target,'analysis':'来源引述林知远公开介绍口罩最高日产超过5000万只。'}
    locked={'analysis':second['fact']*13,'evidence_ids':[second['evidence_id']]}
    package={'chapter':3,'title':'人格特质','facts':[first,second],'research_facts':[first,second],'writing_contract':'evidence_selection_v2'}
    review={'status':'pending_review','requests':0,'issues':['content_coverage_missing'],'items':[{'prior_index':0,'status':'missing','matched_claim_indices':[0],'gaps':[{'prior_quote':'最高','evidence_ids':[first['evidence_id']]}]}]}
    review['items'].append({'prior_index':1,'status':'covered','matched_claim_indices':[1],'gaps':[]})
    return package,[target,locked],[repaired,locked],review,repaired


def model_handler(calls,repaired,locked,*,overflow=False,expand=False):
    def invoke(role,prompt,emit):
        data=json.loads(prompt.splitlines()[-1])
        if '事项定向补写' in role:
            calls.append(data)
            if expand:
                assert len(data['replace_draft'])==2 and not data['locked_analyses']
                assert {r['evidence_id'] for r in data['facts']}==set(repaired['evidence_ids']+locked['evidence_ids'])
                return json.dumps({'claims':[repaired,locked]})
            assert data['replace_draft']==[data['replace_draft'][0]]
            assert data['locked_analyses']==[locked]
            assert {r['evidence_id'] for r in data['facts']}==set(repaired['evidence_ids'])
            return json.dumps({'claims':[{**repaired,'analysis':repaired['analysis']*20}] if overflow else [repaired]})
        if '篇幅压缩' in role:
            assert overflow
            return json.dumps({'claims':data['draft']})
        if '语义复核' in role:
            return json.dumps({'reviews':[{'claim_index':i,'verdict':'supported','supporting_evidence_ids':r['evidence_ids']} for i,r in enumerate(data['claims'])]})
        if '事项覆盖验收' in role:
            matches=[i for i,r in enumerate(data['draft']) if set(r['evidence_ids'])&set(data['prior'][0]['evidence_ids'])]
            return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':matches,'matched_table_indices':[],'gaps':[],'reason':'实际文字完整承接。'}]})
        raise AssertionError(role)
    return invoke


def test_small_qualifier_repair_does_not_unlock_validated_neighboring_text():
    p,current,prior,review,repaired=fixture();calls=[]
    result,errors,audit=_accept_once(p,current,prior,{'chapter':3,'facts':p['facts']},model_handler(calls,repaired,current[1]),None,validate_model_claims,review)
    assert not errors and len(calls)==1 and audit['status']=='passed_after_targeted_repair'
    assert draft_rows(result)[1]==current[1] and draft_rows(result)[0]==repaired
    assert audit['target_claim_indices']==[0] and audit['preserved_claim_indices']==[1]
    assert not audit.get('compaction_reason')


def test_actual_failed_local_length_check_permits_a_later_shared_budget_attempt():
    p,current,prior,review,repaired=fixture();calls=[]
    result,errors,first=_accept_once(p,current,prior,{'chapter':3,'facts':p['facts']},model_handler(calls,repaired,current[1],overflow=True),None,validate_model_claims,review)
    assert result==current and errors and first['validation_rejections']==['analysis_length_budget_exceeded']
    result,errors,second=_accept_once(p,current,prior,{'chapter':3,'facts':p['facts'],'previous_repair_diagnostics':[first]},model_handler(calls,repaired,current[1],expand=True),None,validate_model_claims,review)
    assert not errors and second['compaction_reason']=='measured_local_budget_failure_requires_shared_prose_budget'
    assert len(calls)==2 and current[1]['analysis'] in [r['analysis'] for r in result]


def test_a_missing_qualifier_retries_locally_until_an_actual_length_failure_is_measured():
    p,current,prior,review,repaired=fixture();calls=[]
    regular=model_handler(calls,repaired,current[1])
    def incomplete(role,prompt,emit):
        data=json.loads(prompt.splitlines()[-1])
        if '事项定向补写' in role:
            calls.append(data);assert data['locked_analyses']==[current[1]]
            return json.dumps({'claims':[current[0]]})
        if '事项覆盖验收' in role and '最高' in data['prior'][0]['analysis']:
            return json.dumps({'reviews':[{'prior_index':0,'verdict':'missing','matched_claim_indices':[0],
                'matched_table_indices':[],'gaps':[{'prior_quote':'最高','evidence_ids':prior[0]['evidence_ids']}],
                'reason':'最高这一数量限定仍未保留。'}]})
        return regular(role,prompt,emit)
    result,errors,first=_accept_once(p,current,prior,{'chapter':3,'facts':p['facts']},incomplete,None,validate_model_claims,review)
    assert errors and first['status']=='pending_final_coverage'
    assert '最高' not in draft_rows(result)[0]['analysis'] and draft_rows(result)[1]==current[1]
    result,errors,second=_accept_once(p,current,prior,{'chapter':3,'facts':p['facts'],'previous_repair_diagnostics':[first]},
        model_handler(calls,repaired,current[1]),None,validate_model_claims,review)
    assert not errors and not second.get('compaction_reason')
    assert draft_rows(result)[0]==repaired and draft_rows(result)[1]==current[1]
