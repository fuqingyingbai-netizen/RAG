"""Offline conservation/resume fixtures, not live acceptance results."""
import copy,pytest
from person_conservation import checkpoint_requirements


def fixture():
    current=[{'analysis':'压缩后的当前待验候选。','evidence_ids':['E-PCURRENT']}]
    obligations=[{'analysis':'上一轮不能遗失的原事项。','evidence_ids':['E-PORIGINAL']}]
    content={'last_validated_candidate':current,'status':'pending_delivery','rounds':[
        {'round':1,'status':'pending_final_coverage','candidate_repair':copy.deepcopy(current),'conserved_requirements':obligations},
        {'round':2,'status':'pending_review','issues':['content_review_incomplete']}]}
    return {'claims':copy.deepcopy(current)},content,obligations


def test_actual_pending_candidate_restores_its_full_prior_obligations_without_accepting_them():
    cp,content,obligations=fixture();before=copy.deepcopy(content)
    rows,proof=checkpoint_requirements(cp,content,'authenticated_last_validated_candidate_rebase')
    assert rows==obligations and proof['round']==1 and content==before
    rows[0]['analysis']='caller change';assert content==before
    assert content['status']=='pending_delivery'


@pytest.mark.parametrize('binding',['same_initial_automatic_checkpoint','unknown',None])
def test_unbound_initial_or_unknown_checkpoint_does_not_import_other_candidate_requirements(binding):
    cp,content,_=fixture();assert checkpoint_requirements(cp,content,binding)==([],None)


def test_changed_candidate_cannot_import_requirements_from_another_audit():
    cp,content,_=fixture();cp['claims'][0]['analysis']='人工改动'
    with pytest.raises(ValueError,match='candidate_mismatch'):checkpoint_requirements(cp,content,'authenticated_last_validated_candidate_rebase')


def test_other_round_candidate_is_not_used_as_a_binding():
    cp,content,_=fixture();content['rounds'][0]['candidate_repair']=[]
    assert checkpoint_requirements(cp,content,'authenticated_last_validated_candidate_rebase')==([],None)


def test_malformed_obligation_is_rejected_without_silent_removal():
    cp,content,_=fixture();content['rounds'][0]['conserved_requirements'][0]['evidence_ids']=[]
    with pytest.raises(ValueError,match='invalid_requirements'):checkpoint_requirements(cp,content,'authenticated_last_validated_candidate_rebase')


@pytest.mark.parametrize('valid',[True,False])
def test_resume_keeps_actual_immutable_baselines_separate_from_intermediate_obligations(monkeypatch,valid):
    import person_content_acceptance as acceptance
    original={'analysis':'实际原始基线。','evidence_ids':['E-PORIGINAL']}
    intermediate={'analysis':'后续中间版本。','evidence_ids':['E-PINTERMEDIATE']}
    current={'analysis':'当前待验候选。','evidence_ids':['E-PCURRENT']}
    protected=[original] if valid else [{'analysis':'未知来源。','evidence_ids':['E-PUNKNOWN']}]
    seen=[]
    def step(package,claims,prior,writing,invoke,emit,validate,initial,missing,immutable):
        seen.extend(immutable)
        return claims,[],{'status':'passed_without_content_repair','requests':0}
    monkeypatch.setattr(acceptance,'_accept_once',step)
    package={'chapter':3,'restored_content_protected_prior':protected}
    _,errors,audit=acceptance.accept_content(package,[current],[original,intermediate],{},lambda *a:'',None,None)
    assert not errors
    assert seen==([original] if valid else [original,intermediate,current])
    assert audit['protected_initial_requirements']==seen
