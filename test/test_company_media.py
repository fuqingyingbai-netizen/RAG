import io
import time
from types import SimpleNamespace

import pytest
from PIL import Image
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import company_media as media
import company_knowledge as kb
import company_workspace as ws
from company_catalog import CompanyDocument, document_store
from models import User
from test_company_workspace import setup, upload, project


def test_picture_and_media_originals_bypass_busy_watermark_and_remain_permission_checked(setup, monkeypatch):
    image = io.BytesIO();Image.new('RGB', (64, 40), '#234567').save(image, 'PNG')
    def busy(*args):
        raise AssertionError('Pictures/media must never acquire a watermark slot')
    monkeypatch.setattr(ws, 'export_copy', busy)
    for name, payload in [('photo.png', image.getvalue()), ('note.mp3', b'ID3test-audio')]:
        row = upload(setup, name=name, payload=payload, description='人工说明').json()
        for suffix in ['/original', '/download']:
            response = setup.client.get('/company-knowledge/documents/' + row['id'] + suffix)
            assert response.status_code == 200 and response.content == payload
            assert '_水印副本' not in response.headers.get('x-download-filename', '')
        with setup.db() as db:
            doc = db.get(CompanyDocument, row['id']);doc.visibility='restricted';db.commit()
        setup.user.id, setup.user.username = 2, 'bob'
        assert setup.client.get('/company-knowledge/documents/'+row['id']+'/original').status_code==404
        setup.user.id, setup.user.username = 1, 'alice'


@pytest.mark.parametrize('header,status,body,content_range', [
    (None,200,b'0123456789',None),('bytes=2-4',206,b'234','bytes 2-4/10'),
    ('bytes=7-',206,b'789','bytes 7-9/10'),('bytes=-3',206,b'789','bytes 7-9/10'),
    ('bytes=0-999',206,b'0123456789','bytes 0-9/10'),('bytes=-99',206,b'0123456789','bytes 0-9/10'),
    ('bytes=20-',416,None,'bytes */10'),('bytes=-0',416,None,'bytes */10'),
    ('bytes=4-2',416,None,'bytes */10'),('bytes=1-2,5-7',416,None,'bytes */10'),('invalid',416,None,'bytes */10'),
])
def test_stream_ranges_do_not_buffer_entire_media(tmp_path,header,status,body,content_range):
    target=tmp_path/'test.mp3';target.write_bytes(b'0123456789')
    app=FastAPI()
    @app.api_route('/stream',methods=['GET','HEAD'])
    def stream(request:Request):return media.file_response(target,request)
    with TestClient(app) as client:
        response=client.get('/stream',headers={'Range':header} if header else {})
        assert response.status_code==status
        if body is not None:assert response.content==body and int(response.headers['content-length'])==len(body)
        assert response.headers.get('content-range')==content_range
        assert response.headers['accept-ranges']=='bytes'
        head=client.head('/stream');assert head.status_code==200 and head.content==b'' and head.headers['content-length']=='10'


def test_playback_cookie_cannot_be_used_for_other_files_and_rechecks_acl_version_account(setup, monkeypatch):
    monkeypatch.setenv('COMPANY_KNOWLEDGE_MEDIA_CACHE', str(document_store().local_root/'playback'))
    with setup.db() as db:
        db.add(User(id=1,username='alice',password_hash='unused',role='user'));db.commit()
    row=upload(setup,name='record.mp3',payload=b'ID3playable-bytes',description='录音说明').json()
    base='/company-knowledge/documents/'+row['id']
    for _ in range(100):
        response=setup.client.get(base+'/playback')
        if response.status_code!=202:break
        time.sleep(.01)
    assert response.status_code==200,response.text
    cookie=response.headers['set-cookie'];assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie and '/stream' in cookie
    url=response.json()['url'];assert '?' not in url
    response=setup.client.get(url,headers={'Range':'bytes=0-2'})
    assert response.status_code==206 and response.content==b'ID3'
    # A file URL without its scoped cookie, or a copied cookie on a different file, grants nothing.
    saved=setup.client.cookies.get('ckb_playback')
    setup.client.cookies.clear();assert setup.client.get(url).status_code==401
    setup.client.cookies.set('ckb_playback',saved)
    assert setup.client.get('/company-knowledge/documents/other/stream').status_code==401
    with setup.db() as db:
        doc=db.get(CompanyDocument,row['id']);old_sha=doc.sha256;doc.sha256='new-version';db.commit()
    assert setup.client.get(url).status_code==409
    with setup.db() as db:
        doc=db.get(CompanyDocument,row['id']);doc.sha256=old_sha;doc.state='deleted';db.commit()
    assert setup.client.get(url).status_code==404
    with setup.db() as db:
        doc=db.get(CompanyDocument,row['id']);doc.state='archived';user=db.get(User,1);user.token_version+=1;db.commit()
    assert setup.client.get(url).status_code==401


def test_failed_preparation_is_explicit_and_can_be_retried_without_changing_original(setup, monkeypatch):
    from concurrent.futures import Future
    row=upload(setup,name='bad.webm',payload=b'\x1aE\xdf\xa3invalid',description='说明').json()
    with setup.db() as db:
        doc=db.get(CompanyDocument,row['id']);values=SimpleNamespace(object_key=doc.object_key,sha256=doc.sha256,format=doc.format)
    target=media.cache_path(values)
    # A deterministic failed job tests the response independently of installed codecs.
    failure=Future();failure.set_exception(RuntimeError('broken'))
    with media._lock:media._jobs[str(target)]=failure
    response=setup.client.get('/company-knowledge/documents/'+row['id']+'/playback')
    assert response.status_code==422 and '重试' in response.json()['detail']
    with pytest.raises(Exception):failure.result()
    assert document_store().get_bytes(values.object_key)==b'\x1aE\xdf\xa3invalid'
    def repaired(doc,target,store):
        target.write_bytes(b'compatible-preview');return target
    monkeypatch.setattr(media,'prepare',repaired)
    response=setup.client.get('/company-knowledge/documents/'+row['id']+'/playback?retry=true')
    for _ in range(100):
        if response.status_code!=202:break
        time.sleep(.01);response=setup.client.get('/company-knowledge/documents/'+row['id']+'/playback')
    assert response.status_code==200,response.text


def test_each_seek_rechecks_viewer_permission_and_expired_tickets_fail(setup,monkeypatch):
    from jose import jwt, JWTError
    import auth
    with setup.db() as db:
        db.add(User(id=2,username='bob',password_hash='unused',role='user'));db.commit()
    row=upload(setup,name='public.mp3',payload=b'ID3test-playback',description='说明').json()
    setup.user.username,setup.user.id='bob',2
    base='/company-knowledge/documents/'+row['id']
    for _ in range(100):
        response=setup.client.get(base+'/playback')
        if response.status_code!=202:break
        time.sleep(.01)
    assert response.status_code==200,response.text
    url=response.json()['url']
    assert setup.client.get(url,headers={'Range':'bytes=3-6'}).status_code==206
    ticket=setup.client.cookies.get('ckb_playback')
    with pytest.raises(JWTError):jwt.decode(ticket,auth.SECRET_KEY,algorithms=['HS256'])
    with setup.db() as db:
        doc=db.get(CompanyDocument,row['id']);doc.visibility='restricted';doc.readers=[];db.commit()
    assert setup.client.get(url,headers={'Range':'bytes=7-'}).status_code==404
    claims=jwt.decode(ticket,media.signing_key(),algorithms=['HS256']);claims['exp']=1
    setup.client.cookies.clear();setup.client.cookies.set('ckb_playback',jwt.encode(claims,media.signing_key(),algorithm='HS256'))
    assert setup.client.get(url).status_code==401
