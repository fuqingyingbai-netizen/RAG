"""Deletion receipts, pending copies, provider failures and shared originals."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import threading

import pytest
from sqlalchemy import select, func
from test_company_workspace import setup, upload, stored_original
from test_company_root_files import ready
from test_company_file_clipboard import transfer
from company_catalog import CompanyDocument, CompanyAuditEvent
from company_recycle import RecycleItem
import company_knowledge as kb
import company_ingestion as ingestion


def count(db, model, doc_id):
    column = model.target_id
    return db.scalar(select(func.count()).select_from(model).where(column == doc_id))


def test_delete_queued_copy_preserves_source_bytes_and_blocks_receipt_resurrection(setup, monkeypatch):
    source = upload(setup, root='true').json(); ready(setup, source)
    response, payload = transfer(setup, source)
    clone = response.json()['document']
    async def forbidden(*args, **kwargs):
        raise AssertionError('Unregistered copy must not delete the source cloud index')
    monkeypatch.setattr(kb, 'cloud_rpc', forbidden)
    path = '/company-knowledge/documents/' + clone['id']
    assert setup.client.delete(path).status_code == 200
    assert setup.client.delete(path).status_code == 200
    asyncio.run(ingestion.process_document(clone['id']))
    assert setup.client.get(path+'/original').status_code == 404
    assert setup.client.post(path+'/retry').status_code == 404
    assert setup.client.post('/company-knowledge/documents/'+source['id']+'/copy', json=payload).status_code == 409
    assert [r['id'] for r in setup.client.get('/company-knowledge/documents').json()['documents']] == [source['id']]
    assert stored_original(setup, source['id']) == stored_original(setup, clone['id'])
    with setup.db() as db:
        assert db.get(CompanyDocument, source['id']).cloud_id == 'cloud-'+source['id']
        assert db.get(CompanyDocument, clone['id']).state == 'deleted'
        assert count(db, RecycleItem, clone['id']) == 1
        assert db.scalar(select(func.count()).select_from(CompanyAuditEvent).where(
            CompanyAuditEvent.target_id == clone['id'], CompanyAuditEvent.action == 'document.delete')) == 1


@pytest.mark.parametrize('state', ['ready', 'failed', 'archived', 'deleting'])
def test_delete_cloud_states_is_atomic_and_retryable(setup, monkeypatch, state):
    row = upload(setup).json(); ready(setup, row)
    with setup.db() as db:
        doc = db.get(CompanyDocument, row['id'])
        doc.state = state; doc.stale_cloud_id = 'previous-index'
        old_message = doc.status_message; db.commit()
    calls = []
    async def failing(client, cfg, path, payload):
        calls.append(payload)
        raise TimeoutError('provider-key-should-never-leak')
    monkeypatch.setattr(kb, 'cloud_rpc', failing)
    path = '/company-knowledge/documents/'+row['id']
    result = setup.client.delete(path)
    assert result.status_code == 502 and 'provider-key' not in result.text
    assert '尚未确认' in result.json()['detail']
    with setup.db() as db:
        doc = db.get(CompanyDocument, row['id'])
        assert doc.state == state and doc.status_message == old_message
        assert count(db, RecycleItem, row['id']) == 0
    async def success(*args, **kwargs): return {}
    monkeypatch.setattr(kb, 'cloud_rpc', success)
    assert setup.client.delete(path).status_code == 200
    with setup.db() as db:
        expiry = db.scalar(select(RecycleItem).where(RecycleItem.target_id == row['id'])).purge_after
    assert setup.client.delete(path).status_code == 200
    with setup.db() as db:
        assert db.scalar(select(RecycleItem).where(RecycleItem.target_id == row['id'])).purge_after == expiry
    assert calls[0]['doc_ids'] == ['cloud-'+row['id'], 'previous-index']


@pytest.mark.parametrize('state,lease,job', [
    ('uploading', False, ''), ('parsing', False, ''), ('indexing', False, 'job'),
    ('queued', True, ''), ('failed', True, ''), ('queued', False, 'previous-job')])
def test_active_processing_delete_is_explicit_and_non_destructive(setup, monkeypatch, state, lease, job):
    row = upload(setup).json()
    with setup.db() as db:
        doc = db.get(CompanyDocument, row['id']); doc.state = state; doc.job_id = job
        if lease: doc.lease_until = datetime.utcnow()+timedelta(minutes=2)
        db.commit()
    response = setup.client.delete('/company-knowledge/documents/'+row['id'])
    assert response.status_code == 409 and '本次未删除' in response.text
    assert stored_original(setup, row['id'])
    with setup.db() as db:
        assert db.get(CompanyDocument, row['id']).state == state
        assert count(db, RecycleItem, row['id']) == 0


def test_reader_and_repeated_deleted_request_recheck_permissions(setup, monkeypatch):
    row = upload(setup, root='true').json()
    path = '/company-knowledge/documents/'+row['id']
    setup.user.id, setup.user.username = 2, 'bob'
    assert setup.client.delete(path).status_code == 403
    setup.user.id, setup.user.username = 1, 'alice'
    assert setup.client.delete(path).status_code == 200
    setup.user.id, setup.user.username = 2, 'bob'
    assert setup.client.delete(path).status_code == 403
    assert setup.client.delete('/company-knowledge/documents/not-found').status_code == 404
    with setup.db() as db:
        doc = db.get(CompanyDocument, row['id']); doc.visibility = 'restricted'; doc.readers = []; db.commit()
    assert setup.client.delete(path).status_code == 404


def test_concurrent_delete_returns_retryable_conflict_then_one_recycle_record(setup, monkeypatch):
    row = upload(setup).json(); ready(setup, row)
    entered, release = threading.Event(), threading.Event()
    async def delayed(*args, **kwargs):
        entered.set()
        assert await asyncio.to_thread(release.wait, 10)
        return {}
    monkeypatch.setattr(kb, 'cloud_rpc', delayed)
    path = '/company-knowledge/documents/'+row['id']
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(setup.client.delete, path)
        try:
            assert entered.wait(5)
            assert setup.client.delete(path).status_code == 409
        finally: release.set()
        assert pending.result().status_code == 200
    assert setup.client.delete(path).status_code == 200
    with setup.db() as db: assert count(db, RecycleItem, row['id']) == 1
