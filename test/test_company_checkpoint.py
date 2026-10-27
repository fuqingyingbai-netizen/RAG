from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from report_agents.company_checkpoint import (save_generation_checkpoint, read_generation_checkpoint,
    checkpoint_generation_stage, source_fingerprint)
from research_store import ResearchObjectStore
from research_workflow import ResearchWorkflow


def project():
    return SimpleNamespace(id=19, target_name='远帆设备有限公司', industry='工业设备',
        company_research_intake={'as_of_date': '2026-10-24', 'focus_questions': ['实际经营']},
        sources=[SimpleNamespace(id=1, url='https://issuer.test/statement', title='原始公告',
            content='目标公司完成产品交付。', source_metadata={'entity_validation':'verified'})],
        company_source_review_package={'version':'company-corpus-v7-explicit-entity-admission',
            'diagnostic': {'all_candidate_windows_reviewed':False}, 'review_receipts':[{'error':'timeout'}]},
        company_information_usage_package={'version':'company-information-usage-v3-bound-routing-cache',
            'review_scope':{'as_of_date':'2026-10-24'}, 'records':[{'state':'pending_review'}]},
        company_delivery_contract={'delivery_ready':True}, company_document_review={'status':'passed'})


def store(tmp_path):
    result = ResearchObjectStore()
    result.mode = 'local'
    result.local_root = tmp_path
    return result


def test_preload_before_original_enrichment_keeps_only_candidates_not_delivery_flags(tmp_path,monkeypatch):
    original=project();storage=store(tmp_path);save_generation_checkpoint(original,store=storage)
    monkeypatch.setattr('research_workflow.research_store',storage)
    fresh=SimpleNamespace(id=original.id,target_name=original.target_name,industry=original.industry,
                          sources=deepcopy(original.sources))
    ResearchWorkflow()._preload_company_generation_candidates(fresh,original.company_research_intake)
    assert fresh.company_corpus_analysis_cache['diagnostic']['all_candidate_windows_reviewed'] is False
    assert not hasattr(fresh,'company_delivery_contract') and not hasattr(fresh,'company_document_review')
    fresh.sources[0].content+='新取得原件的补充内容。'
    # The whole-source gate is never relaxed, even though native stages may
    # independently match unaffected candidate inputs already held in memory.
    assert read_generation_checkpoint(fresh,store=storage)=={}


@pytest.mark.parametrize('change',['body','date','industry'])
def test_preload_does_not_load_an_already_changed_input_or_scope(tmp_path,monkeypatch,change):
    original=project();storage=store(tmp_path);save_generation_checkpoint(original,store=storage)
    monkeypatch.setattr('research_workflow.research_store',storage)
    fresh=SimpleNamespace(id=original.id,target_name=original.target_name,industry=original.industry,
                          sources=deepcopy(original.sources));intake=deepcopy(original.company_research_intake)
    if change=='body':fresh.sources[0].content+='不同的原始资料。'
    elif change=='date':intake['as_of_date']='2026-10-23'
    else:fresh.industry='食品'
    ResearchWorkflow()._preload_company_generation_candidates(fresh,intake)
    assert not hasattr(fresh,'company_corpus_analysis_cache')


def test_checkpoint_keeps_real_failures_and_never_reinstates_delivery_flags(tmp_path):
    original=project(); storage=store(tmp_path)
    pointer=save_generation_checkpoint(original,store=storage,report_version='current')
    restored=read_generation_checkpoint(deepcopy(original),store=storage)
    assert restored['company_corpus_analysis_cache']['diagnostic']['all_candidate_windows_reviewed'] is False
    assert restored['company_information_usage_cache']['records'][0]['state']=='pending_review'
    assert set(restored)=={'company_corpus_analysis_cache','company_information_usage_cache'}
    assert save_generation_checkpoint(original,store=storage,report_version='current') is None
    assert pointer['key'].startswith('projects/19/company_generation_checkpoint/')


@pytest.mark.parametrize('change',['target','project','body','metadata','date','industry','questions'])
def test_changed_original_or_research_scope_does_not_load_checkpoint(tmp_path,change):
    original=project();storage=store(tmp_path);save_generation_checkpoint(original,store=storage)
    altered=deepcopy(original)
    if change=='target':altered.target_name='其他主体'
    elif change=='project':altered.id=20
    elif change=='body':altered.sources[0].content+='不同期间的新事实。'
    elif change=='metadata':altered.sources[0].source_metadata['entity_validation']='rejected'
    elif change=='date':altered.company_research_intake['as_of_date']='2026-10-23'
    elif change=='industry':altered.industry='消费食品'
    else:altered.company_research_intake['focus_questions']=['融资净额']
    assert read_generation_checkpoint(altered,store=storage)=={}


def test_immutable_payload_must_match_pointer_hash(tmp_path):
    original=project();storage=store(tmp_path);pointer=save_generation_checkpoint(original,store=storage)
    storage.put_text(pointer['key'], '{}')
    with pytest.raises(ValueError,match='hash_mismatch'):
        read_generation_checkpoint(original,store=storage)


def test_earlier_phase_keeps_later_genuine_cache_for_current_validators(tmp_path):
    original=project();storage=store(tmp_path);save_generation_checkpoint(original,store=storage)
    caches=read_generation_checkpoint(original,store=storage)
    original.company_information_usage_package={}
    original.company_information_usage_cache=caches['company_information_usage_cache']
    original.company_source_review_package['review_receipts'].append({'error':''})
    assert save_generation_checkpoint(original,store=storage)
    assert read_generation_checkpoint(original,store=storage)['company_information_usage_cache']==caches['company_information_usage_cache']


def test_store_failure_does_not_discard_live_packages_or_mark_delivery(tmp_path):
    original=project();original.company_generation_checkpoint_store=SimpleNamespace(
        put_text=lambda *a: (_ for _ in ()).throw(OSError('disk unavailable')))
    before=deepcopy(original.company_source_review_package);events=[]
    checkpoint_generation_stage(original,lambda *a,**kw:events.append((a,kw)))
    assert original.company_source_review_package==before
    assert events[-1][1]['status']=='warning'
    assert not hasattr(original,'_company_checkpoint_sha256')


def test_replays_and_unsaved_projects_do_not_write_implicitly(tmp_path):
    original=project();assert save_generation_checkpoint(original) is None
    original.id=None;assert save_generation_checkpoint(original,store=store(tmp_path)) is None
    assert not list(tmp_path.rglob('*'))


def test_source_hash_is_backward_compatible_with_existing_cleaning_cache():
    import hashlib
    original=project();digest=hashlib.sha256()
    for row in original.sources:
        record={key:getattr(row,key,None) for key in ('id','url','title','content','summary','source_type','source_metadata','credibility_score')}
        digest.update(json.dumps(record,ensure_ascii=False,sort_keys=True,default=str).encode());digest.update(b'\n')
    assert source_fingerprint(original.sources)==digest.hexdigest()
