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
from company_catalog import CompanyDocument
from models import User


@pytest.fixture
def env(monkeypatch, tmp_path):
    for key, value in {'API_KEY':'test-key', 'BASE_URL':'https://test.cn-beijing.maas.aliyuncs.com',
                       'AGENT_ID':'test-app', 'INDEX_ID':'memory-index'}.items():
        monkeypatch.setenv('BAILIAN_KNOWLEDGE_'+key,value)
    monkeypatch.setenv('COMPANY_KNOWLEDGE_USERS','alice,bob')
    engine=create_engine('sqlite:///'+str(tmp_path/'memory.db'),connect_args={'check_same_thread':False})
    for model in (User, CompanyDocument, memory.KnowledgeChatState, memory.KnowledgeChatThread, memory.KnowledgeChatMessage):
        model.__table__.create(engine)
    db=sessionmaker(engine,expire_on_commit=False)
    monkeypatch.setattr(ws,'SessionLocal',db)
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
    restored=env.client.get('/company-knowledge/conversations').json()
    assert restored['session_id']==sid and len(restored['messages'])==2
    assert restored['messages'][1]['references'][0]['local_id']=='doc-a'
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
