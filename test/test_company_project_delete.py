"""Project deletion must confirm the exact tree and revoke every published/draft path."""
import pytest
from sqlalchemy import select
from test_company_workspace import setup,project,upload,stored_original
from company_catalog import CompanyDocument,CompanyProject,CompanyAuditEvent,ensure_company_schema
from company_notes import CompanyNote
from test_company_notes import save,publish,ready


def preview(env,p):
    result=env.client.get('/company-knowledge/projects/'+p['id']+'/deletion-preview')
    assert result.status_code==200,result.text
    return result.json()


def remove(env,p,confirmation):
    return env.client.request('DELETE','/company-knowledge/projects/'+p['id'],json={'confirmation':confirmation})


@pytest.mark.parametrize('category',['项目原件','项目经验'])
def test_delete_entire_project_preserves_recovery_but_denies_all_routes(setup,category):
    p=project(setup,'待移除项目',category=category)
    folder=setup.client.post('/company-knowledge/projects/'+p['id']+'/folders',json={'name':'子目录'}).json()
    row=upload(setup,project_id=p['id'],folder_id=folder['id']).json()
    with setup.db() as db:
        db.get(CompanyDocument,row['id']).state='ready';db.commit()
    note=None
    if category=='项目经验':
        note=setup.client.post('/company-knowledge/notes',json={'project_id':p['id'],'folder_id':folder['id']}).json()
        for title in ('第一版','第二版'):
            note=save(setup,note,title=title);note=publish(setup,note);ready(setup,note)
            with setup.db() as db:
                doc=db.get(CompanyDocument,note['pending_document_id']);doc.worker_id='';doc.lease_until=None;db.commit()
            note=setup.client.get('/company-knowledge/notes/'+note['id']).json()
        note=save(setup,note,title='未发布草稿')
    before=preview(setup,p)
    assert before['document_count']==(3 if note else 1) and before['folder_count']==1
    assert before['note_count']==int(note is not None)
    assert remove(setup,p,'0'*64).status_code==409
    assert stored_original(setup,row['id'])==b'Company knowledge evidence'
    assert remove(setup,p,before['confirmation']).status_code==200
    assert p['id'] not in [p['id'] for p in setup.client.get('/company-knowledge/projects').json()['projects']]
    assert setup.client.get('/company-knowledge/documents').json()['documents']==[]
    for role in ('user','admin'):
        setup.user.role=role
        for endpoint in ('original','download','page','preview'):
            assert setup.client.get('/company-knowledge/documents/'+row['id']+'/'+endpoint).status_code==404
        if note:
            assert setup.client.get('/company-knowledge/notes/'+note['id']).status_code==404
            assert setup.client.get('/company-knowledge/notes/'+note['id']+'/export').status_code==404
            assert setup.client.post('/company-knowledge/notes/'+note['id']+'/publish',json={'revision':1}).status_code==404
        assert setup.client.get('/company-knowledge/projects/'+p['id']+'/deletion-preview').status_code==404
    assert stored_original(setup,row['id'])==b'Company knowledge evidence'
    with setup.db() as db:
        assert db.get(CompanyProject,p['id']).deleted_at
        assert db.get(CompanyDocument,row['id']).state=='deleted'
        assert all(d.state=='deleted' for d in db.scalars(select(CompanyDocument).where(CompanyDocument.knowledge_project_id==p['id'])))
        assert not note or db.get(CompanyNote,note['id'])
        event=db.scalar(select(CompanyAuditEvent).where(CompanyAuditEvent.action=='project.delete'))
        assert event.target_name=='待移除项目' and event.actor_username=='alice'
    assert setup.client.post('/company-knowledge/projects',json={'name':'待移除项目','category':category}).status_code==201


def test_permission_active_work_and_changed_preview_are_atomic(setup):
    p=project(setup,'保留项目')
    setup.user.username,setup.user.id='bob',2
    assert setup.client.get('/company-knowledge/projects/'+p['id']+'/deletion-preview').status_code==403
    assert remove(setup,p,'0'*64).status_code==403
    setup.user.username,setup.user.id='alice',1
    before=preview(setup,p)
    folder=setup.client.post('/company-knowledge/projects/'+p['id']+'/folders',json={'name':'新目录'})
    assert folder.status_code==201
    assert remove(setup,p,before['confirmation']).status_code==409
    row=upload(setup,project_id=p['id']).json()
    assert setup.client.get('/company-knowledge/projects/'+p['id']+'/deletion-preview').status_code==409
    with setup.db() as db:
        assert db.get(CompanyProject,p['id']).deleted_at is None
        assert db.get(CompanyDocument,row['id']).state=='queued'
        db.get(CompanyDocument,row['id']).state='ready'
        db.get(CompanyDocument,row['id']).owner_user_id=2;db.commit()
    assert setup.client.get('/company-knowledge/projects/'+p['id']+'/deletion-preview').status_code==403
    setup.user.role='admin'
    assert preview(setup,p)['document_count']==1


def test_upgrade_adds_nullable_tombstone_without_changing_existing_project(setup):
    p=project(setup,'升级保留')
    engine=setup.db.kw['bind']
    with engine.begin() as conn:conn.exec_driver_sql('ALTER TABLE company_projects DROP COLUMN deleted_at')
    ensure_company_schema(engine)
    with setup.db() as db:
        row=db.get(CompanyProject,p['id'])
        assert row.name=='升级保留' and row.deleted_at is None
