import json
from person_content_acceptance import _check_one

def scenario(year):
    old={'evidence_id':'E-PCOVEROLD','fact':'林知远于2018年任董事长，董事长任期三年，负责研发及采购。','source_url':'https://fixture.invalid/old','subject':'林知远','subject_scope':'person','analysis_allowed':True}
    literal={**old,'evidence_id':'E-PCOVERNEW','fact':f'林知远于{year}年任董事长，董事长任期三年，负责研发及采购。','source_url':'https://fixture.invalid/new','analysis_allowed':False}
    package={'chapter':5,'title':'管理','facts':[old,literal],'research_facts':[old,literal],
        'required_source_displays':[{'evidence_id':literal['evidence_id'],'quote':literal['fact']}]}
    prior=[{'analysis':'来源载林知远2018年任董事长，董事长任期三年，负责研发及采购。','evidence_ids':[old['evidence_id']]}]
    calls=[]
    def invoke(role,prompt,emit):
        calls.append(prompt)
        assert '当前实际正文由draft分析与tables表格或逐字片段共同组成' in prompt
        assert '只由tables完整承接时matched_claim_indices可为空' in prompt
        assert 'draft中保留了旧稿的所有' not in prompt
        packet=json.loads(prompt.splitlines()[-1]);assert packet['tables'][0]['text']==literal['fact']
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[],
            'matched_table_indices':[0],'gaps':[],'reason':'实际片段保留任职、任期及职责。'}]})
    result=_check_one(package,[{'analysis':'来源记载林知远负责研发。','evidence_ids':[old['evidence_id']]}],prior,invoke,None)
    return result,calls,literal

def test_complete_actual_literal_carries_date_tenure_and_duties_without_duplicate_prose():
    result,calls,literal=scenario(2018)
    assert len(calls)==1 and result['status']=='passed'
    assert result['items'][0]['matched_claim_indices']==[] and result['items'][0]['matched_table_indices']==[0]
    assert not literal['analysis_allowed']

def test_wrong_period_literal_still_fails_despite_model_declared_coverage():
    result,calls,literal=scenario(2019)
    assert result['status']=='pending_review' and result['items'][0]['status']=='missing'
    assert result['items'][0]['missing_numeric_anchors']==['2018']
