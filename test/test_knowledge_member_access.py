"""Membership opens internal knowledge without weakening document ceilings."""
import asyncio
from types import SimpleNamespace

import pytest

import company_knowledge as kb
import company_workspace as ws
from company_catalog import CompanyDocument, can_read, can_manage
from test_company_workspace import setup, upload, ready, project, folder


def test_existing_ungranted_member_can_browse_internal_and_create_own_project(setup, monkeypatch):
    row = upload(setup, name='internal.txt').json()
    ready(setup, row['id'])
    setup.user.id, setup.user.username = 2, 'new-member'
    setup.user.knowledge_access = False
    monkeypatch.setenv('COMPANY_KNOWLEDGE_USERS', '')
    assert setup.client.get('/company-knowledge/status').json()['access_allowed']
    assert setup.client.get('/company-knowledge/documents').json()['documents'][0]['can_read']
    assert setup.client.get('/company-knowledge/documents/' + row['id'] + '/original').status_code == 200
    assert set(asyncio.run(ws.prepare_scope(kb.settings(), setup.user, []))) == {'cloud-a'}
    own = project(setup, '新账号项目')
    assert own['can_manage'] and own['confidentiality'] == 'internal'
    assert upload(setup, project_id=own['id']).status_code == 202


@pytest.mark.parametrize('level', ['confidential', 'secret'])
@pytest.mark.parametrize('identity', ['owner', 'reader', 'other'])
def test_classification_blocks_legacy_owners_and_grants_across_all_reads(setup, level, identity):
    setup.user.role = 'admin'
    p = project(setup, '不可公开的项目', confidentiality=level, readers=['bob'])
    f = folder(setup, p['id'])
    row = upload(setup, project_id=p['id'], folder_id=f['id']).json()
    ready(setup, row['id'])
    internal = upload(setup, name='internal.txt').json()
    ready(setup, internal['id'], 'cloud-internal')
    setup.user.role = 'user'
    setup.user.id, setup.user.username = {'owner': (1, 'alice'), 'reader': (2, 'bob'), 'other': (3, 'charlie')}[identity]
    setup.user.knowledge_access = True  # Legacy opt-in must not grant higher classification.
    catalog = setup.client.get('/company-knowledge/documents?page_size=1').json()
    assert catalog['total_count'] == 1 and [d['id'] for d in catalog['documents']] == [internal['id']]
    assert '不可公开' not in str(catalog)
    assert p['id'] not in [p['id'] for p in setup.client.get('/company-knowledge/projects').json()['projects']]
    assert '不可公开' not in str(setup.client.get('/company-knowledge/my-projects').json())
    for endpoint in ['original', 'download', 'preview', 'page', 'thumbnail', 'outline', 'export-status']:
        params = {'request_id': 'abcdef0123456789'} if endpoint == 'export-status' else {}
        assert setup.client.get('/company-knowledge/documents/' + row['id'] + '/' + endpoint, params=params).status_code == 404
    assert setup.client.post('/company-knowledge/documents/' + row['id'] + '/locate', json={'text': '原文'}).status_code == 404
    assert setup.client.post('/company-knowledge/documents/' + row['id'] + '/access-requests', json={}).status_code == 404
    assert setup.client.get('/company-knowledge/audit-events?document_id=' + row['id']).status_code == 404
    assert setup.client.patch('/company-knowledge/documents/' + row['id'], json={'confidentiality': 'internal'}).status_code == 404
    search = setup.client.post('/company-knowledge/search', json={'query': '不可公开', 'document_ids': [row['id']]})
    assert search.status_code == 403
    assert setup.client.post('/company-knowledge/chat/stream', json={'message': '总结', 'document_ids': [row['id']]}).status_code == 403
    assert set(asyncio.run(ws.prepare_scope(kb.settings(), setup.user, []))) == {'cloud-internal'}
    with setup.db() as db:
        protected = db.get(CompanyDocument, row['id'])
        assert not can_read(protected, setup.user) and not can_manage(protected, setup.user)
        assert can_read(protected, SimpleNamespace(role='admin', username='admin'))


@pytest.mark.parametrize('level', ['confidential', 'secret'])
def test_member_cannot_create_or_reclassify_above_internal(setup, level):
    response = setup.client.post('/company-knowledge/projects', json={'name': '越权项目', 'confidentiality': level})
    assert response.status_code == 403
    assert upload(setup, confidentiality=level).status_code == 403
    p = project(setup)
    assert setup.client.patch('/company-knowledge/projects/' + p['id'], json={'name': p['name'], 'confidentiality': level}).status_code == 403
    row = upload(setup).json()
    assert setup.client.patch('/company-knowledge/documents/' + row['id'], json={'confidentiality': level}).status_code == 403
    assert setup.client.get('/company-knowledge/documents/' + row['id'] + '/original').status_code == 200


def test_old_pending_request_cannot_be_approved_after_classification_upgrade(setup):
    row = upload(setup, visibility='restricted').json()
    setup.user.id, setup.user.username = 2, 'bob'
    request = setup.client.post('/company-knowledge/documents/' + row['id'] + '/access-requests', json={}).json()
    setup.user.role = 'admin'
    assert setup.client.patch('/company-knowledge/documents/' + row['id'], json={'confidentiality': 'secret'}).status_code == 200
    assert setup.client.post('/company-knowledge/access-requests/' + request['id'] + '/decision', json={'decision': 'approved'}).status_code == 403
    setup.user.role = 'user'
    assert setup.client.get('/company-knowledge/access-requests/mine').json()['requests'] == []
