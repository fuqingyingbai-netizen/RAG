import asyncio
from datetime import datetime, timedelta
from sqlalchemy import select
from test_company_workspace import setup, upload, project
from company_catalog import CompanyDocument, CompanyProject, document_store
from company_recycle import RecycleItem, purge_due, initialize
from company_notes import CompanyNote


def deleted(env, **fields):
    row = upload(env, **fields).json()
    with env.db() as db:
        db.get(CompanyDocument, row['id']).state = 'ready'
        db.commit()
    response = env.client.delete('/company-knowledge/documents/'+row['id'])
    assert response.status_code == 200, response.text
    items = env.client.get('/company-knowledge/recycle-bin').json()['items']
    return row, next(item for item in items if item['title'] == row['title'])


def test_ten_days_restore_preserves_original_and_denies_other_owner(setup):
    row, item = deleted(setup)
    with setup.db() as db:
        obj = db.get(RecycleItem, item['id'])
        assert obj.purge_after - obj.deleted_at == timedelta(days=10)
    setup.user.username, setup.user.id = 'bob', 2
    assert setup.client.get('/company-knowledge/recycle-bin').json()['items'] == []
    assert setup.client.post('/company-knowledge/recycle-bin/'+item['id']+'/restore').status_code == 404
    setup.user.username, setup.user.id = 'alice', 1
    response = setup.client.post('/company-knowledge/recycle-bin/'+item['id']+'/restore')
    assert response.status_code == 200, response.text
    assert row['id'] in setup.scheduled
    with setup.db() as db:
        doc = db.get(CompanyDocument, row['id'])
        assert doc.state == 'queued'
        assert document_store().get_bytes(doc.object_key)
    assert setup.client.post('/company-knowledge/recycle-bin/'+item['id']+'/restore').status_code == 409


def test_purge_only_expired_and_never_shared_original(setup):
    row, item = deleted(setup)
    assert asyncio.run(purge_due()) == 0
    with setup.db() as db:
        obj = db.get(RecycleItem, item['id']); obj.purge_after = datetime.utcnow()-timedelta(seconds=1)
        doc = db.get(CompanyDocument, row['id']); key = doc.object_key
        db.commit()
    assert setup.client.post('/company-knowledge/recycle-bin/'+item['id']+'/restore').status_code == 409
    assert asyncio.run(purge_due()) == 1
    assert asyncio.run(purge_due()) == 0
    assert not document_store()._local_path(key).exists()
    with setup.db() as db:
        assert db.get(CompanyDocument,row['id']).object_key == ''
        assert db.get(RecycleItem,item['id']).status == 'purged'


def test_project_restore_includes_documents_and_notes(setup):
    p = project(setup, '恢复整个项目', category='项目经验')
    row = upload(setup, project_id=p['id']).json()
    note = setup.client.post('/company-knowledge/notes',json={'project_id':p['id']}).json()
    with setup.db() as db:
        db.get(CompanyDocument,row['id']).state='ready';db.commit()
    preview = setup.client.get('/company-knowledge/projects/'+p['id']+'/deletion-preview').json()
    response = setup.client.request('DELETE','/company-knowledge/projects/'+p['id'],json={'confirmation':preview['confirmation']})
    assert response.status_code == 200, response.text
    items = setup.client.get('/company-knowledge/recycle-bin').json()['items']
    assert len(items) == 1 and items[0]['kind'] == 'project'
    response = setup.client.post('/company-knowledge/recycle-bin/'+items[0]['id']+'/restore')
    assert response.status_code == 200, response.text
    with setup.db() as db:
        assert db.get(CompanyProject,p['id']).deleted_at is None
        assert db.get(CompanyNote,note['id']).deleted_at is None
        assert db.get(CompanyDocument,row['id']).state == 'queued'


def test_legacy_deleted_original_gets_fresh_grace_once(setup):
    row = upload(setup).json()
    with setup.db() as db:
        db.get(CompanyDocument,row['id']).state='deleted';db.commit()
    with setup.db() as db:
        initialize(db.get_bind())
    with setup.db() as db:
        items=list(db.scalars(select(RecycleItem)))
        assert len(items)==1 and items[0].purge_after > datetime.utcnow()+timedelta(days=9)


def test_shared_original_survives_expired_tombstone(setup):
    row,item=deleted(setup)
    other=upload(setup,payload=b'different',name='other.txt').json()
    with setup.db() as db:
        original=db.get(CompanyDocument,row['id'])
        key=original.object_key
        db.get(CompanyDocument,other['id']).object_key=key
        db.get(RecycleItem,item['id']).purge_after=datetime.utcnow()-timedelta(days=1)
        db.commit()
    assert asyncio.run(purge_due())==1
    assert document_store().get_bytes(key)
