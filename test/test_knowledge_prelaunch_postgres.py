"""Opt-in integration against the new, dedicated prelaunch-fix cluster only."""
import asyncio
import os
import time
import uuid

import httpx
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import company_knowledge as kb
import company_workspace as ws
import company_projects as projects
import company_ingestion as ingestion
from company_catalog import CompanyDocument, CompanyProject, CompanyFolder, CompanyAuditEvent, CompanyAccessRequest, document_store
from company_notes import CompanyNote, CompanyNoteAsset, CompanyNotePublication
from company_recycle import RecycleItem
from models import User
from test_company_workspace import setup, project


@pytest.fixture
def pg_setup(setup, monkeypatch):
    value = os.getenv('KNOWLEDGE_FIXES_TEST_PG_URL')
    if not value:
        pytest.skip('requires dedicated isolated PostgreSQL')
    url = make_url(value)
    assert url.host == '127.0.0.1' and url.port == 55449 and url.database == 'knowledge_fixes'
    schema = 'fix_' + uuid.uuid4().hex
    admin = create_engine(value, connect_args={'connect_timeout': 3})
    with admin.begin() as connection:
        assert 'knowledge-fixes-20261112' in connection.scalar(text('SHOW data_directory'))
        connection.execute(text('CREATE SCHEMA ' + schema))
    engine = create_engine(value, connect_args={'connect_timeout': 3,
        'options': '-c search_path=' + schema + ' -c statement_timeout=10000'})
    models = [User, CompanyProject, CompanyFolder, CompanyDocument, CompanyAuditEvent, CompanyAccessRequest,
              RecycleItem, CompanyNote, CompanyNoteAsset, CompanyNotePublication]
    try:
        for model in models:
            model.__table__.create(engine)
        factory = sessionmaker(engine, expire_on_commit=False)
        for module in (ws, projects, ingestion):
            monkeypatch.setattr(module, 'SessionLocal', factory)
        setup.db = factory
        with factory() as db:
            db.add(User(id=1, username='alice', password_hash='synthetic-not-a-login'))
            db.commit()
        yield setup
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text('DROP SCHEMA ' + schema + ' CASCADE'))
        admin.dispose()


@pytest.mark.integration
def test_two_same_project_uploads_never_stall_the_event_loop(pg_setup, monkeypatch):
    directory = project(pg_setup)
    real_write = type(document_store()).put_bytes
    def slow_write(self, *args):
        time.sleep(.3)
        return real_write(self, *args)
    monkeypatch.setattr(type(document_store()), 'put_bytes', slow_write)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=pg_setup.client.app),
                                     base_url='http://test') as client:
            async def upload():
                return await client.post('/company-knowledge/uploads', data={'project_id': directory['id']},
                                         files={'file': ('concurrent.txt', b'same synthetic content')})
            first, second = asyncio.create_task(upload()), asyncio.create_task(upload())
            await asyncio.sleep(.1)
            started = time.perf_counter()
            response = await asyncio.wait_for(client.get('/company-knowledge/projects'), 2)
            assert response.status_code == 200 and time.perf_counter() - started < 2
            responses = await asyncio.wait_for(asyncio.gather(first, second), 5)
            assert sorted(response.status_code for response in responses) == [202, 409]
    asyncio.run(run())
    with pg_setup.db() as db:
        docs = list(db.scalars(select(CompanyDocument)))
        assert len(docs) == 1 and docs[0].version == 1
        assert document_store().get_bytes(docs[0].object_key) == b'same synthetic content'


@pytest.mark.integration
def test_contended_project_returns_busy_without_wait_or_partial_write(pg_setup):
    directory = project(pg_setup)
    async def run():
        with pg_setup.db() as blocker:
            blocker.scalar(select(CompanyProject).where(CompanyProject.id == directory['id']).with_for_update())
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=pg_setup.client.app),
                                         base_url='http://test') as client:
                async def create(number):
                    return await client.post('/company-knowledge/projects/' + directory['id'] + '/folders',
                                             json={'name': 'contended-' + str(number)})
                started = time.perf_counter()
                responses = await asyncio.wait_for(asyncio.gather(*(create(i) for i in range(10))), 5)
                assert time.perf_counter() - started < 5
                assert all(response.status_code == 409 for response in responses)
                assert all('稍后重试' in response.text for response in responses)
            blocker.rollback()
    asyncio.run(run())
    with pg_setup.db() as db:
        assert list(db.scalars(select(CompanyFolder))) == []
    response = pg_setup.client.post('/company-knowledge/projects/' + directory['id'] + '/folders',
                                    json={'name': 'after-release'})
    assert response.status_code == 201


@pytest.mark.integration
def test_exhausted_pool_returns_retryable_busy_and_recovers(pg_setup, monkeypatch):
    directory = project(pg_setup)
    source = pg_setup.db.kw['bind']
    with source.connect() as connection:
        schema = connection.scalar(text('SELECT current_schema()'))
    engine = create_engine(source.url, pool_size=1, max_overflow=0, pool_timeout=.1,
        connect_args={'connect_timeout': 3, 'options': '-c search_path=' + schema})
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(projects, 'SessionLocal', factory)
    try:
        with engine.connect():
            response = pg_setup.client.post('/company-knowledge/projects/' + directory['id'] + '/folders',
                                            json={'name': 'pool-busy'})
            assert response.status_code == 503, response.text
            assert response.headers['retry-after'] == '2'
        response = pg_setup.client.post('/company-knowledge/projects/' + directory['id'] + '/folders',
                                        json={'name': 'pool-recovered'})
        assert response.status_code == 201
        with factory() as db:
            assert [folder.name for folder in db.scalars(select(CompanyFolder))] == ['pool-recovered']
    finally:
        engine.dispose()
