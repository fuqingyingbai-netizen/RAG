import pytest
from person_content_acceptance import repeated_tight_scope_failure


def failure(eid='E-PMISSING',size=47,status='pending_repair_semantics'):
    return {'status':status,'semantic_rejections':['semantic_support_missing'],
        'raw_revision':[{'analysis':'文'*size,'evidence_ids':[eid]}],'repair_available_chars':47}


def test_two_full_tight_candidates_with_same_missing_source_allow_shared_space():
    assert repeated_tight_scope_failure([failure(),failure()],{'E-PMISSING'},47,600)


@pytest.mark.parametrize('history,available',[
    ([failure()],47),
    ([failure('E-POTHER'),failure()],47),
    ([failure(size=20),failure(size=20)],47),
    ([failure(),failure()],200),
    ([failure(status='pending_repair_call'),failure()],47),
    ([failure(status='pending_material_diagnosis'),failure()],47),
    ([{**failure(status='pending_repair_validation'),'validation_rejections':['invalid_structured_output']},failure()],47),
    ([failure(),failure()],46),
])
def test_incomplete_unrelated_transport_or_unpressured_candidates_do_not_expand(history,available):
    assert not repeated_tight_scope_failure(history,{'E-PMISSING'},available,600)


def test_source_validation_failure_with_real_candidate_can_show_pressure():
    a={**failure(status='pending_repair_validation'),'validation_rejections':['unsupported_analysis']}
    assert repeated_tight_scope_failure([a,failure()],{'E-PMISSING'},47,600)
