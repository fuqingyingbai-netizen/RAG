"""Shared boundaries when importing the live industry pipeline into main."""
from contextvars import copy_context
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from database import Base
from industry_collection import CollectionBudgetExhausted, IndustryCollection
from industry_recovery_queue import RecoverySourceQueue
from models import ResearchProject, ResearchSource, User
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
