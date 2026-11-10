"""Department attribution must preserve ACLs, originals, versioning and collection boundaries."""
from sqlalchemy import select

from test_company_workspace import setup, upload, project, folder, stored_original
from company_catalog import CompanyDocument, CompanyProject, CompanyAuditEvent, ensure_company_schema


def ready(env, *ids):
    with env.db() as db:
        for doc_id in ids:
            doc = db.get(CompanyDocument, doc_id)
            doc.state, doc.cloud_id = 'ready', 'test-cloud-' + doc_id
        db.commit()


def test_department_is_inherited_through_nested_uploads_and_does_not_grant_management(setup):
    p = project(setup, department='market', visibility='restricted', readers=['bob'])
    f = folder(setup, p['id'])
    child = folder(setup, p['id'], '下级', f['id'])
    response = upload(setup, project_id=p['id'], folder_id=child['id'], department='expert')
    assert response.status_code == 202
    doc = response.json()
    assert doc['department'] == 'market' and doc['folder_id'] == child['id']
    assert doc['visibility'] == 'restricted' and doc['readers'] == ['bob']
    ready(setup, doc['id'])
    setup.user.username, setup.user.id = 'bob', 2
    assert setup.client.post('/company-knowledge/uploads', files={'file': ('new.txt', b'new')},
                             data={'project_id': p['id'], 'department': 'market'}).status_code == 403
    result = setup.client.get('/company-knowledge/documents?local_only=true').json()['documents']
    found = next(d for d in result if d['id'] == doc['id'])
    assert found['department'] == 'market' and found['can_read'] and not found['can_manage']


def test_project_reclassification_preserves_narrower_file_acl_and_audits_department(setup):
    p = project(setup, department='project')
    doc = upload(setup, project_id=p['id']).json()
    with setup.db() as db:
        row = db.get(CompanyDocument, doc['id'])
        row.inherits_project, row.visibility, row.readers = 0, 'restricted', ['charlie']
        db.commit()
    result = setup.client.patch('/company-knowledge/projects/' + p['id'],
                                json={'name': p['name'], 'department': 'expert'})
    assert result.status_code == 200 and result.json()['department'] == 'expert'
    with setup.db() as db:
        row = db.get(CompanyDocument, doc['id'])
        assert (row.department, row.visibility, row.readers) == ('expert', 'restricted', ['charlie'])
        events = list(db.scalars(select(CompanyAuditEvent).where(CompanyAuditEvent.action == 'project.update')))
        assert events[-1].changes['department'] == {'before': 'project', 'after': 'expert'}
    assert setup.client.patch('/company-knowledge/projects/' + p['id'], json={'name': p['name']}).json()['department'] == 'expert'
    assert setup.client.patch('/company-knowledge/documents/' + doc['id'], json={'department': 'market'}).status_code == 422


def test_department_selection_is_server_filtered_and_never_falls_back_to_all(setup):
    p = project(setup, department='market')
    a = upload(setup, project_id=p['id']).json()
    b = upload(setup, name='expert.txt', root='true', department='expert').json()
    c = upload(setup, name='private.txt', root='true', department='market',
               visibility='restricted', readers='[]').json()
    legacy = upload(setup, name='legacy.txt', root='true').json()
    ready(setup, a['id'], b['id'], c['id'], legacy['id'])
    setup.user.username, setup.user.id = 'bob', 2
    r = setup.client.post('/company-knowledge/selection', json={'department': 'market'})
    assert r.status_code == 200 and r.json()['document_ids'] == [a['id']]
    assert setup.client.post('/company-knowledge/selection', json={'department': 'policy'}).status_code == 409
    r = setup.client.post('/company-knowledge/selection', json={'department': ''})
    assert r.status_code == 200 and r.json()['document_ids'] == [legacy['id']]
    assert setup.client.post('/company-knowledge/selection',
                             json={'department': 'market', 'document_ids': [b['id']]}).status_code == 409
    assert setup.client.post('/company-knowledge/selection', json={}).status_code == 422


def test_new_forms_require_a_valid_department_but_old_clients_and_experience_remain_compatible(setup):
    assert setup.client.post('/company-knowledge/projects', json={'name': '新项目', 'department': ''}).status_code == 422
    assert upload(setup, root='true', department='').status_code == 422
    for invalid in ('市场部', 'public', 'unknown'):
        assert setup.client.post('/company-knowledge/projects', json={'name': '无效', 'department': invalid}).status_code == 422
        assert upload(setup, root='true', department=invalid).status_code == 422
        assert setup.client.post('/company-knowledge/selection', json={'department': invalid}).status_code == 422
    assert project(setup, '旧客户端')['department'] == ''
    assert project(setup, '经验项目', category='项目经验', department='')['department'] == ''
    legacy = upload(setup, root='true')
    assert legacy.status_code == 202
    assert setup.client.patch('/company-knowledge/documents/' + legacy.json()['id'],
                              json={'department': 'unknown'}).status_code == 422
    assert stored_original(setup, legacy.json()['id']) == b'Company knowledge evidence'


def test_moving_version_family_inherits_department_without_replacing_originals(setup):
    source = project(setup, '来源', department='market')
    target = project(setup, '目标', department='expert')
    docs = [upload(setup, payload=content, project_id=source['id']).json() for content in (b'first version', b'second version')]
    ready(setup, *(d['id'] for d in docs))
    originals = [stored_original(setup, d['id']) for d in docs]
    path = '/company-knowledge/documents/' + docs[-1]['id']
    preview = setup.client.post(path + '/move-preview', json={'project_id': target['id']}).json()
    assert preview['before_department'] == '市场部' and preview['after_department'] == '专家资料'
    response = setup.client.post(path + '/move', json={'project_id': target['id'], 'confirmation': preview['confirmation']})
    assert response.status_code == 200 and response.json()['moved_version_count'] == 2
    with setup.db() as db:
        for d in docs:
            row = db.get(CompanyDocument, d['id'])
            assert row.department == 'expert' and row.knowledge_project_id == target['id']
    assert [stored_original(setup, d['id']) for d in docs] == originals


def test_department_is_preserved_across_delete_restore_and_schema_upgrade(setup):
    d = upload(setup, root='true', department='policy').json()
    with setup.db() as db:
        db.get(CompanyDocument, d['id']).state = 'failed'
        db.commit()
    assert setup.client.delete('/company-knowledge/documents/' + d['id']).status_code == 200
    items = setup.client.get('/company-knowledge/recycle-bin').json()['items']
    item = next(item for item in items if item['title'] == d['title'])
    assert setup.client.post('/company-knowledge/recycle-bin/' + item['id'] + '/restore').status_code == 200
    with setup.db() as db:
        assert db.get(CompanyDocument, d['id']).department == 'policy'
        engine = db.get_bind()
    with engine.begin() as connection:
        connection.exec_driver_sql('ALTER TABLE company_documents DROP COLUMN department')
        connection.exec_driver_sql('ALTER TABLE company_projects DROP COLUMN department')
    ensure_company_schema(engine)
    ensure_company_schema(engine)
    with setup.db() as db:
        row = db.get(CompanyDocument, d['id'])
        assert row.department == '' and row.visibility == 'members' and row.owner == 'alice'
    assert stored_original(setup, d['id']) == b'Company knowledge evidence'


def test_legacy_named_upload_keeps_its_original_grouping_and_department(setup):
    p = project(setup, '兼容旧归档', department='project')
    d = upload(setup, project=p['name'], department='market').json()
    ready(setup, d['id'])
    projects = setup.client.get('/company-knowledge/projects').json()['projects']
    rows = setup.client.get('/company-knowledge/documents?local_only=true').json()['documents']
    found = next(row for row in rows if row['id'] == d['id'])
    # Legacy name-based groups remain distinct from explicitly created project IDs.
    assert found['knowledge_project_id'] != p['id'] and found['department'] == 'market'
    assert next(row for row in projects if row['id'] == found['knowledge_project_id'])['department'] == 'market'
    selection = setup.client.post('/company-knowledge/selection', json={'department': 'market'})
    assert selection.status_code == 200 and selection.json()['document_ids'] == [d['id']]
