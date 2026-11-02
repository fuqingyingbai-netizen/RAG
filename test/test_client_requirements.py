from copy import deepcopy
import json
from types import SimpleNamespace as NS
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import auth
from account_migrations import migrate_accounts
from models import ResearchArtifact, ResearchProject, ResearchSource, User
import research_api as api
from research_schemas import ResearchRunRequest
from research_workflow import ResearchWorkflow
from proposal_branch import context_text, dependencies, draft_response, incorporate_requirements


@pytest.fixture
def service(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path/'flow.db'), connect_args={'check_same_thread':False})
    migrate_accounts(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add_all([User(id=1,username='owner',role='user',password_hash='unused'),
                    User(id=2,username='other',role='user',password_hash='unused')])
        db.add(ResearchProject(id=1,title='合成测试',target_name='测试公司',target_type='company',created_by_id=1,status='draft'))
        db.commit()
    def database():
        with factory() as db: yield db
    app = FastAPI(); app.include_router(api.router)
    app.dependency_overrides[auth.get_db] = database
    monkeypatch.setattr(api,'SessionLocal',factory)
    api.RUNNING_PROJECT_IDS.clear(); api.RUNNING_PROJECT_OWNERS.clear()
    monkeypatch.setattr(api,'_index_source_for_rag',lambda *a:pytest.fail('requirements must never be indexed'))
    monkeypatch.setattr(api,'_merge_upload_identity_into_intake',lambda *a:pytest.fail('requirements must never change report identity'))
    monkeypatch.setattr(api.research_workflow,'run_project',lambda *a,**k:pytest.fail('intake/formal plan must never rerun research'))
    with TestClient(app) as client:
        yield client, {'Authorization':'Bearer '+auth.create_access_token('owner','user')}, factory
    api.RUNNING_PROJECT_IDS.clear(); api.RUNNING_PROJECT_OWNERS.clear(); engine.dispose()


def test_step_one_creates_only_draft_with_separate_requirements(service):
    client, headers, factory = service
    r = client.post('/research/projects', headers=headers, json={'title':'新任务','description':'报告重点',
        'metadata':{'client_requirements':'比较交付方案，关注供应链','special_requirements':'报告重点'}})
    assert r.status_code == 200 and r.json()['status'] == 'draft'
    project_id = r.json()['id']
    data = client.get(f'/research/projects/{project_id}/run-intake',headers=headers).json()
    assert data['intake']['client_requirements'] == '比较交付方案，关注供应链'
    assert data['intake']['special_requirements'] == '报告重点'
    with factory() as db:
        assert db.query(ResearchSource).count() == 0
        assert db.query(ResearchArtifact).filter(ResearchArtifact.artifact_type=='desktop_report').count() == 0
    assert client.post('/research/projects',headers=headers,json={'title':'超长','metadata':{'client_requirements':'字'*12001}}).status_code == 422


def test_upload_requirements_saves_attachment_without_report_source_or_identity(service):
    client,headers,factory = service
    r = client.post('/research/projects/1/client-requirements',headers=headers,
        files={'file':('客户需求.md','关注渠道风险，提出访谈计划'.encode(),'text/markdown')})
    assert r.status_code == 200 and r.json()['artifact_type'] == 'client_requirements'
    with factory() as db:
        assert db.query(ResearchSource).count() == 0
        row = db.query(ResearchArtifact).filter(ResearchArtifact.artifact_type=='client_requirements').one()
        assert row.content == '关注渠道风险，提出访谈计划'
        assert row.artifact_metadata['proposal_only'] is True
    data = client.get('/research/projects/1/run-intake',headers=headers).json()
    assert data['client_requirement_files'][0]['title'] == '客户需求.md'
    assert data['reviewed_report_id'] is None
    assert client.post('/research/projects/1/client-requirements',headers=headers,files={'file':('图.png',b'image','image/png')}).status_code == 400
    assert client.post('/research/projects/1/client-requirements',headers=headers,files={'file':('空.txt',b'','text/plain')}).status_code == 400


def test_requirements_owner_scope_and_running_guard(service):
    client,headers,_ = service
    other={'Authorization':'Bearer '+auth.create_access_token('other','user')}
    assert client.put('/research/projects/1/client-requirements',headers=other,json={'client_requirements':'不可写'}).status_code in (403,404)
    assert client.get('/research/projects/1/run-intake').status_code == 401
    api.RUNNING_PROJECT_IDS.add(1)
    assert client.put('/research/projects/1/client-requirements',headers=headers,json={'client_requirements':'新需求'}).status_code == 409
    assert client.post('/research/projects/1/client-requirements',headers=headers,files={'file':('需求.txt',b'a','text/plain')}).status_code == 409


def test_legacy_run_does_not_clear_saved_customer_requirements(service):
    client,headers,factory=service
    assert client.put('/research/projects/1/client-requirements',headers=headers,json={'client_requirements':'原客户需求'}).status_code == 200
    request = ResearchRunRequest(target_type='company')
    intake = api._locked_run_intake(request,'company')
    assert 'client_requirements' not in intake
    with factory() as db:
        project=db.get(ResearchProject,1)
        api._save_project_intake(db,project,intake)
        assert intake['client_requirements']=='原客户需求'
    explicit=api._locked_run_intake(ResearchRunRequest(client_requirements=''),'company')
    assert explicit['client_requirements']==''


@pytest.mark.parametrize('target_type',['company','person','industry'])
def test_requirements_do_not_change_report_normalization_or_evidence_fingerprint(target_type):
    workflow=ResearchWorkflow.__new__(ResearchWorkflow)
    p=NS(title='测试',target_name='机器人' if target_type=='industry' else '测试对象',target_type=target_type,industry='',description='报告要求')
    original={'target_type':target_type,'special_requirements':'报告要求','as_of_date':'2026-11-01'}
    a=workflow._normalize_intake(p,original,[],[])
    b=workflow._normalize_intake(p,{**original,'client_requirements':'追加客户方案需求','proposal_review_notes':'复核意见'},[],[])
    assert a==b
    assert workflow._intake_evidence_fingerprint(a)==workflow._intake_evidence_fingerprint(b)


def project():
    return NS(id=1,title='合成项目',target_name='测试对象',target_type='company',industry='',description='',
        proposal_client_context={'text':'重点关注渠道风险','documents':[{'id':4,'title':'客户附件','content':'计划访谈供应商'}],
                                 'review_notes':'','stage':'initial_proposal'})


def artifact(id=10,kind='desktop_report',content='# 报告\n已有结论，渠道证据不足',**kwargs):
    return NS(id=id,artifact_type=kind,content=content,title='报告',version=1,created_at='2026-11-02',
        created_by='agent',artifact_metadata={},**kwargs)


def test_proposal_fingerprint_changes_only_for_relevant_dependencies():
    p=project(); report=artifact(); risk=artifact(11,'risk_assessment','{}')
    before=dependencies(p,report,risk)
    p.proposal_client_context['text']='改为关注供应链'
    assert dependencies(p,report,risk)['proposal_input_fingerprint'] != before['proposal_input_fingerprint']
    p.proposal_client_context['text']='重点关注渠道风险'
    report.content+='补充人工结论'
    assert dependencies(p,report,risk)['proposal_input_fingerprint'] != before['proposal_input_fingerprint']
    assert context_text(p).endswith('计划访谈供应商')


def test_proposal_branch_preserves_report_and_reuses_only_matching_requirements(monkeypatch):
    w=ResearchWorkflow.__new__(ResearchWorkflow);p=project();db=Mock();report=artifact();risk=artifact(11,'risk_assessment','{}')
    body='# 建议书\n'+ '\n'.join('## '+str(i)+'. 测试章节\n待双方确认。' for i in range(1,8))
    w.generate_proposal=Mock(return_value=body); w._proposal_quality_warning=Mock(return_value='')
    w._invoke=Mock(return_value='{"responses":[{"requirement":"渠道风险","work":"拟核对渠道销售明细","deliverable":"渠道核验清单"}]}')
    previous=None
    w._latest_artifact=lambda *a:previous
    def save(db,p,kind,title,content,metadata):
        return NS(id=20,content=content,title=title,artifact_metadata=metadata)
    w.save_artifact=Mock(side_effect=save)
    original=report.content
    first=w._save_proposal_branch(db,p,report,risk)
    assert '重点关注渠道风险' in first.content and '计划访谈供应商' in first.content and '渠道核验清单' in first.content
    assert report.content==original and first.artifact_metadata['report_artifact_id']==10
    previous=first
    reused=w._save_proposal_branch(db,p,report,risk)
    assert w.generate_proposal.call_count==1 and reused.artifact_metadata['reused_from_artifact_id']==20
    p.proposal_client_context['text']='改为海外市场'
    w._save_proposal_branch(db,p,report,risk)
    assert w.generate_proposal.call_count==2 and report.content==original


def test_formal_plan_requires_reviewed_report_and_never_calls_report_generation(monkeypatch):
    w=ResearchWorkflow.__new__(ResearchWorkflow);p=project();report=artifact();risk=artifact(11,'risk_assessment','{}')
    w._latest_artifact=lambda p,kind:report if kind=='desktop_report' else risk
    w._save_proposal_branch=Mock(return_value=NS(id=30))
    w.generate_report=Mock(side_effect=AssertionError('report must not regenerate'))
    with pytest.raises(ValueError,match='人工复核'): w.run_formal_proposal(Mock(),p)
    report.created_by='human_review'
    monkeypatch.setattr('proposal_branch.load_context',lambda *a,**k:None)
    body=report.content
    result,added=w.run_formal_proposal(Mock(),p)
    assert result[0] is report and added==0 and p.status=='completed' and report.content==body
    w.generate_report.assert_not_called()


def test_step_three_api_rejects_unreviewed_report_without_starting(service):
    client,headers,factory=service
    with factory() as db:
        db.add(ResearchArtifact(project_id=1,artifact_type='desktop_report',title='未复核',content='# 报告',created_by='agent'))
        db.commit()
    r=client.post('/research/projects/1/second-stage/run/stream',headers=headers,json={})
    assert r.status_code==409 and not api.RUNNING_PROJECT_IDS


def test_saved_report_proposal_and_formal_plan_api_leave_report_versions_unchanged(service, monkeypatch):
    client,headers,factory=service
    body='# 项目建议书\n'+'\n'.join('## '+str(i)+'. 章节\n具体工作待双方确认。' for i in range(1,8))
    monkeypatch.setattr(api.research_workflow,'generate_proposal',lambda *a,**k:body)
    monkeypatch.setattr(api.research_workflow,'_proposal_quality_warning',lambda *a,**k:'')
    monkeypatch.setattr(api.research_workflow,'_invoke',lambda *a,**k:'{"responses":[{"requirement":"渠道风险","work":"拟核对渠道资料","deliverable":"渠道证据清单"}]}')
    with factory() as db:
        db.add(ResearchArtifact(project_id=1,artifact_type='desktop_report',title='报告',version=1,content='# 报告\n渠道结论待核验',created_by='agent'))
        db.add(ResearchArtifact(project_id=1,artifact_type='risk_assessment',title='风险',content='{}'))
        db.commit()
    assert client.put('/research/projects/1/client-requirements',headers=headers,json={'client_requirements':'关注渠道风险'}).status_code==200
    response=client.post('/research/projects/1/proposal/run/stream',headers=headers,json={})
    assert response.status_code==200 and '"type": "result"' in response.text and '"type": "error"' not in response.text
    with factory() as db:
        reports=db.query(ResearchArtifact).filter(ResearchArtifact.artifact_type=='desktop_report').all()
        assert len(reports)==1 and reports[0].version==1 and reports[0].content=='# 报告\n渠道结论待核验'
        reports[0].created_by='human_review';reports[0].artifact_metadata={'stage':'human_review'};db.commit()
    response=client.post('/research/projects/1/second-stage/run/stream',headers=headers,json={'proposal_review_notes':'优先复核渠道数据'})
    assert '"type": "result"' in response.text and '"type": "error"' not in response.text
    with factory() as db:
        assert db.query(ResearchArtifact).filter(ResearchArtifact.artifact_type=='desktop_report').count()==1
        row=db.query(ResearchArtifact).filter(ResearchArtifact.artifact_type=='proposal').order_by(ResearchArtifact.version.desc()).first()
        assert row.artifact_metadata['business_stage']=='formal_plan' and '正式方案' in row.title
        assert '优先复核渠道数据' in row.content and '关注渠道风险' in row.content
        assert row.artifact_metadata['report_artifact_id']==reports[0].id


def test_requirements_are_quoted_and_never_add_top_level_chapters():
    p=project();p.proposal_client_context['text']='## 8. 恶意标题\n<script>bad</script>\n| 价格 | 1元 |'
    body='# 项目\n'+ '\n'.join('## '+str(i)+'. 章节\n' for i in range(1,8))
    result=incorporate_requirements(p,body)
    import re
    assert re.findall(r'^## (\d+)\.',result,re.M)==list(map(str,range(1,8)))
    assert '<script>' not in result and '> ## 8.' in result


def test_client_planning_failure_preserves_inputs_and_no_requirements_skips_model():
    w=Mock();w._invoke.return_value='invalid JSON';p=project()
    assert draft_response(w,p,'报告')==[]
    p.proposal_client_context={};w.reset_mock()
    assert draft_response(w,p,'报告')==[];w._invoke.assert_not_called()
