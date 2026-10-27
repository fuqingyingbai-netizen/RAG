"""Preserve reviewed facts on resume without restoring approval or stale acts."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from report_agents.company_checkpoint import save_generation_checkpoint, read_generation_checkpoint
from report_agents.company_event_evidence import review_primary_events, reviewed_event_records
from research_workflow import ResearchWorkflow
from test_company_checkpoint import store
from test_company_event_impact_and_dates import TARGET, AS_OF, source, selection, package, check


def project():
    s=source()
    return SimpleNamespace(id=19,target_name=TARGET,industry='食品',sources=[SimpleNamespace(**s)],
        company_research_intake={'as_of_date':AS_OF,'focus_questions':['经营与具体风险']},
        company_event_review_package=package(selection(s)),
        company_delivery_contract={'delivery_ready':True},company_document_review={'status':'passed'})


def fresh(original):
    return SimpleNamespace(id=original.id,target_name=original.target_name,industry=original.industry,
        sources=deepcopy(original.sources),company_research_intake=deepcopy(original.company_research_intake))


def test_real_review_package_roundtrips_and_preloads_before_reusing_only_validated_events(tmp_path,monkeypatch):
    original=project();storage=store(tmp_path)
    pointer=save_generation_checkpoint(original,store=storage,report_version='current')
    restored=fresh(original);caches=read_generation_checkpoint(restored,store=storage)
    assert set(caches)=={'company_event_review_cache'}
    assert caches['company_event_review_cache']==original.company_event_review_package
    assert not hasattr(restored,'company_delivery_contract') and not hasattr(restored,'company_document_review')
    monkeypatch.setattr('research_workflow.research_store',storage)
    ResearchWorkflow()._preload_company_generation_candidates(restored,restored.company_research_intake)
    assert restored.company_event_review_cache==original.company_event_review_package
    calls=[]
    def unexpected(*args):calls.append(args);raise AssertionError('unchanged valid event must not be rephrased')
    result=review_primary_events(restored.sources,TARGET,AS_OF,unexpected,cache=restored.company_event_review_cache)
    assert calls==[]
    assert result['events']==original.company_event_review_package['events']
    assert result['receipts']==[{'source_url':original.sources[0].url,'reused':True}]
    assert pointer['key'].endswith('.json')


@pytest.mark.parametrize('change',['body','metadata','url','target','date','industry','questions'])
def test_changed_source_or_scope_cannot_load_event_checkpoint(tmp_path,change):
    original=project();storage=store(tmp_path);save_generation_checkpoint(original,store=storage)
    restored=fresh(original)
    if change=='body':restored.sources[0].content+='新的司法程序记录。'
    elif change=='metadata':restored.sources[0].source_metadata['entity_validation']='rejected'
    elif change=='url':restored.sources[0].url+='?other-version=1'
    elif change=='target':restored.target_name='另一个主体'
    elif change=='date':restored.company_research_intake['as_of_date']='2026-10-23'
    elif change=='industry':restored.industry='办公软件'
    else:restored.company_research_intake['focus_questions']=['其他研究问题']
    assert read_generation_checkpoint(restored,store=storage)=={}


@pytest.mark.parametrize('defect',['old_contract','missing_actor_check','unsupported_actor','unbound_quote'])
def test_checkpoint_is_only_a_candidate_and_cannot_skip_current_full_event_validation(tmp_path,defect):
    original=project();storage=store(tmp_path);bad=original.company_event_review_package
    if defect=='old_contract':bad['version']='company-event-evidence-v2-responsibility-and-date-roles'
    elif defect=='missing_actor_check':bad['events'][0]['independent_check']['criteria'].pop('actors_and_obligations')
    elif defect=='unsupported_actor':bad['events'][0]['summary']='赔偿责任主体为第三方公司及其股东。'
    else:bad['events'][0]['quote']='不属于该原件的内容。'
    save_generation_checkpoint(original,store=storage)
    caches=read_generation_checkpoint(fresh(original),store=storage)
    cached=caches['company_event_review_cache']
    assert not reviewed_event_records(cached,original.sources,TARGET,AS_OF)
    good=selection(source());calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        if role=='公司监管原件提取':return json.dumps({'event':good},ensure_ascii=False)
        assert role=='公司监管原件独立核对'
        return json.dumps(check(),ensure_ascii=False)
    result=review_primary_events(original.sources,TARGET,AS_OF,invoke,cache=cached)
    assert calls==['公司监管原件提取','公司监管原件独立核对']
    assert result['receipts'][0]['state']=='accepted'
    assert result['events'][0]['summary']==good['summary']


def test_failed_review_stays_unfinished_and_gets_new_model_calls_after_resume(tmp_path):
    original=project();storage=store(tmp_path)
    original.company_event_review_package.update(events=[],receipts=[{'state':'requires_review','error':'provider_unavailable'}])
    save_generation_checkpoint(original,store=storage)
    cached=read_generation_checkpoint(fresh(original),store=storage)['company_event_review_cache']
    assert cached['receipts'][0]['state']=='requires_review'
    calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        return json.dumps({'event':selection(source())} if role=='公司监管原件提取' else check(),ensure_ascii=False)
    result=review_primary_events(original.sources,TARGET,AS_OF,invoke,cache=cached)
    assert len(calls)==2 and result['receipts'][0]['state']=='accepted'


def test_newly_completed_review_package_replaces_older_cache_without_editing_it(tmp_path):
    original=project();storage=store(tmp_path);old=deepcopy(original.company_event_review_package)
    old['events'][0]['summary']='赔偿责任主体为第三方公司及其股东。'
    original.company_event_review_cache=old
    save_generation_checkpoint(original,store=storage)
    loaded=read_generation_checkpoint(fresh(original),store=storage)['company_event_review_cache']
    assert loaded==original.company_event_review_package
    assert loaded!=old and old['events'][0]['summary'].endswith('股东。')


def test_legacy_checkpoint_without_event_package_does_not_invent_a_completed_review(tmp_path):
    original=project();del original.company_event_review_package
    original.company_information_usage_package={'version':'current','records':[],'review_scope':{'as_of_date':AS_OF}}
    storage=store(tmp_path);save_generation_checkpoint(original,store=storage)
    loaded=read_generation_checkpoint(fresh(original),store=storage)
    assert 'company_event_review_cache' not in loaded
