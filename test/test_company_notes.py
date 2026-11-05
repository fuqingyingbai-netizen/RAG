"""Draft isolation, optimistic edits, publication switching and portable exports."""
import io
import json
import zipfile

import pytest
from PIL import Image
from sqlalchemy import select

from test_company_workspace import setup, project
from company_catalog import CompanyDocument, CompanyAuditEvent, document_store
from company_notes import CompanyNote, CompanyNoteAsset, CompanyNotePublication
from company_note_format import checked_content, word_document, markdown
import company_ingestion as ingestion


def create(setup, **fields):
    p=project(setup, '笔记经验空间', category='手稿笔记', **fields)
    response=setup.client.post('/company-knowledge/notes',json={'project_id':p['id']})
    assert response.status_code==201,response.text
    return p,response.json()


def content(text='保留一线经验'):
    return {'type':'doc','content':[{'type':'paragraph','content':[{'type':'text','text':text}]}]}


def save(setup,note,body=None,**extra):
    response=setup.client.patch('/company-knowledge/notes/'+note['id'],json={'revision':note['revision'],'title':'访谈复盘','content':body or content(),**extra})
    assert response.status_code==200,response.text
    return response.json()


def publish(setup,note):
    response=setup.client.post('/company-knowledge/notes/'+note['id']+'/publish',json={'revision':note['revision']})
    assert response.status_code==200,response.text
    return response.json()


def ready(setup,note):
    with setup.db() as db:
        doc=db.get(CompanyDocument,note['pending_document_id']);doc.worker_id='test-worker';db.commit()
    ingestion.checkpoint(note['pending_document_id'],'test-worker',state='ready')


def test_private_draft_cas_history_and_resume(setup):
    p,note=create(setup);saved=save(setup,note)
    assert saved['revision']==2 and saved['created_by']=='alice'
    assert setup.client.get('/company-knowledge/notes/'+note['id']).json()['content']==content()
    assert setup.client.patch('/company-knowledge/notes/'+note['id'],json={'revision':1,'title':'覆盖','content':content('丢失')}).status_code==409
    assert setup.client.get('/company-knowledge/documents').json()['total_count']==0
    history=setup.client.get('/company-knowledge/notes/'+note['id']+'/history').json()['events']
    change=next(row for row in history if row['action']=='note.save')
    assert change['actor']=='alice' and change['changes']['content']['after']==content()
    setup.user.username,setup.user.id='bob',2
    assert setup.client.get('/company-knowledge/notes').json()['notes']==[]
    assert setup.client.get('/company-knowledge/notes/'+note['id']).status_code==404
    assert setup.client.patch('/company-knowledge/notes/'+note['id'],json={'revision':2,'title':'越权','content':content()}).status_code==403


def test_note_cannot_enter_library_or_exceed_project_acl(setup):
    p=project(setup,'原件项目')
    assert setup.client.post('/company-knowledge/notes',json={'project_id':p['id']}).status_code==422
    p,note=create(setup,confidentiality='secret',visibility='restricted',readers=[])
    note=publish(setup,save(setup,note));ready(setup,note)
    setup.user.username,setup.user.id='bob',2
    assert setup.client.get('/company-knowledge/notes/'+note['id']).status_code==404
    assert setup.client.get('/company-knowledge/notes/'+note['id']+'/export').status_code==404


def test_published_snapshot_is_readable_but_updates_remain_private(setup):
    _,note=create(setup);note=publish(setup,save(setup,note));first=note['pending_document_id'];ready(setup,note)
    note=setup.client.get('/company-knowledge/notes/'+note['id']).json();note=save(setup,note,content('草稿秘密'))
    setup.user.username,setup.user.id='bob',2
    public=setup.client.get('/company-knowledge/notes/'+note['id']).json()
    assert public['content']==content() and not public['can_manage'] and public['revision']==2
    assert setup.client.get('/company-knowledge/notes/'+note['id']+'/export?draft=true').status_code==403
    setup.user.username,setup.user.id='alice',1
    note=publish(setup,note);second=note['pending_document_id'];assert first!=second
    # Publish is idempotent and the previous ready version stays current until success.
    assert publish(setup,note)['pending_document_id']==second
    with setup.db() as db:
        assert len(list(db.scalars(select(CompanyNotePublication))))==2
        assert db.get(CompanyDocument,first).is_current==1 and db.get(CompanyDocument,second).is_current==0
    docs=setup.client.get('/company-knowledge/documents').json()['documents'];assert [d['id'] for d in docs]==[first]
    ready(setup,note)
    with setup.db() as db:
        assert db.get(CompanyDocument,first).is_current==0 and db.get(CompanyDocument,second).is_current==1
    docs=setup.client.get('/company-knowledge/documents').json()['documents'];assert [d['id'] for d in docs]==[second]
    assert docs[0]['note_id']==note['id']
    assert setup.client.patch('/company-knowledge/documents/'+second,json={'title':'绕过.docx'}).status_code==422


def test_asset_ownership_ocr_export_embeds_images_and_watermarks(setup,monkeypatch):
    p,note=create(setup);picture=io.BytesIO();Image.new('RGB',(250,100),'white').save(picture,'PNG')
    url='/company-knowledge/notes/'+note['id']
    response=setup.client.post(url+'/images',files={'file':('screenshot.png',picture.getvalue(),'image/png')});assert response.status_code==201,response.text
    asset=response.json();assert setup.client.post(url+'/images',files={'file':('again.png',picture.getvalue(),'image/png')}).json()['id']==asset['id']
    body=content();body['content'].append({'type':'image','attrs':{'assetId':asset['id'],'width':60,'caption':'现场流程图','ocrText':'核对后的关键步骤'}})
    note=save(setup,note,body)
    import company_notes
    monkeypatch.setattr(company_notes,'recognize_image',lambda data:'现场识别文字')
    assert setup.client.post(url+'/images/'+asset['id']+'/ocr').json()['text']=='现场识别文字'
    source=document_store()
    with setup.db() as db:key=db.get(CompanyNoteAsset,asset['id']).object_key;original=source.get_bytes(key)
    preview=setup.client.get(url+'/images/'+asset['id']);assert preview.status_code==200 and preview.content!=original
    docx=setup.client.get(url+'/export?draft=true');assert docx.status_code==200,docx.text[:200] if docx.status_code!=200 else ''
    with zipfile.ZipFile(io.BytesIO(docx.content)) as doc:
        assert any(name.startswith('word/media/') for name in doc.namelist())
        xml=doc.read('word/document.xml').decode();assert '现场流程图' in xml and '核对后的关键步骤' in xml
        assert b'alice' in b''.join(doc.read(name) for name in doc.namelist() if name.endswith('.xml'))
    exported=setup.client.get(url+'/export?draft=true&format=markdown');assert exported.status_code==200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        md=archive.read('note.md').decode();assert 'images/'+asset['id']+'.png' in md and 'alice' in md
        assert archive.read('images/'+asset['id']+'.png')!=original
    assert source.get_bytes(key)==original
    # A guessed asset ID from a different private draft can never be embedded/read.
    other=setup.client.post('/company-knowledge/notes',json={'project_id':p['id']}).json()
    assert setup.client.patch('/company-knowledge/notes/'+other['id'],json={'revision':1,'title':'偷图片','content':body}).status_code==422
    assert setup.client.get('/company-knowledge/notes/'+other['id']+'/images/'+asset['id']).status_code==404


def test_unpublished_image_not_disclosed_through_published_note(setup):
    _,note=create(setup);note=publish(setup,save(setup,note));ready(setup,note)
    picture=io.BytesIO();Image.new('RGB',(100,100),'blue').save(picture,'PNG');url='/company-knowledge/notes/'+note['id']
    asset=setup.client.post(url+'/images',files={'file':('private.png',picture.getvalue(),'image/png')}).json()
    setup.user.username,setup.user.id='bob',2
    assert setup.client.get(url+'/images/'+asset['id']).status_code==404


def test_empty_publish_failed_retry_and_folder_protection(setup):
    p,note=create(setup)
    assert setup.client.post('/company-knowledge/notes/'+note['id']+'/publish',json={'revision':1}).status_code==422
    note=publish(setup,save(setup,note));old=note['pending_document_id']
    with setup.db() as db:doc=db.get(CompanyDocument,old);doc.state='failed';doc.status_message='暂不可用';db.commit()
    assert publish(setup,note)['pending_document_id']==old
    with setup.db() as db:assert db.get(CompanyDocument,old).state=='queued'
    folder=setup.client.post('/company-knowledge/projects/'+p['id']+'/folders',json={'name':'草稿目录'}).json()
    assert setup.client.post('/company-knowledge/notes',json={'project_id':p['id'],'folder_id':folder['id']}).status_code==201
    assert setup.client.delete('/company-knowledge/projects/'+p['id']+'/folders/'+folder['id']).status_code==409


def test_structured_content_validation_and_table_roundtrip():
    table={'type':'table','content':[{'type':'tableRow','content':[{'type':'tableHeader','attrs':{'colspan':2,'rowspan':1},'content':[{'type':'paragraph','content':[{'type':'text','text':'合并表头'}]}]}]},
        {'type':'tableRow','content':[{'type':'tableCell','content':[{'type':'paragraph','content':[{'type':'text','text':text}]}]} for text in ['甲','乙']]}]}
    clean=checked_content({'type':'doc','content':[table]},set())
    assert '合并表头' in markdown('表格',clean)
    with zipfile.ZipFile(io.BytesIO(word_document('表格',clean,{}))) as doc:assert b'gridSpan' in doc.read('word/document.xml')
    for node in [{'type':'script'}, {'type':'image','attrs':{'assetId':'missing'}}, {'type':'paragraph','content':[{'type':'text','text':'bad','marks':[{'type':'link','attrs':{'href':'javascript:alert(1)'}}]}]},
                 {'type':'table','content':[{'type':'tableRow','content':[{'type':'tableCell','attrs':{'colspan':'2'},'content':[{'type':'paragraph'}]}]}]}]:
        from fastapi import HTTPException
        with pytest.raises(HTTPException):checked_content({'type':'doc','content':[node]},set())


def nested_editor_table():
    paragraph=lambda text: {'type':'paragraph','content':[{'type':'text','text':text}]}
    table={'type':'table','content':[{'type':'tableRow','content':[{'type':'tableCell','content':[paragraph('表格中的事实')]}]}]}
    return {'type':'doc','content':[{'type':'bulletList','content':[{'type':'listItem','content':[paragraph('列表中的研究事项'),table]}]}]}


def test_editor_table_in_list_is_valid_and_portable():
    clean=checked_content(nested_editor_table(),set())
    assert '表格中的事实' in markdown('列表与表格',clean)
    with zipfile.ZipFile(io.BytesIO(word_document('列表与表格',clean,{}))) as doc:
        xml=doc.read('word/document.xml').decode()
        assert '表格中的事实' in xml and '<w:tbl>' in xml


@pytest.mark.parametrize('container',['blockquote','tableCell','tableHeader'])
def test_editor_block_containers_accept_the_same_blocks_as_tiptap(container):
    item=nested_editor_table()['content'][0]
    wrapped={'type':container,'content':[item]}
    if container!='blockquote':wrapped={'type':'table','content':[{'type':'tableRow','content':[wrapped]}]}
    clean=checked_content({'type':'doc','content':[wrapped]},set())
    with zipfile.ZipFile(io.BytesIO(word_document('复杂图文',clean,{}))) as doc:
        assert '表格中的事实' in doc.read('word/document.xml').decode()


def test_nested_blocks_still_enforce_structure_depth_and_safe_nodes():
    from fastapi import HTTPException
    for children in ([{'type':'table','content':[]}],[{'type':'paragraph'},{'type':'script'}]):
        with pytest.raises(HTTPException):checked_content({'type':'doc','content':[{'type':'bulletList','content':[{'type':'listItem','content':children}]}]},set())
    nested={'type':'paragraph'}
    for _ in range(20):nested={'type':'blockquote','content':[nested]}
    with pytest.raises(HTTPException):checked_content({'type':'doc','content':[nested]},set())


def test_nested_editor_blocks_save_publish_and_export(setup):
    _,note=create(setup)
    saved=save(setup,note,nested_editor_table())
    assert saved['content']==checked_content(nested_editor_table(),set())
    assert setup.client.get('/company-knowledge/notes/'+note['id']).json()['content']==saved['content']
    for fmt in ['docx','markdown']:
        assert setup.client.get('/company-knowledge/notes/'+note['id']+'/export',params={'draft':True,'format':fmt}).status_code==200
    assert publish(setup,saved)['pending_document_id']
