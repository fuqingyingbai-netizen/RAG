import json
import pytest
from person_content_acceptance import _accept_once,repeated_local_coverage_capacity_failure
from person_evidence import validate_model_claims


def item(eid='E-PLOCALCAREER'):
    return {'status':'missing','prior_index':0,'matched_claim_indices':[0],
        'gaps':[{'prior_quote':'此前任研究总院副主任及恒川电池总经理，1993年2月创办企业。','evidence_ids':[eid]}]}


def failure(eid='E-PLOCALCAREER'):
    return {'status':'pending_final_coverage','final_review':{'items':[item(eid)]}}


def test_two_validated_local_coverage_failures_can_reallocate_shared_space():
    a={'evidence_id':'E-PLOCALCAREER','fact':item()['gaps'][0]['prior_quote'],'subject':'林知远','subject_scope':'person','source_url':'https://fixture.invalid/career','analysis_allowed':True}
    b={**a,'evidence_id':'E-PLOCKEDOTHER','fact':'来源记载林知远介绍研发计划。'}
    active=[{'analysis':'1993年创办企业。','evidence_ids':[a['evidence_id']]},
        {'analysis':b['fact']+'。'*(581-len(b['fact'])),'evidence_ids':[b['evidence_id']]}]
    prior=[{'analysis':a['fact'],'evidence_ids':[a['evidence_id']]}];seen=[]
    def observe(role,prompt,emit):
        seen.append(json.loads(prompt.splitlines()[-1]));raise ConnectionError('Offline scope observation only')
    _,errors,audit=_accept_once({'chapter':3,'title':'人格特质','facts':[a,b],'writing_contract':'evidence_selection_v2'},
        active,prior,{'facts':[a,b],'previous_repair_diagnostics':[failure(),failure()]},observe,None,validate_model_claims,
        {'status':'pending_review','requests':0,'items':[item()],'issues':['content_coverage_missing']})
    assert errors and audit['compaction_reason']=='repeated_local_coverage_failure_requires_shared_prose_budget'
    assert seen and all(not p['locked_analyses'] and p['replace_draft']==active for p in seen)
    assert all(c in audit['conserved_requirements'] for c in active+prior)


@pytest.mark.parametrize('history,available',[
    ([failure()],19),
    ([failure('E-PDIFFERENT'),failure()],19),
    ([failure(),{'status':'pending_repair_semantics'}],19),
    ([failure(),failure()],200),
])
def test_one_failure_unrelated_gaps_unvalidated_text_or_enough_space_does_not_expand(history,available):
    assert not repeated_local_coverage_capacity_failure(history,[item()],available)


def test_an_intervening_invalid_abbreviation_does_not_erase_two_validated_capacity_failures():
    history=[failure(),failure(),{'status':'pending_repair_validation','validation_rejections':['unsupported_analysis']}]
    assert repeated_local_coverage_capacity_failure(history,[item()],19)
