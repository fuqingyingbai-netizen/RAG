"""Personal home uses isolated databases and never starts research workflows."""
from datetime import datetime
import os
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

import auth
from account_migrations import migrate_accounts
from models import AccountAudit, ResearchArtifact, ResearchProject, User
from personal_home import create_home_router


@pytest.fixture(params=['sqlite'] + (['postgresql'] if os.getenv('ACCOUNT_TEST_POSTGRES') == '1' else []))
def setup_home(tmp_path, request, monkeypatch):
    monkeypatch.setattr(auth, 'SECRET_KEY', 'personal-home-test-secret-12345678901234567890')
    namespace = None
    if request.param == 'postgresql':
        from database import engine as configured_engine
        namespace = 'account_test_' + uuid.uuid4().hex
        with configured_engine.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{namespace}"'))
        engine = create_engine(configured_engine.url, connect_args={'options': f'-csearch_path={namespace}'})
    else:
        engine = create_engine('sqlite:///' + str(tmp_path / 'home.db'), connect_args={'check_same_thread': False})
    factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    migrate_accounts(engine)
    with factory() as db:
        db.add_all([User(id=uid, username=name, role=role, display_name=display_name, notes='PRIVATE_ADMIN_NOTES', password_hash='unused-test-hash')
                    for uid, name, role, display_name in [(1, 'employee', 'user', '张同事'), (2, 'other', 'user', ''),
                                                          (3, 'admin', 'admin', ''), (4, 'empty', 'user', '')]])
        db.flush()
        for pid, owner, status in [(11, 1, 'draft'), (12, 1, 'completed'), (13, 1, 'collecting'), (14, 1, 'collecting'),
                                   (21, 2, 'completed'), (31, 3, 'completed')]:
            db.add(ResearchProject(id=pid, created_by_id=owner, title=f'project-{pid}', target_type='industry',
                                   status=status, updated_at=datetime(2026, 10, 1, 0, 0)))
        db.flush()
        for aid, pid, kind, version, day, metadata in [
            (101, 12, 'desktop_report', 1, 1, {}), (102, 12, 'desktop_report', 2, 2, {}),
            (103, 12, 'proposal', 1, 3, {'proposal_confirmation_status': 'pending'}),
            (104, 21, 'desktop_report', 1, 4, {}), (105, 31, 'desktop_report', 1, 4, {}),
            (106, 12, 'workflow_trace', 1, 5, {}),
            (107, 12, 'desktop_report', 3, 2, {'delivery_status': 'review_draft', 'docx_export_error': 'PRIVATE_ERROR'}),
        ]:
            db.add(ResearchArtifact(id=aid, project_id=pid, artifact_type=kind, title=f'report-{aid}', version=version,
                                    content='PRIVATE_REPORT_BODY', object_key='PRIVATE_OBJECT_PATH', artifact_metadata=metadata,
                                    created_at=datetime(2026, 10, day, 0, 0)))
        db.commit()
    app = FastAPI()
    app.include_router(create_home_router(lambda pid: pid == 14))
    def get_db():
        with factory() as db:
            yield db
    app.dependency_overrides[auth.get_db] = get_db
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        engine.dispose()
        if namespace:
            assert namespace.startswith('account_test_') and len(namespace) == 45
            with configured_engine.begin() as db:
                db.execute(text(f'DROP SCHEMA "{namespace}" CASCADE'))


def headers(username='employee', role='user'):
    return {'Authorization': 'Bearer ' + auth.create_access_token(username, role, 0)}


def test_home_requires_authentication_and_temporary_password_change(setup_home):
    client, factory = setup_home
    assert client.get('/research/home').status_code == 401
    with factory() as db:
        db.get(User, 1).must_change_password = True
        db.commit()
    response = client.get('/research/home', headers=headers())
    assert response.status_code == 403 and response.headers['X-Password-Change-Required'] == 'true'


@pytest.mark.parametrize('username,role,project_ids,report_ids', [
    ('employee', 'user', {11, 12, 13, 14}, {103, 107}), ('admin', 'admin', {31}, {105}),
    ('other', 'user', {21}, {104}),
])
def test_home_is_personal_even_for_administrators(setup_home, username, role, project_ids, report_ids):
    client, _ = setup_home
    response = client.get('/research/home', headers=headers(username, role))
    assert response.status_code == 200, response.text
    data = response.json()
    assert {row['id'] for row in data['recent_projects']} == project_ids
    assert {row['id'] for row in data['recent_reports']} == report_ids
    assert data['summary']['total'] == len(project_ids)
    assert data['user']['username'] == username
    assert 'PRIVATE_' not in response.text and 'password' not in response.text and 'object_key' not in response.text


def test_home_running_count_uses_live_state_and_reports_keep_review_labels(setup_home):
    client, factory = setup_home
    with factory() as db:
        before = [db.scalar(select(func.count()).select_from(model)) for model in (User, ResearchProject, ResearchArtifact, AccountAudit)]
    data = client.get('/research/home', headers=headers()).json()
    assert data['user']['display_name'] == '张同事'
    assert data['summary'] == {'total': 4, 'running': 1, 'completed': 1, 'attention': 2}
    states = {row['id']: row for row in data['recent_projects']}
    assert states[14]['is_running'] and states[14]['state_label'].startswith('进行中')
    assert not states[13]['is_running'] and states[13]['state_label'] == '待继续'
    reports = {row['id']: row for row in data['recent_reports']}
    assert reports[103]['review_label'] == '建议书待确认'
    assert reports[107]['review_label'] == '待复核稿' and reports[107]['export_error']
    assert reports[107]['version'] == 3 and reports[107]['can_download']
    with factory() as db:
        after = [db.scalar(select(func.count()).select_from(model)) for model in (User, ResearchProject, ResearchArtifact, AccountAudit)]
    assert before == after


def test_home_limits_recent_items_without_losing_totals_or_empty_state(setup_home):
    client, factory = setup_home
    empty = client.get('/research/home', headers=headers('empty')).json()
    assert empty['summary'] == {'total': 0, 'running': 0, 'completed': 0, 'attention': 0}
    assert empty['recent_projects'] == empty['recent_reports'] == []
    with factory() as db:
        for index in range(8):
            project = ResearchProject(created_by_id=1, title=f'new-{index}', status='paused', updated_at=datetime(2026, 10, 10))
            db.add(project)
            db.flush()
            db.add(ResearchArtifact(project_id=project.id, artifact_type='desktop_report', title=f'new-report-{index}',
                                    created_at=datetime(2026, 10, 10), content='', object_key=''))
        db.commit()
    data = client.get('/research/home', headers=headers()).json()
    assert data['summary']['total'] == 12
    assert len(data['recent_projects']) == len(data['recent_reports']) == 6
    assert all(row['title'].startswith('new-') for row in data['recent_projects'])
    assert all(not row['can_download'] for row in data['recent_reports'])


def test_concurrent_project_creation_keeps_overview_roster_consistent(setup_home):
    _, factory = setup_home
    inserted = False
    def is_running(pid):
        nonlocal inserted
        if not inserted:
            inserted = True
            with factory() as db:
                db.add(ResearchProject(id=1000, created_by_id=1, title='new-concurrent-project', status='draft', updated_at=datetime(2026, 10, 31)))
                db.flush()
                db.add(ResearchArtifact(id=1000, project_id=1000, artifact_type='desktop_report', title='new-concurrent-report', content='fixture', created_at=datetime(2026, 10, 31)))
                db.commit()
        return pid == 14
    app = FastAPI()
    app.include_router(create_home_router(is_running))
    def get_db():
        with factory() as db:
            yield db
    app.dependency_overrides[auth.get_db] = get_db
    with TestClient(app) as client:
        first = client.get('/research/home', headers=headers())
        assert first.status_code == 200, first.text
        data = first.json()
        assert data['summary']['total'] == 4
        assert 1000 not in {row['id'] for row in data['recent_projects']}
        assert 1000 not in {row['id'] for row in data['recent_reports']}
        refreshed = client.get('/research/home', headers=headers()).json()
        assert refreshed['summary']['total'] == 5
        assert refreshed['recent_projects'][0]['id'] == refreshed['recent_reports'][0]['id'] == 1000
