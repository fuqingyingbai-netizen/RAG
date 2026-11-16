"""Shared boundaries when importing the live industry pipeline into main."""
from contextvars import copy_context
import asyncio
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from database import Base
from industry_collection import CollectionBudgetExhausted, IndustryCollection
from industry_recovery_queue import RecoverySourceQueue
from models import ResearchArtifact, ResearchProject, ResearchSource, User
from source_catalog import source_records
from source_retention import finalize_web_sources
from web_search import budgeted_request, search_request_budget


@pytest.mark.parametrize('route', ['industry', 'company', 'person'])
def test_industry_archive_retention_preserves_other_route_cleanup(route):
    deleted, commits = [], []
    source = NS(id=1, object_key='projects/42/raw_web/1.txt', content='Original disclosure.',
                summary='', url='https://original.test/disclosure',
                source_metadata={'retention_policy': 'transient_web_body'})
    project = NS(id=42, target_type=route, sources=[source])
    store = NS(delete_object=deleted.append)
    db = NS(commit=lambda: commits.append(True))

    assert finalize_web_sources(db, project, store) == 1
    if route == 'industry':
        assert source.content == 'Original disclosure.'
        assert source.object_key == 'projects/42/raw_web/1.txt'
        assert source.source_metadata['retention_policy'] == 'review_archive'
        assert not deleted
        assert finalize_web_sources(db, project, store) == 0
        assert len(commits) == 1
    else:
        assert source.content == source.object_key == ''
        assert source.source_metadata['retention_policy'] == 'record_only'
        assert deleted == ['projects/42/raw_web/1.txt']


def test_industry_request_budget_does_not_leak_to_later_requests():
    collection = IndustryCollection(clock=lambda: 0)
    collection.begin('initial')
    requests = []

    def transport(*args, **kwargs):
        requests.append(kwargs['timeout'])
        return 'response'

    with collection.request_scope('industry question'):
        assert budgeted_request('exa', transport, timeout=30) == 'response'
        stale_context = copy_context()
    assert search_request_budget.get() is None
    assert collection.used['search_requests'] == 1
    assert budgeted_request('exa', transport, timeout=45) == 'response'
    assert collection.used['search_requests'] == 1
    collection.end()
    with pytest.raises(CollectionBudgetExhausted, match='expired_collection_phase'):
        stale_context.run(budgeted_request, 'exa', transport, timeout=30)
    assert requests == [30, 45]


def test_source_catalog_pages_metadata_without_selecting_original_bodies():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username='source-catalog-fixture', password_hash='unused-test-hash')
        db.add(user)
        db.flush()
        project = ResearchProject(title='Test industry', target_name='Test industry',
                                  target_type='industry', created_by_id=user.id)
        db.add(project)
        db.flush()
        project_id = project.id
        for number in range(2):
            db.add(ResearchSource(project_id=project_id, source_type='web', title=f'Original {number}',
                url=f'https://original.test/{number}', content='PRIVATE ORIGINAL BODY', summary='s' * 900,
                object_key=f'projects/{project_id}/raw_web/{number}.txt',
                source_metadata={'retention_policy': 'review_archive', 'private_marker': 'never-list'}))
        db.commit()
        statements = []
        event.listen(engine, 'before_cursor_execute',
                     lambda conn, cursor, statement, params, context, many: statements.append(statement))
        first = source_records(db, project_id, page=1, page_size=1)
        second = source_records(db, project_id, page=2, page_size=1)
        assert first['total'] == second['total'] == 2
        assert first['records'][0]['id'] != second['records'][0]['id']
        row = first['records'][0]
        assert row['has_archive'] and row['archive_verified'] is False
        assert row['summary_truncated'] and len(row['summary']) == 800
        assert 'content' not in row and 'source_metadata' not in row
        assert not any('research_sources.content' in statement for statement in statements)
    engine.dispose()


def test_recovery_queue_keeps_uncommitted_sources_for_resume():
    source = NS(id=7, content='An original disclosure.', summary='', source_metadata={})
    queue = RecoverySourceQueue('fixture-run')
    queue.enqueue([source, source])
    queue.reserve([source])
    queue.stage()
    queue.release()
    assert queue.snapshot()['pending_source_ids'] == [7]
    assert queue.snapshot()['processed_source_ids'] == []
    queue.reserve([source])
    queue.stage()
    queue.commit(123)
    state = queue.snapshot()
    assert state['pending_source_ids'] == []
    assert state['processed_source_ids'] == [7]
    assert state['processed_artifacts'] == {'7': 123}


@pytest.mark.parametrize('route', ['industry', 'company', 'person'])
def test_industry_bulk_delete_does_not_change_other_route_cleanup(route, tmp_path, monkeypatch):
    import research_api as api

    engine = create_engine(f'sqlite:///{tmp_path / "delete.sqlite"}',
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    prefixes, individual = [], []
    monkeypatch.setattr(api, 'research_store', NS(delete_prefix=prefixes.append))
    monkeypatch.setattr(api, '_delete_project_file', lambda key, project_id: individual.append(key) if key else None)
    monkeypatch.setattr(api, 'UPLOAD_DIR', tmp_path / 'uploads')
    monkeypatch.setattr(api, 'RUNNING_PROJECT_IDS', set())
    with Session(engine) as db:
        user = User(username='delete-fixture', password_hash='unused-test-hash')
        db.add(user)
        db.flush()
        projects = [ResearchProject(title=kind, target_name=kind, target_type=kind,
                                    created_by_id=user.id) for kind in (route, 'industry')]
        db.add_all(projects)
        db.flush()
        ids = [project.id for project in projects]
        for project_id in ids:
            db.add(ResearchSource(project_id=project_id, source_type='web',
                object_key=f'projects/{project_id}/raw_web/original.txt', content='Retained original.'))
            db.add(ResearchArtifact(project_id=project_id, artifact_type='desktop_report',
                title='Test report', content='Report body.'))
        db.commit()
        result = asyncio.run(api.delete_project(ids[0], db, user))
        db.expire_all()
        assert db.query(ResearchProject).filter_by(id=ids[0]).count() == 0
        assert db.query(ResearchSource).filter_by(project_id=ids[0]).count() == 0
        assert db.query(ResearchArtifact).filter_by(project_id=ids[0]).count() == 0
        assert db.query(ResearchProject).filter_by(id=ids[1]).count() == 1
        assert db.query(ResearchSource).filter_by(project_id=ids[1]).count() == 1
        assert prefixes == [f'projects/{ids[0]}']
        if route == 'industry':
            assert result['cleanup_pending'] is False and not individual
        else:
            assert 'cleanup_pending' not in result
            assert f'projects/{ids[0]}/raw_web/original.txt' in individual
    engine.dispose()
