import json
import pytest
from person_claim_repair import repair_source_findings
from person_evidence import validate_model_claims


def fixture(name):
    facts=[{'evidence_id':'E-PREPAIR000001','fact':f'{name}于2018年任董事。',
            'subject_scope':'person','analysis_allowed':True,'source_url':'https://fixture.invalid/role'},
           {'evidence_id':'E-PREPAIR000002','fact':f'{name}于2019年要求当天下午4点前处理投诉。',
            'subject_scope':'person','analysis_allowed':True,'source_url':'https://fixture.invalid/event'}]
    p={'chapter':5,'title':'管理','facts':facts,'writing_contract':'evidence_selection_v2'}
    good={'evidence_ids':[facts[0]['evidence_id']],'analysis':f'来源记载{name}于2018年任董事。'}
    bad={'evidence_ids':[facts[1]['evidence_id']],'analysis':f'来源记载{name}要求当日16时前处理投诉。'}
    raw=json.dumps({'claims':[good,bad]},ensure_ascii=False)
    claims,errors=validate_model_claims(raw,p)
    return p,good,bad,raw,claims,errors


@pytest.mark.parametrize('name',['陈安','欧阳清和','Alex Morgan'])
def test_each_failed_revision_is_repaired_with_its_own_exact_diagnostic(name):
    p,good,bad,raw,claims,errors=fixture(name)
    seen=[]
    def invoke(role,prompt,*args):
        data=json.loads(prompt[prompt.index('{"material":'):]);seen.append(data)
        if len(seen)==1:
            assert data['corrections'][0]['unmatched_numeric_literals']==['16']
            text=f'来源记载{name}要求当日15时前处理投诉。'
        else:
            assert data['corrections'][0]['unmatched_numeric_literals']==['15']
            assert '15时' in data['corrections'][0]['rejected_analysis']
            assert data['accepted_analyses'][0]['analysis']==good['analysis']
            text=f'来源记载{name}要求当天下午4点前处理投诉。'
        return json.dumps({'claims':[{'evidence_ids':bad['evidence_ids'],'analysis':text}]})
    final,errors,audit=repair_source_findings(raw,p,{'facts':p['facts']},claims,errors,invoke,None,validate_model_claims)
    assert not errors and len(seen)==audit['requests']==2
    assert final[0]['analysis']==good['analysis'] and '下午4点' in final[1]['analysis']
    assert audit['source_repair_rounds'][0]['final_rejections']==['unsupported_analysis']


def test_exhausted_revision_is_still_pending_and_raw_text_remains_auditable():
    p,good,bad,raw,claims,errors=fixture('陈安')
    def invoke(*args):return json.dumps({'claims':[bad]})
    final,errors,audit=repair_source_findings(raw,p,{'facts':p['facts']},claims,errors,invoke,None,validate_model_claims)
    assert errors==['unsupported_analysis'] and audit['status']=='still_requires_review'
    assert audit['requests']==3 and len(audit['source_repair_rounds'])==3
    assert final[0]['analysis']==good['analysis'] and not final[1]['analysis']
    assert audit['next_candidate'][-1]['analysis']==bad['analysis']


def test_later_provider_failure_keeps_last_actual_candidate_and_pending_status():
    p,good,bad,raw,claims,errors=fixture('陈安');calls=[]
    def invoke(*args):
        calls.append(1)
        if len(calls)==2:raise TimeoutError('offline mock')
        return json.dumps({'claims':[bad]})
    final,errors,audit=repair_source_findings(raw,p,{'facts':p['facts']},claims,errors,invoke,None,validate_model_claims)
    assert errors==['unsupported_analysis','source_role_repair_unavailable']
    assert audit['requests']==2 and audit['source_repair_rounds'][-1]['exception_type']=='TimeoutError'
    assert final[0]['analysis']==good['analysis']


def test_context_source_permissions_never_become_repairable_personal_prose():
    p,good,bad,raw,claims,errors=fixture('陈安')
    p['facts'][1]['analysis_allowed']=False
    bad['analysis']='来源称其要求处理投诉。'
    raw=json.dumps({'claims':[good,bad]});claims,errors=validate_model_claims(raw,p)
    def forbidden(*args):raise AssertionError('Scope cannot be rewritten into permission')
    final,errors,audit=repair_source_findings(raw,p,{'facts':p['facts']},claims,errors,forbidden,None,validate_model_claims)
    assert errors==['personal_analysis_not_permitted'] and audit['requests']==0
    assert final[0]['analysis']==good['analysis'] and not final[1]['analysis']


def test_next_round_uses_actual_compressed_revision_instead_of_oversized_raw_answer(monkeypatch):
    import person_prose_budget
    p,good,bad,raw,claims,errors=fixture('陈安');seen=[]
    def compact(*args,**kwargs):
        return json.dumps({'claims':[{'analysis':'来源记载陈安要求当日15时前处理投诉。','evidence_ids':bad['evidence_ids']}]}),1
    monkeypatch.setattr(person_prose_budget,'compact_draft',compact)
    def invoke(role,prompt,*args):
        data=json.loads(prompt[prompt.index('{"material":'):]);seen.append(data)
        if len(seen)==1:text='来源记载陈安要求当日16时前处理投诉。'+'说明'*400
        else:
            assert data['corrections'][0]['unmatched_numeric_literals']==['15']
            text='来源记载陈安要求当天下午4点前处理投诉。'
        return json.dumps({'claims':[{'analysis':text,'evidence_ids':bad['evidence_ids']}]})
    final,errors,audit=repair_source_findings(raw,p,{'facts':p['facts']},claims,errors,invoke,None,validate_model_claims)
    assert not errors and len(seen)==2 and '下午4点' in final[1]['analysis']
