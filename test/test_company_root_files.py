"""Root placement, version-family relocation and permission-bound confirmations."""
from datetime import datetime, timedelta
import pytest
from sqlalchemy import select

from test_company_workspace import setup, upload, project, stored_original
from company_catalog import CompanyDocument, CompanyProject, CompanyFolder, backfill_company_projects


def ready(state, row, **values):
    with state.db() as db:
        doc = db.get(CompanyDocument, row['id'])
        doc.state, doc.cloud_id = 'ready', 'cloud-' + doc.id
        for key, value in values.items():
            setattr(doc, key, value)
        db.commit()


def preview(state, row, **target):
    return state.client.post('/company-knowledge/documents/' + row['id'] + '/move-preview', json=target)


def move(state, row, **target):
    response = preview(state, row, **target)
    assert response.status_code == 200, response.text
    return state.client.post('/company-knowledge/documents/' + row['id'] + '/move', json=target | {'confirmation': response.json()['confirmation']})


def test_root_upload_stays_root_and_defaults_shared_without_fake_project(setup):
    row = upload(setup, root='true').json()
    assert row['is_root'] == 1 and row['knowledge_project_id'] == '' and row['inherits_project'] == 0
    assert row['confidentiality'] == 'internal' and row['visibility'] == 'members'
    for _ in range(2):
        assert setup.client.get('/company-knowledge/projects').json()['projects'] == []
    mine = setup.client.get('/company-knowledge/my-projects').json()
    assert mine['project_count'] == 0 and mine['root_document_count'] == mine['document_count'] == 1
    setup.user.username, setup.user.id = 'bob', 2
    found = setup.client.get('/company-knowledge/documents').json()['documents'][0]
    assert found['can_read'] and not found['can_manage'] and found['is_root'] == 1
    assert preview(setup, row).status_code == 403
    assert upload(setup, root='true', project='fake').status_code == 422
    setup.user.username, setup.user.id = 'alice', 1
    assert setup.client.patch('/company-knowledge/documents/' + row['id'], json={'project':'fake'}).status_code == 422


def test_move_all_versions_preserves_original_and_index_and_inherits_then_retains_acl(setup):
    rows = [upload(setup, root='true', payload=value).json() for value in (b'version one', b'version two')]
    for row in rows:
        ready(setup, row)
    target = project(setup, '单独授权项目', visibility='restricted', readers=['bob'], tags=['归档'])
    folder = setup.client.post('/company-knowledge/projects/' + target['id'] + '/folders', json={'name':'子目录'}).json()
    response = preview(setup, rows[-1], project_id=target['id'], folder_id=folder['id'])
    assert response.json()['version_count'] == 2 and response.json()['access_changes']
    result = move(setup, rows[-1], project_id=target['id'], folder_id=folder['id'])
    assert result.status_code == 200 and result.json()['moved_version_count'] == 2
    with setup.db() as db:
        for row in rows:
            doc = db.get(CompanyDocument,row['id'])
            assert (doc.knowledge_project_id, doc.folder_id, doc.is_root, doc.inherits_project) == (target['id'],folder['id'],0,1)
            assert doc.readers == ['bob'] and doc.visibility == 'restricted' and doc.tags == ['归档']
            assert doc.cloud_id == 'cloud-' + doc.id and doc.state == 'ready'
    assert stored_original(setup, rows[0]['id']) == b'version one'
    assert move(setup, rows[-1]).status_code == 200
    assert setup.client.get('/company-knowledge/projects').status_code == 200
    with setup.db() as db:
        for row in rows:
            doc=db.get(CompanyDocument,row['id'])
            assert doc.is_root == 1 and not doc.knowledge_project_id and not doc.project and not doc.folder_id
            assert doc.visibility == 'restricted' and doc.readers == ['bob'] and doc.inherits_project == 0
    events=setup.client.get('/company-knowledge/audit-events',params={'document_id':rows[0]['id']}).json()['events']
    assert sum(e['action']=='document.move' for e in events)==2
    setup.user.username, setup.user.id='charlie',3
    assert not setup.client.get('/company-knowledge/documents').json()['documents'][0]['can_read']


def test_stale_confirmation_missing_confirmation_and_collision_do_not_move(setup):
    row=upload(setup,root='true').json();ready(setup,row)
    target=project(setup,'目标')
    token=preview(setup,row,project_id=target['id']).json()['confirmation']
    assert setup.client.patch('/company-knowledge/projects/'+target['id'],json={'name':'目标','visibility':'restricted'}).status_code==200
    path='/company-knowledge/documents/'+row['id']+'/move'
    assert setup.client.post(path,json={'project_id':target['id'],'confirmation':token}).status_code==409
    assert setup.client.post(path,json={'project_id':target['id']}).status_code==409
    other=upload(setup,project_id=target['id']).json();ready(setup,other)
    assert preview(setup,row,project_id=target['id']).status_code==409
    with setup.db() as db:
        assert db.get(CompanyDocument,row['id']).is_root==1


def test_processing_foreign_folder_cross_collection_and_notes_are_rejected(setup):
    row=upload(setup,root='true').json()
    target=project(setup,'目标')
    assert preview(setup,row,project_id=target['id']).status_code==409
    ready(setup,row,lease_until=datetime.utcnow()+timedelta(minutes=1))
    assert preview(setup,row,project_id=target['id']).status_code==409
    ready(setup,row,lease_until=None)
    case=project(setup,'经验',category='项目经验')
    assert preview(setup,row,project_id=case['id']).status_code==422
    folder=setup.client.post('/company-knowledge/projects/'+case['id']+'/folders',json={'name':'目录'}).json()
    assert preview(setup,row,project_id=target['id'],folder_id=folder['id']).status_code==404
    assert preview(setup,row,folder_id=folder['id']).status_code==422
    ready(setup,row,note_id='note')
    assert preview(setup,row,project_id=target['id']).status_code==422


def test_secret_stays_secret_on_move_out_and_media_metadata_reindexes(setup):
    setup.user.role='admin'
    target=project(setup,'机密',confidentiality='secret',visibility='restricted')
    row=upload(setup,project_id=target['id']).json();ready(setup,row)
    response=move(setup,row)
    assert response.status_code==200
    assert response.json()['document']['confidentiality']=='secret'
    setup.user.role='user';setup.user.username='bob';setup.user.id=2
    assert not setup.client.get('/company-knowledge/documents').json()['documents']
    setup.user.role='admin';setup.user.username='alice';setup.user.id=1
    media=upload(setup,root='true',name='sample.mp3',payload=b'ID3test',description='人工说明').json();ready(setup,media)
    internal=project(setup,'音频项目',tags=['音频'])
    assert preview(setup,media,project_id=internal['id']).json()['reindex_required']
    before=len(setup.scheduled)
    response=move(setup,media,project_id=internal['id'])
    assert response.status_code==200 and response.json()['document']['state']=='queued'
    assert setup.scheduled[before:]==[media['id']]
    with setup.db() as db:
        doc=db.get(CompanyDocument,media['id'])
        assert not doc.cloud_id and doc.stale_cloud_id=='cloud-'+doc.id
