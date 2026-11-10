"""Subtree selection, current permissions, and non-blocking catalogue browsing."""
import asyncio

from company_catalog import CompanyDocument, CompanyProject, CompanyFolder, can_read, can_manage
import company_knowledge as kb
import company_workspace as ws
from test_company_workspace import setup, project


def seed(setup):
    a=project(setup, '项目甲');b=project(setup, '项目乙')
    with setup.db() as db:
        db.add_all([CompanyFolder(id='parent',project_id=a['id'],name='二级目录',parent_id=''),
                    CompanyFolder(id='child',project_id=a['id'],name='三级目录',parent_id='parent'),
                    CompanyFolder(id='sibling',project_id=a['id'],name='同级目录',parent_id='')])
        for id,pid,folder,state,visibility in [('a-root',a['id'],'','ready','members'),
            ('a-parent',a['id'],'parent','ready','members'),('a-child',a['id'],'child','ready','members'),
            ('a-sibling',a['id'],'sibling','ready','members'),('waiting',a['id'],'child','indexing','members'),
            ('locked',a['id'],'child','ready','restricted'),('b-root',b['id'],'','ready','members')]:
            db.add(CompanyDocument(id=id,index_id='test-index',title=id+'.txt',format='TXT',cloud_id='cloud-'+id,
                owner='bob' if id=='locked' else 'alice',owner_user_id=2 if id=='locked' else 1,
                project='项目甲' if pid==a['id'] else '项目乙',knowledge_project_id=pid,folder_id=folder,
                state=state,visibility=visibility,confidentiality='internal',category='项目原件',is_current=1))
        db.commit()
    return a,b


def test_selecting_parent_folder_includes_descendants_and_excludes_siblings_and_locked_files(setup):
    seed(setup)
    response=setup.client.post('/company-knowledge/selection',json={'folder_ids':['parent']})
    assert response.status_code==200
    result=response.json()
    assert set(result['document_ids'])=={'a-parent','a-child'}
    assert result['skipped_count']==1


def test_multiple_projects_union_with_file_and_folder_selections_deduplicates(setup):
    a,b=seed(setup)
    result=setup.client.post('/company-knowledge/selection',json={
        'project_ids':[a['id'],b['id']], 'folder_ids':['child'], 'document_ids':['a-child']}).json()
    assert set(result['document_ids'])=={'a-root','a-parent','a-child','a-sibling','b-root'}
    assert result['document_count']==5


def test_invalid_empty_cross_collection_or_unreadable_selection_never_means_all(setup):
    a,b=seed(setup)
    for body,status in [({},422),({'folder_ids':['missing']},403),({'document_ids':['locked']},403),
                        ({'project_ids':[a['id']],'scope':'experience'},403)]:
        assert setup.client.post('/company-knowledge/selection',json=body).status_code==status
    empty=project(setup,'空项目')
    assert setup.client.post('/company-knowledge/selection',json={'project_ids':[empty['id']]}).status_code==409


def test_permissions_are_rechecked_before_answer_after_a_selection(setup):
    a,b=seed(setup)
    assert setup.client.post('/company-knowledge/selection',json={'document_ids':['a-root']}).status_code==200
    with setup.db() as db:
        row=db.get(CompanyDocument,'a-root');row.owner='bob';row.owner_user_id=2;row.visibility='restricted';db.commit()
    response=setup.client.post('/company-knowledge/chat/stream',json={'message':'总结','document_ids':['a-root']})
    assert response.status_code==403


def test_experience_is_shared_with_members_but_management_and_unpublished_drafts_stay_owned(setup):
    p=project(setup,'共享经验',category='项目经验',visibility='restricted',readers=['charlie'])
    assert p['visibility']=='members' and p['readers']==[]
    with setup.db() as db:
        # Existing historical rows follow the same policy without rewriting originals.
        directory=db.get(CompanyProject,p['id']);directory.confidentiality='secret';directory.visibility='restricted'
        db.add(CompanyDocument(id='experience',index_id='test-index',title='已发布.txt',format='TXT',cloud_id='exp-cloud',
            owner='alice',owner_user_id=1,knowledge_project_id=p['id'],category='项目经验',
            confidentiality='secret',visibility='restricted',state='ready',is_current=1))
        db.commit()
    draft=setup.client.post('/company-knowledge/notes',json={'project_id':p['id']}).json()
    setup.user.username='bob';setup.user.id=2
    projects=setup.client.get('/company-knowledge/projects').json()['projects']
    shared=next(row for row in projects if row['id']==p['id'])
    assert shared['visibility']=='members' and not shared['can_manage']
    docs=setup.client.get('/company-knowledge/documents').json()['documents']
    shared_doc=next(row for row in docs if row['id']=='experience')
    assert shared_doc['can_read'] and not shared_doc['can_manage'] and shared_doc['confidentiality']=='internal'
    assert setup.client.post('/company-knowledge/selection',json={'scope':'experience','project_ids':[p['id']]}).json()['document_ids']==['experience']
    assert setup.client.get('/company-knowledge/notes/'+draft['id']).status_code in (403,404)
    assert setup.client.patch('/company-knowledge/projects/'+p['id'],json={'name':'越权修改'}).status_code==403


def test_local_browsing_returns_saved_rows_while_cloud_sync_is_blocked(setup,monkeypatch):
    seed(setup)
    async def check():
        started=asyncio.Event();blocked=asyncio.Event()
        async def slow(*args,**kwargs):
            started.set();await blocked.wait()
        monkeypatch.setattr(ws,'sync_catalog',slow)
        ws.last_sync.clear()
        result=await asyncio.wait_for(ws.documents(page_number=1,page_size=100,refresh=False,local_only=True,user=setup.user),1)
        assert result['total_count']==7
        await started.wait()
        task=ws.catalogue_sync_tasks['test-index'];task.cancel()
        await asyncio.gather(task,return_exceptions=True)
    asyncio.run(check())
