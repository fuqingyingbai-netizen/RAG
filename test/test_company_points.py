"""Real isolated SQL transactions and HTTP authentication; never use the configured database."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace
import copy
import os
import uuid

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import auth
import company_knowledge as kb
import company_workspace as ws
import company_ingestion as ingestion
import company_projects
import company_points as p
import company_points_api as api
import account_api
from company_catalog import CompanyDocument, CompanyAuditEvent
from database import Base
from models import User


@pytest.fixture(scope='session')
def points_postgres_schema():
    postgres = os.getenv('POINTS_TEST_DATABASE_URL')
    if not postgres:
        yield None
        return
    url = make_url(postgres)
    assert url.host == '127.0.0.1' and url.database == 'points_test' and os.getenv('POINTS_TEST_OWNED_CONTAINER')
    schema = 'points_test_' + uuid.uuid4().hex
    control = create_engine(url)
    with control.begin() as connection:
        connection.execute(text('CREATE SCHEMA ' + schema))
    engine = create_engine(url, connect_args={'options': '-csearch_path=' + schema})
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        with control.begin() as connection:
            connection.execute(text('DROP SCHEMA ' + schema + ' CASCADE'))
        control.dispose()


@pytest.fixture
def system(tmp_path, monkeypatch, points_postgres_schema):
    for name, value in {'API_KEY': 'synthetic', 'BASE_URL': 'https://test.cn-beijing.maas.aliyuncs.com', 'INDEX_ID': 'test-index', 'AGENT_ID': 'test-agent'}.items():
        monkeypatch.setenv('BAILIAN_KNOWLEDGE_' + name, value)
    monkeypatch.setenv('COMPANY_KNOWLEDGE_LOCAL_STORE', str(tmp_path / 'originals'))
    if points_postgres_schema is not None:
        engine = points_postgres_schema
        p.PointsEvent.__table__.create(engine, checkfirst=True)
        with engine.begin() as connection:
            connection.execute(text('TRUNCATE TABLE ' + ','.join('"' + table.name + '"' for table in Base.metadata.sorted_tables) + ' RESTART IDENTITY CASCADE'))
    else:
        engine = create_engine('sqlite:///' + str(tmp_path / 'points.db'), connect_args={'check_same_thread': False, 'timeout': 15})
        @event.listens_for(engine, 'connect')
        def ephemeral_test_storage(connection, record):
            connection.execute('PRAGMA journal_mode=MEMORY')
            connection.execute('PRAGMA synchronous=OFF')
    if points_postgres_schema is None:
        Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    for module in (p, api, auth, ws, ingestion, company_projects):
        monkeypatch.setattr(module, 'SessionLocal', factory)
    clock = [datetime(2026, 11, 16, 2, 0, 0)]
    monkeypatch.setattr(p, 'now', lambda: clock[0])
    p.initialize(engine)
    clock[0] += timedelta(seconds=1)
    with factory() as db:
        for i, name in enumerate(('alice', 'bob', 'charlie', 'admin'), 1):
            db.add(User(id=i, username=name, password_hash='unused-test-only', role='admin' if name == 'admin' else 'user',
                        is_active=True, must_change_password=False, token_version=0))
        db.commit()
    monkeypatch.setattr(account_api, 'verify_password', lambda password, digest: password == 'admin-test-password')
    scheduled = []
    monkeypatch.setattr(ws, 'schedule_document', scheduled.append)
    app = FastAPI()
    app.include_router(api.router)
    app.include_router(kb.router)
    app.include_router(account_api.router)

    @app.exception_handler(kb.KnowledgeError)
    async def handler(request, exc):
        return JSONResponse(status_code=exc.status_code, content={'detail': str(exc)})

    def db_dependency():
        with factory() as db:
            yield db
    app.dependency_overrides[auth.get_db] = db_dependency
    client = TestClient(app)
    def login(name):
        with factory() as db:
            user = db.scalar(select(User).where(User.username == name))
            client.headers['Authorization'] = 'Bearer ' + auth.create_access_token(user.username, user.role, user.token_version)
        return user
    login('bob')
    yield SimpleNamespace(db=factory, engine=engine, client=client, clock=clock, login=login, scheduled=scheduled, app=app)
    client.close()
    p.initialized.discard(engine)
    if points_postgres_schema is None:
        engine.dispose()


def doc(s, owner=1, **fields):
    identity = uuid.uuid4().hex
    values = dict(id=identity, title=identity + '.txt', index_id='test-index', cloud_id='cloud-' + identity,
        format='TXT', size=30, object_key=identity + '.txt', sha256=p.key(identity), state='ready',
        owner='alice' if owner == 1 else 'bob', owner_user_id=owner, uploaded_by_user_id=owner,
        uploaded_by='alice' if owner == 1 else 'bob', version=1, is_current=1, category='项目原件',
        confidentiality='internal', visibility='members', created_at=s.clock[0], updated_at=s.clock[0])
    values.update(fields)
    with s.db() as db:
        row = CompanyDocument(**values)
        db.add(row)
        db.commit()
    return row


def preview(s, row, reader=2):
    with s.db() as db:
        db.add(CompanyAuditEvent(id=uuid.uuid4().hex, index_id=row.index_id, project_id='', target_type='document',
            target_id=row.id, target_name=row.title, actor_id=reader, actor_username='bob', action='document.preview',
            changes={}, details={}, created_at=s.clock[0]))
        db.commit()


def read(s, row, reader='bob'):
    s.login(reader)
    preview(s, row, 2 if reader == 'bob' else 3)
    response = s.client.post('/points/read-sessions', json={'document_id': row.id})
    assert response.status_code == 200, response.text
    return response.json()


def complete_read(s, row):
    session = read(s, row)
    result = None
    for sequence in range(1, 4):
        s.clock[0] += timedelta(seconds=10)
        response = s.client.post('/points/read-sessions/' + session['session_id'] + '/heartbeat',
            json={'sequence': sequence, 'active': True, 'interacted': sequence == 1})
        assert response.status_code == 200, response.text
        result = response.json()
    return session, result


def capture(s, row):
    with s.db() as db:
        p.capture_ready(db, row.id)
        db.commit()


def total(s, user_id):
    with s.db() as db:
        row = db.get(p.PointsAccount, user_id)
        ledger = db.scalar(select(func.coalesce(func.sum(p.PointsEntry.amount), 0)).where(p.PointsEntry.user_id == user_id))
        assert (row.total if row else 0) == ledger
        return ledger


def test_additive_initialization_is_repeatable_and_does_not_backfill(system):
    s = system
    old = doc(s, created_at=s.clock[0] - timedelta(days=20))
    capture(s, old)
    p.initialize(s.engine)
    p.reconcile(s.db)
    with s.db() as db:
        assert db.scalar(select(func.count()).select_from(p.PointsRule)) == 1
        assert db.scalar(select(func.count()).select_from(p.PointsEvent)) == 0
        assert db.scalar(select(func.count()).select_from(User)) == 4
        assert db.get(CompanyDocument, old.id).state == 'ready'


def test_real_read_session_awards_once_and_survives_page_reopen(system):
    row = doc(system)
    session, result = complete_read(system, row)
    assert result['complete'] and result['awarded'] == 2
    assert total(system, 2) == 2
    replay = system.client.post('/points/read-sessions/' + session['session_id'] + '/heartbeat',
        json={'sequence': 3, 'active': True, 'interacted': True})
    assert replay.json()['awarded'] == 0
    assert read(system, row)['eligible'] is False
    assert total(system, 2) == 2


def test_preview_delivery_ownership_scope_and_auth_are_required(system):
    s = system
    row = doc(s)
    assert s.client.post('/points/read-sessions', json={'document_id': row.id}).status_code == 409
    private = doc(s, visibility='restricted', readers=[])
    assert s.client.post('/points/read-sessions', json={'document_id': private.id}).status_code == 404
    other_index = doc(s, index_id='other-index')
    assert s.client.post('/points/read-sessions', json={'document_id': other_index.id}).status_code == 404
    owned = doc(s, owner=2)
    assert s.client.post('/points/read-sessions', json={'document_id': owned.id}).status_code == 409
    row = doc(s, confidentiality='secret')
    assert s.client.post('/points/read-sessions', json={'document_id': row.id}).status_code == 404
    s.client.headers.clear()
    assert s.client.get('/points/me').status_code == 401


def test_hidden_tabs_fast_replays_and_large_gaps_do_not_count(system):
    s = system
    row = doc(s)
    session = read(s, row)
    path = '/points/read-sessions/' + session['session_id'] + '/heartbeat'
    payload = {'sequence': 1, 'active': True, 'interacted': True}
    assert s.client.post(path, json=payload).status_code == 429
    s.clock[0] += timedelta(seconds=10)
    assert s.client.post(path, json={**payload, 'active': False}).json()['seconds'] == 0
    assert s.client.post(path, json=payload).json()['seconds'] == 0
    s.clock[0] += timedelta(seconds=60)
    assert s.client.post(path, json={**payload, 'sequence': 2}).json()['seconds'] == 0
    assert total(s, 2) == 0


def test_a_second_device_closes_the_first_session_and_sessions_are_private(system):
    s = system
    row = doc(s)
    first = read(s, row)
    second = read(s, row)
    s.clock[0] += timedelta(seconds=10)
    payload = {'sequence': 1, 'active': True, 'interacted': True}
    assert s.client.post('/points/read-sessions/' + first['session_id'] + '/heartbeat', json=payload).status_code == 409
    s.login('charlie')
    assert s.client.post('/points/read-sessions/' + second['session_id'] + '/heartbeat', json=payload).status_code == 404


def test_daily_read_cap_and_permission_revocation(system):
    s = system
    for _ in range(6):
        complete_read(s, doc(s))
    assert total(s, 2) == 10
    row = doc(s)
    session = read(s, row)
    with s.db() as db:
        db.get(CompanyDocument, row.id).visibility = 'restricted'
        db.commit()
    s.clock[0] += timedelta(seconds=10)
    assert s.client.post('/points/read-sessions/' + session['session_id'] + '/heartbeat',
        json={'sequence': 1, 'active': True, 'interacted': True}).status_code == 404


def test_midnight_expires_session_and_new_day_can_earn_again(system):
    s = system
    row = doc(s)
    complete_read(s, row)
    s.clock[0] += timedelta(days=1)
    _, result = complete_read(s, row)
    assert result['awarded'] == 2 and total(s, 2) == 4
    row = doc(s)
    s.clock[0] = datetime(2026, 11, 17, 15, 59, 55)
    session = read(s, row)
    s.clock[0] += timedelta(seconds=10)
    assert s.client.post('/points/read-sessions/' + session['session_id'] + '/heartbeat',
        json={'sequence': 1, 'active': True, 'interacted': True}).status_code == 409


def test_read_identity_survives_rename_and_file_versions(system):
    s = system
    first = doc(s)
    complete_read(s, first)
    with s.db() as db:
        original = db.get(CompanyDocument, first.id)
        original.title = 'renamed.txt'
        db.commit()
    second = doc(s, title='renamed.txt', version=2)
    assert read(s, second)['eligible'] is False
    assert total(s, 2) == 2


def test_version_identity_is_persisted_before_independent_metadata_edits(system):
    s = system
    first = doc(s, title='versioned.txt')
    complete_read(s, first)
    second = doc(s, title=first.title, version=2)
    capture(s, second)
    with s.db() as db:
        db.get(CompanyDocument, second.id).title = 'new-title.txt'
        db.commit()
    assert read(s, second)['eligible'] is False


def test_upload_outbox_is_idempotent_and_daily_cap_is_atomic(system):
    s = system
    rows = [doc(s) for _ in range(5)]
    for row in rows:
        capture(s, row)
        capture(s, row)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: p.process_pending(s.db), range(4)))
    assert total(s, 1) == 30
    p.process_pending(s.db)
    assert total(s, 1) == 30
    with s.db() as db:
        assert db.scalar(select(func.count()).select_from(p.PointsEntry).where(p.PointsEntry.amount > 0)) == 3
        assert db.scalar(select(func.count()).select_from(p.PointsEvent)) == 5


def test_duplicate_content_changes_of_location_and_old_material_do_not_earn(system):
    s = system
    first = doc(s)
    duplicate = doc(s, sha256=first.sha256, title='different-name.txt', folder_id='another-folder')
    version = doc(s, version=2)
    old = doc(s, created_at=s.clock[0] - timedelta(days=5))
    old_copy = doc(s, sha256=old.sha256)
    for row in [first, duplicate, version, old_copy]:
        capture(s, row)
    p.process_pending(s.db)
    assert total(s, 1) == 10


@pytest.mark.parametrize('fields', [{'state': 'failed'}, {'size': 0}, {'object_key': ''}, {'format': 'MP4'}])
def test_ineligible_uploads_do_not_earn(system, fields):
    row = doc(system, **fields)
    capture(system, row)
    p.process_pending(system.db)
    assert total(system, 1) == 0


@pytest.mark.parametrize('visibility,confidentiality', [('members', 'internal'), ('restricted', 'internal'), ('restricted', 'secret')])
def test_admin_upload_to_another_owners_project_earns_for_actual_uploader_regardless_of_acl(system, visibility, confidentiality):
    s = system
    s.login('alice')
    response = s.client.post('/company-knowledge/projects', json={'name': 'Delegated upload project', 'visibility': visibility, 'department': 'market'})
    assert response.status_code == 201, response.text
    project = response.json()
    s.login('admin')
    if confidentiality == 'secret':
        response = s.client.patch('/company-knowledge/projects/' + project['id'], json={'name': project['name'], 'department': 'market', 'visibility': visibility, 'confidentiality': 'secret'})
        assert response.status_code == 200, response.text
    response = s.client.post('/company-knowledge/uploads', files={'file': ('delegated.txt', b'Synthetic delegated contribution')}, data={'project_id': project['id']})
    assert response.status_code == 202, response.text
    identity = response.json()['id']
    waiting = s.client.get('/points/activity').json()['items']
    assert any(row['title'] == 'delegated.txt' and row['expected'] == 10 for row in waiting)
    with s.db() as db:
        row = db.get(CompanyDocument, identity)
        assert row.owner_user_id == 1 and row.uploaded_by_user_id == 4
        assert (row.visibility, row.confidentiality) == (visibility, confidentiality)
        row.created_at = s.clock[0]
        row.worker_id = 'delegated-worker'
        db.commit()
    ingestion.checkpoint(identity, 'delegated-worker', state='ready')
    p.process_pending(s.db)
    p.process_pending(s.db)
    assert total(s, 4) == 10 and total(s, 1) == 0
    s.login('bob')
    if visibility == 'restricted':
        assert s.client.get('/company-knowledge/documents/' + identity + '/original').status_code == 404
    assert s.client.get('/points/ledger').json()['items'] == []


def test_upload_reward_survives_acl_revocation_without_leaking_titles(system):
    s = system
    row = doc(s, owner=2, uploaded_by='alice', uploaded_by_user_id=1)
    capture(s, row)
    with s.db() as db:
        source = db.get(CompanyDocument, row.id)
        source.confidentiality, source.visibility = 'secret', 'restricted'
        db.commit()
    p.process_pending(s.db)
    assert total(s, 1) == 10
    s.login('alice')
    assert s.client.get('/company-knowledge/documents/' + row.id + '/original').status_code == 404
    assert s.client.get('/points/ledger').json()['items'][0]['title'] == '关联资料已不可访问'
    assert s.client.post('/points/read-sessions', json={'document_id': row.id}).status_code == 404


def test_requeued_legacy_permission_rejection_is_awarded_once_by_new_worker(system):
    s = system
    row = doc(s, owner=2, uploaded_by='admin', uploaded_by_user_id=4, visibility='restricted')
    capture(s, row)
    with s.db() as db:
        event = db.get(p.PointsEvent, p.key('ready', row.id))
        event.status, event.reason = 'ignored', '该资料不符合共享贡献奖励条件'
        db.commit()
    p.process_pending(s.db)
    assert total(s, 4) == 0
    with s.db() as db:
        event = db.get(p.PointsEvent, p.key('ready', row.id))
        event.status, event.reason = 'pending', '权限条件取消后重新结算'
        db.commit()
    p.process_pending(s.db)
    p.process_pending(s.db)
    assert total(s, 4) == 10 and total(s, 2) == 0


def test_suspending_user_blocks_pending_rewards_and_hides_rank(system):
    s = system
    row = doc(s)
    capture(s, row)
    with s.db() as db:
        db.get(User, 1).is_active = False
        db.commit()
    p.process_pending(s.db)
    assert total(s, 1) == 0
    s.login('alice')
    assert s.client.get('/points/me').status_code == 401


def test_real_upload_checkpoint_captures_one_event_and_points_fault_does_not_fail_ingestion(system):
    s = system
    s.login('alice')
    response = s.client.post('/company-knowledge/uploads', files={'file': ('new.txt', b'New synthetic evidence')})
    assert response.status_code == 202, response.text
    identity = response.json()['id']
    with s.db() as db:
        row = db.get(CompanyDocument, identity)
        row.created_at = s.clock[0]
        row.worker_id = 'worker'
        db.commit()
    p.PointsEvent.__table__.drop(s.engine)
    ingestion.checkpoint(identity, 'worker', state='ready')
    with s.db() as db:
        assert db.get(CompanyDocument, identity).state == 'ready'
    p.PointsEvent.__table__.create(s.engine)
    p.reconcile(s.db)
    p.process_pending(s.db)
    assert total(s, 1) == 10


def test_actual_note_publish_is_awarded_once_not_also_as_upload(system, monkeypatch):
    s = system
    s.login('alice')
    response = s.client.post('/company-knowledge/projects', json={'name': '经验项目', 'category': '手稿笔记'})
    assert response.status_code == 201, response.text
    project_id = response.json()['id']
    note = s.client.post('/company-knowledge/notes', json={'project_id': project_id}).json()
    body = {'type': 'doc', 'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': 'Synthetic reusable knowledge'}]}]}
    note = s.client.patch('/company-knowledge/notes/' + note['id'], json={'revision': note['revision'], 'title': '复盘', 'content': body}).json()
    for text in ('first', 'second'):
        result = s.client.post('/company-knowledge/notes/' + note['id'] + '/publish', json={'revision': note['revision']})
        assert result.status_code == 200, result.text
        identity = result.json()['pending_document_id']
        with s.db() as db:
            row = db.get(CompanyDocument, identity)
            row.created_at = s.clock[0]
            row.worker_id = 'worker'
            db.commit()
        ingestion.checkpoint(identity, 'worker', state='ready')
        p.process_pending(s.db)
        body['content'][0]['content'][0]['text'] = 'Revised body ' + text
        note = s.client.patch('/company-knowledge/notes/' + note['id'], json={'revision': note['revision'], 'title': '复盘', 'content': body}).json()
    assert total(s, 1) == 15
    with s.db() as db:
        assert list(db.scalars(select(p.PointsEntry.kind))) == ['note']


def test_leaderboard_ties_month_boundaries_and_no_private_profile_disclosure(system):
    s = system
    capture(s, doc(s, owner=1))
    capture(s, doc(s, owner=2))
    p.process_pending(s.db)
    with s.db() as db:
        db.get(User, 1).display_name = 'admin-only-name'
        db.get(User, 1).notes = 'PRIVATE-STAFF-NOTE'
        db.commit()
    response = s.client.get('/points/leaderboard')
    data = response.json()
    assert [row['rank'] for row in data['items']] == [1, 1]
    assert 'admin-only-name' not in response.text and 'PRIVATE-STAFF-NOTE' not in response.text
    assert 'document_id' not in response.text
    s.clock[0] = datetime(2026, 12, 1, 0)
    assert s.client.get('/points/leaderboard?period=month').json()['total'] == 0
    assert s.client.get('/points/leaderboard?period=all').json()['total'] == 2


def test_rules_require_admin_validate_ranges_and_use_optimistic_versions(system):
    s = system
    assert s.client.get('/admin/points/users').status_code == 403
    s.login('admin')
    policy = copy.deepcopy(p.DEFAULT)
    payload = {'expected_version': 1, 'policy': policy, 'reason': 'trial policy update'}
    policy['read_points'] = -1
    assert s.client.put('/admin/points/rules', json=payload).status_code == 422
    policy['read_points'] = 3
    result = s.client.put('/admin/points/rules', json=payload)
    assert result.status_code == 200, result.text
    assert result.json()['effective_at'] == '2026-11-16T16:00:00Z'
    assert s.client.get('/points/rules').json()['current']['policy']['read_points'] == 2
    assert s.client.put('/admin/points/rules', json=payload).status_code == 409
    s.clock[0] += timedelta(days=1)
    assert s.client.get('/points/rules').json()['current']['policy']['read_points'] == 3


def test_emergency_pause_stops_reading_and_preserves_ledger(system):
    s = system
    row = doc(s)
    complete_read(s, row)
    s.login('admin')
    policy = copy.deepcopy(p.DEFAULT)
    policy['enabled'] = False
    result = s.client.put('/admin/points/rules', json={'expected_version': 1, 'policy': policy,
        'reason': 'Emergency pause', 'immediate_pause': True})
    assert result.status_code == 200
    s.login('bob')
    assert s.client.post('/points/read-sessions', json={'document_id': row.id}).status_code == 409
    assert total(s, 2) == 2


def confirmation(s, user_id):
    response = s.client.post('/auth/confirm-admin', json={'password': 'admin-test-password',
        'action': 'points_adjust', 'target_user_id': user_id})
    assert response.status_code == 200, response.text
    return {'X-Admin-Confirmation': response.json()['confirmation_token']}


def test_adjustments_require_password_are_idempotent_and_reversals_keep_history(system):
    s = system
    capture(s, doc(s))
    p.process_pending(s.db)
    s.login('admin')
    with s.db() as db:
        original = db.scalar(select(p.PointsEntry))
    payload = {'request_id': uuid.uuid4().hex, 'amount': -10, 'reason': 'Correct duplicate reward', 'original_id': original.id}
    path = '/admin/points/users/1/adjustments'
    assert s.client.post(path, json=payload).status_code == 403
    response = s.client.post(path, json=payload, headers=confirmation(s, 1))
    assert response.status_code == 200, response.text
    assert s.client.post(path, json=payload).status_code == 200
    assert total(s, 1) == 0
    assert s.client.post(path, json={**payload, 'request_id': uuid.uuid4().hex}, headers=confirmation(s, 1)).status_code == 409
    with s.db() as db:
        assert db.get(p.PointsEntry, original.id).amount == 10
        assert db.scalar(select(func.count()).select_from(p.PointsEntry)) == 2
    assert s.client.post('/admin/points/users/4/adjustments', json={'request_id': uuid.uuid4().hex, 'amount': 10, 'reason': 'not allowed'}).status_code == 403


def test_private_ledger_and_revoked_document_titles_are_filtered(system):
    s = system
    row = doc(s, title='SENSITIVE-TITLE.txt')
    complete_read(s, row)
    with s.db() as db:
        db.get(CompanyDocument, row.id).visibility = 'restricted'
        db.commit()
    response = s.client.get('/points/ledger')
    assert 'SENSITIVE-TITLE' not in response.text
    assert '不可访问' in response.text
    s.login('charlie')
    assert s.client.get('/points/ledger').json()['total'] == 0
    assert s.client.get('/points/ledger?user_id=2').json()['total'] == 0


def test_participation_exclusion_keeps_balance_but_stops_new_earnings(system):
    s = system
    capture(s, doc(s))
    p.process_pending(s.db)
    s.login('admin')
    response = s.client.patch('/admin/points/users/1/participation', json={'excluded': True, 'reason': 'test account'})
    assert response.status_code == 200
    capture(s, doc(s))
    p.process_pending(s.db)
    assert total(s, 1) == 10
    assert s.client.get('/points/leaderboard').json()['total'] == 0


def test_backend_never_accepts_client_supplied_points_or_unbounded_pages(system):
    row = doc(system)
    assert system.client.post('/points/read-sessions', json={'document_id': row.id, 'points': 1000}).status_code == 422
    assert system.client.get('/points/ledger?page_size=100000').status_code == 422
    assert system.client.get('/points/leaderboard?period=invalid').status_code == 422


def test_points_database_failure_is_contained_to_points_routes(system):
    p.PointsEntry.__table__.drop(system.engine)
    response = system.client.get('/points/me')
    assert response.status_code == 503
    assert 'SQL' not in response.text and 'SELECT' not in response.text
    assert system.client.get('/auth/me').status_code == 200
    p.PointsEntry.__table__.create(system.engine)


def test_note_award_belongs_to_creator_not_project_owner(system):
    s = system
    s.login('alice')
    project = s.client.post('/company-knowledge/projects', json={'name': '经验项目', 'category': '手稿笔记'}).json()
    s.login('admin')
    note = s.client.post('/company-knowledge/notes', json={'project_id': project['id']}).json()
    content = {'type': 'doc', 'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': 'Original synthetic note by administrator'}]}]}
    note = s.client.patch('/company-knowledge/notes/' + note['id'], json={'revision': note['revision'], 'title': '原创笔记', 'content': content}).json()
    published = s.client.post('/company-knowledge/notes/' + note['id'] + '/publish', json={'revision': note['revision']}).json()
    with s.db() as db:
        row = db.get(CompanyDocument, published['pending_document_id'])
        row.created_at, row.worker_id = s.clock[0], 'worker'
        db.commit()
    ingestion.checkpoint(row.id, 'worker', state='ready')
    p.process_pending(s.db)
    assert total(s, 4) == 15 and total(s, 1) == 0
    assert s.client.get('/points/leaderboard').json()['total'] == 0


def test_ledger_failure_rolls_back_total_and_retry_awards_exactly_once(system, monkeypatch):
    s = system
    capture(s, doc(s))
    real_award = p.award_event
    def interrupted(db, event):
        real_award(db, event)
        raise RuntimeError('Synthetic failure after ledger flush, before commit')
    monkeypatch.setattr(p, 'award_event', interrupted)
    p.process_pending(s.db)
    assert total(s, 1) == 0
    with s.db() as db:
        event = db.scalar(select(p.PointsEvent))
        assert event.status == 'failed' and event.attempts == 1
    monkeypatch.setattr(p, 'award_event', real_award)
    s.clock[0] += timedelta(seconds=30)
    p.process_pending(s.db)
    p.process_pending(s.db)
    assert total(s, 1) == 10


def test_pending_event_retains_original_rule_and_business_day(system):
    s = system
    capture(s, doc(s))
    original_day = p.day(s.clock[0])
    s.login('admin')
    policy = copy.deepcopy(p.DEFAULT)
    policy['upload_points'] = 99
    assert s.client.put('/admin/points/rules', json={'expected_version': 1,
        'policy': policy, 'reason': 'Future reward values'}).status_code == 200
    s.clock[0] += timedelta(days=1)
    p.process_pending(s.db)
    assert total(s, 1) == 10
    with s.db() as db:
        entry = db.scalar(select(p.PointsEntry))
        assert entry.business_day == original_day and entry.rule_id == 1


def test_full_application_boot_registers_points_and_preserves_auth_and_knowledge(system, monkeypatch):
    import asyncio
    import app as application
    import database
    s = system
    monkeypatch.setattr(database, 'engine', s.engine)
    monkeypatch.setattr(application.research_api_module, 'recover_stale_research_projects', lambda: None)
    async def idle_cleanup():
        await asyncio.Future()
    monkeypatch.setattr(application, 'invitation_cleanup_loop', idle_cleanup)
    with TestClient(application.create_app()) as client:
        client.headers.update(s.client.headers)
        assert client.get('/auth/me').status_code == 200
        assert client.get('/points/me').status_code == 200
        assert client.get('/company-knowledge/status').status_code == 200
        assert client.get('/version').status_code == 200
        assert client.get('/').status_code == 200
        assert client.get('/knowledge-points.js').status_code == 200
