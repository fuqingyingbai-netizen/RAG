import json
import pytest
from person_content_acceptance import _accept_once,draft_rows
from person_evidence import validate_model_claims


def fixture(size):
    a={'evidence_id':'E-PAPPENDOLD','fact':'来源称林知远介绍工程师文化。','source_url':'https://fixture.invalid/old',
        'subject':'林知远','subject_scope':'person','analysis_allowed':True}
    b={**a,'evidence_id':'E-PAPPENDNEW','fact':'林知远公开介绍研发计划。','source_url':'https://fixture.invalid/new'}
    old={'analysis':a['fact']+'。'*(size-len(a['fact'])),'evidence_ids':[a['evidence_id']]}
    new={'analysis':b['fact'],'evidence_ids':[b['evidence_id']]}
    p={'chapter':3,'title':'人格特质','facts':[a,b],'research_facts':[a,b],'writing_contract':'evidence_selection_v2'}
    review={'status':'passed','requests':0,'issues':[],'items':[]}
    missing=[{'material_evidence_ids':[b['evidence_id']],'source_question':'补入本条研发计划。','matched_claim_indices':[]}]
    return p,old,new,review,missing


def test_a_measured_failed_append_budget_then_allows_shared_compaction():
    p,old,new,review,missing=fixture(590);seen=[]
    def oversized(role,prompt,emit):
        data=json.loads(prompt.splitlines()[-1])
        if '事项定向补写' in role:
            seen.append(data);assert data['locked_analyses']==[old] and data['replace_draft']==[]
        return json.dumps({'claims':[new]})
    result,errors,first=_accept_once(p,[old],[old],{'chapter':3,'facts':p['facts']},oversized,None,validate_model_claims,review,missing)
    assert result==[old] and errors and first['validation_rejections']==['analysis_length_budget_exceeded']
    def shared(role,prompt,emit):
        data=json.loads(prompt.splitlines()[-1])
        if '事项定向补写' in role:
            seen.append(data);assert data['locked_analyses']==[] and data['replace_draft']==[old]
            return json.dumps({'claims':[{'analysis':p['facts'][0]['fact'],'evidence_ids':old['evidence_ids']},new]})
        if '语义复核' in role:return json.dumps({'reviews':[{'claim_index':i,'verdict':'supported','supporting_evidence_ids':r['evidence_ids']} for i,r in enumerate(data['claims'])]})
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[0],'gaps':[]}]})
    result,errors,second=_accept_once(p,[old],[old],{'chapter':3,'facts':p['facts'],'previous_repair_diagnostics':[first]},shared,None,validate_model_claims,review,missing)
    assert not errors and second['compaction_reason']=='measured_local_budget_failure_requires_shared_prose_budget'
    assert len(seen)==2 and draft_rows(result)[-1]==new


@pytest.mark.parametrize('size',[600,598])
def test_no_usable_sentence_space_can_expand_immediately(size):
    p,old,new,review,missing=fixture(size);packets=[]
    def stop_after_observing(role,prompt,emit):
        packets.append(json.loads(prompt.splitlines()[-1]));raise ConnectionError('offline scope observation only')
    _,errors,audit=_accept_once(p,[old],[old],{'chapter':3,'facts':p['facts']},stop_after_observing,None,validate_model_claims,review,missing)
    assert errors and audit['compaction_reason']=='new_substantive_material_requires_shared_prose_budget'
    assert all(not r['locked_analyses'] and r['replace_draft']==[old] for r in packets)


def test_a_new_topic_with_38_characters_still_uses_append_first():
    p,old,new,review,missing=fixture(562);packets=[]
    def observe(role,prompt,emit):
        packets.append(json.loads(prompt.splitlines()[-1]));raise ConnectionError('Offline scope observation only')
    _,_,audit=_accept_once(p,[old],[old],{'chapter':3,'facts':p['facts']},observe,None,validate_model_claims,review,missing)
    assert 'compaction_reason' not in audit
    assert all(r['locked_analyses']==[old] and not r['replace_draft'] for r in packets)
