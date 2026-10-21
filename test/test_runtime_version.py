"""Version query uses loaded values and never starts business operations."""
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
import runpy
import sys

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from runtime_version import create_version_router


VERSIONS = {'cleaning': 'cleaning-loaded-v12', 'risk': 'risk-loaded-v8', 'report': 'report-loaded-v20'}


def test_version_is_public_read_only_and_not_cached():
    app = FastAPI()
    app.include_router(create_version_router(VERSIONS))
    client = TestClient(app)
    response = client.get('/version')
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {'service', 'instance_id', 'loaded_at_utc', 'industry'}
    assert data['service'] == 'rag-backend' and data['industry'] == VERSIONS
    assert UUID(data['instance_id'])
    assert datetime.fromisoformat(data['loaded_at_utc']).utcoffset().total_seconds() == 0
    assert response.headers['cache-control'] == 'no-store, max-age=0'
    assert response.headers['pragma'] == 'no-cache'
    assert client.post('/version').status_code == 405
    route = next(r for r in app.routes if r.path == '/version')
    assert not route.dependant.dependencies  # No auth, database or research dependencies.


def test_snapshot_does_not_read_new_disk_values_or_change_between_requests(monkeypatch):
    versions = dict(VERSIONS)
    app = FastAPI()
    app.include_router(create_version_router(versions))
    client = TestClient(app)
    first = client.get('/version').json()
    versions['report'] = 'a-new-file-value-not-loaded-by-the-app'
    def no_disk(*args, **kwargs):
        raise AssertionError('Version queries must not reread source files')
    monkeypatch.setattr(Path, 'read_text', no_disk)
    monkeypatch.setattr(Path, 'read_bytes', no_disk)
    assert client.get('/version').json() == first


def test_new_application_has_a_new_instance_identity():
    def instance():
        app = FastAPI()
        app.include_router(create_version_router(VERSIONS))
        return TestClient(app).get('/version').json()['instance_id']
    assert instance() != instance()


def test_real_app_registers_version_before_static_without_business_calls(monkeypatch):
    calls = []
    def no_business(*args, **kwargs):
        calls.append('unexpected business operation')
        raise AssertionError('The query must not initialize a database or recover tasks')
    # Import the actual application factory using isolated service doubles.
    # In particular, do not enter its business startup lifespan in this test.
    monkeypatch.setitem(sys.modules, 'api', SimpleNamespace(router=APIRouter()))
    monkeypatch.setitem(sys.modules, 'research_api', SimpleNamespace(
        router=APIRouter(), recover_stale_research_projects=no_business, _is_project_running=no_business))
    monkeypatch.setitem(sys.modules, 'account_lifecycle', SimpleNamespace(invitation_cleanup_loop=no_business))
    def home_router(is_running):
        assert is_running is no_business
        return APIRouter()
    monkeypatch.setitem(sys.modules, 'personal_home', SimpleNamespace(create_home_router=home_router))
    knowledge_router = APIRouter()
    knowledge_router.add_api_route('/company-knowledge-test', lambda: {'available': True})
    monkeypatch.setitem(sys.modules, 'company_knowledge', SimpleNamespace(
        router=knowledge_router, KnowledgeError=type('KnowledgeError', (Exception,), {})))
    monkeypatch.setitem(sys.modules, 'database', SimpleNamespace(init_db=no_business))
    monkeypatch.setitem(sys.modules, 'research_workflow', SimpleNamespace(
        INDUSTRY_CLEANING_VERSION=VERSIONS['cleaning'], INDUSTRY_REPORT_VERSION=VERSIONS['report']))
    monkeypatch.setitem(sys.modules, 'industry_research', SimpleNamespace(INDUSTRY_RISK_VERSION=VERSIONS['risk']))
    namespace = runpy.run_path(str(Path(__file__).resolve().parents[1]/'backend/app.py'), run_name='version_endpoint_test')
    app = namespace['app']
    response = TestClient(app).get('/version')
    assert response.status_code == 200 and response.json()['industry'] == VERSIONS
    paths = [getattr(r, 'path', None) for r in app.routes]
    assert paths.index('/version') < paths.index('')  # Root static mount cannot swallow it.
    assert paths.index('/company-knowledge-test') < paths.index('')
    assert not calls
