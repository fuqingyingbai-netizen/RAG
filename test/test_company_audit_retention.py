"""Knowledge history retention must never erase file retry protection."""
from datetime import datetime,timedelta
import pytest
from sqlalchemy import select,func
from test_company_workspace import setup,upload,stored_original
from test_company_root_files import ready
from test_company_file_clipboard import transfer
from company_catalog import CompanyAuditEvent,CompanyFileReceipt,CompanyDocument
import company_audit as audit


def event(id,created,index='test-index'):
    return CompanyAuditEvent(id=id,index_id=index,project_id='',target_type='document',target_id='synthetic',
        target_name='synthetic.txt',actor_id=1,actor_username='alice',action='document.preview',created_at=created,details={},changes={})


def test_rolling_ten_day_visibility_boundary_and_bounded_purge(setup,monkeypatch):
    now=datetime.utcnow()
    class Clock(datetime):
        @classmethod
        def utcnow(cls):return now
    monkeypatch.setattr(audit,'datetime',Clock)
    setup.user.role='admin'
    with setup.db() as db:
        db.add_all([event('expired',now-timedelta(days=10,seconds=1)),event('boundary',now-timedelta(days=10)),
                    event('recent',now-timedelta(days=10)+timedelta(seconds=1)),event('new',now)])
        db.commit()
    page=setup.client.get('/company-knowledge/audit-events').json()
    assert {e['id'] for e in page['events']}=={'recent','new'}
    assert page['retention_days']==10 and page['can_delete']
    assert page['events'][0]['expires_at']==(now+timedelta(days=10)).isoformat()+'Z'
    assert audit.purge_expired(setup.db,limit=1,now=now)==1
    assert audit.purge_expired(setup.db,limit=1,now=now)==1
    assert audit.purge_expired(setup.db,now=now)==0
    with setup.db() as db:assert db.scalar(select(func.count()).select_from(CompanyAuditEvent))==2


def test_only_admin_can_delete_and_deletion_never_changes_file(setup):
    row=upload(setup,root='true').json()
    listing=setup.client.get('/company-knowledge/audit-events',params={'document_id':row['id']}).json()
    id=listing['events'][0]['id'];path='/company-knowledge/audit-events/'+id
    assert not listing['can_delete'] and setup.client.delete(path).status_code==403
    setup.user.role='admin'
    assert setup.client.delete(path).status_code==200
    assert setup.client.delete(path).status_code==404
    assert stored_original(setup,row['id'])==b'Company knowledge evidence'
    with setup.db() as db:
        db.add(event('other-index',datetime.utcnow(),'foreign-index'));db.commit()
    assert setup.client.delete('/company-knowledge/audit-events/other-index').status_code==404
    setup.client.app.dependency_overrides.clear()
    assert setup.client.delete(path).status_code==401


def test_delete_legacy_upload_audit_preserves_idempotent_receipt(setup):
    row=upload(setup,root='true',request_id='same-upload').json()
    with setup.db() as db:
        logged=db.scalar(select(CompanyAuditEvent).where(CompanyAuditEvent.target_id==row['id']))
        id=logged.id;db.delete(db.get(CompanyFileReceipt,id));db.commit()
    setup.user.role='admin'
    assert setup.client.delete('/company-knowledge/audit-events/'+id).status_code==200
    result=upload(setup,root='true',request_id='same-upload')
    assert result.status_code==202 and result.json()['id']==row['id']
    with setup.db() as db:
        assert db.get(CompanyFileReceipt,id) and not db.get(CompanyAuditEvent,id)
        assert db.scalar(select(func.count()).select_from(CompanyDocument))==1


def test_expired_legacy_copy_receipt_remains_replayable_and_permission_checked(setup):
    row=upload(setup,root='true').json();ready(setup,row)
    response,data=transfer(setup,row);assert response.status_code==201
    clone=response.json()['document']
    with setup.db() as db:
        logged=db.scalar(select(CompanyAuditEvent).where(CompanyAuditEvent.target_id==clone['id']))
        id=logged.id;logged.created_at=datetime.utcnow()-timedelta(days=11)
        db.delete(db.get(CompanyFileReceipt,id));db.commit()
    assert audit.purge_expired(setup.db)==1
    result=setup.client.post('/company-knowledge/documents/'+row['id']+'/copy',json=data)
    assert result.status_code==201 and result.json()['document']['id']==clone['id']
    with setup.db() as db:
        assert db.scalar(select(func.count()).select_from(CompanyDocument))==2
        db.get(CompanyDocument,clone['id']).state='deleted';db.commit()
    assert setup.client.post('/company-knowledge/documents/'+row['id']+'/copy',json=data).status_code==409


def test_cleanup_rolls_back_if_receipt_cannot_be_preserved(setup,monkeypatch):
    with setup.db() as db:
        db.add_all([event('a',datetime.utcnow()-timedelta(days=11)),event('b',datetime.utcnow()-timedelta(days=11))]);db.commit()
    def preserve(db,row):
        if row.id=='b':raise RuntimeError('synthetic receipt storage failure')
    monkeypatch.setattr(audit,'preserve_receipt',preserve)
    with pytest.raises(RuntimeError):audit.purge_expired(setup.db)
    with setup.db() as db:assert db.scalar(select(func.count()).select_from(CompanyAuditEvent))==2
