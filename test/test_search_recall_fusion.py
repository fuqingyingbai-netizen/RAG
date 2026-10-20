"""Real failure modes reproduced without spending search-provider quota."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

import web_search
from search_results import canonical_source_url, fuse_search_results
from web_search import WebSearchProvider
from research_workflow import ResearchWorkflow


def row(url, *, provider='serper', body='', summary='', score=60, **meta):
    return {'url':url,'title':'阿里巴巴公开资料','content':body,'summary':summary,
            'credibility_score':score,'metadata':{'provider':provider,**meta}}


def fake_engines(monkeypatch, batches):
    provider=WebSearchProvider()
    provider.engines=[(name,lambda *a,_rows=rows,**kw:deepcopy(_rows)) for name,rows in batches.items()]
    for name in batches:monkeypatch.setenv(name.upper()+'_API_KEY','offline-test-key')
    monkeypatch.setenv('WEB_SEARCH_PROVIDER','multi')
    return provider


def alibaba_batches():
    # Explicit fixture: 20 shared documents, 10 unique per provider. This is
    # not a claim about the live Alibaba search overlap or relevance rate.
    names=['tavily','serper','exa','serpapi','brave','bocha']
    scores=[80,60,65,62,62,65]
    return {name:[row(f'https://shared.example/doc/{i}?utm_source={name}#section',provider=name,score=scores[j]) for i in range(20)]
                 +[row(f'https://{name}.example/unique/{i}',provider=name,score=scores[j]) for i in range(10)]
            for j,name in enumerate(names)}


def test_research_candidate_budget_preserves_all_80_unique_documents(monkeypatch):
    provider=fake_engines(monkeypatch,alibaba_batches())
    results=provider.search('阿里巴巴',limit=30,candidate_limit=180)
    assert len(results)==80
    assert results.audit['raw_count']==180 and results.audit['unique_count']==80
    assert results.audit['deduplicated_count']==100 and results.audit['trimmed_count']==0
    assert sum('serper.example/unique/' in r['url'] for r in results)==10
    # The normal search API still respects its explicit display/result limit.
    display=provider.search('阿里巴巴',limit=30)
    assert len(display)==30 and display.audit['trimmed_count']==50


def test_workflow_requests_candidate_union_instead_of_another_global_30(monkeypatch):
    provider=fake_engines(monkeypatch,alibaba_batches())
    monkeypatch.setattr('research_workflow.web_search_provider',provider)
    events=[]
    batches=ResearchWorkflow.__new__(ResearchWorkflow)._search_query_items_parallel(
        [{'query':'阿里巴巴','module':'公司背景'}],30,list(alibaba_batches()),emit=events.append)
    assert len(batches[0][1])==80
    assert batches[0][0]['search_result_audit']['trimmed_count']==0
    completed=next(e for e in events if e['label']=='在线检索完成')
    assert completed['search_result_audit']['raw_count']==180


def test_rank_fusion_ignores_native_and_hardcoded_scores():
    batches={'serper':[row('https://low.example/first',score=1)],
             'exa':[row('https://other.example/first',provider='exa',score=100)]}
    first=fuse_search_results(batches,result_limit=2)
    swapped=deepcopy(batches)
    swapped['serper'][0]['credibility_score']=100
    swapped['exa'][0]['credibility_score']=1
    second=fuse_search_results(swapped,result_limit=2)
    assert [r['url'] for r in first]==[r['url'] for r in second]
    assert first[0]['metadata']['search_fusion_score']==first[1]['metadata']['search_fusion_score']
    assert all(r['credibility_score']==0 for r in first)


def test_one_provider_cannot_vote_twice_for_tracking_variants():
    results=fuse_search_results({'exa':[row('https://example.com/a'),row('https://example.com/a?utm_source=x')]},result_limit=10)
    assert len(results)==1
    assert results[0]['metadata']['search_fusion_score']==1/61
    assert len(results[0]['metadata']['search_matches'])==2


def test_completion_order_cannot_choose_a_summary_over_an_original(monkeypatch):
    batches={'exa':[row('https://example.com/a',provider='exa',body='简短摘要',summary='简短摘要')],
             'serper':[row('https://example.com/a?utm_source=search',body='阿里巴巴原始报告正文。'*100,
                           summary='短摘要',content_origin='original_page',fetch_status='done',
                           document_pages=[{'page':1,'text':'阿里巴巴原始报告正文。'}])]}
    provider=fake_engines(monkeypatch,batches)
    monkeypatch.setattr(web_search,'as_completed',lambda futures:iter(futures))
    first=provider.multi_engine_search('阿里巴巴',30,candidate_limit=60)
    monkeypatch.setattr(web_search,'as_completed',lambda futures:reversed(list(futures)))
    second=provider.multi_engine_search('阿里巴巴',30,candidate_limit=60)
    assert first==second and first.audit==second.audit
    chosen=first[0]
    assert chosen['metadata']['provider']=='serper'
    assert chosen['content']==batches['serper'][0]['content']
    assert chosen['metadata']['document_pages']==batches['serper'][0]['metadata']['document_pages']
    assert chosen['metadata']['search_providers']==['exa','serper']


def test_failed_fetch_loser_cannot_overwrite_winners_pdf_metadata():
    full=row('https://example.com/report.pdf',body='原始PDF正文。'*100,fetch_status='done',document_pages=[{'page':1}])
    blocked=row('https://example.com/report.pdf#p=2',provider='exa',body='Access denied '*2000,
                fetch_status='blocked_or_challenge',document_extraction={'method':'failed'})
    results=fuse_search_results({'exa':[blocked],'serper':[full]},result_limit=30)
    assert results[0]['content']==full['content'] and 'document_extraction' not in results[0]['metadata']
    assert full['metadata']=={'provider':'serper','fetch_status':'done','document_pages':[{'page':1}]}


@pytest.mark.parametrize('a,b',[
    ('https://EXAMPLE.com:443/a?utm_source=wechat&id=1#section','https://example.com/a?id=1'),
    ('https://example.com/a?id=1&utm_medium=x&gclid=abc','https://example.com/a?id=1'),
    ('https://example.com','https://example.com/'),
])
def test_tracking_variants_share_an_identity(a,b):
    assert canonical_source_url(a)==canonical_source_url(b)


@pytest.mark.parametrize('a,b',[
    ('https://example.com/a?id=1','https://example.com/a?id=2'),
    ('https://example.com/a?source=1','https://example.com/a?source=2'),
    ('https://example.com/a?from=one','https://example.com/a?from=two'),
    ('https://example.com/a?signature=a','https://example.com/a?signature=b'),
    ('https://example.com/#/document/1','https://example.com/#/document/2'),
    ('https://example.com/a','https://example.com/a/'),
])
def test_document_selectors_and_real_routes_remain_distinct(a,b):
    assert canonical_source_url(a)!=canonical_source_url(b)


def test_fused_source_quality_no_longer_depends_on_which_engine_had_the_body():
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    source=row('https://www.gov.cn/zhengce/xx',body='阿里巴巴政策原文。'*300,
        search_score_kind='reciprocal_rank_fusion',score=100)
    a=w.score_source(source,query='阿里巴巴',target='阿里巴巴')
    source['metadata']['provider']='bocha';source['credibility_score']=1
    b=w.score_source(source,query='阿里巴巴',target='阿里巴巴')
    assert a['score']==b['score'] and a['provider_score']==b['provider_score']==0


def test_cleaner_deduplicates_before_tracking_noise_can_consume_another_fact():
    def source(i,url):
        return SimpleNamespace(id=i,url=url,title='阿里巴巴',content='阿里巴巴业务说明。'*100,summary='',
                               source_type='web',credibility_score=60,source_metadata={})
    sources=[source(1,'https://example.com/a?utm_source=x#top'),source(2,'https://example.com/a'),
             source(3,'https://example.com/a?id=2')]
    packet=ResearchWorkflow.__new__(ResearchWorkflow)._fast_clean_sources(sources,SimpleNamespace(target_type='company',target_name='阿里巴巴'))
    assert len(packet['facts'])==2


@pytest.mark.parametrize('requested,expected', [(30,20),(6,6),(0,0)])
def test_tavily_native_result_limit_is_respected(monkeypatch,requested,expected):
    monkeypatch.setenv('TAVILY_API_KEY','test-only')
    sent=[]
    def post(url,**kwargs):
        sent.append(kwargs['json'])
        return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'results':[]})
    monkeypatch.setattr(web_search.requests,'post',post)
    assert WebSearchProvider()._search_tavily('阿里巴巴',requested)==[]
    assert sent[0]['max_results']==expected


def test_no_engines_or_empty_urls_are_auditable(monkeypatch):
    provider=fake_engines(monkeypatch,{})
    result=provider.multi_engine_search('阿里巴巴',30,candidate_limit=180)
    assert result==[] and result.audit['raw_count']==0
    malformed=fuse_search_results({'serper':[None,{},row('')]},result_limit=30)
    assert malformed==[] and malformed.audit['invalid_or_empty_url_count']==3


def test_expanded_candidates_reach_the_real_collector_and_sqlite(monkeypatch,tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from database import Base
    from models import User,ResearchProject
    from research_store import ResearchObjectStore
    batches=alibaba_batches()
    long_title='阿里巴巴披露'+'资'*(518-len('阿里巴巴披露'))
    long_url=next(iter(batches.values()))[0]['url']
    for rows in batches.values():
        for r in rows:
            r['content']='阿里巴巴集团公开业务资料与经营信息。'*100
            r['summary']='阿里巴巴公开资料摘要'
            if canonical_source_url(r['url'])==canonical_source_url(long_url):r['title']=long_title
    provider=fake_engines(monkeypatch,batches)
    monkeypatch.setattr('research_workflow.web_search_provider',provider)
    monkeypatch.setenv('ONLINE_SOURCE_MAX_PER_HOST','8')
    monkeypatch.setenv('ONLINE_TECH_SOURCE_MAX_PER_PROJECT','25')
    store=ResearchObjectStore();store.mode='local';store.local_root=tmp_path/'objects'
    monkeypatch.setattr('research_workflow.research_store',store)
    monkeypatch.setattr('report_agents.company_risk_register.recall_discovery_queries',lambda *a:[])
    monkeypatch.setattr('report_agents.company_assessment.assessment_discovery_queries',lambda *a:[])
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    w._expand_search_queries=lambda *a:[{'query':'阿里巴巴','module':'公司背景'}]
    w.evaluate_source_quality=lambda *a:{'information_gaps':[]}
    w._gap_queries=lambda *a:[]
    def no_fetch(*a,**kw):raise AssertionError('Existing complete bodies must not be fetched again')
    w._fetch_web_url_with_timeout=no_fetch
    events=[]
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            user=User(username='search-regression',password_hash='not-a-real-credential');db.add(user);db.flush()
            project=ResearchProject(created_by_id=user.id,title='阿里巴巴',target_name='阿里巴巴',target_type='company',industry='互联网')
            db.add(project);db.commit()
            added=w.collect_web_sources(db,project,[],[],30,emit=events.append,
                plan={'modules':[]},intake={'target_type':'company','target_name':'阿里巴巴','max_search_rounds':1},reuse_archived=False)
            # 8 shared-host URLs + 8 per unique provider host. The 24 domain
            # quota skips are intentional, explicit events, not hidden top-30 loss.
            assert added==len(project.sources)==56
            assert len({canonical_source_url(s.url) for s in project.sources})==56
            assert sum(e['label']=='跳过同域名过量来源' for e in events)==24
            assert not any(e['label']=='单条网页归档失败，继续下一条' for e in events)
            assert all(s.source_metadata['search_matches'] for s in project.sources)
            long_source=next(s for s in project.sources if canonical_source_url(s.url)==canonical_source_url(long_url))
            assert len(long_source.title)<=512
            assert long_source.source_metadata['full_source_title']==long_title
            assert long_source.source_metadata['title_truncated'] is True
    finally:
        engine.dispose()
