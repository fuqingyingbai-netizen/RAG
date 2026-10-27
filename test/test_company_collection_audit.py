from types import SimpleNamespace
import pytest
from company_collection_audit import CollectionAudit,primary_candidate,module_host_counts

TARGET='青禾制造股份有限公司'


def test_primary_reserve_does_not_use_query_echo_or_an_untrusted_domain():
    assert primary_candidate({'url':'https://www.hkexnews.hk/filing.pdf','title':TARGET+'董事会公告'},TARGET)
    assert not primary_candidate({'url':'https://www.hkexnews.hk/filing.pdf','title':'远山科技有限公司公告',
                                   'summary':TARGET,'metadata':{'query':TARGET}},TARGET)
    assert not primary_candidate({'url':'https://spam.example/filing.pdf','title':TARGET+'公告'},TARGET)
    assert primary_candidate({'url':'https://issuer.example/a','title':TARGET+'公告'},TARGET,{'issuer.example'})


def test_deferred_candidate_remains_auditable_and_is_not_labelled_irrelevant():
    audit=CollectionAudit(TARGET)
    item={'url':'https://www.hkexnews.hk/a.pdf','title':TARGET+'原件'}
    audit.candidate(item,'query','治理')
    audit.observe(dict(stage='web_search',url=item['url'],query='query',module='治理',label='跳过同域名过量来源',status='skipped',skip_reason='deferred_host_budget'))
    result=audit.snapshot([])
    assert result['candidates'][0]['outcome']=='deferred_host_budget'
    assert result['candidates'][0]['title']==item['title']
    assert result['candidates'][0]['archived_source_id'] is None
    # The same URL can subsequently be admitted for another research question.
    audit.candidate(item,'another','业务')
    audit.observe(dict(stage='web_search',url=item['url'],query='another',module='业务',label='网页来源已保存',status='done',budget_route='primary_document_module_reserve'))
    result=audit.snapshot([dict(url=item['url'],id=10)])
    assert result['summary']['outcomes']=={'deferred_host_budget':1,'archived':1}
    assert all(r['archived_source_id']==10 for r in result['candidates'])


def test_module_reserve_counts_originals_without_double_counting_query_tracker_variants():
    rows=[dict(url='https://example.org/a?utm_source=x',source_metadata={'module':'治理'}),
          dict(url='https://example.org/a',source_metadata={'module':'治理'}),
          dict(url='https://example.org/b',source_metadata={'module':'业务'})]
    assert module_host_counts(rows)=={('example.org','治理'):1,('example.org','业务'):1}


@pytest.mark.parametrize('provider_text',[False,True])
def test_real_collector_can_admit_a_primary_for_an_uncovered_module_after_another_module_deferred_it(monkeypatch,tmp_path,provider_text):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from database import Base
    from models import User,ResearchProject,ResearchSource,ResearchArtifact
    from research_store import ResearchObjectStore
    from research_workflow import ResearchWorkflow
    monkeypatch.setenv('ONLINE_SOURCE_MAX_PER_HOST','1')
    monkeypatch.setenv('ONLINE_AUTHORITY_SOURCE_MAX_PER_HOST','1')
    monkeypatch.setenv('COMPANY_PRIMARY_SOURCES_PER_MODULE_HOST','2')
    monkeypatch.setattr('report_agents.company_risk_register.recall_discovery_queries',lambda *a:[])
    monkeypatch.setattr('report_agents.company_assessment.assessment_discovery_queries',lambda *a:[])
    store=ResearchObjectStore();store.mode='local';store.local_root=tmp_path/'objects'
    monkeypatch.setattr('research_workflow.research_store',store)
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    queries=[{'query':'governance','module':'治理'},{'query':'business','module':'业务'}]
    def row(name):return dict(url='https://www.hkexnews.hk/'+name+'.pdf',title=TARGET+'公告',
        content=TARGET+'公开披露董事会及主营业务事项。'*100,summary='',metadata={'provider':'offline',**({'content_origin':'provider_raw_content'} if provider_text else {})})
    w._expand_search_queries=lambda *a:queries
    w._search_query_items_parallel=lambda *a:[(queries[0],[row('a'),row('b')]),
        (queries[1],[row('a'),row('b'),row('c')])]
    w.evaluate_source_quality=lambda *a:{'information_gaps':[]}
    w._gap_queries=lambda *a:[]
    w._fetch_web_url_with_timeout=lambda *a,**kw:{'status':'done','content':row('a')['content'],'content_type':'application/pdf','pages':1}
    if provider_text:
        def forbidden_fetch(*args,**kwargs):raise AssertionError('supplied original must not be discarded or fetched again')
        w._fetch_web_url_with_timeout=forbidden_fetch
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            user=User(username='reserve-regression',password_hash='not-a-credential');db.add(user);db.flush()
            p=ResearchProject(created_by_id=user.id,title=TARGET,target_name=TARGET,target_type='company',industry='制造')
            db.add(p);db.flush()
            for number in range(2):db.add(ResearchSource(project_id=p.id,url=f'https://www.hkexnews.hk/old{number}.pdf',
                title=TARGET,content=TARGET+'历史资料',source_type='filing',source_metadata={'module':'治理'}))
            db.commit()
            added=w.collect_web_sources(db,p,[],[],10,plan={'modules':[]},
                intake={'target_type':'company','max_search_rounds':1},reuse_archived=False)
            assert added==(3 if provider_text else 2) and len(p.sources)==(5 if provider_text else 4)
            expected={'https://www.hkexnews.hk/c.pdf'} if provider_text else {'https://www.hkexnews.hk/a.pdf','https://www.hkexnews.hk/b.pdf'}
            assert {s.url for s in p.sources if (s.source_metadata or {}).get('module')=='业务'}==expected
            rows=p.company_collection_audit_package['candidates']
            if not provider_text:assert any(r['url'].endswith('/a.pdf') and r['module']=='治理' and r['outcome']=='deferred_host_budget' for r in rows)
            else:assert all(s.source_metadata.get('retained_provider_receipt') for s in p.sources if s.url.endswith(('/a.pdf','/b.pdf','/c.pdf')))
            assert any(r['url'].endswith('/a.pdf') and r['module']=='业务' and (
                r['archived_source_id'] is not None if provider_text else r['outcome']=='archived') for r in rows)
            assert db.query(ResearchArtifact).filter_by(artifact_type='company_collection_audit').count()==1
    finally:engine.dispose()
