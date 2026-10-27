"""Offline planning-hint robustness; no coverage shortcut."""
import copy,json
import pytest
import person_content_acceptance as module
from person_evidence import validate_model_claims


@pytest.mark.parametrize('hints',[[0],None,['0',True,-1,999]])
def test_source_display_overflow_hints_cannot_index_an_empty_draft(hints):
    f={'evidence_id':'E-PHINTNEW','fact':'陈安拟在未来12个月增持股份。','subject':'陈安','subject_scope':'person',
        'source_url':'https://fixture.invalid/new','analysis_allowed':True}
    p={'chapter':10,'title':'专项调研','facts':[f],'research_facts':[f],'writing_contract':'evidence_selection_v2'}
    missing=[{'material_evidence_ids':[f['evidence_id']],'matched_claim_indices':hints,'source_question':'补入原文中的增持计划，保留计划状态。'}]
    original=copy.deepcopy(missing);seen=[]
    def observe(role,prompt,emit):
        data=json.loads(prompt.splitlines()[-1]);seen.append(data);raise ConnectionError('Offline scope observation')
    _,errors,audit=module._accept_once(p,[],[],{'facts':[f]},observe,None,validate_model_claims,
        {'status':'passed','requests':0,'items':[],'issues':[]},missing)
    assert errors and seen and audit['status']=='pending_repair_call'
    assert all(not d['replace_draft'] and d['missing_items'][0]['matched_claim_indices']==[] for d in seen)
    assert missing==original and p['facts'][0]['fact']==f['fact']
    assert audit['normalized_repair_target_hints']
