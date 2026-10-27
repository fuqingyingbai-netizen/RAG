"""Offline loss regressions; source-valid proposals are not accepted evidence."""
import copy
import run_person_content_acceptance as runner
import person_content_acceptance as acceptance
from person_conservation import remember_source_validated_candidate,source_conservation_prior
from test_person_content_acceptance import fixture


def test_only_actual_analysis_is_remembered_by_value_without_promoting_pending_rows():
    p,old,current=fixture();before=copy.deepcopy(old)
    remember_source_validated_candidate(p,[*old,{'analysis':'','review_analysis':'待核内容','evidence_ids':['E-PUNKNOWN']}])
    old[0]['analysis']='外部对象后来改变'
    assert p['pre_semantic_conservation_candidates']==before
    assert source_conservation_prior(p,[],current)==before
    assert source_conservation_prior(p,before,current)==before
    assert source_conservation_prior(p,[],before)==[]


def test_semantic_rewrite_cannot_hide_dropped_source_valid_details_from_coverage(monkeypatch):
    p,old,current=fixture();remember_source_validated_candidate(p,old)
    p['require_material_dispositions']=False;seen=[]
    def check(package,claims,prior,*args):
        seen.extend(prior)
        return {'status':'pending_review','requests':0,'items':[],
            'issues':['content_review_incomplete']}
    monkeypatch.setattr(acceptance,'check_coverage',check)
    result,errors,audit=acceptance.accept_content(p,current,[],{'facts':p['facts']},None,None,None)
    assert seen==old and result==current and errors
    assert audit['status']=='pending_delivery'
    assert old[0] in audit['protected_initial_requirements']


def test_runner_records_candidate_before_semantic_repair_can_drop_a_supported_clause(monkeypatch):
    p,old,current=fixture();original=copy.deepcopy(old)
    def review(*args,**kwargs):return current,['semantic_support_missing'],{'requests':0}
    def repair(*args,**kwargs):return current,[],{'status':'repaired'}
    monkeypatch.setattr(runner,'review_analyses',review);monkeypatch.setattr(runner,'repair_semantic_findings',repair)
    result,errors,audit=runner.review_complete_candidate(p,p['facts'],old,{},None,'离线修订测试')
    assert not errors and result==current
    assert p['pre_semantic_conservation_candidates']==original


def test_exactly_unchanged_candidate_does_not_add_review_work_or_change_no_prior_status():
    p,old,current=fixture();remember_source_validated_candidate(p,current)
    def forbidden(*args):raise AssertionError('No model needed for identical source-bound rows')
    result,errors,audit=acceptance.accept_content(p,current,[],{},forbidden,None,None)
    assert result==current and not errors and audit['status']=='no_prior_draft_comparison'
