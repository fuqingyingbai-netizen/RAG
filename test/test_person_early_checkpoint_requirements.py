"""Offline interrupted-review state tests; no live acceptance is simulated."""
import copy
import pytest
import person_content_acceptance as acceptance
from person_conservation import checkpoint_requirements


def rows():
    return [{'analysis':'实际旧事项'+str(i),'evidence_ids':['E-PSOURCE'+str(i)]} for i in range(4)]


def test_early_unavailable_review_keeps_every_obligation_not_only_immutable_subset(monkeypatch):
    prior=rows();current=[{'analysis':'当前实际候选','evidence_ids':['E-PCURRENT']}]
    p={'chapter':3,'restored_content_protected_prior':[prior[0]]}
    def step(*args):
        return current,['content_review_unavailable'],{'status':'pending_review','requests':0,
            'initial_review':{'status':'pending_review','items':[],'issues':['content_review_unavailable']}}
    monkeypatch.setattr(acceptance,'_accept_once',step)
    result,errors,audit=acceptance.accept_content(p,current,prior,{},None,None,None)
    assert errors and audit['status']=='pending_delivery'
    assert audit['protected_initial_requirements']==[prior[0]]
    assert audit['last_validated_requirements']==prior
    restored,proof=checkpoint_requirements({'claims':current},audit,'authenticated_last_validated_candidate_rebase')
    assert restored==prior and proof['restored_items']==4
    restored[0]['analysis']='调用者改变对象'
    assert audit['last_validated_requirements']==prior


def test_failed_compaction_proposal_does_not_replace_obligations_in_saved_checkpoint(monkeypatch):
    prior=rows();current=[{'analysis':'当前候选','evidence_ids':['E-PCURRENT']}]
    def step(*args):return current,['invalid_repair'],{'status':'pending_repair_validation','requests':0,
        'conserved_requirements':[current[0]],'initial_review':{'status':'pending_review','items':[]},
        'validation_rejections':['unsupported_analysis'],'raw_revision':current}
    monkeypatch.setattr(acceptance,'_accept_once',step)
    result,errors,audit=acceptance.accept_content({'chapter':3},current,prior,{},None,None,None)
    assert errors and audit['last_validated_requirements']==prior


@pytest.mark.parametrize('bad',[None,[{}],[{'analysis':'','evidence_ids':['E-PX']}],
    [{'analysis':'实际旧稿','evidence_ids':[]}],[{'analysis':'实际旧稿','evidence_ids':[None]}]])
def test_malformed_complete_snapshot_is_rejected_instead_of_falling_back_and_losing_rows(bad):
    current=[{'analysis':'当前候选','evidence_ids':['E-PCURRENT']}]
    with pytest.raises(ValueError,match='invalid_requirements'):
        checkpoint_requirements({'claims':current},{'last_validated_candidate':current,
            'last_validated_requirements':bad},'authenticated_last_validated_candidate_rebase')


def test_complete_snapshot_still_requires_authentic_binding_and_exact_candidate():
    current=[{'analysis':'当前候选','evidence_ids':['E-PCURRENT']}]
    content={'last_validated_candidate':current,'last_validated_requirements':rows()}
    assert checkpoint_requirements({'claims':current},content,'same_initial_automatic_checkpoint')==([],None)
    with pytest.raises(ValueError,match='candidate_mismatch'):
        checkpoint_requirements({'claims':[]},content,'authenticated_last_validated_candidate_rebase')
