import json
from person_content_acceptance import _check_one

def test_contradictory_covered_with_gaps_is_rechecked_and_missing_stays_missing():
    fact={'evidence_id':'E-PREVIEW123','fact':'林知远负责研发及采购。','source_url':'https://fixture.invalid/roles','subject_scope':'person','subject':'林知远','analysis_allowed':True}
    prior=[{'analysis':'来源载林知远负责研发及采购。','evidence_ids':[fact['evidence_id']]}]
    current=[{'analysis':'来源载林知远负责研发。','evidence_ids':[fact['evidence_id']]}]
    package={'chapter':5,'title':'管理','facts':[fact],'research_facts':[fact]}
    calls=[]
    def invoke(role,prompt,emit):
        calls.append((role,prompt))
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered' if len(calls)==1 else 'missing','matched_claim_indices':[0],
            'matched_table_indices':[],'gaps':[{'prior_quote':'及采购','evidence_ids':[fact['evidence_id']]}],'reason':'采购职责未承接。'}]})
    result=_check_one(package,current,prior,invoke,None)
    assert len(calls)==2 and '结论一致性' in calls[-1][1]
    assert result['items'][0]['status']=='missing' and result['issues']==['content_coverage_missing']

def test_repeated_contradiction_never_becomes_a_pass():
    fact={'evidence_id':'E-PREVIEW123','fact':'林知远负责研发及采购。','source_url':'https://fixture.invalid/roles','subject_scope':'person','subject':'林知远','analysis_allowed':True}
    prior=[{'analysis':'来源载林知远负责研发及采购。','evidence_ids':[fact['evidence_id']]}]
    package={'chapter':5,'title':'管理','facts':[fact],'research_facts':[fact]}
    def invoke(role,prompt,emit):
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[0],
            'gaps':[{'prior_quote':'及采购','evidence_ids':[fact['evidence_id']]}],'reason':'存在缺口。'}]})
    result=_check_one(package,[{'analysis':'来源载林知远负责研发。','evidence_ids':[fact['evidence_id']]}],prior,invoke,None)
    assert result['requests']==2 and result['status']=='pending_review'
    assert result['items'][0]['status']=='pending_review'


def test_actual_new_source_literal_can_carry_old_fact_after_conflicting_review():
    old={'evidence_id':'E-PREVIEW123','fact':'林知远负责一般营运及策略。','source_url':'https://fixture.invalid/old','subject_scope':'person','subject':'林知远','analysis_allowed':True}
    alternate={**old,'evidence_id':'E-PREVIEW456','source_url':'https://fixture.invalid/new','analysis_allowed':False}
    prior=[{'analysis':'来源载林知远负责一般营运及策略。','evidence_ids':[old['evidence_id']]}]
    package={'chapter':5,'title':'管理','facts':[old,alternate],'research_facts':[old,alternate],
        'required_source_displays':[{'evidence_id':alternate['evidence_id'],'quote':alternate['fact']}]}
    current=[{'analysis':'来源记载林知远。','evidence_ids':[old['evidence_id']]}];calls=[]
    def invoke(role,prompt,emit):
        calls.append(prompt);packet=json.loads(prompt.splitlines()[-1])
        assert packet['tables'][0]['text']==alternate['fact']
        if len(calls)==1:
            return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[0],'gaps':[{'prior_quote':'负责一般营运及策略','evidence_ids':[old['evidence_id']]}]}]})
        assert '不要求draft再次引用或复述' in prompt
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[],'matched_table_indices':[0],'gaps':[],'reason':'真实逐字片段完整承接同主体职责。'}]})
    result=_check_one(package,current,prior,invoke,None)
    assert len(calls)==2 and result['status']=='passed'
    assert result['items'][0]['matched_table_indices']==[0]
    assert not alternate['analysis_allowed']
