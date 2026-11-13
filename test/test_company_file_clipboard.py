"""File API acceptance, real original bytes and persistent retry receipts."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import uuid

import pytest
from sqlalchemy import select
from test_company_workspace import setup, upload, project, stored_original
from test_company_root_files import ready
from company_catalog import CompanyDocument, document_store
from company_recycle import RecycleItem, purge_due
from company_file_operations import file_lock
from company_retrieval import distinct_sources


def current(s, row):
    return s.client.get('/company-knowledge/documents/'+row['id']+'/versions').json()['versions'][0]


def transfer(s, row, action='copy', **target):
    path='/company-knowledge/documents/'+row['id']+'/'+action
    data=dict(request_id=uuid.uuid4().hex, expected_modified_at=current(s,row)['modified_at'], **target)
    pre=s.client.post(path+'-preview',json=data)
    assert pre.status_code==200, pre.text
    response=s.client.post(path,json=data|{'confirmation':pre.json()['confirmation']})
    return response, data|{'confirmation':pre.json()['confirmation']}


def test_upload_duplicate_shares_bytes_private_acl_and_sequential_copy_names(setup):
    source=upload(setup,root='true',visibility='restricted',readers='["bob"]',request_id='initial').json()
    for n in (1,2):
        result=upload(setup,root='true',request_id='duplicate'+str(n))
        assert result.status_code==202, result.text
        row=result.json()
        assert row['title']=='evidence（副本'+('2' if n==2 else '')+'）.txt'
        assert row['display_title'].endswith('_V1.txt') and row['version']==1
        assert row['visibility']=='restricted' and row['readers']==['bob']
        assert row['copy_origin']['source_id']==source['id'] and row['upload_notice']
        with setup.db() as db:
            assert db.get(CompanyDocument,row['id']).object_key==db.get(CompanyDocument,source['id']).object_key
        replay=upload(setup,root='true',request_id='duplicate'+str(n)).json()
        assert replay['id']==row['id']
    assert len(list(document_store().local_root.rglob('*.txt')))==1
    mismatch=upload(setup,payload=b'other',root='true',request_id='duplicate1')
    assert mismatch.status_code==409


def test_new_version_latest_only_history_and_download_name_normalization(setup):
    first=upload(setup,root='true').json()
    second=upload(setup,root='true',payload=b'second').json()
    assert first['display_title']=='evidence_V1.txt' and second['display_title']=='evidence_V2.txt'
    third=upload(setup,root='true',name='evidence_V2.txt',payload=b'third').json()
    assert third['title']=='evidence.txt' and third['version']==3
    from company_file_operations import upload_family
    with setup.db() as db:
        canonical, versions = upload_family(db,'test-index','alice','','','','evidence_V2_水印副本.txt')
        assert canonical=='evidence.txt' and len(versions)==3
    listing=setup.client.get('/company-knowledge/documents').json()['documents']
    assert [row['id'] for row in listing]==[third['id']]
    history=setup.client.get('/company-knowledge/documents/'+third['id']+'/versions').json()['versions']
    assert [r['version'] for r in history]==[3,2,1] and [r['is_latest'] for r in history]==[True,False,False]
    assert stored_original(setup,first['id'])!=stored_original(setup,second['id'])
    response=setup.client.get('/company-knowledge/documents/'+second['id']+'/download')
    from urllib.parse import unquote
    assert unquote(response.headers['x-download-filename']).startswith('evidence_V2')
    assert setup.client.get('/company-knowledge/my-projects').json()['document_count']==1


def test_copy_latest_only_new_index_receipt_and_source_snapshot(setup):
    old=upload(setup,root='true').json();ready(setup,old)
    source=upload(setup,root='true',payload=b'new').json();ready(setup,source)
    target=project(setup,'目标')
    before=len(setup.scheduled)
    response,data=transfer(setup,source,project_id=target['id'])
    assert response.status_code==201, response.text
    clone=response.json()['document']
    assert clone['version']==1 and clone['cloud_id'] is None and clone['state']=='queued'
    assert clone['knowledge_project_id']==target['id'] and clone['copy_origin']['source_version']==2
    assert setup.scheduled[before:]==[clone['id']]
    assert stored_original(setup,clone['id'])==b'new'
    path='/company-knowledge/documents/'+source['id']+'/copy'
    assert setup.client.post(path,json=data).json()['document']['id']==clone['id']
    assert setup.client.post(path+'-preview',json=data).json()['completed']
    assert len(setup.client.get('/company-knowledge/documents').json()['documents'])==2
    stale=dict(data,request_id='fresh',expected_modified_at='stale')
    assert setup.client.post(path+'-preview',json=stale).status_code==409
    oldpath='/company-knowledge/documents/'+old['id']+'/copy-preview'
    assert setup.client.post(oldpath,json={'project_id':target['id']}).status_code==409


def test_cut_moves_family_replay_after_lost_response_and_conflict_never_overwrites(setup):
    rows=[upload(setup,root='true',payload=x).json() for x in (b'first',b'second')]
    for row in rows:ready(setup,row)
    target=project(setup,'目标',visibility='restricted',readers=['bob'])
    response,data=transfer(setup,rows[-1],'move',project_id=target['id'])
    assert response.status_code==200 and response.json()['moved_version_count']==2
    path='/company-knowledge/documents/'+rows[-1]['id']+'/move'
    replay=setup.client.post(path+'-preview',json=data)
    assert replay.json()['completed'] and replay.json()['result']['document']['id']==rows[-1]['id']
    assert setup.client.post(path,json=data).json()['moved_version_count']==2
    with setup.db() as db:
        assert all(db.get(CompanyDocument,r['id']).knowledge_project_id==target['id'] for r in rows)
    other=upload(setup,root='true',payload=b'root file').json();ready(setup,other)
    pre=setup.client.post('/company-knowledge/documents/'+other['id']+'/move-preview',json={'project_id':target['id']})
    assert pre.status_code==409 and stored_original(setup,other['id'])==b'root file'


@pytest.mark.parametrize('problem,status',[('busy',409),('note',422),('research',422),('permission',403),('library',422),('missing',409)])
def test_copy_rejects_invalid_sources_and_destinations(setup,problem,status):
    row=upload(setup,root='true').json();ready(setup,row)
    target=project(setup,'目标',category='项目经验' if problem=='library' else '项目原件')
    if problem=='busy':
        with setup.db() as db:
            db.get(CompanyDocument,row['id']).state='parsing';db.commit()
    if problem=='note':ready(setup,row,note_id='note')
    if problem=='research':ready(setup,row,research_project_id=123)
    if problem=='permission':setup.user.id,setup.user.username=2,'bob'
    if problem=='missing':
        with setup.db() as db:document_store().delete_object(db.get(CompanyDocument,row['id']).object_key)
    response=setup.client.post('/company-knowledge/documents/'+row['id']+'/copy-preview',json={'project_id':target['id']})
    assert response.status_code==status,response.text


def test_shared_original_survives_one_purge_then_last_reference_reclaims(setup,monkeypatch):
    source=upload(setup,root='true').json();ready(setup,source)
    response,_=transfer(setup,source)
    clone=response.json()['document'];ready(setup,clone)
    async def rpc(*args,**kwargs):return {}
    import company_knowledge as kb
    monkeypatch.setattr(kb,'cloud_rpc',rpc)
    for index,row in enumerate((source,clone)):
        assert setup.client.delete('/company-knowledge/documents/'+row['id']).status_code==200
        with setup.db() as db:
            item=db.scalar(select(RecycleItem).where(RecycleItem.target_id==row['id']))
            item.purge_after=datetime.utcnow()-timedelta(days=1)
            db.commit()
        assert asyncio.run(purge_due())==1
        if index==0:assert stored_original(setup,clone['id'])==b'Company knowledge evidence'
    assert not list(document_store().local_root.rglob('*.txt'))


def test_shared_object_lock_rejects_concurrent_reference_changes(setup):
    def other():
        with setup.db() as db:
            with pytest.raises(Exception) as error:
                with file_lock(db,'shared-original'):pass
            assert error.value.status_code==409
    with setup.db() as db, file_lock(db,'shared-original'):
        with ThreadPoolExecutor() as executor:executor.submit(other).result()
    with setup.db() as db,file_lock(db,'shared-original'):pass


def test_purge_preserves_note_attachment_reference(setup):
    from company_notes import CompanyNoteAsset
    row=upload(setup,root='true').json()
    with setup.db() as db:
        doc=db.get(CompanyDocument,row['id']);doc.state='ready';key=doc.object_key;digest=doc.sha256;db.commit()
    p=project(setup,'附件测试',category='项目经验')
    note=setup.client.post('/company-knowledge/notes',json={'project_id':p['id']}).json()
    with setup.db() as db:
        db.add(CompanyNoteAsset(id='shared-asset',note_id=note['id'],object_key=key,sha256=digest,width=1,height=1));db.commit()
    assert setup.client.delete('/company-knowledge/documents/'+row['id']).status_code==200
    with setup.db() as db:
        item=db.scalar(select(RecycleItem).where(RecycleItem.target_id==row['id']));item.purge_after=datetime.utcnow()-timedelta(days=1);db.commit()
    assert asyncio.run(purge_due())==1
    assert document_store().get_bytes(key)


def test_identical_evidence_deduplicates_after_acl_not_distinct_media_descriptions():
    allowed={'a':{'content_key':'sha:text'},'b':{'content_key':'sha:text'},'c':{'content_key':'sha:mp4:desc1'},'d':{'content_key':'sha:mp4:desc2'},'e':{},'f':{}}
    rows,removed=distinct_sources(allowed)
    assert set(rows)=={'a','c','d','e','f'} and removed==1


def test_restored_version_stays_visible_and_rename_keeps_whole_history(setup,monkeypatch):
    import company_knowledge as kb
    async def rpc(*args,**kwargs):return {}
    monkeypatch.setattr(kb,'cloud_rpc',rpc)
    first=upload(setup,root='true').json();ready(setup,first)
    second=upload(setup,root='true',payload=b'new content').json();ready(setup,second)
    assert setup.client.delete('/company-knowledge/documents/'+second['id']).status_code==200
    assert setup.client.get('/company-knowledge/documents').json()['documents']==[]
    item=setup.client.get('/company-knowledge/recycle-bin').json()['items'][0]
    restored=setup.client.post('/company-knowledge/recycle-bin/'+item['id']+'/restore')
    assert restored.status_code==200,restored.text
    rows=setup.client.get('/company-knowledge/documents').json()['documents']
    assert len(rows)==1 and rows[0]['id']==second['id'] and rows[0]['version']==3
    ready(setup,second)
    response=setup.client.patch('/company-knowledge/documents/'+second['id'],json={'title':'renamed.txt'})
    assert response.status_code==200,response.text
    versions=setup.client.get('/company-knowledge/documents/'+second['id']+'/versions').json()['versions']
    assert len(versions)==2 and all(row['title']=='renamed.txt' for row in versions)
