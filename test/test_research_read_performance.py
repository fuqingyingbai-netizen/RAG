"""Prevent expensive UI reads from loading archived research bodies."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine,event
from sqlalchemy.orm import sessionmaker

import auth
from account_migrations import migrate_accounts
from models import ResearchArtifact,ResearchProject,ResearchSource,User
import research_api as api


@pytest.fixture
def read_api(tmp_path,monkeypatch):
    engine=create_engine('sqlite:///'+str(tmp_path/'reads.db'),connect_args={'check_same_thread':False})
    migrate_accounts(engine); factory=sessionmaker(engine,expire_on_commit=False)
    with factory() as db:
        db.add_all([User(id=1,username='read-owner',role='user',password_hash='unused'),
                    User(id=2,username='read-other',role='user',password_hash='unused')]);db.flush()
        db.add(ResearchProject(id=1,title='Synthetic read fixture',created_by_id=1,status='failed'));db.flush()
        for id,kind,body,metadata in [
            (1,'project_intake','{}',{'company_name':'Synthetic subject'}),
            (2,'cleaned_facts','PRIVATE_FACT_BODY'*10000,{}),
            (3,'desktop_report','SAVED_REPORT_BODY'*10000,{'docx_object_key':'synthetic/report.docx'}),
            (4,'workflow_trace',json.dumps([{'stage':'report','status':'running'}]),{'last_event_timestamp':'2026-10-21T01:00:00'}),
            (5,'proposal','\n\t\u3000 ',{}),
        ]:
            db.add(ResearchArtifact(id=id,project_id=1,artifact_type=kind,title=kind,content=body,artifact_metadata=metadata))
        db.add(ResearchSource(project_id=1,source_type='upload',title='Source',content='PRIVATE_SOURCE_BODY'*10000,summary='Summary',object_key='synthetic/source.txt'))
        db.commit()
    app=FastAPI();app.include_router(api.router)
    @app.get('/responsive-check')
    async def responsive_check(): return {'ok':True}
    def get_db():
        with factory() as db:yield db
    app.dependency_overrides[auth.get_db]=get_db
    monkeypatch.setattr(api,'_is_project_running',lambda _:False)
    monkeypatch.setattr(api.research_workflow,'run_project',lambda *a,**k:pytest.fail('read must not run research'))
    statements=[]
    def capture(conn,cursor,statement,parameters,context,executemany): statements.append((statement,parameters))
    event.listen(engine,'before_cursor_execute',capture)
    try:
        with TestClient(app) as client:
            headers={'Authorization':'Bearer '+auth.create_access_token('read-owner','user')}
            statements.clear();yield client,headers,statements
    finally:engine.dispose()


def test_intake_read_filters_in_sql_instead_of_loading_the_relationship(read_api):
    client,headers,statements=read_api
    response=client.get('/research/projects/1/run-intake',headers=headers)
    assert response.status_code==200 and response.json()['intake']['company_name']=='Synthetic subject'
    queries=[(sql,params) for sql,params in statements if 'FROM research_artifacts' in sql]
    assert len(queries)==1
    assert 'project_intake' in queries[0][1] and 'LIMIT' in queries[0][0]
    assert len(response.content)<1024


def test_detail_omits_archived_bodies_and_preserves_saved_text_and_trace_meaning(read_api):
    client,headers,statements=read_api
    response=client.get('/research/projects/1/detail',headers=headers)
    assert response.status_code==200
    data=response.json()
    assert data['recovery']['saved']['report_text_records']==1
    assert data['recovery']['saved']['proposal_text_records']==0
    assert data['trace']==[{'stage':'report','status':'running'}]
    assert data['source_count']==1 and data['artifact_count']==5
    assert 'PRIVATE_' not in response.text and 'SAVED_REPORT_BODY' not in response.text
    assert all('research_sources.content AS' not in sql for sql,_ in statements)
    for sql,params in statements:
        if 'research_artifacts.content AS' in sql:
            assert 'project_intake' in params or tuple(params)==(4,), (sql,params)


def test_lightweight_review_parameters_remain_authenticated_and_owner_scoped(read_api):
    client,headers,_=read_api
    path='/research/projects/1/run-intake'
    assert client.get(path).status_code==401
    other={'Authorization':'Bearer '+auth.create_access_token('read-other','user')}
    assert client.get(path,headers=other).status_code==403
    assert client.get('/research/projects/999/run-intake',headers=headers).status_code==404


def test_repository_returns_only_requested_excerpts_without_loading_whole_bodies(read_api):
    client,headers,statements=read_api
    response=client.get('/research/repository?limit=20',headers=headers)
    assert response.status_code==200
    rows=response.json()['results']
    report=next(row for row in rows if row.get('artifact_type')=='desktop_report')
    assert report['snippet']==('SAVED_REPORT_BODY'*10000)[:500]
    assert all(len(row['snippet'])<=500 for row in rows)
    assert all('research_artifacts.content AS' not in sql and 'research_sources.content AS' not in sql for sql,_ in statements)
    assert any('substr(' in sql for sql,_ in statements)
    assert client.get('/research/search?q=SAVED_REPORT_BODY&limit=20',headers=headers).status_code==200


def test_waiting_for_a_detail_read_does_not_block_other_requests(read_api,monkeypatch):
    client,headers,_=read_api
    entered,release=threading.Event(),threading.Event()
    original=api._get_project
    def slow(db,project_id,user):
        entered.set();assert release.wait(5)
        return original(db,project_id,user)
    monkeypatch.setattr(api,'_get_project',slow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        detail=pool.submit(client.get,'/research/projects/1/detail',headers=headers)
        try:
            assert entered.wait(2)
            quick=pool.submit(client.get,'/responsive-check')
            assert quick.result(timeout=1).json()=={'ok':True}
        finally: release.set()
        assert detail.result(timeout=3).status_code==200


def test_source_list_never_transports_unused_full_text(read_api):
    client,headers,statements=read_api
    response=client.get('/research/projects/1/sources',headers=headers)
    assert response.status_code==200 and response.json()[0]['summary']=='Summary'
    assert 'PRIVATE_SOURCE_BODY' not in response.text
    assert all('research_sources.content AS' not in sql for sql,_ in statements)


def test_metadata_only_artifact_list_is_opt_in_and_never_loads_bodies(read_api):
    client,headers,statements=read_api
    response=client.get('/research/projects/1/artifacts?include_content=false',headers=headers)
    assert response.status_code==200 and len(response.json())==5
    assert all(row['content']=='' for row in response.json())
    assert all('research_artifacts.content AS' not in sql for sql,_ in statements)
    response=client.get('/research/projects/1/artifacts',headers=headers)
    assert any(row['content'].startswith('PRIVATE_FACT_BODY') for row in response.json())


@pytest.mark.parametrize('path,expected_key',[
    ('/research/artifacts/3/download','synthetic/report.docx'),
    ('/research/sources/1/download','synthetic/source.txt'),
])
def test_original_downloads_skip_text_bodies_and_keep_owner_checks(read_api,monkeypatch,path,expected_key):
    client,headers,statements=read_api
    keys=[]
    def get_bytes(key):
        keys.append(key);return b'SYNTHETIC ORIGINAL'
    monkeypatch.setattr(api.research_store,'get_bytes',get_bytes)
    assert client.get(path).status_code==401
    other={'Authorization':'Bearer '+auth.create_access_token('read-other','user')}
    assert client.get(path,headers=other).status_code==403
    assert keys==[]
    statements.clear()
    response=client.get(path,headers=headers)
    assert response.status_code==200 and response.content==b'SYNTHETIC ORIGINAL'
    assert keys==[expected_key] and 'attachment;' in response.headers['content-disposition']
    assert all('research_sources.content AS' not in sql and 'research_artifacts.content AS' not in sql for sql,_ in statements)


def test_download_retains_database_fallback_when_export_is_missing(read_api,monkeypatch):
    client,headers,_=read_api
    def missing(_):raise FileNotFoundError('synthetic missing export')
    monkeypatch.setattr(api.research_store,'get_bytes',missing)
    response=client.get('/research/artifacts/3/download',headers=headers)
    assert response.status_code==200
    assert response.content==b'SAVED_REPORT_BODY'*10000
    assert '.md' in response.headers['content-disposition']


def test_slow_object_storage_download_does_not_block_other_requests(read_api,monkeypatch):
    client,headers,_=read_api
    entered,release=threading.Event(),threading.Event()
    def slow(_):
        entered.set();assert release.wait(5);return b'SYNTHETIC ORIGINAL'
    monkeypatch.setattr(api.research_store,'get_bytes',slow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        download=pool.submit(client.get,'/research/artifacts/3/download',headers=headers)
        try:
            assert entered.wait(2)
            quick=pool.submit(client.get,'/responsive-check')
            assert quick.result(timeout=1).json()=={'ok':True}
        finally:release.set()
        assert download.result(timeout=3).content==b'SYNTHETIC ORIGINAL'


def test_first_upload_parsing_does_not_block_other_requests(read_api, monkeypatch, tmp_path):
    client, headers, _ = read_api
    entered, release = threading.Event(), threading.Event()
    def slow_parse(*_):
        entered.set(); assert release.wait(5)
        return 'Synthetic uploaded source, fully parsed.'
    monkeypatch.setattr(api, 'UPLOAD_DIR', tmp_path/'upload')
    monkeypatch.setattr(api, '_lightweight_upload_text', slow_parse)
    monkeypatch.setattr(api, '_merge_upload_identity_into_intake', lambda *a: {})
    monkeypatch.setattr(api, '_index_source_for_rag', lambda *a: {'vector_index_status':'disabled'})
    monkeypatch.setattr(api.research_store, 'put_bytes', lambda *a: 'synthetic/original.docx')
    monkeypatch.setattr(api.research_store, 'put_text', lambda *a: 'synthetic/parsed.txt')
    with ThreadPoolExecutor(max_workers=2) as pool:
        upload = pool.submit(client.post, '/research/projects/1/upload', headers=headers,
                             files={'file':('synthetic.docx',b'synthetic file','application/octet-stream')})
        try:
            assert entered.wait(2)
            quick = pool.submit(client.get, '/responsive-check')
            assert quick.result(timeout=1).json() == {'ok':True}
        finally:
            release.set()
        response = upload.result(timeout=3)
        assert response.status_code == 200, response.text
