import asyncio
import base64
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import company_knowledge as kb
import company_workspace as ws
import company_ingestion as ingestion
from company_catalog import CompanyAccessRequest, CompanyDocument, document_store
from models import User

real_sync_catalog = ws.sync_catalog


@pytest.fixture
def setup(monkeypatch, tmp_path):
    for key in ('MODEL', 'BASE_URL', 'ARK_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    for key, value in {'API_KEY': 'test-secret', 'BASE_URL': 'https://test.cn-beijing.maas.aliyuncs.com',
                       'AGENT_ID': 'aid-test', 'INDEX_ID': 'test-index'}.items():
        monkeypatch.setenv('BAILIAN_KNOWLEDGE_' + key, value)
    monkeypatch.setenv('COMPANY_KNOWLEDGE_USERS', 'alice,bob,charlie')
    monkeypatch.setenv('COMPANY_KNOWLEDGE_LOCAL_STORE', str(tmp_path / 'originals'))
    monkeypatch.setenv('COMPANY_KNOWLEDGE_OBJECT_STORE', 'local')
    engine = create_engine('sqlite:///' + str(tmp_path / 'catalog.db'), connect_args={'check_same_thread': False})
    CompanyDocument.__table__.create(engine)
    User.__table__.create(engine)
    CompanyAccessRequest.__table__.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(ws, 'SessionLocal', factory)
    monkeypatch.setattr(ingestion, 'SessionLocal', factory)
    async def sync(*args, **kwargs):
        return
    monkeypatch.setattr(ws, 'sync_catalog', sync)
    scheduled = []
    monkeypatch.setattr(ws, 'schedule_document', scheduled.append)
    app = FastAPI()
    app.include_router(kb.router)
    user = SimpleNamespace(id=1, role='user', username='alice')
    app.dependency_overrides[kb.get_current_user] = lambda: user
    yield SimpleNamespace(client=TestClient(app), user=user, db=factory, scheduled=scheduled)
    engine.dispose()


def upload(setup, payload=b'Company knowledge evidence', name='evidence.txt', **fields):
    return setup.client.post('/company-knowledge/uploads', files={'file': (name, payload)}, data=fields)


def ready(setup, doc_id, cloud_id='cloud-a'):
    with setup.db() as db:
        doc = db.get(CompanyDocument, doc_id)
        doc.state, doc.cloud_id = 'ready', cloud_id
        db.commit()


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(kb.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


def test_upload_original_versions_duplicate_and_scope_acl(setup):
    response = upload(setup, project='P1', industry='汽车', visibility='restricted', readers='["bob"]')
    assert response.status_code == 202
    row = response.json()
    assert row['state'] == 'queued' and row['has_original'] and row['version'] == 1
    assert row['id'] in setup.scheduled
    assert setup.client.get(f'/company-knowledge/documents/{row["id"]}/original').content == b'Company knowledge evidence'
    assert upload(setup, project='P1').status_code == 409
    second = upload(setup, payload=b'New version', project='P1').json()
    assert second['version'] == 2
    ready(setup, row['id'])
    setup.user.id, setup.user.username = 3, 'charlie'
    listing = setup.client.get('/company-knowledge/documents').json()
    locked = next(doc for doc in listing['documents'] if doc['id'] == row['id'])
    assert not locked['can_read'] and locked['can_request'] and locked['cloud_id'] is None
    assert setup.client.get(f'/company-knowledge/documents/{row["id"]}/original').status_code == 404
    assert setup.client.get(f'/company-knowledge/documents/{row["id"]}/preview').status_code == 404
    assert setup.client.post('/company-knowledge/chat/stream', json={'message': 'test', 'document_ids': [row['id']]}).status_code == 403
    setup.user.id, setup.user.username = 2, 'bob'
    assert setup.client.get(f'/company-knowledge/documents/{row["id"]}/original').status_code == 200
    assert setup.client.patch('/company-knowledge/documents/' + row['id'], json={}).status_code == 403


@pytest.mark.parametrize('name,payload,status', [('x.exe', b'test', 422), ('x.pdf', b'fake pdf', 422),
    ('x.docx', b'PKbad zip', 422), ('x.txt', b'', 422), ('x.txt', b'x' * (ws.MAX_BYTES + 1), 413)],
    ids=['executable', 'fake-pdf', 'corrupt-office', 'empty', 'oversize'])
def test_invalid_uploads_never_start_cloud_tasks(setup, name, payload, status):
    assert upload(setup, payload=payload, name=name).status_code == status
    assert not setup.scheduled


def test_upload_acl_cannot_be_bypassed_by_unapproved_user(setup):
    setup.user.id, setup.user.username = 4, 'new-user'
    assert upload(setup).status_code == 403
    assert setup.client.get('/company-knowledge/documents').status_code == 403


def test_ingestion_upload_headers_explicit_import_and_ready(setup, monkeypatch):
    response = upload(setup, name='proof.pdf', payload=b'%PDF-1.4\nproof')
    doc_id = response.json()['id']
    requests = []
    def handler(request):
        requests.append(request)
        body = json.loads(request.content) if request.method == 'POST' else None
        path = request.url.path
        if path.endswith('applyFileUploadLease'):
            assert isinstance(body['sizeBytes'], str) and body['category'] == 'default'
            assert body['contentMd5'] == base64.b64encode(hashlib.md5(b'%PDF-1.4\nproof').digest()).decode()
            return httpx.Response(200, json={'code': 'Success', 'data': {'leaseId': 'lease', 'param': {
                'url': 'https://bucket.oss-cn-beijing.aliyuncs.com/proof', 'headers': {'Content-Type': 'application/pdf'}}}})
        if request.method == 'PUT':
            assert 'Authorization' not in request.headers and request.content == b'%PDF-1.4\nproof'
            return httpx.Response(200)
        if path.endswith('addFile'):
            assert body['parser'] == 'DOCMIND' and body['leaseId'] == 'lease'
            return httpx.Response(200, json={'code': 'Success', 'data': {'fileId': 'cloud-a'}})
        if path.endswith('job/create'):
            assert body == {'indexId': 'test-index', 'sourceType': 'DATA_CENTER_FILE', 'docIds': ['cloud-a']}
            return httpx.Response(200, json={'success': True, 'data': {'ingestionId': 'job-a'}})
        assert path.endswith('index_job/status') and request.url.params['job_id'] == 'job-a'
        return httpx.Response(200, json={'success': True, 'data': {'rows': [{'doc_id': 'cloud-a', 'status': 'FINISH'}]}})
    transport(monkeypatch, handler)
    asyncio.run(ingestion.process_document(doc_id))
    with setup.db() as db:
        doc = db.get(CompanyDocument, doc_id)
        assert doc.state == 'ready' and doc.cloud_id == 'cloud-a' and doc.job_id == 'job-a'
        assert doc.worker_id == '' and doc.lease_until is None
    # Restart/repeated delivery must not reupload a completed file.
    asyncio.run(ingestion.process_document(doc_id))
    assert len(requests) == 5


def test_registered_file_is_reused_after_import_failure(setup, monkeypatch):
    doc_id = upload(setup).json()['id']
    with setup.db() as db:
        doc = db.get(CompanyDocument, doc_id)
        doc.cloud_id, doc.state = 'cloud-a', 'queued'
        db.commit()
    called = []
    def handler(request):
        called.append(request.url.path)
        return httpx.Response(200, json={'success': False, 'code': 'Error', 'message': 'test-secret'})
    transport(monkeypatch, handler)
    asyncio.run(ingestion.process_document(doc_id))
    assert called == ['/api/v1/indices/rag/index/job/create']
    with setup.db() as db:
        doc = db.get(CompanyDocument, doc_id)
        assert doc.state == 'failed' and doc.cloud_id == 'cloud-a'
        assert 'test-secret' not in doc.status_message
    assert setup.client.post(f'/company-knowledge/documents/{doc_id}/retry').status_code == 202


@pytest.mark.parametrize('local_model', [False, True])
def test_retrieval_filters_and_postfilter_before_generation(setup, monkeypatch, local_model):
    if local_model:
        monkeypatch.setenv('MODEL', 'qwen3.8-max')
        monkeypatch.setenv('BASE_URL', 'https://relay.example.test/v1/')
        monkeypatch.setenv('ARK_API_KEY', 'relay-test-key')
    doc_id = upload(setup, visibility='restricted').json()['id']
    ready(setup, doc_id)
    with setup.db() as db:
        db.add(CompanyDocument(id='private-b', index_id='test-index', cloud_id='cloud-b', title='SECRET-TITLE',
            format='TXT', owner='charlie', visibility='restricted', state='ready'))
        db.commit()
    def handler(request):
        body = json.loads(request.content)
        if request.url.path.endswith('/retrieve'):
            assert request.url.host == 'test.cn-beijing.maas.aliyuncs.com'
            assert request.headers['Authorization'] == 'Bearer test-secret'
            assert body['search_filters'] == [{'doc_id': ['cloud-a']}]
            return httpx.Response(200, json={'success': True, 'data': {'nodes': [
                {'metadata': {'doc_id': 'cloud-a', 'content': 'Authorized evidence', 'doc_name': 'proof'}},
                {'metadata': {'doc_id': 'cloud-b', 'content': 'SECRET-CONTENT', 'doc_name': 'SECRET-TITLE'}}]}})
        if request.url.path.endswith('/app/get'):
            assert not local_model
            return httpx.Response(200, json={'data': {'agent_details': [{'agent_version': '1', 'agent_config': {'agent_model': 'test-model'}}]}})
        assert request.url.path.endswith('/chat/completions')
        if local_model:
            assert str(request.url) == 'https://relay.example.test/v1/chat/completions'
            assert request.headers['Authorization'] == 'Bearer relay-test-key'
            assert body['model'] == 'qwen3.8-max'
        else:
            assert body['model'] == 'test-model'
        assert 'SECRET' not in request.content.decode() and 'stale assistant' not in request.content.decode()
        assert '待复核' in body['messages'][0]['content']
        frames = [{'choices': [{'delta': {'content': 'Answer [id_1]'}, 'finish_reason': None}]},
                  {'choices': [{'delta': {}, 'finish_reason': 'stop'}]}]
        return httpx.Response(200, text=''.join('data: ' + json.dumps(f) + '\n\n' for f in frames), headers={'Content-Type': 'text/event-stream'})
    transport(monkeypatch, handler)
    result = setup.client.post('/company-knowledge/chat/stream', json={'message': 'Summarize',
        'document_ids': [doc_id], 'history': [{'role': 'assistant', 'content': 'stale assistant SECRET'}]})
    assert result.status_code == 200 and 'Answer [id_1]' in result.text and '"type": "done"' in result.text
    assert 'SECRET' not in result.text


def test_empty_scope_and_no_hits_never_fall_back_to_unfiltered_agent(setup, monkeypatch):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={'data': {'nodes': []}})
    transport(monkeypatch, handler)
    response = setup.client.post('/company-knowledge/chat/stream', json={'message': 'test'})
    assert '当前资料中未找到依据' in response.text and calls == []
    doc_id = upload(setup).json()['id']
    ready(setup, doc_id)
    response = setup.client.post('/company-knowledge/chat/stream', json={'message': 'test'})
    assert '当前资料中未找到依据' in response.text and len(calls) == 1


def test_revocation_changes_next_query_and_original_access(setup):
    doc_id = upload(setup).json()['id']
    ready(setup, doc_id)
    assert setup.client.patch(f'/company-knowledge/documents/{doc_id}', json={'visibility': 'restricted'}).status_code == 200
    setup.user.id, setup.user.username = 2, 'bob'
    response = setup.client.post('/company-knowledge/chat/stream', json={'message': 'test'})
    assert '当前资料中未找到依据' in response.text
    assert setup.client.get(f'/company-knowledge/documents/{doc_id}/original').status_code == 404


def test_partial_metadata_patch_does_not_publish_restricted_file(setup):
    doc_id = upload(setup, visibility='restricted', readers='["bob"]', project='Private project').json()['id']
    response = setup.client.patch(f'/company-knowledge/documents/{doc_id}', json={'review': '已复核'})
    assert response.status_code == 200
    assert response.json()['visibility'] == 'restricted' and response.json()['readers'] == ['bob']
    assert response.json()['project'] == 'Private project'


def test_confidential_document_request_admin_approval_grants_read_download_and_qa_scope(setup):
    uploaded = upload(setup, project='Orion', confidentiality='secret', visibility='members').json()
    doc_id = uploaded['id']
    ready(setup, doc_id)
    assert uploaded['confidentiality'] == 'secret' and uploaded['visibility'] == 'restricted'

    setup.user.id, setup.user.username = 2, 'bob'
    locked = next(doc for doc in setup.client.get('/company-knowledge/documents').json()['documents'] if doc['id'] == doc_id)
    assert not locked['can_read'] and locked['status'] == 'LOCKED' and not locked['has_original']
    assert setup.client.get(f'/company-knowledge/documents/{doc_id}/original').status_code == 404
    request = setup.client.post(f'/company-knowledge/documents/{doc_id}/access-requests',
                                json={'reason': '新员工学习 Orion 项目'}).json()
    assert request['status'] == 'pending' and request['requester_id'] == 2
    locked = next(doc for doc in setup.client.get('/company-knowledge/documents').json()['documents'] if doc['id'] == doc_id)
    assert locked['request_status'] == 'pending' and not locked['can_request']

    setup.user.id, setup.user.username, setup.user.role = 99, 'admin', 'admin'
    pending = setup.client.get('/company-knowledge/access-requests').json()['requests']
    assert pending[0]['reason'] == '新员工学习 Orion 项目'
    approved = setup.client.post(f'/company-knowledge/access-requests/{request["id"]}/decision',
                                 json={'decision': 'approved', 'note': '限项目学习使用'})
    assert approved.status_code == 200 and approved.json()['status'] == 'approved'

    setup.user.id, setup.user.username, setup.user.role = 2, 'bob', 'user'
    granted = next(doc for doc in setup.client.get('/company-knowledge/documents').json()['documents'] if doc['id'] == doc_id)
    assert granted['can_read'] and granted['cloud_id'] == 'cloud-a'
    assert setup.client.get(f'/company-knowledge/documents/{doc_id}/original').status_code == 200
    allowed = asyncio.run(ws.prepare_scope(kb.settings(), setup.user, [doc_id]))
    assert list(allowed) == ['cloud-a']


def test_rejected_request_does_not_grant_access(setup):
    doc_id = upload(setup, confidentiality='confidential').json()['id']
    setup.user.id, setup.user.username = 3, 'charlie'
    request = setup.client.post(f'/company-knowledge/documents/{doc_id}/access-requests', json={}).json()
    setup.user.id, setup.user.username, setup.user.role = 99, 'admin', 'admin'
    assert setup.client.post(f'/company-knowledge/access-requests/{request["id"]}/decision',
        json={'decision': 'rejected', 'note': '暂不属于当前项目组'}).status_code == 200
    setup.user.id, setup.user.username, setup.user.role = 3, 'charlie', 'user'
    row = next(doc for doc in setup.client.get('/company-knowledge/documents').json()['documents'] if doc['id'] == doc_id)
    assert not row['can_read'] and row['request_status'] == 'rejected' and row['can_request']


def test_my_projects_are_grouped_by_stable_account_id_and_scope_excludes_other_owners(setup):
    first = upload(setup, project='Project A', industry='汽车').json()['id']
    second = upload(setup, name='second.txt', project='Project A', industry='汽车').json()['id']
    ready(setup, first, 'cloud-a')
    ready(setup, second, 'cloud-b')
    with setup.db() as db:
        db.add(CompanyDocument(id='other', index_id='test-index', cloud_id='cloud-other', title='Other.txt',
            format='TXT', owner='bob', owner_user_id=2, project='Project B', confidentiality='internal',
            visibility='members', state='ready'))
        db.commit()
    result = setup.client.get('/company-knowledge/my-projects').json()
    assert result['account_id'] == 1 and result['project_count'] == 1 and result['document_count'] == 2
    assert result['projects'][0]['name'] == 'Project A' and result['projects'][0]['ready_count'] == 2
    allowed = asyncio.run(ws.prepare_scope(kb.settings(), setup.user, [], 'my-projects'))
    assert set(allowed) == {'cloud-a', 'cloud-b'}


def test_project_summary_uses_account_catalogue_counts_without_claiming_personal_contributions(setup):
    upload(setup, project='Project A', industry='汽车')
    with setup.db() as db:
        db.add(CompanyDocument(id='other', index_id='test-index', title='Other.txt', format='TXT',
            owner='bob', owner_user_id=2, project='SECRET-OTHER', state='ready'))
        db.commit()
    response = setup.client.post('/company-knowledge/chat/stream', json={
        'message': '总结我做了哪些项目'})
    assert response.status_code == 200
    assert 'Project A' in response.text and 'SECRET-OTHER' not in response.text
    assert '1 个项目' in response.text and '不能单独证明' in response.text
    assert '"type": "done"' in response.text


def test_ordinary_employee_cannot_approve_requests_or_manage_secret_documents(setup):
    doc_id = upload(setup, confidentiality='secret').json()['id']
    setup.user.id, setup.user.username = 2, 'bob'
    request = setup.client.post(f'/company-knowledge/documents/{doc_id}/access-requests', json={'reason': '培训'}).json()
    assert setup.client.get('/company-knowledge/access-requests').status_code == 403
    assert setup.client.post(f'/company-knowledge/access-requests/{request["id"]}/decision',
        json={'decision': 'approved'}).status_code == 403
    assert setup.client.patch(f'/company-knowledge/documents/{doc_id}', json={'confidentiality': 'internal'}).status_code == 404


def test_delete_removes_only_selected_cloud_index_and_hides_original(setup, monkeypatch):
    doc_id = upload(setup).json()['id']
    ready(setup, doc_id)
    def handler(request):
        assert request.url.path.endswith('/index/delete_file')
        assert json.loads(request.content) == {'index_id': 'test-index', 'doc_ids': ['cloud-a']}
        return httpx.Response(200, json={'success': True, 'data': {}})
    transport(monkeypatch, handler)
    assert setup.client.delete(f'/company-knowledge/documents/{doc_id}').status_code == 200
    assert setup.client.get(f'/company-knowledge/documents/{doc_id}/original').status_code == 404
    assert setup.client.get('/company-knowledge/documents').json()['documents'] == []


def test_preview_rejects_unexpected_file_chunks(setup, monkeypatch):
    doc_id = upload(setup).json()['id']
    ready(setup, doc_id)
    def handler(request):
        assert json.loads(request.content)['docId'] == 'cloud-a'
        return httpx.Response(200, json={'data': {'total': 2, 'nodes': [
            {'metadata': {'doc_id': 'cloud-b', 'content': 'SECRET'}},
            {'metadata': {'doc_id': 'cloud-a', 'content': 'Evidence'}}]}})
    transport(monkeypatch, handler)
    response = setup.client.get(f'/company-knowledge/documents/{doc_id}/preview')
    assert len(response.json()['references']) == 1 and 'SECRET' not in response.text


def test_pdf_original_pages_render_with_bounds_and_access_control(setup):
    import io
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    writer.add_blank_page(width=200, height=300)
    content = io.BytesIO()
    writer.write(content)
    doc_id = upload(setup, payload=content.getvalue(), name='pages.pdf', visibility='restricted').json()['id']
    response = setup.client.get(f'/company-knowledge/documents/{doc_id}/page?page=2')
    assert response.status_code == 200 and response.content.startswith(b'\x89PNG')
    assert response.headers['x-document-pages'] == '2'
    assert setup.client.get(f'/company-knowledge/documents/{doc_id}/page?page=3').status_code == 422
    setup.user.id, setup.user.username = 2, 'bob'
    assert setup.client.get(f'/company-knowledge/documents/{doc_id}/page').status_code == 404


def test_bad_oss_host_and_business_failure_are_rejected():
    assert kb.oss_upload_url('https://bucket.oss-cn-beijing.aliyuncs.com/file')
    assert not kb.oss_upload_url('https://evil.example/file')
    assert not kb.oss_upload_url('https://bucket.oss-cn-beijing.aliyuncs.com.evil.example/file')


def test_sync_keeps_same_name_files_separate_and_never_publicizes_unknown_managed_files(setup, monkeypatch):
    async def cloud(*args):
        return {'total_count': 3, 'documents': [
            {'id': 'legacy-a', 'title': 'Same name', 'format': 'PDF', 'size': 10, 'status': 'FINISH', 'tags': []},
            {'id': 'legacy-b', 'title': 'Same name', 'format': 'PDF', 'size': 11, 'status': 'FINISH', 'tags': []},
            {'id': 'managed-unknown', 'title': 'Secret', 'format': 'PDF', 'size': 12, 'status': 'FINISH', 'tags': ['company-workspace']},
        ]}
    monkeypatch.setattr(kb, 'list_cloud_documents', cloud)
    asyncio.run(real_sync_catalog(kb.settings(), force=True))
    with setup.db() as db:
        docs = list(db.scalars(select(CompanyDocument)))
        assert len(docs) == 2 and {doc.cloud_id for doc in docs} == {'legacy-a', 'legacy-b'}
        docs[0].state = 'deleted'
        db.commit()
    asyncio.run(real_sync_catalog(kb.settings(), force=True))
    with setup.db() as db:
        assert len(list(db.scalars(select(CompanyDocument)))) == 2


def test_active_database_lease_prevents_another_worker_from_claiming_file(setup, monkeypatch):
    from datetime import datetime, timedelta
    doc_id = upload(setup).json()['id']
    with setup.db() as db:
        doc = db.get(CompanyDocument, doc_id)
        doc.worker_id = 'other-worker'
        doc.lease_until = datetime.utcnow() + timedelta(minutes=3)
        db.commit()
    def handler(request):
        raise AssertionError('A second worker must not call cloud APIs')
    transport(monkeypatch, handler)
    asyncio.run(ingestion.process_document(doc_id))
    with setup.db() as db:
        assert db.get(CompanyDocument, doc_id).worker_id == 'other-worker'


def test_catalogue_labels_resolve_queries_without_expanding_selected_scope():
    allowed = {'resume': {'project': '秋招', 'industry': '人力资源'},
               'template': {'project': '历史资料', 'industry': ''},
               'other-resume': {'project': '春招', 'industry': '人力资源'}}
    selected, label = ws.catalogue_scope('有没有关于秋招简历的文件，我要看看实习经历', allowed)
    assert list(selected) == ['resume'] and label == '项目：秋招'
    selected, _ = ws.catalogue_scope('比较秋招和春招的实习经历', allowed)
    assert set(selected) == {'resume', 'other-resume'}
    selected, _ = ws.catalogue_scope('人力资源相关文件', allowed)
    assert set(selected) == {'resume', 'other-resume'}
    selected, label = ws.catalogue_scope('有没有关于秋招的文件', {'template': allowed['template']})
    assert list(selected) == ['template'] and label == ''


def test_catalogue_matching_avoids_negated_labels_and_partial_english_words():
    allowed = {'one': {'project': 'AI'}, 'two': {'project': '秋招'}}
    assert ws.catalogue_scope('Please provide detail', allowed)[1] == ''
    assert ws.catalogue_scope('排除秋招，看看其他资料', allowed)[1] == ''
    assert list(ws.catalogue_scope('看看 AI 项目资料', allowed)[0]) == ['one']


def test_many_table_rows_cannot_crowd_another_document_out_of_evidence():
    nodes = [{'score': 1 - index * .01, 'metadata': {'doc_id': 'table', 'content': 'row ' + str(index)}} for index in range(20)]
    nodes.append({'score': .3, 'metadata': {'doc_id': 'resume', 'content': 'Internship evidence'}})
    selected = ws.reference_candidates(nodes, {'table': {}, 'resume': {}}, 'test-index')
    assert len([row for row in selected if row[0] == 'table']) == 4
    assert any(row[0] == 'resume' for row in selected)
    assert not ws.reference_candidates(nodes, {}, 'test-index')
