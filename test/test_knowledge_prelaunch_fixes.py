"""Regression checks for the prelaunch findings; synthetic local data only."""
import asyncio
import hashlib
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from openpyxl import Workbook

import company_ingestion as ingestion
import company_knowledge as kb
from company_catalog import CompanyDocument, document_store
from company_sheet_preview import sheet_info
from test_company_workspace import setup, upload, project, transport


def test_missing_physical_original_is_reported_and_can_be_restored(setup):
    payload = b'original recovery evidence'
    row = upload(setup, payload=payload).json()
    with setup.db() as db:
        doc = db.get(CompanyDocument, row['id'])
        key = doc.object_key
        doc.state, doc.cloud_id = 'ready', 'old-cloud'
        db.commit()
    document_store().delete_object(key)
    base = '/company-knowledge/documents/' + row['id']
    response = setup.client.get(base + '/download')
    assert response.status_code == 404
    assert response.headers['x-preview-error'] == 'original_missing'
    response = setup.client.post(base + '/original', files={'file': ('evidence.txt', payload)},
                                 data={'confirmation': row['id']})
    assert response.status_code == 202, response.text
    with setup.db() as db:
        doc = db.get(CompanyDocument, row['id'])
        assert doc.state == 'queued' and doc.stale_cloud_id == 'old-cloud' and not doc.cloud_id
        assert document_store().get_bytes(doc.object_key) == payload
        assert doc.sha256 == hashlib.sha256(payload).hexdigest()
    assert setup.client.post(base + '/original', files={'file': ('evidence.txt', payload)},
                             data={'confirmation': row['id']}).status_code == 409


def test_missing_original_restore_keeps_permissions_and_requires_confirmation(setup):
    row = upload(setup).json()
    with setup.db() as db:
        doc = db.get(CompanyDocument, row['id'])
        document_store().delete_object(doc.object_key)
        doc.state = 'ready'
        db.commit()
    url = '/company-knowledge/documents/' + row['id'] + '/original'
    files = {'file': ('evidence.txt', b'recovery')}
    assert setup.client.post(url, files=files, data={'confirmation': 'wrong'}).status_code == 422
    setup.user.username, setup.user.id = 'bob', 2
    assert setup.client.post(url, files=files, data={'confirmation': row['id']}).status_code == 403


@pytest.mark.parametrize('rows,columns,page,column,last', [(10001, 1, 201, 1, 'row-10001'),
                                                         (1, 257, 1, 257, 'column-257')])
def test_dimensionless_spreadsheet_exposes_last_valid_row_and_column(setup, rows, columns, page, column, last):
    book = Workbook(write_only=True)
    sheet = book.create_sheet('streamed')
    for row in range(1, rows + 1):
        sheet.append([f'row-{row}' if columns == 1 else f'column-{i}' for i in range(1, columns + 1)])
    output = io.BytesIO()
    book.save(output)
    record = upload(setup, payload=output.getvalue(), name='streamed.xlsx').json()
    sheet_info.cache_clear()
    response = setup.client.get('/company-knowledge/documents/' + record['id'] + '/sheet',
                                 params={'page': page, 'column': column})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['sheets'][0]['rows'] == rows and result['sheets'][0]['columns'] == columns
    assert result['mode'] == 'table' and result['values'][-1][-1] == last
    sheet_info.cache_clear()


def test_file_write_does_not_hold_project_lock_or_block_browsing(setup, monkeypatch):
    directory = project(setup)
    entered, release = threading.Event(), threading.Event()
    store = document_store()
    real_write = type(store).put_bytes
    def slow_write(self, *args):
        entered.set()
        assert release.wait(10), 'synthetic storage write timed out'
        return real_write(self, *args)
    monkeypatch.setattr(type(store), 'put_bytes', slow_write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(upload, setup, project_id=directory['id'])
        try:
            assert entered.wait(5)
            response = setup.client.post('/company-knowledge/projects/' + directory['id'] + '/folders',
                                         json={'name': 'usable-during-upload'})
            assert response.status_code == 201, response.text
            assert setup.client.get('/company-knowledge/projects').status_code == 200
        finally:
            release.set()
        assert future.result(timeout=10).status_code == 202


def test_client_disconnect_during_storage_cannot_delete_a_later_committed_original(setup, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    real_write = type(document_store()).put_bytes
    def slow_write(self, *args):
        entered.set()
        assert release.wait(5)
        return real_write(self, *args)
    monkeypatch.setattr(type(document_store()), 'put_bytes', slow_write)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=setup.client.app), base_url='http://test') as client:
            pending = asyncio.create_task(client.post('/company-knowledge/uploads',
                files={'file': ('cancelled.txt', b'disconnect evidence')}))
            try:
                for _ in range(100):
                    if entered.is_set():
                        break
                    await asyncio.sleep(.01)
                assert entered.is_set()
                pending.cancel()
                await asyncio.sleep(.02)
            finally:
                release.set()
            with pytest.raises(asyncio.CancelledError):
                await pending
    asyncio.run(run())
    with setup.db() as db:
        doc = db.query(CompanyDocument).one()
        assert document_store().get_bytes(doc.object_key) == b'disconnect evidence'
        assert setup.scheduled == [doc.id]


@pytest.mark.parametrize('cleanup_available', [True, False])
@pytest.mark.parametrize('commit_acknowledged', [False, True])
def test_registration_checkpoint_failure_never_creates_second_cloud_file(setup, monkeypatch, cleanup_available, commit_acknowledged):
    doc_id = upload(setup).json()['id']
    registered, calls = {}, []
    real_checkpoint = ingestion.checkpoint
    failed = False
    def checkpoint(*args, **values):
        nonlocal failed
        if values.get('cloud_id') and not failed:
            failed = True
            if commit_acknowledged:
                real_checkpoint(*args, **values)
            raise RuntimeError('synthetic checkpoint failure')
        return real_checkpoint(*args, **values)
    monkeypatch.setattr(ingestion, 'checkpoint', checkpoint)
    def handler(request):
        path = request.url.path
        body = json.loads(request.content) if request.method == 'POST' else {}
        calls.append(path)
        if path.endswith('applyFileUploadLease'):
            return httpx.Response(200, json={'data': {'leaseId': 'lease-test', 'param': {
                'url': 'https://bucket.oss-cn-beijing.aliyuncs.com/upload'}}})
        if request.method == 'PUT':
            return httpx.Response(200)
        if path.endswith('addFile'):
            file_id = 'cloud-' + str(len(registered) + 1)
            registered[file_id] = {'fileId': file_id, 'tags': body['tags']}
            return httpx.Response(200, json={'data': {'fileId': file_id}})
        if path.endswith('deleteFile'):
            if not cleanup_available:
                return httpx.Response(503)
            registered.pop(body['fileId'])
            return httpx.Response(200, json={'data': {}})
        if path.endswith('listFile'):
            return httpx.Response(200, json={'data': {'fileList': list(registered.values())}})
        if path.endswith('job/create'):
            return httpx.Response(200, json={'data': {'ingestionId': 'job-test'}})
        assert path.endswith('index_job/status')
        return httpx.Response(200, json={'data': {'rows': [{'doc_id': next(iter(registered)), 'status': 'FINISH'}]}})
    transport(monkeypatch, handler)
    asyncio.run(ingestion.process_document(doc_id))
    assert setup.client.post('/company-knowledge/documents/' + doc_id + '/retry').status_code == 202
    asyncio.run(ingestion.process_document(doc_id))
    with setup.db() as db:
        doc = db.get(CompanyDocument, doc_id)
        assert doc.state == 'ready' and doc.cloud_id in registered
    assert len(registered) == 1
    assert sum(path.endswith('addFile') for path in calls) == (2 if cleanup_available and not commit_acknowledged else 1)


def test_registration_recovery_reads_tags_from_details_and_all_pages():
    async def run():
        doc_id, lease = 'synthetic-doc', 'synthetic-lease'
        calls = []
        def handler(request):
            body = json.loads(request.content)
            calls.append(request.url.path)
            if request.url.path.endswith('describeFile'):
                return httpx.Response(200, json={'data': {'fileId': body['fileId'], 'tags': ['other-version']}})
            if not body.get('nextToken'):
                return httpx.Response(200, json={'data': {'fileList': [{'fileId': 'unrelated'}],
                                                        'hasNext': True, 'nextToken': 'next'}})
            return httpx.Response(200, json={'data': {'hasNext': False, 'fileList': [{'fileId': 'owned',
                'tags': [ingestion.document_tag(doc_id), ingestion.registration_tag(lease)]}]}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            recovered = await ingestion.recover_registration(client, {'base_url': 'https://cloud.invalid', 'api_key': 'x'},
                                                              doc_id, lease, 'synthetic.txt')
            assert recovered == 'owned' and len(calls) == 3
    asyncio.run(run())


@pytest.mark.parametrize('malformed', ['file-list', 'tags'])
def test_incomplete_cloud_reconciliation_refuses_to_register_again(malformed):
    async def run():
        def handler(request):
            data = {} if malformed == 'file-list' or request.url.path.endswith('describeFile') else {
                'fileList': [{'fileId': 'unknown-tags'}]}
            return httpx.Response(200, json={'data': data})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(kb.KnowledgeError, match='本次未重新注册文件'):
                await ingestion.recover_registration(client, {'base_url': 'https://cloud.invalid', 'api_key': 'x'},
                                                     'doc', 'lease', 'synthetic.txt')
    asyncio.run(run())


@pytest.mark.parametrize('code', ['NoSuchKey', 'AccessDenied'])
def test_object_storage_missing_is_distinguished_from_permission_failure(monkeypatch, code):
    from minio.error import S3Error
    from research_store import ResearchObjectStore
    store = ResearchObjectStore()
    store.mode = 'minio'
    class Client:
        def stat_object(self, *args):
            raise S3Error(response=None, code=code, message='synthetic storage error',
                          resource=None, request_id=None, host_id=None)
        get_object = stat_object
    monkeypatch.setattr(store, '_client', lambda: Client())
    if code == 'NoSuchKey':
        assert not store.exists('originals/test.txt')
        with pytest.raises(FileNotFoundError):
            store.get_bytes('originals/test.txt')
    else:
        with pytest.raises(S3Error):
            store.exists('originals/test.txt')
        with pytest.raises(S3Error):
            store.get_bytes('originals/test.txt')


@pytest.mark.parametrize('status,attempts', [(503, 2), (502, 2), (504, 2), (401, 1), (403, 1), (429, 1)])
def test_model_retries_only_explicit_transient_rejection(status, attempts):
    async def run():
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(status if len(calls) == 1 else 200, json={'choices': []})
        config = {'base_url': 'https://model.invalid/v1', 'api_key': 'synthetic', 'provider': 'test'}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            if attempts == 1:
                with pytest.raises(kb.KnowledgeError):
                    async with kb.model_response(client, config, {'stream': True}):
                        pytest.fail('a refusal must not yield a response')
            else:
                async with kb.model_response(client, config, {'stream': True}) as response:
                    assert response.status_code == 200
            assert len(calls) == attempts
    asyncio.run(run())


def test_partial_model_stream_is_never_replayed():
    async def run():
        calls = []
        class BrokenStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'data: partial\n\n'
                raise httpx.ReadError('synthetic disconnect')
        def handler(request):
            calls.append(request)
            return httpx.Response(200, stream=BrokenStream())
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(httpx.ReadError):
                async with kb.model_response(client, {'base_url': 'https://model.invalid', 'api_key': 'x',
                                                       'provider': 'test'}, {'stream': True}) as response:
                    async for _ in response.aiter_bytes():
                        pass
        assert len(calls) == 1
    asyncio.run(run())


@pytest.mark.parametrize('stream,read_timeout', [(True, 120), (False, 85)])
def test_model_keeps_existing_read_allowance(stream, read_timeout):
    async def run():
        def handler(request):
            assert request.extensions['timeout']['read'] == read_timeout
            assert request.extensions['timeout']['connect'] == 20
            return httpx.Response(200, json={'choices': []})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            async with kb.model_response(client, {'base_url': 'https://model.invalid', 'api_key': 'x',
                                                   'provider': 'test'}, {'stream': stream}):
                pass
    asyncio.run(run())
