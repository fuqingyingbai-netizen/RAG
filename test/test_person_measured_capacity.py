"""Offline writer-scope regressions; all final acceptance gates remain."""
import json
import pytest
import person_content_acceptance as module
from person_evidence import validate_model_claims


@pytest.mark.parametrize('locked_chars',[100,295,350])
def test_measured_local_length_failure_can_reallocate_above_or_below_half_budget(locked_chars):
    fs=[{'evidence_id':f'E-PCAPACITY{i}','fact':f'陈安介绍第{i}项研究计划。','subject':'陈安',
        'subject_scope':'person','source_url':f'https://fixture.invalid/{i}','analysis_allowed':True} for i in range(2)]
    old=[{'analysis':fs[0]['fact']+'。'*(locked_chars-len(fs[0]['fact'])),'evidence_ids':[fs[0]['evidence_id']]},
        {'analysis':fs[1]['fact'],'evidence_ids':[fs[1]['evidence_id']]}]
    package={'chapter':9,'title':'利益关系','facts':fs,'research_facts':fs,'writing_contract':'evidence_selection_v2'}
    missing=[{'material_evidence_ids':[fs[1]['evidence_id']],'matched_claim_indices':[1],'source_question':'补充本条重要原文事实。'}]
    review={'status':'passed','requests':0,'items':[],'issues':[]};packets=[]
    def observe(role,prompt,emit):
        packets.append(json.loads(prompt.splitlines()[-1]));raise ConnectionError('Offline writer-scope observation')
    history=[{'status':'pending_repair_validation','validation_rejections':['analysis_length_budget_exceeded']}]
    _,_,audit=module._accept_once(package,old,old,{'facts':fs,'previous_repair_diagnostics':history},observe,None,validate_model_claims,review,missing)
    assert audit['compaction_reason']=='measured_local_budget_failure_requires_shared_prose_budget'
    assert packets and all(not p['locked_analyses'] and p['replace_draft']==old for p in packets)
    assert all(c in audit['conserved_requirements'] for c in old)
