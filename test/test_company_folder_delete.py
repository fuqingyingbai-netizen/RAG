"""Confirmed folder deletion is atomic, scoped, and recoverable for ten days."""
from datetime import datetime, timedelta
import asyncio
import pytest
from sqlalchemy import select, create_engine, text, inspect
from test_company_workspace import setup, project, upload, stored_original
from company_catalog import CompanyDocument, CompanyFolder, CompanyProject, ensure_company_schema
from company_notes import CompanyNote
from company_recycle import RecycleItem, purge_due


def folder(env, p, name='资料', parent_id=''):
    response = env.client.post('/company-knowledge/projects/'+p['id']+'/folders', json={'name': name, 'parent_id': parent_id})
    assert response.status_code == 201, response.text
    return response.json()


def url(p, f):
    return '/company-knowledge/projects/'+p['id']+'/folders/'+f['id']


def preview(env, p, f):
    response = env.client.get(url(p, f)+'/deletion-preview')
    assert response.status_code == 200, response.text
    return response.json()


def remove(env, p, f, token=None):
    return env.client.request('DELETE', url(p, f), json={'confirmation': token or preview(env, p, f)['confirmation']})


def ready(env, doc):
    with env.db() as db:
        db.get(CompanyDocument, doc['id']).state = 'ready'
        db.commit()


def recycle(env, kind='folder'):
    return next(item for item in env.client.get('/company-knowledge/recycle-bin').json()['items'] if item['kind'] == kind)


def restore(env, item):
    return env.client.post('/company-knowledge/recycle-bin/'+item['id']+'/restore')


def test_empty_folder_permanent_delete_requires_matching_supplied_preview(setup):
    p = project(setup, '空目录项目'); f = folder(setup, p)
    assert preview(setup, p, f)['recyclable'] is False
    assert remove(setup, p, f, '0'*64).status_code == 409
    assert remove(setup, p, f).status_code == 200
    with setup.db() as db:
        assert db.get(CompanyFolder, f['id']) is None
        assert list(db.scalars(select(RecycleItem))) == []


@pytest.mark.parametrize('category', ['项目原件', '项目经验'])
def test_subtree_hidden_everywhere_and_restored_without_separately_deleted_files(setup, category):
    p = project(setup, '目录恢复项目', category=category)
    root = folder(setup, p); child = folder(setup, p, '子目录', root['id']); leaf = folder(setup, p, '孙目录', child['id'])
    sibling = folder(setup, p, '旁边目录')
    doc = upload(setup, project_id=p['id'], folder_id=leaf['id']).json(); ready(setup, doc)
    old = upload(setup, payload=b'previous deletion', name='old.txt', project_id=p['id'], folder_id=child['id']).json(); ready(setup, old)
    assert setup.client.delete('/company-knowledge/documents/'+old['id']).status_code == 200
    note = None
    if category == '项目经验':
        response = setup.client.post('/company-knowledge/notes', json={'project_id': p['id'], 'folder_id': child['id']})
        assert response.status_code == 201; note = response.json()
    scope = preview(setup, p, root)
    assert (scope['folder_count'], scope['document_count'], scope['note_count']) == (2, 1, int(note is not None))
    assert setup.client.delete(url(p, root)).status_code == 409  # no unconfirmed cascade, even from an older tab
    assert remove(setup, p, root, scope['confirmation']).status_code == 200
    listed = setup.client.get('/company-knowledge/projects').json()['folders']
    assert {f['id'] for f in listed} == {sibling['id']}
    assert setup.client.get('/company-knowledge/documents/'+doc['id']+'/original').status_code == 404
    assert setup.client.patch(url(p, child), json={'name': '不可重命名'}).status_code == 404
    assert setup.client.post('/company-knowledge/projects/'+p['id']+'/folders', json={'name':'不可新建','parent_id':child['id']}).status_code == 404
    assert upload(setup, payload=b'forbidden', project_id=p['id'], folder_id=child['id']).status_code == 404
    assert setup.client.post('/company-knowledge/selection', json={'folder_ids':[child['id']]}).status_code == 403
    if note:
        assert setup.client.get('/company-knowledge/notes/'+note['id']).status_code == 404
        assert setup.client.post('/company-knowledge/notes', json={'project_id':p['id'], 'folder_id':child['id']}).status_code == 404
    item = recycle(setup)
    assert item['title'] == root['name']
    with setup.db() as db:
        row = db.get(RecycleItem, item['id'])
        assert row.purge_after-row.deleted_at == timedelta(days=10)
        grouped = [r for r in db.scalars(select(RecycleItem)) if r.target_id != old['id']]
        assert all(r.purge_after == row.purge_after for r in grouped)
        assert db.get(CompanyDocument, doc['id']).state == 'deleted'
    # An independently deleted child cannot be restored into an invisible directory.
    assert restore(setup, recycle(setup, 'document')).status_code == 409
    assert stored_original(setup, doc['id']) == b'Company knowledge evidence'
    response = restore(setup, item)
    assert response.status_code == 200, response.text
    with setup.db() as db:
        for f in [root, child, leaf]:
            actual = db.get(CompanyFolder, f['id'])
            assert (actual.name, actual.parent_id, actual.deleted_at) == (f['name'], f['parent_id'], None)
        assert db.get(CompanyDocument, doc['id']).folder_id == leaf['id']
        assert db.get(CompanyDocument, old['id']).state == 'deleted'
        if note: assert db.get(CompanyNote, note['id']).deleted_at is None
    assert restore(setup, item).status_code == 409


def test_scope_change_busy_work_and_foreign_content_prevent_atomic_delete(setup):
    p = project(setup, '删除边界'); root = folder(setup, p)
    token = preview(setup, p, root)['confirmation']
    child = folder(setup, p, '新增', root['id'])
    assert remove(setup, p, root, token).status_code == 409
    doc = upload(setup, project_id=p['id'], folder_id=child['id']).json()
    assert setup.client.get(url(p, root)+'/deletion-preview').status_code == 409
    ready(setup, doc)
    token = preview(setup, p, root)['confirmation']
    with setup.db() as db:
        d = db.get(CompanyDocument, doc['id']); d.lease_until = datetime.utcnow()+timedelta(minutes=2); db.commit()
    assert remove(setup, p, root, token).status_code == 409
    with setup.db() as db:
        d = db.get(CompanyDocument, doc['id']); d.lease_until = None; d.owner='bob'; d.owner_user_id=2; db.commit()
    assert setup.client.get(url(p, root)+'/deletion-preview').status_code == 403
    setup.user.role = 'admin'
    assert remove(setup, p, root).status_code == 200


def test_read_only_users_cannot_preview_delete_or_restore(setup):
    p = project(setup, '权限目录'); root = folder(setup, p); folder(setup, p, '子', root['id'])
    scope = preview(setup, p, root)
    setup.user.id, setup.user.username = 2, 'bob'
    assert setup.client.get(url(p, root)+'/deletion-preview').status_code == 403
    assert remove(setup, p, root, scope['confirmation']).status_code == 403
    setup.user.id, setup.user.username = 1, 'alice'
    assert remove(setup, p, root).status_code == 200; item = recycle(setup)
    setup.user.id, setup.user.username = 2, 'bob'
    assert restore(setup, item).status_code == 404


def test_restore_name_collision_preserves_tree_and_missing_parent_reports_root_fallback(setup):
    p = project(setup, '恢复冲突'); parent = folder(setup, p, '上级'); root = folder(setup, p, '资料', parent['id'])
    child = folder(setup, p, '子', root['id'])
    assert remove(setup, p, root).status_code == 200; item = recycle(setup)
    assert remove(setup, p, parent).status_code == 200
    replacement = folder(setup, p, root['name'])
    response = restore(setup, item)
    assert response.status_code == 200 and response.json()['notices']
    with setup.db() as db:
        restored = db.get(CompanyFolder, root['id'])
        assert restored.parent_id == '' and '恢复' in restored.name
        assert db.get(CompanyFolder, child['id']).parent_id == root['id']
        assert db.get(CompanyFolder, replacement['id']).name == root['name']


def test_expired_tree_is_not_restorable_and_originals_reclaimed_in_bounded_passes(setup):
    p = project(setup, '到期清理'); root = folder(setup, p)
    doc = upload(setup, project_id=p['id'], folder_id=root['id']).json(); ready(setup, doc)
    assert remove(setup, p, root).status_code == 200; item = recycle(setup)
    with setup.db() as db:
        for row in db.scalars(select(RecycleItem)):
            row.purge_after = datetime.utcnow()-timedelta(days=1)
        db.commit()
    assert restore(setup, item).status_code == 409
    for _ in range(3): asyncio.run(purge_due())
    with setup.db() as db:
        assert db.get(CompanyDocument, doc['id']).object_key == ''
        assert all(row.status == 'purged' for row in db.scalars(select(RecycleItem)))


def test_folder_tombstone_migration_preserves_existing_rows(tmp_path):
    engine = create_engine('sqlite:///'+str(tmp_path/'legacy.db'))
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE company_folders (id VARCHAR(64) PRIMARY KEY, project_id VARCHAR(64), parent_id VARCHAR(64), name VARCHAR(200), created_at TIMESTAMP, updated_at TIMESTAMP)'))
        connection.execute(text("INSERT INTO company_folders (id,project_id,parent_id,name) VALUES ('f','p','','legacy')"))
    ensure_company_schema(engine)
    assert 'deleted_at' in {c['name'] for c in inspect(engine).get_columns('company_folders')}
    with engine.connect() as connection:
        assert connection.execute(text('SELECT name,deleted_at FROM company_folders')).one() == ('legacy', None)
    engine.dispose()


def test_published_versions_and_unpublished_note_restore_with_folder_then_survive_project_restore(setup):
    from test_company_notes import save, publish, ready as ready_note
    p = project(setup, '笔记整树恢复', category='项目经验'); root = folder(setup, p)
    note = setup.client.post('/company-knowledge/notes', json={'project_id':p['id'], 'folder_id':root['id']}).json()
    for title in ['旧发布版', '新发布版']:
        note = publish(setup, save(setup, note, title=title)); ready_note(setup, note)
        with setup.db() as db:
            doc = db.get(CompanyDocument, note['pending_document_id']); doc.worker_id=''; doc.lease_until=None; db.commit()
        note = setup.client.get('/company-knowledge/notes/'+note['id']).json()
    note = save(setup, note, title='未发布草稿')
    assert preview(setup, p, root)['document_count'] == 2
    assert remove(setup, p, root).status_code == 200; item = recycle(setup)
    assert restore(setup, item).status_code == 200
    with setup.db() as db:
        assert db.get(CompanyNote, note['id']).title == '未发布草稿'
        assert len(list(db.scalars(select(CompanyDocument).where(CompanyDocument.note_id == note['id'], CompanyDocument.state != 'deleted')))) == 2
        for doc in db.scalars(select(CompanyDocument).where(CompanyDocument.note_id == note['id'])): doc.state='ready'
        db.commit()
    # An older independently deleted subtree stays separate when its whole project is later deleted.
    assert remove(setup, p, root).status_code == 200; folder_item = recycle(setup)
    scope = setup.client.get('/company-knowledge/projects/'+p['id']+'/deletion-preview').json()
    assert scope['folder_count'] == 0
    assert setup.client.request('DELETE','/company-knowledge/projects/'+p['id'],json={'confirmation':scope['confirmation']}).status_code == 200
    assert restore(setup, folder_item).status_code == 409
    assert restore(setup, recycle(setup, 'project')).status_code == 200
    with setup.db() as db: assert db.get(CompanyFolder, root['id']).deleted_at is not None
    assert restore(setup, folder_item).status_code == 200
