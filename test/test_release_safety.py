"""Exercise file boundaries and workflow admission with isolated databases and storage."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import auth
import api as legacy
import research_api as api
from account_migrations import migrate_accounts
from models import ParentChunk, ResearchArtifact, ResearchProject, ResearchSource, User
from research_store import ResearchObjectStore
from http_delivery import RequestBodyLimit


@pytest.fixture
def site(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path/'site.db'), connect_args={'check_same_thread':False})
    migrate_accounts(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add_all([User(id=1,username='owner',role='user',password_hash='unused'),
                    User(id=2,username='other',role='user',password_hash='unused'),
                    User(id=3,username='admin',role='admin',password_hash='unused')])
        db.flush()
        db.add_all([ResearchProject(id=1,title='Own project',created_by_id=1),
                    ResearchProject(id=2,title='Other project',created_by_id=2)])
        db.commit()
    def get_db():
        with factory() as db:yield db
    app=FastAPI();app.include_router(api.router);app.include_router(legacy.router)
    app.add_middleware(RequestBodyLimit)
    app.dependency_overrides[auth.get_db]=get_db
    @app.get('/responsive-check')
    async def responsive():return {'ok':True}
    monkeypatch.setattr(api,'SessionLocal',factory)
    monkeypatch.setattr(api,'UPLOAD_DIR',tmp_path/'uploads')
    monkeypatch.setattr(api.research_store,'mode','local')
    monkeypatch.setattr(api.research_store,'local_root',tmp_path/'objects')
    monkeypatch.setattr(api,'_lightweight_upload_text',lambda path,*a:path.read_text())
    monkeypatch.setattr(api,'_merge_upload_identity_into_intake',lambda *a:{})
    monkeypatch.setattr(api,'_index_source_for_rag',lambda *a:{'vector_index_status':'disabled'})
    api.RUNNING_PROJECT_IDS.clear();api.RUNNING_PROJECT_OWNERS.clear()
    headers={name:{'Authorization':'Bearer '+auth.create_access_token(name,role)}
             for name,role in [('owner','user'),('other','user'),('admin','admin')]}
    try:
        with TestClient(app) as client:yield SimpleNamespace(client=client,headers=headers,db=factory,root=tmp_path)
    finally:
        api.RUNNING_PROJECT_IDS.clear();api.RUNNING_PROJECT_OWNERS.clear();engine.dispose()


@pytest.mark.parametrize('key',['../outside.txt','/absolute.txt','projects/1/../../outside.txt',
                               'projects\\1\\outside.txt','C:/outside.txt','a//b','a/./b','a\x00b'])
def test_store_rejects_unsafe_identifiers_before_disk_or_minio(tmp_path,monkeypatch,key):
    store=ResearchObjectStore();store.local_root=tmp_path/'objects'
    for mode in ['local','minio']:
        store.mode=mode
        monkeypatch.setattr(store,'_client',lambda:pytest.fail('invalid key reached network client'))
        for operation in [lambda:store.get_bytes(key),lambda:store.get_text(key),
                          lambda:store.put_bytes(key,b'no'),lambda:store.delete_object(key),lambda:store.delete_prefix(key)]:
            with pytest.raises(ValueError):operation()
    assert not (tmp_path/'objects').exists()


def test_manual_metadata_cannot_supply_file_authority(site):
    victim=site.root/'outside.txt';victim.write_text('PRIVATE SENTINEL')
    other_upload=api.UPLOAD_DIR/'2'/'private.txt';other_upload.parent.mkdir(parents=True);other_upload.write_text('OTHER ORIGINAL')
    reply=site.client.post('/research/projects/1/sources',headers=site.headers['owner'],json={
        'title':'My note','content':'OWN NOTE','metadata':{'original_object_key':'../outside.txt',
            'local_path':str(other_upload),'original_filename':'outside.txt','images':[{'url':'local://'+str(victim)}],'module':'interview'}})
    assert reply.status_code==200,reply.text
    sid=reply.json()['id']
    with site.db() as db:assert db.get(ResearchSource,sid).source_metadata=={'module':'interview'}
    assert site.client.get(f'/research/sources/{sid}/download',headers=site.headers['owner']).content==b'OWN NOTE'
    assert site.client.delete(f'/research/sources/{sid}',headers=site.headers['owner']).status_code==200
    assert victim.read_text()=='PRIVATE SENTINEL' and other_upload.read_text()=='OTHER ORIGINAL'


@pytest.mark.parametrize('key',['../outside.txt','projects/2/uploads/private.txt'])
def test_existing_forged_metadata_is_blocked_on_read_and_delete(site,key):
    outside=site.root/'outside.txt';outside.write_text('PRIVATE SENTINEL')
    api.research_store.put_text('projects/2/uploads/private.txt','OTHER ORIGINAL')
    with site.db() as db:
        row=ResearchSource(project_id=1,source_type='manual',title='Old metadata',content='OWN NOTE',
                           source_metadata={'original_object_key':key})
        db.add(row);db.commit();sid=row.id
    assert site.client.get(f'/research/sources/{sid}/download',headers=site.headers['owner']).status_code==404
    assert site.client.delete(f'/research/sources/{sid}',headers=site.headers['owner']).status_code==200
    assert outside.read_text()=='PRIVATE SENTINEL'
    assert api.research_store.get_text('projects/2/uploads/private.txt')=='OTHER ORIGINAL'


def upload(site,content):
    r=site.client.post('/research/projects/1/upload',headers=site.headers['owner'],files={'file':('review.txt',content,'text/plain')})
    assert r.status_code==200,r.text
    return r.json()['source']['id']


def test_same_name_originals_remain_distinct_and_deleting_one_keeps_the_other(site):
    first=upload(site,b'FIRST ORIGINAL');second=upload(site,b'SECOND ORIGINAL')
    assert first!=second
    for sid,content in [(first,b'FIRST ORIGINAL'),(second,b'SECOND ORIGINAL')]:
        assert site.client.get(f'/research/sources/{sid}/download',headers=site.headers['owner']).content==content
    assert site.client.delete(f'/research/sources/{first}',headers=site.headers['owner']).status_code==200
    assert site.client.get(f'/research/sources/{second}/download',headers=site.headers['owner']).content==b'SECOND ORIGINAL'


def test_report_history_keeps_its_original_when_the_upload_source_is_removed(site):
    sid=upload(site,b'REVIEWED ORIGINAL')
    with site.db() as db:
        source=db.get(ResearchSource,sid)
        row=ResearchArtifact(project_id=1,artifact_type='desktop_report',title='Reviewed',version=1,
            content='REVIEWED TEXT',created_by='human_review',artifact_metadata={
                'review_original_object_key':source.source_metadata['original_object_key'],'original_filename':'review.txt'})
        db.add(row);db.commit();aid=row.id
    assert site.client.delete(f'/research/sources/{sid}',headers=site.headers['owner']).status_code==200
    assert site.client.get(f'/research/artifacts/{aid}/download',headers=site.headers['owner']).content==b'REVIEWED ORIGINAL'


def test_legacy_shared_original_is_not_deleted_while_another_source_references_it(site):
    key=api.research_store.put_text('projects/1/uploads/legacy.txt','SHARED ORIGINAL')
    with site.db() as db:
        rows=[ResearchSource(project_id=1,source_type='upload',title='Legacy',source_metadata={'original_object_key':key}) for _ in range(2)]
        db.add_all(rows);db.commit();first,second=[r.id for r in rows]
    assert site.client.delete(f'/research/sources/{first}',headers=site.headers['owner']).status_code==200
    assert site.client.get(f'/research/sources/{second}/download',headers=site.headers['owner']).content==b'SHARED ORIGINAL'


def test_non_stream_research_runs_off_loop_and_limits_are_released(site,monkeypatch):
    entered,release=threading.Event(),threading.Event()
    def work(*args,**kwargs):entered.set();assert release.wait(5);return [],0
    monkeypatch.setattr(api.research_workflow,'run_project',work)
    monkeypatch.setattr(api,'_refresh_failed_upload_ocr',lambda *a:{})
    monkeypatch.setattr(api,'_save_project_intake',lambda *a:None)
    with ThreadPoolExecutor(max_workers=3) as pool:
        running=pool.submit(site.client.post,'/research/projects/1/run',headers=site.headers['owner'],json={})
        try:
            assert entered.wait(2)
            quick=pool.submit(site.client.get,'/responsive-check')
            assert quick.result(timeout=1).json()=={'ok':True}
            denied=site.client.post('/research/projects/2/run',headers=site.headers['other'],json={})
            assert denied.status_code==429
            stream=site.client.post('/research/projects/2/run/stream',headers=site.headers['other'],json={})
            assert stream.status_code==200 and '"type": "error"' in stream.text
        finally:release.set()
        assert running.result(timeout=3).status_code==200
    assert not api.RUNNING_PROJECT_IDS and not api.RUNNING_PROJECT_OWNERS


@pytest.mark.parametrize('filename',['../victim.docx','..\\victim.docx'])
def test_admin_upload_rejects_unsafe_filename_before_touching_services(site,monkeypatch,filename):
    monkeypatch.setattr(legacy.milvus_manager,'init_collection',lambda:pytest.fail('unsafe file reached indexing'))
    r=site.client.post('/documents/upload',headers=site.headers['admin'],files={'file':(filename,b'invalid')})
    assert r.status_code==400


def test_raw_quote_in_filename_is_invalid():
    from upload_limits import validate_filename
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:validate_filename('bad"file.docx')
    assert error.value.status_code==400


def test_admin_failed_parse_preserves_old_indexes_and_same_name_is_explicit_conflict(site,monkeypatch):
    calls=[]
    monkeypatch.setattr(legacy,'UPLOAD_DIR',site.root/'library')
    monkeypatch.setattr(legacy.milvus_manager,'init_collection',lambda:None)
    monkeypatch.setattr(legacy.milvus_manager,'query',lambda **kw:[])
    monkeypatch.setattr(legacy.milvus_manager,'delete',lambda *a:calls.append('delete-vector'))
    monkeypatch.setattr(legacy.parent_chunk_store,'contains_filename',lambda *a:False)
    monkeypatch.setattr(legacy.parent_chunk_store,'delete_by_filename',lambda *a:calls.append('delete-parent'))
    monkeypatch.setattr(legacy.loader,'load_document',lambda *a:(_ for _ in ()).throw(ValueError('bad doc')))
    failed=site.client.post('/documents/upload',headers=site.headers['admin'],files={'file':('new.docx',b'invalid')})
    assert failed.status_code==400 and calls==[]
    legacy.UPLOAD_DIR.joinpath('old.docx').write_bytes(b'OLD ORIGINAL')
    duplicate=site.client.post('/documents/upload',headers=site.headers['admin'],files={'file':('old.docx',b'invalid')})
    assert duplicate.status_code==409 and calls==[]
    assert legacy.UPLOAD_DIR.joinpath('old.docx').read_bytes()==b'OLD ORIGINAL'


def test_file_limit_rejects_before_persisting_upload(site,monkeypatch):
    monkeypatch.setenv('MAX_UPLOAD_BYTES','4')
    r=site.client.post('/research/projects/1/upload',headers=site.headers['owner'],files={'file':('big.txt',b'12345')})
    assert r.status_code==413 and not api.UPLOAD_DIR.exists()
    monkeypatch.setenv('MAX_JSON_BYTES','4')
    r=site.client.post('/research/projects/1/sources',headers=site.headers['owner'],json={'content':'too long'})
    assert r.status_code==413


def test_chunked_json_body_is_limited_without_content_length(site,monkeypatch):
    monkeypatch.setenv('MAX_JSON_BYTES','4')
    r=site.client.post('/research/projects/1/sources',headers={**site.headers['owner'],
        'Content-Type':'application/json'},content=iter([b'{"content":',b'"large"}']))
    assert r.status_code==413


def test_restart_recovers_a_recent_interrupted_job(site):
    with site.db() as db:
        db.get(ResearchProject,1).status='report_generating';db.commit()
    assert api.recover_stale_research_projects()==1
    with site.db() as db:assert db.get(ResearchProject,1).status=='paused'


def test_existing_parent_records_are_checked_without_loading_text(site,monkeypatch):
    import parent_chunk_store
    monkeypatch.setattr(parent_chunk_store,'SessionLocal',site.db)
    with site.db() as db:
        db.add(ParentChunk(chunk_id='existing::parent',filename='existing.docx',text='retained parent'));db.commit()
    assert legacy.parent_chunk_store.contains_filename('existing.docx')
    assert not legacy.parent_chunk_store.contains_filename('new.docx')
