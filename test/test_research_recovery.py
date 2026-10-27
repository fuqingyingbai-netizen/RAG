"""Recovery advice uses persisted facts and never runs research or reads blobs."""
from copy import deepcopy
from datetime import datetime
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import auth
import research_api as api
from account_migrations import migrate_accounts
from models import ResearchArtifact, ResearchProject, ResearchSource, User
from research_recovery import build_recovery, failure_reason


def artifact(id=1, kind='desktop_report', body='saved body', version=1, **meta):
    return SimpleNamespace(id=id, artifact_type=kind, content=body, version=version,
                           created_at=datetime(2026, 10, 21), artifact_metadata=meta, object_key='unverified-key')


def source(**meta):
    return SimpleNamespace(source_metadata=meta)


def test_failed_workflow_uses_last_run_stage_and_only_confirmed_saved_text():
    rows = [artifact(), artifact(2, 'proposal', body='', docx_export_error='PRIVATE_ERROR')]
    trace = [{'stage': 'report', 'status': 'error', 'detail': '401 OLD_SECRET'},
             {'stage': 'init', 'status': 'running'}, {'stage': 'report', 'status': 'running'},
             {'stage': 'workflow', 'status': 'error', 'detail': 'TimeoutError at https://user:SECRET@service.test'}]
    result = build_recovery(SimpleNamespace(status='failed'), [source(), source(extraction_status='failed')], rows, trace)
    assert result['saved'] == {'source_records': 2, 'report_text_records': 1, 'proposal_text_records': 0}
    workflow = result['issues'][0]
    assert workflow['stage'] == '报告生成' and workflow['reason_code'] == 'timeout'
    assert workflow['actions'][0]['kind'] == 'run'
    assert '不保证从失败位置直接接续' in workflow['actions'][0]['description']
    assert 'SECRET' not in json.dumps(result)
    assert any(issue['kind'] == 'parsing' for issue in result['issues'])
    export = next(issue for issue in result['issues'] if issue['kind'] == 'export')
    assert not any(action['kind'] == 'download' for action in export['actions'])
    assert '未确认' in export['reason']


def test_healthy_latest_report_suppresses_older_export_and_knowledge_failures():
    rows = [artifact(1, version=1, docx_export_error='old failure', knowledge_sync_status='failed'), artifact(2, version=2)]
    result = build_recovery(SimpleNamespace(status='completed'), [], rows, [{'stage': 'workflow', 'status': 'error', 'detail': 'old failure'}])
    assert result['issues'] == []
    assert result['saved']['report_text_records'] == 2


def test_export_and_knowledge_failures_are_distinct_and_offer_narrow_actions():
    result = build_recovery(SimpleNamespace(status='completed'), [],
                            [artifact(docx_export_error='PRIVATE_ERROR', knowledge_sync_status='failed')], [])
    export, knowledge = result['issues']
    assert export['kind'] == 'export' and knowledge['kind'] == 'knowledge'
    assert {action['kind'] for action in export['actions']} == {'download', 'history'}
    assert {action['kind'] for action in knowledge['actions']} == {'retry_knowledge', 'download'}
    assert '不重新生成研究报告' in knowledge['advice']
    assert 'PRIVATE_ERROR' not in str(result)


def test_live_knowledge_metadata_overrides_last_saved_sync_attempt():
    result = build_recovery(SimpleNamespace(status='completed'), [], [artifact(knowledge_sync_status='failed')], [],
                            artifact_metadata={1: {'knowledge_sync_status': 'ready'}})
    assert result['issues'] == []


def test_unknown_failure_and_running_project_never_invent_resume_position():
    result = build_recovery(SimpleNamespace(status='failed'), [], [artifact(knowledge_sync_status='failed')], [None, 'bad'], running=True)
    workflow = result['issues'][0]
    assert workflow['stage'] == '未记录具体阶段' and workflow['reason_code'] == 'unclassified'
    assert workflow['actions'] == []
    assert not any(action['kind'] in {'run', 'retry_knowledge'} for issue in result['issues'] for action in issue['actions'])


def test_paused_workflow_and_disabled_resume_describe_real_execution_rules(monkeypatch):
    monkeypatch.setenv('WORKFLOW_RESUME_ENABLED', 'false')
    journal = artifact(kind='industry_run', run_status='paused', current_stage='cleaning')
    result = build_recovery(SimpleNamespace(status='paused'), [], [journal], [])
    workflow = result['issues'][0]
    assert workflow['stage'] == '数据清洗' and workflow['reason_code'] == 'paused'
    assert workflow['actions'][0]['label'] == '重新执行'
    assert '未开启阶段复用' in result['run_notice']


@pytest.mark.parametrize('error,code', [('401 private key', 'auth'), ('429 quota exhausted', 'limit'),
    ('request timed out', 'timeout'), ('No space left on device', 'storage'), ('ConnectionError', 'connection'),
    ('证据不足', 'evidence'), ('RateLimitError', 'limit'), ('project 1401 failed at row 4290', 'unclassified'),
    ('unrecognized internal detail', 'unclassified')])
def test_failure_reasons_are_actionable_without_raw_provider_details(error, code):
    result = failure_reason(error)
    assert result['code'] == code
    assert error not in result['reason'] + result['advice']


def test_building_guidance_does_not_mutate_saved_inputs():
    row = artifact(docx_export_error='failure')
    before = deepcopy(vars(row))
    build_recovery(SimpleNamespace(status='failed'), [], [row], [])
    assert vars(row) == before


@pytest.fixture
def recovery_api(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path / 'recovery.db'), connect_args={'check_same_thread': False})
    migrate_accounts(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add_all([User(id=1, username='recovery-owner', role='user', password_hash='unused'),
                    User(id=2, username='recovery-other', role='user', password_hash='unused'),
                    User(id=3, username='recovery-admin', role='admin', password_hash='unused')])
        db.flush()
        db.add(ResearchProject(id=1, title='Fixture project', status='failed', created_by_id=1))
        db.flush()
        db.add(ResearchArtifact(id=1, project_id=1, artifact_type='desktop_report', title='Saved report', content='SAVED_BODY'))
        db.add(ResearchArtifact(id=2, project_id=1, artifact_type='workflow_trace', title='Trace', content=json.dumps([
            {'stage': 'report', 'status': 'running'}, {'stage': 'workflow', 'status': 'error', 'detail': 'TimeoutError'}])))
        db.commit()
    app = FastAPI(); app.include_router(api.router)
    def get_db():
        with factory() as db:
            yield db
    app.dependency_overrides[auth.get_db] = get_db
    monkeypatch.setattr(api, '_is_project_running', lambda _: False)
    monkeypatch.setattr(api.research_workflow, 'run_project', lambda *a, **k: pytest.fail('must not run research'))
    monkeypatch.setattr(api.research_store, 'get_bytes', lambda *a, **k: pytest.fail('must not read stored blobs'))
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        engine.dispose()


def test_detail_recovery_is_authenticated_scoped_and_read_only(recovery_api):
    client, factory = recovery_api
    path = '/research/projects/1/detail'
    assert client.get(path).status_code == 401
    other = {'Authorization': 'Bearer ' + auth.create_access_token('recovery-other', 'user')}
    assert client.get(path, headers=other).status_code == 403
    owner = {'Authorization': 'Bearer ' + auth.create_access_token('recovery-owner', 'user')}
    response = client.get(path, headers=owner)
    assert response.status_code == 200
    recovery = response.json()['recovery']
    assert recovery['saved']['report_text_records'] == 1
    assert recovery['issues'][0]['stage'] == '报告生成'
    assert 'SAVED_BODY' not in json.dumps(recovery)
    admin = {'Authorization': 'Bearer ' + auth.create_access_token('recovery-admin', 'admin')}
    assert client.get(path, headers=admin).status_code == 200
    assert client.get('/research/projects/999/detail', headers=owner).status_code == 404
    with factory() as db:
        assert db.get(ResearchProject, 1).status == 'failed'
        assert db.get(ResearchArtifact, 1).content == 'SAVED_BODY'
        assert len(db.scalars(select(ResearchArtifact)).all()) == 2
