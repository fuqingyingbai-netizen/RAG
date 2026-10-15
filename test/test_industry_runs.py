import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database import Base
from industry_runs import RunJournal, STAGES, artifact_reference
from models import ResearchArtifact, ResearchProject, User
from research_workflow import ResearchWorkflow, WorkflowPaused


def reference(eid=1):
    return SimpleNamespace(id=eid,artifact_type='cleaned_facts',version=2,created_at='2026-10-15',
        content='{"facts":[]}',artifact_metadata={'pipeline_version':'test-v1','source_fingerprint':'abc','password':'private'})


def test_each_attempt_has_its_own_id_and_explicit_executor_limit():
    first=RunJournal(68);second=RunJournal(68,parent_run_id=first.data['run_id'])
    assert first.data['run_id']!=second.data['run_id']
    assert second.data['parent_run_id']==first.data['run_id']
    assert second.data['worker_liveness']=='not_verified'
    assert second.data['automatic_restart_recovery'] is False


def test_stage_manifest_records_content_hashes_and_reuse_without_private_payloads():
    ref=artifact_reference(reference(),{1})
    assert ref['usage']=='reused' and len(ref['content_sha256'])==64
    assert 'password' not in json.dumps(ref)
    assert artifact_reference(reference(2),{1})['usage']=='created'


def test_checkpoint_order_and_snapshot_isolation():
    journal=RunJournal(68)
    with pytest.raises(ValueError):journal.checkpoint('risk')
    journal.checkpoint('init')
    snapshot=journal.snapshot();snapshot['stages'][0]['status']='corrupt'
    assert journal.data['stages'][0]['status']=='completed'
    assert journal.data['current_stage']=='planning'


def test_parallel_model_events_are_counted_without_database_writes():
    journal=RunJournal(68)
    with ThreadPoolExecutor(max_workers=5) as pool:
        events=list(pool.map(lambda n:journal.tag_event({'type':'trace_step','stage':'llm','status':'done','timestamp':str(n)}),range(100)))
    assert journal.snapshot()['observed_event_counts']['done']==100
    assert all(e['run_id']==journal.data['run_id'] for e in events)


def test_heartbeats_do_not_advance_actual_activity():
    journal=RunJournal(68)
    journal.tag_event({'timestamp':'actual','status':'done'})
    journal.tag_event({'timestamp':'heartbeat','heartbeat':True,'status':'running'})
    assert journal.data['last_backend_event_timestamp']=='actual'


@pytest.fixture
def database(tmp_path):
    engine=create_engine(f'sqlite:///{tmp_path / "runs.sqlite"}')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user=User(username='offline-test',password_hash='unused-test-hash')
        db.add(user);db.commit()
        project=ResearchProject(title='机器人',target_name='机器人',target_type='industry',industry='机器人',created_by_id=user.id)
        db.add(project);db.commit();db.refresh(project)
        yield db,project,engine
    engine.dispose()


def fake_execution(workflow, monkeypatch, stop=None):
    def execute(db,project,*args):
        emit=args[4];checkpoint=args[-1]
        for stage in STAGES[:-1]:
            emit({'type':'trace_step','stage':stage,'status':'running','timestamp':'2026-10-15T00:00:00'})
            if stage==stop:raise RuntimeError('private API token must not be retained')
            if stage=='planning':
                artifact=ResearchArtifact(project_id=project.id,artifact_type='research_plan',title='计划',content='{}',version=1)
                db.add(artifact);db.commit()
            checkpoint(stage)
        return [],0
    monkeypatch.setattr(workflow,'_run_project_impl',execute)


def test_completed_run_survives_session_restart_and_downloads_current_database_json(database, monkeypatch):
    db,project,engine=database;workflow=ResearchWorkflow.__new__(ResearchWorkflow)
    monkeypatch.setattr('research_workflow.research_store.put_text',lambda *a:pytest.fail('Journal must not depend on object storage'))
    fake_execution(workflow,monkeypatch)
    artifacts,_=workflow.run_project(db,project,[],[])
    record=artifacts[-1];record_id=record.id
    assert record.object_key==''
    assert json.loads(record.content)['status']=='completed'
    assert json.loads(record.content)['stages'][1]['outputs'][0]['usage']=='created'
    import research_api
    monkeypatch.setattr(research_api,'_get_project',lambda *a:project)
    response=asyncio.run(research_api.download_artifact(record_id,db,SimpleNamespace()))
    assert json.loads(response.body)['status']=='completed'
    assert response.media_type.startswith('application/json')
    with Session(engine) as new_db:
        persisted=new_db.get(ResearchArtifact,record_id)
        assert json.loads(persisted.content)['stages'][-1]['name']=='proposal'
        assert persisted.artifact_metadata['run_status']=='completed'


def test_new_run_preserves_old_history_and_links_parent(database,monkeypatch):
    db,project,_=database;workflow=ResearchWorkflow.__new__(ResearchWorkflow)
    fake_execution(workflow,monkeypatch)
    first=workflow.run_project(db,project,[],[])[0][-1]
    first_body=first.content
    second=workflow.run_project(db,project,[],[])[0][-1]
    assert second.id!=first.id and second.version==first.version+1
    assert json.loads(second.content)['parent_run_id']==json.loads(first.content)['run_id']
    assert first.content==first_body


def test_failure_preserves_last_completed_stage_and_safe_error_type(database,monkeypatch):
    db,project,_=database;workflow=ResearchWorkflow.__new__(ResearchWorkflow)
    fake_execution(workflow,monkeypatch,stop='cleaning')
    with pytest.raises(RuntimeError):workflow.run_project(db,project,[],[])
    record=workflow._latest_artifact(project,'industry_run');data=json.loads(record.content)
    assert data['status']=='failed' and data['current_stage']=='cleaning'
    assert data['stages'][-2]['status']=='completed'
    assert data['error_type']=='RuntimeError' and 'private API token' not in record.content
    assert project.industry_run_id is None


def test_pause_is_persisted_separately_from_failure(database,monkeypatch):
    db,project,_=database;workflow=ResearchWorkflow.__new__(ResearchWorkflow)
    def paused(*args):raise WorkflowPaused('pause')
    monkeypatch.setattr(workflow,'_run_project_impl',paused)
    with pytest.raises(WorkflowPaused):workflow.run_project(db,project,[],[])
    assert json.loads(workflow._latest_artifact(project,'industry_run').content)['status']=='paused'


def test_company_execution_retains_existing_path_without_run_artifact(monkeypatch):
    workflow=ResearchWorkflow.__new__(ResearchWorkflow);calls=[]
    monkeypatch.setattr(workflow,'_run_project_impl',lambda *args:(calls.append(args) or ([],0)))
    assert workflow.run_project(None,SimpleNamespace(target_type='company'),[],[])==([],0)
    assert len(calls)==1


def test_journal_creation_failure_prevents_execution_and_clears_context(database,monkeypatch):
    db,project,_=database;workflow=ResearchWorkflow.__new__(ResearchWorkflow)
    def fail(*args,**kwargs):raise RuntimeError('journal unavailable')
    monkeypatch.setattr(workflow,'save_artifact',fail)
    monkeypatch.setattr(workflow,'_run_project_impl',lambda *args:pytest.fail('Unjournaled industry execution'))
    with pytest.raises(RuntimeError,match='journal unavailable'):workflow.run_project(db,project,[],[])
    assert project.industry_run_id is None


@pytest.mark.parametrize('alias',[' 行业 ','sector','目标行业'])
def test_industry_aliases_also_receive_independent_journals(database,monkeypatch,alias):
    db,project,_=database;workflow=ResearchWorkflow.__new__(ResearchWorkflow)
    fake_execution(workflow,monkeypatch)
    record=workflow.run_project(db,project,[],[],intake={'target_type':alias})[0][-1]
    assert json.loads(record.content)['status']=='completed'


def test_new_industry_outputs_are_tagged_with_run_id(database,monkeypatch):
    db,project,_=database;workflow=ResearchWorkflow.__new__(ResearchWorkflow)
    project.industry_run_id='run-test';project.industry_run_started_at='2026-10-15T00:00:00'
    monkeypatch.setattr('research_workflow.research_store.put_text',lambda *args:'test/key')
    artifact=workflow.save_artifact(db,project,'research_plan','计划','{}')
    assert artifact.artifact_metadata['run_id']=='run-test'


def test_stale_run_trace_cannot_overwrite_a_new_run_even_with_a_later_event_time(database,monkeypatch):
    import research_api
    db,project,_=database
    writes=[]
    monkeypatch.setattr(research_api.research_store,'put_text',lambda *args:(writes.append(args) or 'trace/key'))
    def event(run,start,stamp):
        return {'type':'trace_step','stage':'init','run_id':run,'run_started_at':start,'timestamp':stamp,'status':'running'}
    research_api._save_workflow_trace(db,project,[event('new','2026-10-15T02:00:00','2026-10-15T02:00:00')])
    research_api._save_workflow_trace(db,project,[event('old','2026-10-15T01:00:00','2026-10-15T03:00:00')])
    research_api._save_workflow_trace(db,project,[{'type':'trace_step','timestamp':'2026-10-15T04:00:00','status':'running'}])
    assert len(writes)==1
    record=db.query(ResearchArtifact).filter(ResearchArtifact.artifact_type=='workflow_trace').one()
    assert record.artifact_metadata['run_id']=='new'


def test_stream_trace_preserves_previous_run_and_uses_different_object_keys(database,monkeypatch):
    import research_api
    db,project,_=database;keys=[]
    monkeypatch.setattr(research_api.research_store,'put_text',lambda key,*args:(keys.append(key) or key))
    old={'type':'trace_step','stage':'init','run_id':'first','run_started_at':'2026-10-15T01:00:00',
         'timestamp':'2026-10-15T01:01:00','status':'done'}
    new={**old,'run_id':'second','run_started_at':'2026-10-15T02:00:00','timestamp':'2026-10-15T02:00:00'}
    research_api._save_workflow_trace(db,project,[old])
    research_api._save_workflow_trace(db,project,[new])
    rows=db.query(ResearchArtifact).filter(ResearchArtifact.artifact_type=='workflow_trace').order_by(ResearchArtifact.id).all()
    assert len(rows)==2 and rows[1].version==rows[0].version+1
    assert json.loads(rows[0].content)==[old]
    assert keys[0]!=keys[1]
    assert research_api._latest_workflow_trace(rows)==[new]


def test_new_run_beats_old_run_event_timestamp_and_legacy_trace_is_retained(database,monkeypatch):
    import research_api
    db,project,_=database
    monkeypatch.setattr(research_api.research_store,'put_text',lambda key,*args:key)
    # A late old-worker event must not select a previous run as current.
    old={'run_id':'first','run_started_at':'2026-10-15T01:00:00','timestamp':'2026-10-15T03:00:00'}
    new={'run_id':'second','run_started_at':'2026-10-15T02:00:00','timestamp':'2026-10-15T02:00:00'}
    research_api._save_workflow_trace(db,project,[{'timestamp':'2026-10-14T00:00:00'}])
    research_api._save_workflow_trace(db,project,[old])
    research_api._save_workflow_trace(db,project,[new])
    rows=db.query(ResearchArtifact).filter(ResearchArtifact.artifact_type=='workflow_trace').all()
    assert len(rows)==3
    assert research_api._latest_workflow_trace(rows)==[new]
