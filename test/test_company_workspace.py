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
from company_catalog import CompanyAccessRequest, CompanyDocument, CompanyProject, CompanyFolder, CompanyAuditEvent, document_store
from models import User

real_sync_catalog = ws.sync_catalog


@pytest.fixture
def setup(monkeypatch, tmp_path):
    for key in ('MODEL', 'BASE_URL', 'ARK_API_KEY', 'COMPANY_KNOWLEDGE_MODEL',
                'COMPANY_KNOWLEDGE_BASE_URL', 'COMPANY_KNOWLEDGE_API_KEY'):
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
    CompanyProject.__table__.create(engine)
    CompanyFolder.__table__.create(engine)
    CompanyAuditEvent.__table__.create(engine)
    from company_recycle import RecycleItem
    RecycleItem.__table__.create(engine)
    from company_notes import CompanyNote, CompanyNoteAsset, CompanyNotePublication
    for model in (CompanyNote, CompanyNoteAsset, CompanyNotePublication):model.__table__.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(ws, 'SessionLocal', factory)
    import company_projects
    monkeypatch.setattr(company_projects, 'SessionLocal', factory)
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


def stored_original(setup, doc_id):
    """The server's archival bytes remain unchanged; HTTP exports are marked derivatives."""
    with setup.db() as db:
        return document_store().get_bytes(db.get(CompanyDocument, doc_id).object_key)


def test_original_and_download_openapi_describe_dynamic_file_responses(setup):
    schema = setup.client.get('/openapi.json').json()
    for suffix in ('original', 'download'):
        response = schema['paths'][f'/company-knowledge/documents/{{doc_id}}/{suffix}']['get']['responses']['200']
        assert response['content']['*/*']['schema'] == {'type': 'string', 'format': 'binary'}
        assert 'application/json' not in response['content']


def test_server_attribution_owned_edits_and_audit_permissions(setup):
    p = project(setup, '审计项目')
    assert p['created_by'] == p['modified_by'] == 'alice'
    response = setup.client.patch('/company-knowledge/projects/' + p['id'], json={
        'name': '修正名称', 'description': '修正背景', 'created_by': 'forged', 'modified_by': 'forged'})
    assert response.status_code == 200 and response.json()['created_by'] == 'alice'
    rows = setup.client.get('/company-knowledge/audit-events', params={'project_id': p['id']}).json()['events']
    edited = next(row for row in rows if row['action'] == 'project.update')
    assert edited['actor_username'] == 'alice'
    assert edited['changes']['name'] == {'before': '审计项目', 'after': '修正名称'}
    assert edited['changes']['description'] == {'before': '', 'after': '修正背景'}
    setup.user.username, setup.user.id = 'bob', 2
    assert setup.client.patch('/company-knowledge/projects/' + p['id'], json={'name': '越权'}).status_code == 403
    assert setup.client.get('/company-knowledge/audit-events', params={'project_id': p['id']}).status_code == 404
    assert setup.client.get('/company-knowledge/audit-events').status_code == 403
    setup.user.role = 'admin'
    row = upload(setup, project_id=p['id'], uploaded_by='forged').json()
    assert row['owner'] == 'alice' and row['uploaded_by'] == 'bob' and row['modified_by'] == 'bob'
    assert setup.client.patch('/company-knowledge/documents/' + row['id'], json={'title': 'renamed.txt', 'modified_by': 'forged'}).status_code == 200
    events = setup.client.get('/company-knowledge/audit-events', params={'document_id': row['id']}).json()['events']
    assert {'document.upload', 'document.update'} <= {e['action'] for e in events}
    edited = next(e for e in events if e['action'] == 'document.update')
    assert edited['actor_username'] == 'bob' and edited['changes']['title']['before'] == 'evidence.txt'
    assert setup.client.put('/company-knowledge/audit-events/' + edited['id'], json={}).status_code in (404,405)


def test_audit_rolls_back_with_failed_project_changes(setup):
    a, b = project(setup, '审计 A'), project(setup, '审计 B')
    assert setup.client.patch('/company-knowledge/projects/' + b['id'], json={'name': a['name']}).status_code == 409
    rows = setup.client.get('/company-knowledge/audit-events', params={'project_id': b['id']}).json()['events']
    assert len(rows) == 1 and rows[0]['action'] == 'project.create'
    assert setup.client.get('/company-knowledge/projects').json()['projects'][0]['name'] in ('审计 A', '审计 B')


def test_every_export_route_is_personalised_and_original_is_preserved(setup):
    import io
    from pypdf import PdfReader
    from company_watermark import text_to_pdf
    source = text_to_pdf(b'Company knowledge evidence')
    row = upload(setup, payload=source, name='evidence.pdf').json()
    traces = set()
    for suffix in ('/download', '/original', '/original?download=true', '/original?download=false'):
        response = setup.client.get('/company-knowledge/documents/' + row['id'] + suffix)
        assert response.status_code == 200 and response.headers['content-type'] == 'application/pdf'
        pdf = PdfReader(io.BytesIO(response.content))
        assert pdf.metadata['/DownloadAccount'] == 'alice'
        assert 'Company knowledge evidence' in pdf.pages[0].extract_text()
        assert response.headers['x-watermark-trace'] == pdf.metadata['/WatermarkTrace']
        traces.add(response.headers['x-watermark-trace'])
    assert len(traces) == 4 and stored_original(setup, row['id']) == source
    setup.user.id, setup.user.username = 2, 'bob'
    response = setup.client.get('/company-knowledge/documents/' + row['id'] + '/download')
    assert PdfReader(io.BytesIO(response.content)).metadata['/DownloadAccount'] == 'bob'
    assert setup.client.get('/company-knowledge/audit-events', params={'document_id': row['id']}).status_code == 404
    setup.user.role = 'admin'
    history = setup.client.get('/company-knowledge/audit-events', params={'document_id': row['id']}).json()['events']
    generated = next(e for e in history if e['id'] == response.headers['x-watermark-trace'])
    assert generated['action'] == 'document.download' and generated['actor_username'] == 'bob'
    assert generated['details']['sha256'] == hashlib.sha256(response.content).hexdigest()


def test_export_failure_never_falls_back_to_original_and_rechecks_acl(setup, monkeypatch):
    from company_watermark import WatermarkError
    row = upload(setup).json()
    def failure(*args):
        raise WatermarkError('模拟转换失败')
    monkeypatch.setattr(ws, 'export_copy', failure)
    response = setup.client.get('/company-knowledge/documents/' + row['id'] + '/download')
    assert response.status_code == 503 and b'Company knowledge evidence' not in response.content
    events = setup.client.get('/company-knowledge/audit-events', params={'document_id': row['id']}).json()['events']
    assert events[0]['action'] == 'document.export_failed'
    setup.user.id, setup.user.username = 2, 'bob'
    def revoked(data, fmt, title, identity):
        with setup.db() as db:
            doc = db.get(CompanyDocument, row['id']); doc.visibility = 'restricted'; doc.readers = []; db.commit()
        return b'%PDF-marked', 'application/pdf', 'marked.pdf'
    monkeypatch.setattr(ws, 'export_copy', revoked)
    assert setup.client.get('/company-knowledge/documents/' + row['id'] + '/download').status_code == 404


def test_download_progress_is_account_scoped_and_duplicate_ids_do_not_repeat_exports(setup, monkeypatch):
    row = upload(setup).json()
    request_id = 'abcdef0123456789'
    url = '/company-knowledge/documents/' + row['id']
    observed = []
    real_export = ws.export_copy
    def generate(data, fmt, title, identity, progress):
        progress('converting', 0, 0)
        status = setup.client.get(url + '/export-status', params={'request_id': request_id})
        assert status.status_code == 200 and status.json()['stage'] == 'converting'
        observed.append(status.json())
        return real_export(data, fmt, title, identity, progress)
    monkeypatch.setattr(ws, 'export_copy', generate)
    response = setup.client.get(url + '/download', params={'request_id': request_id})
    assert response.status_code == 200 and observed
    assert setup.client.get(url + '/export-status', params={'request_id': request_id}).json()['stage'] == 'ready'
    assert setup.client.get(url + '/download', params={'request_id': request_id}).status_code == 409
    assert len(observed) == 1
    setup.user.id, setup.user.username = 2, 'bob'
    assert setup.client.get(url + '/export-status', params={'request_id': request_id}).status_code == 404
    assert setup.client.get(url + '/export-status', params={'request_id': 'unknown01'}).status_code == 422
    from company_watermark import WatermarkError
    def failure(*args):
        raise WatermarkError('测试转换失败')
    monkeypatch.setattr(ws, 'export_copy', failure)
    failed_id = 'abcdef9876543210'
    assert setup.client.get(url + '/download', params={'request_id': failed_id}).status_code == 503
    failed = setup.client.get(url + '/export-status', params={'request_id': failed_id})
    assert failed.status_code == 200 and failed.json()['stage'] == 'failed'
    assert failed.headers['cache-control'] == 'private, no-store'


def test_audit_schema_upgrade_retains_existing_records_and_is_repeatable(setup):
    from company_catalog import ensure_company_schema
    p = project(setup)
    row = upload(setup, project_id=p['id']).json()
    with setup.db() as db:
        engine = db.get_bind()
    with engine.begin() as connection:
        for column in ('uploaded_by', 'uploaded_by_user_id', 'modified_by'):
            connection.exec_driver_sql('ALTER TABLE company_documents DROP COLUMN ' + column)
        for column in ('created_by', 'modified_by'):
            connection.exec_driver_sql('ALTER TABLE company_projects DROP COLUMN ' + column)
    ensure_company_schema(engine); ensure_company_schema(engine)
    with setup.db() as db:
        assert db.get(CompanyDocument, row['id']).uploaded_by == ''
        assert db.get(CompanyProject, p['id']).created_by == ''
        assert len(list(db.scalars(select(CompanyAuditEvent)))) == 2
    assert stored_original(setup, row['id']) == b'Company knowledge evidence'


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
    response = setup.client.get(f'/company-knowledge/documents/{row["id"]}/original')
    assert response.status_code == 200 and b'Company knowledge evidence' in response.content and response.headers['x-watermark-trace']
    assert stored_original(setup, row['id']) == b'Company knowledge evidence'
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


def test_inactive_account_cannot_upload_or_browse_knowledge(setup):
    setup.user.id, setup.user.username = 4, 'new-user'
    setup.user.is_active = False
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
        evidence=json.loads(body['messages'][0]['content'].split('本轮资料：\n',1)[1])
        focus=evidence[0]['focus']
        assert evidence[0]['text'][focus['start']:focus['end']]==focus['text']
        assert len(evidence)==1 and evidence[0]['citation']=='[id_1]' and evidence[0]['text']=='Authorized evidence'
        frames = [{'choices': [{'delta': {'content': 'Answer [id_1]'}, 'finish_reason': None}]},
                  {'choices': [{'delta': {}, 'finish_reason': 'stop'}]}]
        return httpx.Response(200, text=''.join('data: ' + json.dumps(f) + '\n\n' for f in frames), headers={'Content-Type': 'text/event-stream'})
    transport(monkeypatch, handler)
    result = setup.client.post('/company-knowledge/chat/stream', json={'message': 'Summarize',
        'document_ids': [doc_id], 'history': [{'role': 'assistant', 'content': 'stale assistant SECRET'}]})
    events = [json.loads(line[6:]) for line in result.text.splitlines() if line.startswith('data: ')]
    answer = ''.join(event.get('text', '') for event in events if event['type'] == 'answer_delta')
    assert result.status_code == 200 and answer == 'Answer [id_1]' and events[-1]['type'] == 'done'
    assert 'SECRET' not in result.text


@pytest.mark.parametrize('local_model', [False, True])
@pytest.mark.parametrize('status', [401, 403, 404])
def test_generation_errors_identify_the_answer_provider(setup, monkeypatch, local_model, status):
    if local_model:
        monkeypatch.setenv('MODEL', 'qwen3.8-max')
        monkeypatch.setenv('BASE_URL', 'https://relay.example.test/v1')
        monkeypatch.setenv('ARK_API_KEY', 'relay-test-key')
    doc_id = upload(setup).json()['id']
    ready(setup, doc_id)

    def handler(request):
        if request.url.path.endswith('/retrieve'):
            assert request.headers['Authorization'] == 'Bearer test-secret'
            return httpx.Response(200, json={'data': {'nodes': [
                {'metadata': {'doc_id': 'cloud-a', 'content': 'Authorized evidence'}}]}})
        if request.url.path.endswith('/app/get'):
            assert not local_model
            return httpx.Response(200, json={'data': {'agent_details': [
                {'agent_version': '1', 'agent_config': {'agent_model': 'test-model'}}]}})
        assert request.url.path.endswith('/chat/completions')
        return httpx.Response(status, json={'error': 'test-secret relay-test-key'})

    transport(monkeypatch, handler)
    response = setup.client.post('/company-knowledge/chat/stream', json={
        'message': 'Summarize', 'document_ids': [doc_id]})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert any(event['type'] == 'citations' for event in events)
    assert events[-1]['type'] == 'error'
    assert ('回答模型' if local_model else '百炼') in events[-1]['message']
    if local_model:
        assert '百炼' not in events[-1]['message']
    assert 'test-secret' not in response.text and 'relay-test-key' not in response.text
    assert not any(event['type'] == 'done' for event in events)


def test_retrieval_auth_error_still_identifies_bailian_with_external_answer_model(setup, monkeypatch):
    monkeypatch.setenv('MODEL', 'qwen3.8-max')
    monkeypatch.setenv('BASE_URL', 'https://relay.example.test/v1')
    monkeypatch.setenv('ARK_API_KEY', 'relay-test-key')
    doc_id = upload(setup).json()['id']
    ready(setup, doc_id)
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(401, json={'error': 'test-secret'})

    transport(monkeypatch, handler)
    response = setup.client.post('/company-knowledge/chat/stream', json={
        'message': 'Summarize', 'document_ids': [doc_id]})
    assert calls == ['/api/v1/indices/rag/index/retrieve']
    assert '百炼接口认证失败' in response.text and '回答模型' not in response.text
    assert 'test-secret' not in response.text


def test_empty_scope_and_no_hits_never_fall_back_to_unfiltered_agent(setup, monkeypatch):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={'data': {'nodes': []}})
    transport(monkeypatch, handler)
    response = setup.client.post('/company-knowledge/chat/stream', json={'message': '查询项目资料'})
    assert '当前资料中未找到依据' in response.text and calls == []
    doc_id = upload(setup).json()['id']
    ready(setup, doc_id)
    response = setup.client.post('/company-knowledge/chat/stream', json={'message': '查询项目资料'})
    assert '当前资料中未找到依据' in response.text and len(calls) == 1


def test_revocation_changes_next_query_and_original_access(setup):
    doc_id = upload(setup).json()['id']
    ready(setup, doc_id)
    assert setup.client.patch(f'/company-knowledge/documents/{doc_id}', json={'visibility': 'restricted'}).status_code == 200
    setup.user.id, setup.user.username = 2, 'bob'
    response = setup.client.post('/company-knowledge/chat/stream', json={'message': '查询项目资料'})
    assert '当前资料中未找到依据' in response.text
    assert setup.client.get(f'/company-knowledge/documents/{doc_id}/original').status_code == 404


def test_partial_metadata_patch_does_not_publish_restricted_file(setup):
    doc_id = upload(setup, visibility='restricted', readers='["bob"]', project='Private project').json()['id']
    response = setup.client.patch(f'/company-knowledge/documents/{doc_id}', json={'review': '已复核'})
    assert response.status_code == 200
    assert response.json()['visibility'] == 'restricted' and response.json()['readers'] == ['bob']
    assert response.json()['project'] == 'Private project'


def test_restricted_internal_request_admin_approval_grants_read_download_and_qa_scope(setup):
    uploaded = upload(setup, project='Orion', confidentiality='internal', visibility='restricted').json()
    doc_id = uploaded['id']
    ready(setup, doc_id)
    assert uploaded['confidentiality'] == 'internal' and uploaded['visibility'] == 'restricted'

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
    doc_id = upload(setup, visibility='restricted').json()['id']
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
    doc_id = upload(setup, visibility='restricted').json()['id']
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


@pytest.mark.parametrize('citation',['[id_999]','［id_1]','【id_1】'])
def test_generated_unknown_citation_cannot_be_marked_complete(setup, monkeypatch,citation):
    doc_id=upload(setup).json()['id'];ready(setup,doc_id)
    def handler(request):
        if request.url.path.endswith('/retrieve'):
            return httpx.Response(200,json={'data':{'nodes':[{'metadata':{'doc_id':'cloud-a','content':'真实依据'}}]}})
        if request.url.path.endswith('/app/get'):
            return httpx.Response(200,json={'data':{'agent_details':[{'agent_version':'1','agent_config':{'agent_model':'test'}}]}})
        frames=[{'choices':[{'delta':{'content':'错误引用'+citation},'finish_reason':None}]},
                {'choices':[{'delta':{},'finish_reason':'stop'}]}]
        return httpx.Response(200,text=''.join('data: '+json.dumps(f)+'\n\n' for f in frames),headers={'Content-Type':'text/event-stream'})
    transport(monkeypatch,handler)
    response=setup.client.post('/company-knowledge/chat/stream',json={'message':'核实资料','document_ids':[doc_id]})
    events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert events[-1]['type']=='error' and '引用检查' in events[-1]['message']
    assert not any(event['type']=='done' for event in events)


def test_tags_description_editing_and_locked_metadata_redaction(setup):
    row = upload(setup, project='案例项目', category='项目原件', visibility='restricted',
                 tags='["行业背景", "行业背景", "访谈"]', description='只给授权账号阅读的说明').json()
    assert row['tags'] == ['行业背景', '访谈'] and row['created_at']
    assert row['description'] == '只给授权账号阅读的说明'
    response = setup.client.patch('/company-knowledge/documents/' + row['id'], json={
        'tags': ['修正标签'], 'description': '更正说明', 'industry': '汽车'})
    assert response.status_code == 200
    assert response.json()['visibility'] == 'restricted'
    assert response.json()['tags'] == ['修正标签']
    setup.user.id, setup.user.username = 3, 'charlie'
    locked = setup.client.get('/company-knowledge/documents').json()['documents'][0]
    assert locked['tags'] == [] and locked['description'] == '' and not locked['can_read']
    assert setup.client.patch('/company-knowledge/documents/' + row['id'], json={'tags': ['越权']}).status_code == 404


@pytest.mark.parametrize('tags', ['[" "]', '["' + '长' * 41 + '"]', '"not-a-list"', '[' + ','.join('"x"' for _ in range(21)) + ']'])
def test_tag_limits_are_enforced_on_upload_and_edit(setup, tags):
    assert upload(setup, tags=tags).status_code == 422
    row = upload(setup).json()
    assert setup.client.patch('/company-knowledge/documents/' + row['id'], json={'tags': json.loads(tags)}).status_code == 422


def test_media_indexes_only_description_and_reindexes_edits_without_changing_original(setup, monkeypatch):
    audio = b'RIFF' + (40).to_bytes(4, 'little') + b'WAVE' + b'original-audio-fixture'
    assert upload(setup, name='复盘.wav', payload=audio).status_code == 422
    row = upload(setup, name='复盘.wav', payload=audio, category='案例复盘', description='访谈复盘经验', tags='["访谈方法"]').json()
    assert row['media_kind'] == 'audio' and row['state'] == 'queued'
    observed, puts = [], []
    sequence = {'n': 0}
    def handler(request):
        observed.append(request.url.path)
        body = json.loads(request.content) if request.method == 'POST' else {}
        if request.method == 'PUT':
            assert 'Authorization' not in request.headers
            assert b'original-audio-fixture' not in request.content
            puts.append(request.content.decode())
            return httpx.Response(200)
        if request.url.path.endswith('delete_file'):
            assert body['doc_ids'] == ['cloud-media-1']
            return httpx.Response(200, json={'data': {}})
        if request.url.path.endswith('applyFileUploadLease'):
            sequence['n'] += 1
            assert body['fileName'] == '复盘.wav.md'
            return httpx.Response(200, json={'data': {'leaseId': 'lease', 'param': {'url': 'https://bucket.oss-cn-beijing.aliyuncs.com/summary'}}})
        if request.url.path.endswith('addFile'):
            assert body['parser'] == 'AUTO_SELECT'
            return httpx.Response(200, json={'data': {'fileId': 'cloud-media-' + str(sequence['n'])}})
        if request.url.path.endswith('job/create'):
            return httpx.Response(200, json={'data': {'ingestionId': 'job'}})
        return httpx.Response(200, json={'data': {'rows': [{'doc_id': 'cloud-media-' + str(sequence['n']), 'status': 'FINISH'}]}})
    transport(monkeypatch, handler)
    asyncio.run(ingestion.process_document(row['id']))
    assert '访谈复盘经验' in puts[0] and '访谈方法' in puts[0] and '未自动转写' in puts[0]
    response = setup.client.get('/company-knowledge/documents/' + row['id'] + '/original')
    assert response.status_code == 200 and response.content == audio  # Media originals no longer require a marked export.
    assert stored_original(setup, row['id']) == audio
    response = setup.client.patch('/company-knowledge/documents/' + row['id'], json={'description': '已修正的访谈经验'})
    assert response.status_code == 200 and response.json()['state'] == 'queued'
    assert response.json()['cloud_id'] is None
    assert setup.client.patch('/company-knowledge/documents/' + row['id'], json={'description': '过早再次编辑'}).status_code == 409
    asyncio.run(ingestion.process_document(row['id']))
    assert '已修正的访谈经验' in puts[1] and '访谈复盘经验' not in puts[1]
    assert stored_original(setup, row['id']) == audio
    assert observed.count('/api/v1/indices/rag/index/delete_file') == 1


@pytest.mark.parametrize('name,payload', [('fake.mp3', b'not audio'), ('fake.mp4', b'not video'), ('fake.wav', b'RIFFwrong')])
def test_media_content_must_match_extension(setup, name, payload):
    assert upload(setup, name=name, payload=payload, description='测试说明').status_code == 422


def test_additive_catalogue_migration_preserves_existing_rows_and_is_repeatable(setup):
    from company_catalog import ensure_company_schema
    row = upload(setup).json()
    with setup.db() as db:
        engine = db.get_bind()
    with engine.begin() as connection:
        for name in ('tags', 'description', 'stale_cloud_id'):
            connection.exec_driver_sql('ALTER TABLE company_documents DROP COLUMN ' + name)
    ensure_company_schema(engine)
    ensure_company_schema(engine)
    with setup.db() as db:
        doc = db.get(CompanyDocument, row['id'])
        assert doc.title == 'evidence.txt' and doc.tags == [] and doc.description == '' and doc.stale_cloud_id == ''


def test_conflicting_project_edit_returns_a_recoverable_error_and_preserves_original(setup):
    first = upload(setup, project='P1').json()
    second = upload(setup, project='P2').json()
    response = setup.client.patch('/company-knowledge/documents/' + second['id'], json={'project':'P1','tags':['应回滚']})
    assert response.status_code == 409
    with setup.db() as db:
        doc = db.get(CompanyDocument, second['id'])
        assert doc.project == 'P2' and doc.tags == []
    assert stored_original(setup, second['id']) == b'Company knowledge evidence'


def project(setup, name='AI Agent 研究', **values):
    response = setup.client.post('/company-knowledge/projects', json={'name': name, **values})
    assert response.status_code == 201, response.text
    return response.json()


def folder(setup, project_id, name='录音', parent_id=''):
    response = setup.client.post('/company-knowledge/projects/' + project_id + '/folders', json={'name':name,'parent_id':parent_id})
    assert response.status_code == 201, response.text
    return response.json()


def test_empty_project_persists_and_nested_folders_are_project_scoped(setup):
    p = project(setup, industry='人工智能', tags=['行业背景'])
    assert p['document_count'] == 0 and p['tags'] == ['行业背景']
    root = folder(setup,p['id'])
    child = folder(setup,p['id'],'访谈一',root['id'])
    other = project(setup,'另一项目')
    assert setup.client.post('/company-knowledge/projects/'+other['id']+'/folders',json={'name':'越界','parent_id':root['id']}).status_code == 404
    assert setup.client.post('/company-knowledge/projects/'+p['id']+'/folders',json={'name':'录音'}).status_code == 409
    assert setup.client.post('/company-knowledge/projects/'+p['id']+'/folders',json={'name':'../secret'}).status_code == 422
    state=setup.client.get('/company-knowledge/projects').json()
    assert next(row for row in state['projects'] if row['id']==p['id'])['folder_count']==2
    assert next(row for row in state['folders'] if row['id']==child['id'])['parent_id']==root['id']
    assert setup.client.delete('/company-knowledge/projects/'+p['id']+'/folders/'+root['id']).status_code == 409
    assert setup.client.delete('/company-knowledge/projects/'+p['id']+'/folders/'+child['id']).status_code == 200


def test_experience_categories_support_photo_handwriting_and_prevent_reclassification_across_collections(setup):
    library=project(setup,'规范资料项目',category='项目原件')
    experience=project(setup,'手稿经验项目',category='手稿笔记')
    assert experience['category']=='手稿笔记'
    for p,category in [(library,'现场照片'),(experience,'行业资料')]:
        result=setup.client.patch('/company-knowledge/projects/'+p['id'],json={'name':p['name'],'category':category})
        assert result.status_code==422
    assert setup.client.patch('/company-knowledge/projects/'+experience['id'],json={'name':experience['name'],'category':'现场照片'}).status_code==200
    library_file=upload(setup,project_id=library['id']).json()
    experience_file=upload(setup,project_id=experience['id'],name='手稿.png',payload=b'\x89PNG\r\n\x1a\nphoto-fixture').json()
    assert experience_file['category']=='现场照片' and experience_file['inherits_project']==1
    assert setup.client.patch('/company-knowledge/documents/'+library_file['id'],json={'category':'影音随记'}).status_code==422


def test_project_upload_inherits_metadata_and_versions_are_local_to_folder(setup):
    setup.user.role='admin'
    p=project(setup,industry='AI',tags=['项目标签'],confidentiality='secret',readers=['bob'])
    a=folder(setup,p['id'],'报告'); b=folder(setup,p['id'],'笔录')
    first=upload(setup,project_id=p['id'],folder_id=a['id'],tags='["伪造标签"]',confidentiality='internal').json()
    assert first['project']==p['name'] and first['industry']=='AI' and first['tags']==['项目标签']
    assert first['confidentiality']=='secret' and first['visibility']=='restricted'
    assert first['inherits_project']==1 and first['folder_id']==a['id'] and first['version']==1
    assert upload(setup,project_id=p['id'],folder_id=a['id']).status_code==409
    second=upload(setup,project_id=p['id'],folder_id=b['id']).json()
    assert second['version']==1 and second['id']!=first['id']
    newer=upload(setup,payload=b'new version',project_id=p['id'],folder_id=a['id']).json()
    assert newer['version']==2
    assert setup.client.patch('/company-knowledge/documents/'+first['id'],json={'tags':['changed']}).status_code==422
    assert setup.client.patch('/company-knowledge/documents/'+first['id'],json={'title':'改名.pdf'}).status_code==422
    moved=setup.client.patch('/company-knowledge/documents/'+first['id'],json={'title':'访谈.txt','folder_id':b['id']})
    assert moved.status_code==200 and moved.json()['folder_id']==b['id']


def test_project_access_cannot_be_bypassed_by_folder_or_file_requests(setup):
    setup.user.role='admin'
    p=project(setup,confidentiality='secret',readers=[])
    f=folder(setup,p['id'])
    row=upload(setup,project_id=p['id'],folder_id=f['id']).json()
    setup.user.id,setup.user.username,setup.user.role=2,'bob','user'
    assert setup.client.get('/company-knowledge/projects').json()['projects']==[]
    assert upload(setup,project_id=p['id']).status_code==404
    assert setup.client.post('/company-knowledge/projects/'+p['id']+'/folders',json={'name':'不能建'}).status_code==404
    assert setup.client.get('/company-knowledge/documents/'+row['id']+'/original').status_code==404
    setup.user.id,setup.user.username=1,'alice'
    public=project(setup,'公开项目')
    setup.user.id,setup.user.username=2,'bob'
    assert upload(setup,project_id=public['id']).status_code==403


def test_project_rename_and_acl_edits_update_inherited_files_without_losing_originals(setup):
    p=project(setup,tags=['原标签'])
    row=upload(setup,project_id=p['id']).json()
    setup.user.role='admin'
    values={'name':'新的项目名称','industry':'新行业','tags':['修正标签'],'confidentiality':'confidential','readers':['bob']}
    response=setup.client.patch('/company-knowledge/projects/'+p['id'],json=values)
    assert response.status_code==200,response.text
    with setup.db() as db:
        doc=db.get(CompanyDocument,row['id'])
        assert doc.project=='新的项目名称' and doc.industry=='新行业' and doc.tags==['修正标签']
        assert doc.visibility=='restricted' and doc.readers==['bob']
    assert stored_original(setup, row['id']) == b'Company knowledge evidence'
    setup.user.id,setup.user.username,setup.user.role=3,'charlie','user'
    assert setup.client.get('/company-knowledge/documents/'+row['id']+'/original').status_code==404


def test_project_media_without_notes_is_archive_only_and_can_gain_or_remove_description_index(setup,monkeypatch):
    p=project(setup)
    audio=b'RIFF'+(40).to_bytes(4,'little')+b'WAVE'+b'original-fixture'
    result=upload(setup,name='访谈.wav',payload=audio,project_id=p['id'])
    assert result.status_code==202,result.text
    row=result.json()
    assert row['state']=='archived' and row['id'] not in setup.scheduled
    assert stored_original(setup, row['id']) == audio
    changed=setup.client.patch('/company-knowledge/documents/'+row['id'],json={'description':'人工说明'})
    assert changed.status_code==200 and changed.json()['state']=='queued' and row['id'] in setup.scheduled
    ready(setup,row['id'],'media-cloud')
    calls=[]
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200,json={'data':{}})
    transport(monkeypatch,handler)
    assert setup.client.patch('/company-knowledge/documents/'+row['id'],json={'description':''}).status_code==200
    asyncio.run(ingestion.process_document(row['id']))
    assert calls==['/api/v1/indices/rag/index/delete_file']
    with setup.db() as db:
        doc=db.get(CompanyDocument,row['id'])
        assert doc.state=='archived' and doc.cloud_id is None and not doc.stale_cloud_id


def test_project_migration_keeps_legacy_acl_and_can_repeat_without_duplicate_projects(setup):
    from company_catalog import backfill_company_projects
    secret=upload(setup,project='历史项目',visibility='restricted',readers='["bob"]').json()
    with setup.db() as db: engine=db.get_bind()
    backfill_company_projects(engine);backfill_company_projects(engine)
    state=setup.client.get('/company-knowledge/projects').json()
    assert len(state['projects'])==1
    p=state['projects'][0]
    with setup.db() as db:
        doc=db.get(CompanyDocument,secret['id'])
        assert doc.knowledge_project_id==p['id'] and doc.visibility=='restricted' and doc.readers==['bob']
        assert not doc.inherits_project
    assert setup.client.patch('/company-knowledge/documents/'+secret['id'],json={'project':'不能绕过目录修改'}).status_code==422


def test_project_media_rename_requeues_index_and_empty_projects_count_in_my_projects(setup):
    p=project(setup)
    empty=setup.client.get('/company-knowledge/my-projects').json()
    assert empty['project_count']==1 and empty['document_count']==0
    audio=b'RIFF'+(40).to_bytes(4,'little')+b'WAVE'+b'original-fixture'
    row=upload(setup,name='访谈.wav',payload=audio,project_id=p['id'],description='人工说明').json()
    ready(setup,row['id'],'old-media-index')
    response=setup.client.patch('/company-knowledge/projects/'+p['id'],json={'name':'改名项目'})
    assert response.status_code==200,response.text
    with setup.db() as db:
        doc=db.get(CompanyDocument,row['id'])
        assert doc.project=='改名项目' and doc.state=='queued' and doc.cloud_id is None
        assert doc.stale_cloud_id=='old-media-index'
    assert setup.scheduled.count(row['id'])==2


def test_directory_upgrade_removes_legacy_global_file_uniqueness_without_losing_files(setup):
    from company_catalog import ensure_company_schema
    from sqlalchemy import inspect
    row=upload(setup,project='历史升级项目').json()
    with setup.db() as db:engine=db.get_bind()
    with engine.begin() as connection:
        for index in inspect(engine).get_indexes('company_documents'):
            if set(index['column_names']) & {'knowledge_project_id','folder_id'}:
                connection.exec_driver_sql('DROP INDEX '+index['name'])
        for column in ('knowledge_project_id','folder_id','inherits_project'):
            connection.exec_driver_sql('ALTER TABLE company_documents DROP COLUMN '+column)
        connection.exec_driver_sql("CREATE UNIQUE INDEX uq_company_active_content ON company_documents (index_id,owner,project,title,sha256) WHERE sha256 != '' AND state != 'deleted'")
        connection.exec_driver_sql("CREATE UNIQUE INDEX uq_company_file_version ON company_documents (index_id,owner,project,title,version) WHERE sha256 != ''")
    ensure_company_schema(engine);ensure_company_schema(engine)
    assert 'uq_company_active_content' not in {index['name'] for index in inspect(engine).get_indexes('company_documents')}
    with setup.db() as db:
        doc=db.get(CompanyDocument,row['id']);project_id=doc.knowledge_project_id
        assert project_id and doc.folder_id==''
    f=folder(setup,project_id,'报告')
    assert upload(setup,project_id=project_id,folder_id=f['id']).status_code==202
    assert stored_original(setup, row['id']) == b'Company knowledge evidence'


def test_migration_does_not_merge_unnamed_files_into_an_existing_named_project(setup):
    from company_catalog import backfill_company_projects
    named=project(setup,'未归档资料')
    legacy=upload(setup,project='').json()
    with setup.db() as db:engine=db.get_bind()
    backfill_company_projects(engine);backfill_company_projects(engine)
    state=setup.client.get('/company-knowledge/projects').json()
    assert len(state['projects'])==2
    with setup.db() as db:
        doc=db.get(CompanyDocument,legacy['id'])
        assert doc.knowledge_project_id!=named['id'] and doc.project==''
    summary=setup.client.get('/company-knowledge/my-projects').json()
    assert summary['project_count']==2 and summary['document_count']==1
