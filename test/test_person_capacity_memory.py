"""Offline repair-scope memory regressions; no live calls."""
import json
import pytest
import person_content_acceptance as module
from person_evidence import validate_model_claims


def setup():
    facts=[{'evidence_id':f'E-PMEMORY{i}','fact':f'陈安介绍第{i}项研发计划。','subject':'陈安','subject_scope':'person',
        'source_url':f'https://fixture.invalid/{i}','analysis_allowed':True} for i in range(3)]
    active=[{'analysis':facts[0]['fact']+'。'*(295-len(facts[0]['fact'])),'evidence_ids':[facts[0]['evidence_id']]},
        {'analysis':facts[1]['fact'],'evidence_ids':[facts[1]['evidence_id']]}]
    p={'chapter':9,'title':'利益关系','facts':facts,'research_facts':facts,'writing_contract':'evidence_selection_v2'}
    missing=[{'material_evidence_ids':[facts[1]['evidence_id']],'matched_claim_indices':[1],'source_question':'补入原文中的重要事实。'}]
    review={'status':'passed','requests':0,'items':[],'issues':[]}
    return p,active,missing,review


def once(p,active,missing,review,history,invoke):
    return module._accept_once(p,active,active,{'facts':p['facts'],'previous_repair_diagnostics':history},invoke,None,validate_model_claims,review,missing)


def prior_local_failure():
    p,active,missing,review=setup()
    row={'analysis':p['facts'][1]['fact']+'。'*350,'evidence_ids':[p['facts'][1]['evidence_id']]}
    _,_,audit=once(p,active,missing,review,[],lambda *args:json.dumps({'claims':[row]}))
    assert audit['status']=='pending_repair_validation' and 'analysis_length_budget_exceeded' in audit['validation_rejections']
    assert audit['repair_available_chars']==305
    return p,active,missing,review,audit


@pytest.mark.parametrize('change',[None,'missing_source','current_prose'])
def test_space_failure_survives_source_rejection_only_for_same_active_draft_and_task(change):
    p,active,missing,review,first=prior_local_failure()
    middle={**first,'validation_rejections':['unsupported_analysis'],'repair_available_chars':600}
    history=[first,middle]
    if change=='missing_source':missing=[{**missing[0],'material_evidence_ids':[p['facts'][2]['evidence_id']]}]
    if change=='current_prose':active=[{**active[0],'analysis':'另'+active[0]['analysis'][1:]},active[1]]
    packets=[]
    def observe(role,prompt,emit):
        packets.append(json.loads(prompt.splitlines()[-1]));raise ConnectionError('Offline scope observation')
    _,errors,audit=once(p,active,missing,review,history,observe)
    assert errors and packets
    if change is None:
        assert all(not d['locked_analyses'] and d['replace_draft']==active for d in packets)
        assert all(c in audit['conserved_requirements'] for c in active)
    else:
        assert all(d['locked_analyses']==[active[0]] and d['replace_draft']==[active[1]] for d in packets)
        assert 'compaction_reason' not in audit


def test_internal_scope_hash_does_not_bloat_writer_feedback():
    history=[{'status':'pending_repair_validation','local_scope_context_key':'internal-key','local_available_chars':305,
        'validation_rejections':['analysis_length_budget_exceeded'],'raw_revision':[{'analysis':'原候选','evidence_ids':['E-PMEMORY1']}]}]
    feedback=module.writer_repair_feedback(history)
    assert 'local_scope_context_key' not in feedback[0] and 'local_available_chars' not in feedback[0]
    assert feedback[0]['validation_rejections']==history[0]['validation_rejections'] and feedback[0]['raw_revision']==history[0]['raw_revision']
