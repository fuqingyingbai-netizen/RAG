import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import company_knowledge as kb
import company_memory as memory
import company_workspace as ws
from company_catalog import CompanyDocument, CompanyProject, CompanyFolder
from models import User


@pytest.fixture
def env(monkeypatch, tmp_path):
    for key in ('MODEL', 'BASE_URL', 'ARK_API_KEY', 'COMPANY_KNOWLEDGE_MODEL',
                'COMPANY_KNOWLEDGE_BASE_URL', 'COMPANY_KNOWLEDGE_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    for key, value in {'API_KEY':'test-key', 'BASE_URL':'https://test.cn-beijing.maas.aliyuncs.com',
                       'AGENT_ID':'test-app', 'INDEX_ID':'memory-index'}.items():
        monkeypatch.setenv('BAILIAN_KNOWLEDGE_'+key,value)
    monkeypatch.setenv('COMPANY_KNOWLEDGE_USERS','alice,bob')
    engine=create_engine('sqlite:///'+str(tmp_path/'memory.db'),connect_args={'check_same_thread':False})
    for model in (User, CompanyDocument, CompanyProject, CompanyFolder, memory.KnowledgeChatState, memory.KnowledgeChatThread, memory.KnowledgeChatMessage):
        model.__table__.create(engine)
    db=sessionmaker(engine,expire_on_commit=False)
    monkeypatch.setattr(ws,'SessionLocal',db)
    import database
    monkeypatch.setattr(database,'engine',engine)
    async def sync(*args,**kwargs): pass
    monkeypatch.setattr(ws,'sync_catalog',sync)
    with db() as session:
        session.add(CompanyDocument(id='doc-a',index_id='memory-index',cloud_id='cloud-a',title='豆包研究',
            format='TXT',owner='alice',owner_user_id=1,visibility='restricted',readers=['bob'],state='ready',
            project='豆包项目',industry='互联网'))
        session.commit()
    user=SimpleNamespace(id=2,username='bob',role='user')
    app=FastAPI();app.include_router(kb.router)
    app.dependency_overrides[kb.get_current_user]=lambda:user
    with TestClient(app) as client:
        yield SimpleNamespace(client=client,user=user,db=db)
    engine.dispose()


def create(env,ids=None):
    response=env.client.post('/company-knowledge/conversations',json={'document_ids':ids or ['doc-a']})
    assert response.status_code==201,response.text
    return response.json()['session_id']


def add_experience(env):
    with env.db() as db:
        db.add(CompanyDocument(id='experience-a',index_id='memory-index',cloud_id='experience-cloud',title='现场手稿照片',
            format='PNG',owner='bob',owner_user_id=2,visibility='members',state='ready',category='手稿笔记',
            project='现场经验',industry='内部实践'))
        db.commit()


def test_collections_reject_cross_collection_ids_and_personal_scopes(env):
    add_experience(env)
    for scope,expected in [('accessible',{'cloud-a'}),('experience',{'experience-cloud'}),('my-experience',{'experience-cloud'}),('my-projects',set())]:
        cfg={'index_id':'memory-index'}
        assert set(asyncio.run(ws.prepare_scope(cfg,env.user,[],scope)))==expected
    for scope,ids in [('accessible',['experience-a']),('experience',['doc-a']),('experience',['experience-a','doc-a'])]:
        response=env.client.post('/company-knowledge/conversations',json={'scope':scope,'document_ids':ids})
        assert response.status_code==403,response.text


def test_conversation_histories_and_active_threads_are_collection_isolated(env):
    add_experience(env)
    library=create(env)
    response=env.client.post('/company-knowledge/conversations',json={'scope':'experience','document_ids':['experience-a']})
    assert response.status_code==201,response.text
    experience=response.json()['session_id']
    lib=env.client.get('/company-knowledge/conversations?collection=library').json()
    exp=env.client.get('/company-knowledge/conversations?collection=experience').json()
    assert lib['session_id']==library and [s['id'] for s in lib['sessions']]==[library]
    assert exp['session_id']==experience and [s['id'] for s in exp['sessions']]==[experience]
    assert exp['scope']=='experience' and exp['collection']=='experience'
    forged=env.client.post('/company-knowledge/chat/stream',json={'message':'总结经验','session_id':experience,'scope':'accessible','document_ids':['experience-a']})
    assert forged.status_code==409
    deleted=env.client.delete('/company-knowledge/conversations/'+experience).json()
    assert deleted['collection']=='experience' and deleted['session_id'] is None and deleted['sessions']==[]


def test_experience_retrieval_filters_cloud_and_does_not_ingest_library_history(env,monkeypatch):
    add_experience(env)
    requests=[]
    def handler(request):
        body=json.loads(request.content);requests.append((request.url.path,body))
        if request.url.path.endswith('/app/get'):
            return httpx.Response(200,json={'data':{'agent_details':[{'agent_version':'1','agent_config':{'agent_model':'test'}}]}})
        if request.url.path.endswith('/retrieve'):
            return httpx.Response(200,json={'data':{'nodes':[
                {'metadata':{'doc_id':'cloud-a','content':'LIBRARY_PRIVATE_EVIDENCE','doc_name':'资料库原件'}},
                {'metadata':{'doc_id':'experience-cloud','content':'EXPERIENCE_ONLY_EVIDENCE','doc_name':'现场手稿照片'}}]}})
        frames=[{'choices':[{'delta':{'content':'经验沉淀内容 [id_1]'},'finish_reason':None}]},{'choices':[{'delta':{},'finish_reason':'stop'}]}]
        return httpx.Response(200,text=''.join('data: '+json.dumps(f,ensure_ascii=False)+'\n\n' for f in frames))
    original=httpx.AsyncClient
    monkeypatch.setattr(kb.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    response=env.client.post('/company-knowledge/conversations',json={'scope':'experience','document_ids':[]})
    assert response.status_code==201
    sid=response.json()['session_id']
    answer=env.client.post('/company-knowledge/chat/stream',json={'message':'总结现场手稿','session_id':sid,'scope':'experience','document_ids':[],'request_id':'experience-turn'})
    assert answer.status_code==200 and '"type": "saved"' in answer.text
    retrieval=next(body for path,body in requests if path.endswith('/retrieve'))
    assert retrieval['search_filters']==[{'doc_id':['experience-cloud']}]
    generated=[body for path,body in requests if path.endswith('/chat/completions') and body.get('stream')]
    assert generated and 'LIBRARY_PRIVATE_EVIDENCE' not in json.dumps(generated)
    restored=env.client.get('/company-knowledge/conversations?collection=experience').json()
    assert restored['messages'][-1]['references'][0]['local_id']=='experience-a'
    assert env.client.get('/company-knowledge/conversations?collection=library').json()['messages']==[]


def call(env,sid,message='总结豆包业务布局',request_id='one',**extra):
    return env.client.post('/company-knowledge/chat/stream',json={'session_id':sid,'request_id':request_id,
        'document_ids':['doc-a'],'message':message,**extra})


def upstream(monkeypatch, rewrite='豆包的商业化情况', summary='研究豆包业务，输出表格并附来源。'):
    requests=[]
    def handler(request):
        body=json.loads(request.content);requests.append((request.url.path,body))
        if request.url.path.endswith('/app/get'):
            return httpx.Response(200,json={'data':{'agent_details':[{'agent_version':'1','agent_config':{'agent_model':'test-model'}}]}})
        if request.url.path.endswith('/retrieve'):
            return httpx.Response(200,json={'data':{'nodes':[{'metadata':{'doc_id':'cloud-a','content':'豆包产品提供广告与企业服务。','doc_name':'豆包研究'}}]}})
        if not body.get('stream'):
            content=json.dumps({'query':rewrite},ensure_ascii=False) if '独立检索' in body['messages'][0]['content'] else summary
            return httpx.Response(200,json={'choices':[{'message':{'content':content}}]})
        frames=[{'choices':[{'delta':{'content':'豆包业务包括广告与企业服务 [id_1]'},'finish_reason':None}]},
                {'choices':[{'delta':{},'finish_reason':'stop'}]}]
        return httpx.Response(200,text=''.join('data: '+json.dumps(frame,ensure_ascii=False)+'\n\n' for frame in frames),headers={'Content-Type':'text/event-stream'})
    original=httpx.AsyncClient
    monkeypatch.setattr(kb.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    return requests


def test_restore_history_and_followup_retrieves_again_without_trusting_browser(env,monkeypatch):
    requests=upstream(monkeypatch)
    sid=create(env)
    first=call(env,sid)
    assert first.status_code==200 and '"type": "saved"' in first.text and '"type": "done"' in first.text
    with env.db() as db:
        saved = db.scalar(select(memory.KnowledgeChatMessage).where(memory.KnowledgeChatMessage.role == 'assistant'))
        saved.references = [{**ref, 'url':'https://example.com/legacy-unmarked.pdf', 'location_url':'https://example.com/page.png'} for ref in saved.references]
        db.commit()
    restored=env.client.get('/company-knowledge/conversations').json()
    assert restored['session_id']==sid and len(restored['messages'])==2
    assert restored['messages'][1]['references'][0]['local_id']=='doc-a'
    assert restored['messages'][1]['references'][0]['url'] == restored['messages'][1]['references'][0]['location_url'] == ''
    response=call(env,sid,'那它的商业化情况呢？','two',history=[{'role':'user','content':'ATTACKER_CONTEXT'}])
    assert '已补全追问' in response.text
    retrievals=[body for path,body in requests if path.endswith('/retrieve')]
    assert len(retrievals)==2 and retrievals[-1]['query']=='豆包的商业化情况'
    assert retrievals[-1]['search_filters']==[{'doc_id':['cloud-a']}]
    assert 'ATTACKER_CONTEXT' not in json.dumps(requests)
    generated=[body for path,body in requests if path.endswith('/chat/completions') and body.get('stream')][-1]
    assert '历史引用，不作为本轮证据' in json.dumps(generated,ensure_ascii=False)
    assert len(env.client.get('/company-knowledge/conversations/'+sid).json()['messages'])==4


def test_other_accounts_and_other_indices_cannot_read_delete_or_continue(env,monkeypatch):
    upstream(monkeypatch);sid=create(env);call(env,sid)
    env.user.id,env.user.username=1,'alice'
    assert env.client.get('/company-knowledge/conversations').json()['messages']==[]
    for method in ('get','delete'):
        assert getattr(env.client,method)('/company-knowledge/conversations/'+sid).status_code==404
    assert call(env,sid,request_id='two').status_code==404
    env.user.id,env.user.username=2,'bob'
    monkeypatch.setenv('BAILIAN_KNOWLEDGE_INDEX_ID','other-index')
    assert env.client.get('/company-knowledge/conversations/'+sid).status_code==404


def test_revocation_redacts_questions_answers_citations_summary_and_title(env,monkeypatch):
    requests=upstream(monkeypatch);sid=create(env);call(env,sid)
    with env.db() as db:
        thread=db.get(memory.KnowledgeChatThread,sid)
        thread.summary='SECRET_SUMMARY';thread.summary_dependencies=dict(thread.dependencies)
        doc=db.get(CompanyDocument,'doc-a');doc.readers=[];db.commit()
    result=env.client.get('/company-knowledge/conversations/'+sid).json()
    assert result['scope_unavailable'] and all(row['redacted'] for row in result['messages'])
    assert all(not row['references'] for row in result['messages'])
    assert '豆包' not in json.dumps(result,ensure_ascii=False) and 'SECRET_SUMMARY' not in json.dumps(result)
    assert call(env,sid,'那它呢','two').status_code==403
    assert len([path for path,_ in requests if path.endswith('/retrieve')])==1


@pytest.mark.parametrize('level', ['confidential', 'secret'])
def test_classification_ceiling_redacts_old_granted_history_and_citations(env,monkeypatch,level):
    requests=upstream(monkeypatch);sid=create(env);call(env,sid)
    with env.db() as db:
        doc=db.get(CompanyDocument,'doc-a')
        # Preserve the owner/grant and all content; only classification changes.
        doc.confidentiality=level
        db.commit()
    result=env.client.get('/company-knowledge/conversations/'+sid).json()
    assert result['scope_unavailable'] and all(row['redacted'] for row in result['messages'])
    assert all(not row['references'] for row in result['messages'])
    assert '豆包' not in json.dumps(result,ensure_ascii=False)
    assert call(env,sid,'继续','classification-ceiling').status_code==403
    assert len([path for path,_ in requests if path.endswith('/retrieve')])==1


def test_document_update_invalidates_history_and_scope_cannot_be_forged(env,monkeypatch):
    upstream(monkeypatch);sid=create(env);call(env,sid)
    with env.db() as db:
        doc=db.get(CompanyDocument,'doc-a');doc.version=2;db.commit()
    assert all(row['redacted'] for row in env.client.get('/company-knowledge/conversations/'+sid).json()['messages'])
    assert call(env,sid,'next','two',document_ids=[]).status_code==409
    assert '"type": "done"' in call(env,sid,'重新总结豆包业务布局','three').text
    restored=env.client.get('/company-knowledge/conversations/'+sid).json()
    assert restored['sessions'][0]['title']=='历史研究（部分资料不可用）'
    assert all(row['redacted'] for row in restored['messages'][:2])
    assert all(not row['redacted'] for row in restored['messages'][-2:])


def test_concurrent_duplicate_and_deleted_session_never_resurrects(env):
    sid=create(env)
    cfg=kb.settings();cfg['allowed_documents']={'cloud-a':{'id':'doc-a'}}
    token,plan,deps=memory.begin_turn(env.user,cfg,sid,'one','问题')
    with pytest.raises(Exception) as duplicate:
        memory.begin_turn(env.user,cfg,sid,'one','问题')
    assert duplicate.value.status_code==409
    with pytest.raises(Exception) as concurrent:
        memory.begin_turn(env.user,cfg,sid,'two','问题')
    assert concurrent.value.status_code==409
    assert env.client.delete('/company-knowledge/conversations/'+sid).status_code==200
    context={'summary':'','through':0,'summary_dependencies':{}}
    assert not memory.finish_turn(env.user,cfg,sid,token,'one','LATE_ANSWER',[],context,deps,True)
    assert env.client.get('/company-knowledge/conversations').json()['sessions']==[]


def test_expired_worker_can_be_recovered_without_old_answer_overwriting(env):
    sid=create(env);cfg=kb.settings();cfg['allowed_documents']={'cloud-a':{'id':'doc-a'}}
    token,_,deps=memory.begin_turn(env.user,cfg,sid,'old','旧问题')
    with env.db() as db:
        db.get(memory.KnowledgeChatThread,sid).busy_until=datetime.utcnow()-timedelta(seconds=1);db.commit()
    newtoken,_,_=memory.begin_turn(env.user,cfg,sid,'new','新问题')
    assert token!=newtoken
    assert not memory.finish_turn(env.user,cfg,sid,token,'old','旧答案',[],{'summary':'','through':0,'summary_dependencies':{}},deps,True)
    rows=env.client.get('/company-knowledge/conversations/'+sid).json()['messages']
    assert rows[0]['status']=='interrupted'


def test_summary_compresses_context_without_deleting_originals_and_failure_does_not_advance(env,monkeypatch):
    upstream(monkeypatch);sid=create(env)
    with env.db() as db:
        deps={'doc-a':memory.fingerprint(db.get(CompanyDocument,'doc-a'))}
        for n in range(44):
            db.add(memory.KnowledgeChatMessage(thread_id=sid,request_id=str(n),role='user' if n%2==0 else 'assistant',
                content=('研究豆包业务布局，结果附引用。' if n%2==0 else '旧答案不能作为本轮依据。')*30,dependencies=deps))
        db.commit()
    response=call(env,sid,request_id='summary-turn')
    assert '"status": "compressed"' in response.text or '"status": "compressed_partial"' in response.text
    with env.db() as db:
        thread=db.get(memory.KnowledgeChatThread,sid)
        assert thread.summary and thread.summary_through>0
        assert len(list(db.scalars(select(memory.KnowledgeChatMessage).where(memory.KnowledgeChatMessage.thread_id==sid))))==46
    plan={'summary':'保留摘要','through':3,'summary_dependencies':{},'invalidated':False,
          'rows':[{'id':n,'role':'user','content':'研究对象'*100,'dependencies':{}} for n in range(4,50)]}
    async def fail(*args,**kwargs):raise TimeoutError()
    monkeypatch.setattr(memory,'complete',fail)
    context=asyncio.run(memory.prepare_context({},plan))
    assert context['status']=='deferred' and context['through']==3 and context['summary']=='保留摘要'


def test_pagination_and_new_thread_keep_old_messages(env):
    sid=create(env)
    with env.db() as db:
        for n in range(83):db.add(memory.KnowledgeChatMessage(thread_id=sid,request_id=str(n),role='user',content=str(n)))
        db.commit()
    page=env.client.get('/company-knowledge/conversations/'+sid).json()
    assert page['has_more'] and len(page['messages'])==80
    older=env.client.get('/company-knowledge/conversations/'+sid,params={'before_id':page['messages'][0]['id']}).json()
    assert len(older['messages'])==3 and not older['has_more']
    new=create(env)
    assert new!=sid and len(env.client.get('/company-knowledge/conversations').json()['sessions'])==2
    assert len(env.client.get('/company-knowledge/conversations/'+sid).json()['messages'])==80


def test_ambiguous_followup_failure_clarifies_without_retrieval(env,monkeypatch):
    calls=upstream(monkeypatch);sid=create(env);call(env,sid)
    async def ambiguous(*args,**kwargs):return '{"query":null}'
    monkeypatch.setattr(memory,'complete',ambiguous)
    response=call(env,sid,'那它呢','two')
    assert '未能确认' in response.text and len([p for p,_ in calls if p.endswith('/retrieve')])==1


def test_knowledge_provider_covers_summary_rewrite_and_answer_without_changing_report_settings(env, monkeypatch):
    shared={'MODEL':'report-model','BASE_URL':'https://reports.example.test/v1','ARK_API_KEY':'report-key'}
    for key,value in {**shared,'COMPANY_KNOWLEDGE_MODEL':'glm-5.2',
            'COMPANY_KNOWLEDGE_BASE_URL':'https://knowledge-relay.example.test/v1/',
            'COMPANY_KNOWLEDGE_API_KEY':'knowledge-key'}.items():
        monkeypatch.setenv(key,value)
    requests=[]
    def handler(request):
        body=json.loads(request.content);requests.append((request.url.host,request.url.path,body))
        if request.url.path.endswith('/retrieve'):
            assert request.url.host=='test.cn-beijing.maas.aliyuncs.com'
            assert request.headers['Authorization']=='Bearer test-key'
            assert body['query']=='豆包的商业化情况'
            assert body['search_filters']==[{'doc_id':['cloud-a']}]
            return httpx.Response(200,json={'data':{'nodes':[{'metadata':{
                'doc_id':'cloud-a','content':'豆包提供广告与企业服务。'}}]}})
        assert str(request.url)=='https://knowledge-relay.example.test/v1/chat/completions'
        assert request.headers['Authorization']=='Bearer knowledge-key'
        assert body['model']=='glm-5.2'
        assert body['thinking']=={'type':'disabled'} and 'enable_thinking' not in body
        if not body['stream']:
            content='{"query":"豆包的商业化情况"}' if '独立检索' in body['messages'][0]['content'] else '研究豆包业务，结果附引用。'
            return httpx.Response(200,json={'choices':[{'message':{'content':content}}]})
        frames=[{'choices':[{'delta':{'content':'广告与企业服务 [id_1]'},'finish_reason':None}]},
                {'choices':[{'delta':{},'finish_reason':'stop'}]}]
        return httpx.Response(200,text=''.join('data: '+json.dumps(f)+'\n\n' for f in frames))
    original=httpx.AsyncClient
    monkeypatch.setattr(kb.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    sid=create(env)
    with env.db() as db:
        deps={'doc-a':memory.fingerprint(db.get(CompanyDocument,'doc-a'))}
        for n in range(44):
            db.add(memory.KnowledgeChatMessage(thread_id=sid,request_id=str(n),
                role='user' if n%2==0 else 'assistant',content='研究豆包的业务布局与商业化。'*45,dependencies=deps))
        db.commit()
    response=call(env,sid,'那么它的商业化情况呢？','scoped-turn')
    assert '"type": "done"' in response.text and '广告与企业服务' in response.text
    assert '已补全追问' in response.text and '"status": "compressed' in response.text
    model_calls=[body for host,path,body in requests if path.endswith('/chat/completions')]
    assert len(model_calls)==3 and sum(bool(b['stream']) for b in model_calls)==1
    import os
    assert {key:os.environ[key] for key in shared}==shared


@pytest.mark.parametrize('failure', ['permission','timeout','invalid-json','non-object'])
def test_rewrite_service_failures_are_not_reported_as_ambiguous_questions(env,monkeypatch,failure):
    upstream(monkeypatch);sid=create(env);call(env,sid)
    async def fail(*args,**kwargs):
        if failure=='permission':raise kb.provider_error(403,provider='知识库模型')
        if failure=='timeout':raise TimeoutError()
        if failure=='non-object':return '[]'
        return 'broken JSON'
    monkeypatch.setattr(memory,'complete',fail)
    response=call(env,sid,'那么它呢？','failed-rewrite')
    assert '未能确认' not in response.text and '"type": "done"' not in response.text
    assert '"type": "error"' in response.text
    assert {'permission':'知识库模型访问权限不足','timeout':'追问补全服务响应超时',
        'invalid-json':'追问补全服务返回格式异常','non-object':'追问补全服务返回格式异常'}[failure] in response.text


def test_partial_knowledge_provider_does_not_fall_back_to_report_provider(env,monkeypatch):
    monkeypatch.setenv('COMPANY_KNOWLEDGE_MODEL','knowledge-model')
    monkeypatch.setenv('MODEL','report-model')
    monkeypatch.setenv('BASE_URL','https://report.example.test/v1')
    monkeypatch.setenv('ARK_API_KEY','report-secret')
    async def check():
        async with httpx.AsyncClient() as client:
            await kb.model_settings(client,kb.settings())
    with pytest.raises(kb.KnowledgeError,match='模型配置不完整'):
        asyncio.run(check())
