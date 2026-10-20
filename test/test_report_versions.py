"""Report history is read-only, scoped, body-free in lists and bounded in previews."""
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import auth
from account_migrations import migrate_accounts
from models import ResearchArtifact, ResearchProject, User
from report_versions import PREVIEW_LIMIT, create_report_versions_router
from research_api import _get_project


@pytest.fixture
def history(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'history.db'), connect_args={'check_same_thread': False})
    migrate_accounts(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add_all([User(id=1, username='owner', role='user', password_hash='unused'),
                    User(id=2, username='other', role='user', password_hash='unused'),
                    User(id=3, username='admin', role='admin', password_hash='unused')])
        db.flush()
        db.add_all([ResearchProject(id=1, title='Own research', created_by_id=1),
                    ResearchProject(id=2, title='Private research', created_by_id=2),
                    ResearchProject(id=3, title='Empty research', created_by_id=1)])
        db.flush()
        for version in range(1, 14):
            meta = {'PRIVATE_SECRET': 'HIDDEN_DIAGNOSTIC', 'docx_object_key': 'HIDDEN_FILE_KEY'}
            creator = 'agent'
            if version == 2:
                creator = 'human_review'
                meta.update(stage='human_review', original_filename='C:\\private\\edited.docx', delivery_status='review_draft')
            if version == 3:
                meta.update(reexported_from_artifact_id=1)
            if version == 4:
                meta.update(stage='second_stage')
            db.add(ResearchArtifact(id=version, project_id=1, artifact_type='desktop_report',
                                    title='Own report', version=version, created_at=datetime(2026, 10, 1),
                                    created_by=creator, content='PRIVATE_BODY_' + str(version), artifact_metadata=meta))
        db.add_all([
            ResearchArtifact(id=101, project_id=1, artifact_type='proposal', title='Proposal', version=4,
                             content='PROPOSAL_BODY', artifact_metadata={'proposal_confirmation_status': 'pending'}),
            ResearchArtifact(id=102, project_id=2, artifact_type='desktop_report', title='Other report', version=1, content='OTHER_PRIVATE_BODY'),
            ResearchArtifact(id=103, project_id=1, artifact_type='cleaned_facts', title='Facts', version=1, content='FACTS'),
            ResearchArtifact(id=104, project_id=1, artifact_type='desktop_report', title='Long report', version=15,
                             content='X' * (PREVIEW_LIMIT + 10), artifact_metadata={'docx_export_error': 'INTERNAL_ERROR', 'quality_warning': 'PRIVATE_WARNING'}),
            ResearchArtifact(id=105, project_id=1, artifact_type='desktop_report', title='Original only', version=16,
                             content='', artifact_metadata={'review_original_object_key': 'PRIVATE_ORIGINAL_KEY'}, created_by='human_review'),
        ])
        db.commit()
    app = FastAPI()
    app.include_router(create_report_versions_router(_get_project), prefix='/research')
    def get_db():
        with factory() as db:
            yield db
    app.dependency_overrides[auth.get_db] = get_db
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        engine.dispose()


def headers(name='owner', role='user'):
    return {'Authorization': 'Bearer ' + auth.create_access_token(name, role)}


@pytest.mark.parametrize('path', ['/research/projects/1/report-versions', '/research/artifacts/1/preview'])
def test_history_requires_current_authenticated_account(history, path):
    client, factory = history
    assert client.get(path).status_code == 401
    with factory() as db:
        db.get(User, 1).is_active = False
        db.commit()
    assert client.get(path, headers=headers()).status_code == 401


@pytest.mark.parametrize('path', ['/research/projects/2/report-versions', '/research/artifacts/102/preview'])
def test_history_cannot_read_other_accounts_reports(history, path):
    client, _ = history
    denied = client.get(path, headers=headers())
    assert denied.status_code == 403 and 'OTHER_PRIVATE_BODY' not in denied.text
    assert client.get(path, headers=headers('admin', 'admin')).status_code == 200


def test_paginated_type_specific_list_has_no_report_bodies_or_raw_metadata(history):
    client, _ = history
    first = client.get('/research/projects/1/report-versions?page_size=10', headers=headers())
    assert first.status_code == 200 and first.headers['cache-control'] == 'no-store'
    data = first.json()
    assert data['total'] == 15 and len(data['records']) == 10
    assert data['records'][0]['record_label'] == '记录 016'
    assert [r['id'] for r in data['records'] if r['is_latest']] == [105]
    assert all(r['artifact_type'] == 'desktop_report' for r in data['records'])
    for private in ['PRIVATE_BODY', 'HIDDEN_DIAGNOSTIC', 'HIDDEN_FILE_KEY', 'PRIVATE_ORIGINAL_KEY', 'INTERNAL_ERROR', 'PRIVATE_WARNING']:
        assert private not in first.text
    second = client.get('/research/projects/1/report-versions?page=2', headers=headers()).json()
    assert len(second['records']) == 5
    assert not {r['id'] for r in data['records']} & {r['id'] for r in second['records']}
    origins = {r['version']: r for r in second['records']}
    assert origins[2]['origin_label'] == '上传修订' and origins[2]['original_filename'] == 'edited.docx'
    assert origins[3]['origin_label'] == '重新导出'
    assert origins[4]['origin_label'] == '补充资料后生成'
    proposal = client.get('/research/projects/1/report-versions?artifact_type=proposal', headers=headers()).json()
    assert proposal['total'] == 1 and proposal['records'][0]['id'] == 101
    assert proposal['records'][0]['review_label'] == '建议书待确认'


def test_record_preview_is_exact_bounded_and_read_only(history):
    client, factory = history
    with factory() as db:
        before = [(row.id, row.content, row.artifact_metadata) for row in db.scalars(select(ResearchArtifact))]
    exact = client.get('/research/artifacts/2/preview', headers=headers())
    assert exact.status_code == 200 and exact.headers['cache-control'] == 'no-store'
    assert exact.json()['content'] == 'PRIVATE_BODY_2' and exact.json()['truncated'] is False
    long = client.get('/research/artifacts/104/preview', headers=headers()).json()
    assert len(long['content']) == PREVIEW_LIMIT and long['truncated'] is True
    empty = client.get('/research/artifacts/105/preview', headers=headers()).json()
    assert empty['has_preview'] is False and empty['content'] == ''
    for aid in [103, 999]:
        assert client.get(f'/research/artifacts/{aid}/preview', headers=headers()).status_code == 404
    with factory() as db:
        after = [(row.id, row.content, row.artifact_metadata) for row in db.scalars(select(ResearchArtifact))]
    assert after == before


@pytest.mark.parametrize('query', ['page=0', 'page_size=0', 'page_size=51', 'artifact_type=cleaned_facts'])
def test_invalid_history_filters_are_rejected(history, query):
    client, _ = history
    assert client.get('/research/projects/1/report-versions?' + query, headers=headers()).status_code == 422


def test_history_empty_missing_and_temporary_password_states(history):
    client, factory = history
    assert client.get('/research/projects/3/report-versions', headers=headers()).json()['records'] == []
    assert client.get('/research/projects/1/report-versions?page=99', headers=headers()).json()['records'] == []
    assert client.get('/research/projects/999/report-versions', headers=headers()).status_code == 404
    with factory() as db:
        db.get(User, 1).must_change_password = True
        db.commit()
    assert client.get('/research/projects/1/report-versions', headers=headers()).status_code == 403
