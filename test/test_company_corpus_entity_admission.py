from copy import deepcopy
import hashlib
import json

import pytest

from report_agents.company_corpus import prepare_corpus,build_corpus_review,_batches,disclosed_aliases,research_context
from report_agents.company_corpus import build_corpus_review_with_recovery
from report_agents.company_corpus_writer import corpus_cache_matches
from test_company_corpus import source,project,TARGET


def select_all(role,prompt,trace):
    docs=json.loads(prompt.split('资料：\n',1)[1])['originals']
    return json.dumps({'decisions':[{'evidence_id':d['evidence_id'],'disposition':'accepted'} for d in docs],
        'facts':[{'evidence_id':d['evidence_id'],'window_id':w['window_id'],'chapter':2,'scope':'target',
                  'relevance':'登记字段按原文主体列示'} for d in docs for w in d['windows']]})


def build(p,invoke=select_all):return build_corpus_review(p,{'facts':[]},{},invoke,lambda *a,**k:None)


@pytest.mark.parametrize('state',['rejected','ambiguous'])
def test_explicit_entity_failure_is_not_recovered_by_unknown_publisher_fallback_or_duplicate(state):
    bad=source();bad['source_metadata']['entity_validation']=state
    good=source(2,body=bad['content'])
    p=project([bad,good]);result=build(p)
    assert result['source_review']['1']['state']=='entity_subject_quarantined'
    assert {f['source_id'] for f in result['facts']}=={'2'}
    assert result['source_review']['1']['original_sha256']==result['source_review']['2']['original_sha256']


def test_related_context_and_its_exact_copy_cannot_inherit_target_scope():
    related=source();related['source_metadata']['entity_validation']='related_entity_context'
    related_copy=deepcopy(related);related_copy['id']=3;related_copy['url']='https://www.tianyancha.com/company/3'
    own=source(2,body=related['content']);result=build(project([related,own,related_copy]))
    by_id={f['source_id']:f for f in result['facts']}
    assert by_id['2']['scope']=='target'
    for sid in ('1','3'):
        assert by_id[sid]['scope']=='third_party_about_target'
        assert '关联企业候选资料' in by_id[sid]['boundary']
        assert by_id[sid]['eligible_for_risk_scoring'] is False


def test_quarantined_original_cannot_create_a_target_alias():
    s=source(body=TARGET+'（以下简称“伪称别名”）发布模型及其他技术服务，披露收入及研发业务。')
    s['source_metadata']['entity_validation']='rejected'
    assert '伪称别名' not in disclosed_aliases(TARGET,[s])


@pytest.mark.parametrize('change',['entity_validation','publisher_verified','url','title'])
def test_source_semantics_change_invalidates_full_cache_even_when_native_bytes_do_not(change):
    s=source();p=project([s]);package=build(p)
    assert corpus_cache_matches(p,package)
    if change=='entity_validation':s['source_metadata'][change]='rejected'
    elif change=='publisher_verified':s['source_metadata'][change]=False
    else:s[change]+='-changed'
    assert not corpus_cache_matches(p,package)


def test_v6_model_proposals_are_revalidated_on_the_same_bound_inputs_not_rerequested():
    s=source();p=project([s]);p.company_research_intake['industry']='办公软件'
    package=build(p);legacy=deepcopy(package);version='company-corpus-v6-explicit-research-scope'
    legacy['version']=version;batch=list(_batches(prepare_corpus(p,{'facts':[]})[0]))[0]
    context=research_context(p);scope='\ncontext:'+json.dumps(context,ensure_ascii=False,sort_keys=True)
    key=hashlib.sha256((version+'\n'+TARGET+'\n2026-10-20'+scope+'\n'+json.dumps(batch,ensure_ascii=False,sort_keys=True)).encode()).hexdigest()
    legacy['review_receipts'][0]['input_sha256']=key;p.company_corpus_analysis_cache=legacy
    def no_call(*a):raise AssertionError('unchanged, real receipt should be reused')
    result=build(p,no_call)
    assert result['diagnostic']['cached_review_batches']==1
    assert result['diagnostic']['model_requests']==0
    assert result['facts']==package['facts']


def unique_sources(count):
    return [source(i,body=TARGET+f'在原表第{i}条披露注册资本及登记信息，此处保留原表字段与当前主体，不推定实缴或实际融资到账。') for i in range(1,count+1)]


def test_transient_failure_retries_only_incomplete_batch_and_counts_both_passes():
    p=project(unique_sources(7));calls=[]
    def invoke(role,prompt,trace):
        docs=json.loads(prompt.split('资料：\n',1)[1])['originals'];ids=tuple(d['source_id'] for d in docs)
        calls.append(ids)
        if ids[0]=='1' and calls.count(ids)==1:raise TimeoutError('temporary provider timeout')
        return select_all(role,prompt,trace)
    result=build_corpus_review_with_recovery(p,{}, {},invoke,lambda *a,**k:None)
    assert result['diagnostic']['all_candidate_windows_reviewed']
    assert len(result['facts'])==7 and len(calls)==3
    assert calls.count(('7',))==1
    assert result['diagnostic']['cached_review_batches']==1
    assert result['diagnostic']['model_requests_including_recovery']==3


def test_open_transport_circuit_is_not_reset_to_repeat_all_failed_requests():
    from report_agents.company_transport import bounded_company_invoke
    p=project(unique_sources(60));calls=[]
    def fail(*args):calls.append(1);raise TimeoutError('provider unavailable')
    guarded=bounded_company_invoke(fail,cooldown_seconds=0)
    result=build_corpus_review_with_recovery(p,{}, {},guarded,lambda *a,**k:None)
    assert result['diagnostic']['all_candidate_windows_reviewed'] is False
    assert any(r['error']=='provider_unavailable' and r['attempts']==0 for r in result['review_receipts'])
    assert len(calls)==5 and not result.get('recovery_history')


def test_exhaustion_at_last_batch_does_not_get_a_new_provider_budget_on_second_pass():
    from report_agents.company_transport import bounded_company_invoke
    p=project(unique_sources(30));calls=[]
    def fail(*args):calls.append(1);raise TimeoutError('provider unavailable')
    guarded=bounded_company_invoke(fail,cooldown_seconds=0)
    result=build_corpus_review_with_recovery(p,{}, {},guarded,lambda *a,**k:None)
    assert len(calls)==5
    assert result['diagnostic']['all_candidate_windows_reviewed'] is False
    assert result['recovery_history']
    assert all(r['error']=='provider_unavailable' and r['attempts']==0 for r in result['review_receipts'])
    assert result['diagnostic']['model_requests_including_recovery']==5


def test_recovered_provider_retries_only_failed_original_batches_and_retains_successes():
    from report_agents.company_transport import bounded_company_invoke
    import threading
    p=project(unique_sources(42));calls=[];lock=threading.Lock()
    def invoke(role,prompt,trace):
        docs=json.loads(prompt.split('资料：\n',1)[1])['originals']
        with lock:
            calls.append(tuple(d['source_id'] for d in docs));number=len(calls)
        if number<=3:raise TimeoutError('temporary outage')
        return select_all(role,prompt,trace)
    guarded=bounded_company_invoke(invoke,cooldown_seconds=0)
    result=build_corpus_review_with_recovery(p,{}, {},guarded,lambda *a,**k:None)
    assert result['diagnostic']['all_candidate_windows_reviewed'] is True
    assert len(result['facts'])==42
    assert len(calls)==10
    assert result['diagnostic']['cached_review_batches']==4
