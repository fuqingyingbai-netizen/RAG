"""Offline source guard tests for immutable-baseline restoration."""
import copy
import run_person_content_acceptance as runner
from test_person_content_acceptance import fixture


def test_one_rejected_baseline_does_not_make_all_intermediate_versions_immutable():
    p,old,current=fixture();valid=copy.deepcopy(old[0])
    invalid={**valid,'analysis':'来源载2010年任董事长。'}
    before=copy.deepcopy([invalid,valid]);result=runner.restore_source_valid_protection(p,[invalid],[valid],p['research_facts'])
    assert result['protected_initial_requirement_guard_rejections']
    assert result['protected_initial_requirements_restored']==1
    assert p['restored_content_protected_prior']==[valid]
    assert [invalid,valid]==before


def test_protection_restore_never_promotes_a_guard_rejected_row():
    p,old,current=fixture();invalid={**old[0],'analysis':'来源称2010年任董事长。'}
    result=runner.restore_source_valid_protection(p,[],[invalid],p['research_facts'])
    assert result['protected_initial_requirement_guard_rejections']
    assert p['restored_content_protected_prior']==[]
