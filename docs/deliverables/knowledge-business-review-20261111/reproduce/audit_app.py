"""Loopback-only acceptance app. Real knowledge routes, disposable data, fake providers.

Run with --data-dir <empty test directory> --port 8891. Never mount in production.
"""
import argparse
import asyncio
import hashlib
import ipaddress
import json
import os
import re
from pathlib import Path
import socket
import sys


def build_app(data_dir):
    root = Path(data_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / 'KNOWLEDGE_AUDIT_ONLY'
    if any(root.iterdir()) and not marker.exists():
        raise RuntimeError('Refusing a nonempty directory without an audit marker')
    marker.touch()
    repo = Path('E:/projects/RAG/work/knowledge-business-review-code-20261111')
    os.environ.update(PYTHON_DOTENV_DISABLED='1', DATABASE_URL='sqlite:///' + (root/'audit.sqlite').as_posix(),
        JWT_SECRET_KEY='disposable-audit-only', COMPANY_KNOWLEDGE_OBJECT_STORE='local',
        COMPANY_KNOWLEDGE_LOCAL_STORE=str(root/'originals'), LANGSMITH_TRACING='false',
        BAILIAN_KNOWLEDGE_API_KEY='fake-audit-key', BAILIAN_KNOWLEDGE_INDEX_ID='audit-index',
        BAILIAN_KNOWLEDGE_AGENT_ID='audit-agent', BAILIAN_KNOWLEDGE_BASE_URL='https://audit.cn-beijing.maas.aliyuncs.com')
    # A missing provider stub must fail locally rather than call any real service.
    old_connect = socket.socket.connect
    def local_connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            host = address[0]
            if host != 'localhost' and not ipaddress.ip_address(host).is_loopback:
                raise RuntimeError('Audit app blocks external service connections')
        return old_connect(sock, address)
    socket.socket.connect = local_connect
    sys.path.insert(0, str(repo/'backend'))
    from sqlalchemy import event, select
    from database import Base, engine, SessionLocal
    import company_knowledge as kb
    import company_workspace as ws
    import company_memory as memory
    from company_catalog import CompanyDocument, CompanyProject, CompanyFolder, document_store
    from company_notes import publication_ready
    from models import User
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import HTMLResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    @event.listens_for(engine, 'connect')
    def sqlite_test_settings(connection, _):
        connection.execute('PRAGMA synchronous=OFF')
        connection.execute('PRAGMA journal_mode=WAL')
    Base.metadata.create_all(engine)
    async def no_cloud(*args, **kwargs):
        return None
    ws.sync_catalog = no_cloud
    async def cloud_rpc(*args, **kwargs):
        return {'nodes': [], 'total_count': 0}
    kb.cloud_rpc = cloud_rpc
    def index_locally(doc_id):
        if doc_id=='processing-owned':return  # Keep this synthetic fixture processing for state assertions.
        with SessionLocal() as db:
            doc = db.get(CompanyDocument, doc_id)
            if doc and doc.state != 'deleted':
                doc.state, doc.cloud_id = 'ready', 'audit-cloud-'+doc.id
                doc.status_message = '隔离验收索引已就绪'
                publication_ready(db, doc.id)
                db.commit()
    ws.schedule_document = index_locally
    async def fake_grounded_answer(cfg, question):
        (root/'last-question.json').write_text(json.dumps({'scope':question.scope,
            'document_ids':question.document_ids,'session_id':question.session_id}, ensure_ascii=False),encoding='utf-8')
        yield {'type':'progress','stage':'retrieving','label':'隔离检索完成','finished':True}
        await asyncio.sleep(0.15)
        if 'audit-export-income' in question.document_ids and question.message=='请生成合成收入表':
            yield {'type':'citations','citations':[{'id':'1','local_id':'audit-export-income','document_id':'audit-income-cloud','title':'TS-收入表.txt','version':1,'pages':[], 'text':'甲项目收入120万元，乙项目收入80万元。','evidence_id':'synthetic-income'}]}
            yield {'type':'answer_delta','text':'隔离合成样本，供导出流程验收。\n\n| 项目 | 收入（万元） | 来源 |\n|---|---|---|\n|甲项目|120|[id_1]|\n|乙项目|80|[id_1]|'}
        else:
            yield {'type':'answer_delta','text':'隔离验收回答：仅使用已选范围，实际会话与权限检查仍执行。'}
        yield {'type':'done','usage':{}}
    ws.grounded_answer = fake_grounded_answer
    async def fake_complete(cfg, instruction, data, **kwargs):
        return json.dumps({'query':data.get('本轮追问','请总结资料')},ensure_ascii=False)
    memory.complete = fake_complete
    with SessionLocal() as db:
        if not db.get(User,1):
            db.add_all([User(id=i,username=name,password_hash='not-a-password',role=role,is_active=active)
                for i,name,role,active in [(1,'alice','user',True),(2,'bob','user',True),
                    (3,'audit-admin','admin',True),(4,'disabled','user',False)]])
            for pid,name,owner,category,visibility in [('owned','验收项目甲','alice','项目原件','members'),
                ('other','他人共享项目','bob','研究成果','members'),
                ('private','他人私有项目','bob','项目原件','restricted'),
                ('experience','共享经验','bob','项目经验','members')]:
                db.add(CompanyProject(id=pid,index_id='audit-index',name=name,owner=owner,
                    owner_user_id=1 if owner=='alice' else 2,category=category,industry='半导体',
                    visibility=visibility,confidentiality='internal',created_by=owner,modified_by=owner))
            db.add_all([CompanyFolder(id='level-one',project_id='owned',parent_id='',name='研究资料'),
                CompanyFolder(id='level-two',project_id='owned',parent_id='level-one',name='访谈记录'),
                CompanyFolder(id='sibling',project_id='owned',parent_id='',name='合同资料')])
            for i in range(28):
                pid = 'owned' if i<24 else 'other' if i<26 else 'experience' if i==26 else 'private'
                folder = 'level-two' if i<21 else 'sibling' if i==21 else ''
                owner = 'alice' if pid=='owned' else 'bob'
                content=('isolated business audit '+str(i)).encode()
                key=f'audit/{i}.txt';document_store().put_bytes(key,content,'text/plain')
                db.add(CompanyDocument(id=f'file-{i:02}',index_id='audit-index',cloud_id=f'seed-cloud-{i}',
                    title=f'访谈材料{i+1:02}.txt',format='TXT',size=len(content),sha256=hashlib.sha256(content).hexdigest(),
                    owner=owner,owner_user_id=1 if owner=='alice' else 2,uploaded_by=owner,
                    knowledge_project_id=pid,folder_id=folder,project={'owned':'验收项目甲','other':'他人共享项目',
                        'experience':'共享经验','private':'他人私有项目'}[pid],
                    category='项目经验' if pid=='experience' else '研究成果' if pid=='other' else '项目原件',
                    industry='半导体',visibility='restricted' if pid=='private' else 'members',
                    confidentiality='internal',state='ready',object_key=key,is_current=1))
            db.commit()
    app = FastAPI(title='Disposable knowledge business audit')
    def audit_user(request:Request):
        auth = request.headers.get('authorization','')
        name = (request.cookies.get('audit_user','') if not auth or auth=='Bearer audit-browser-only'
            else auth.removeprefix('Bearer audit-') if auth.startswith('Bearer audit-') else '')
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.username==name))
            if not user:
                raise HTTPException(401,'隔离验收账号未登录')
            db.expunge(user)
            return user
    app.dependency_overrides[kb.get_current_user] = audit_user
    app.include_router(kb.router)
    # The production startup worker is not registered in this standalone app.
    app.router.on_startup.clear(); app.router.on_shutdown.clear()
    @app.get('/audit/login/{username}',include_in_schema=False)
    def login(username:str):
        if username not in ('alice','bob','audit-admin','disabled'):
            raise HTTPException(404)
        response=RedirectResponse('/preview')
        response.set_cookie('audit_user',username,httponly=True,samesite='strict')
        return response
    @app.get('/audit/evidence',include_in_schema=False)
    def evidence(request:Request):
        user=audit_user(request)
        return {'account':user.username,'last_question':json.loads((root/'last-question.json').read_text())
            if (root/'last-question.json').exists() else None}
    @app.get('/preview',include_in_schema=False)
    def preview(request:Request):
        html=(repo/'frontend/index.html').read_text(encoding='utf-8')
        head=html.split('</head>')[0]+'</head>'
        for link in re.findall(r'<link\b[^>]*rel="stylesheet"[^>]*>',html):
            if link not in head: head=head.replace('</head>',link+'</head>')
        scripts=''.join('<script src="/'+name+'"></script>' for name in ['vendor/vue-3.5.44/vue.global.prod.js',
            'vendor/element-plus-2.14.7/index.full.min.js','vendor/marked-18.1.2/marked.umd.js',
            'vendor/purify-3.4.17.min.js','safe-markdown.js','knowledge-document-viewer.js',
            'knowledge-note-editor.js','company-knowledge.js'])
        return HTMLResponse((head+'''<body><nav aria-label="隔离验收账号" style="padding:8px 24px;background:#f1f3f5">
          当前验收账号：ACTOR_TOKEN · 隔离验收：<a href="/audit/login/alice">创建者 Alice</a> · <a href="/audit/login/bob">成员 Bob</a> ·
          <a href="/audit/login/audit-admin">管理员</a></nav><div id="app"><nav aria-label="隔离部门入口"><button @click="entry={department:'market',nonce:Date.now()}">进入市场部</button><button @click="entry={department:'project',nonce:Date.now()}">进入项目部</button><button @click="entry={department:'policy',nonce:Date.now()}">进入制度文件</button><button @click="entry={department:'expert',nonce:Date.now()}">进入专家资料</button><button @click="clearFault()">解除模拟故障</button></nav><div class="app-shell company-knowledge-shell">
          <main class="el-main" style="padding:24px;min-height:100vh"><company-knowledge :department-entry="entry" @department-change="entry=null"/></main></div></div>'''+scripts+'''
          <script>localStorage.setItem('accessToken','audit-browser-only');Vue.createApp({components:{CompanyKnowledge},data:()=>({entry:null}),methods:{async clearFault(){await fetch('/audit/clear-fault')}}}).use(ElementPlus).mount('#app');</script></body></html>''').replace('ACTOR_TOKEN',audit_user(request).username))
    app.mount('/',StaticFiles(directory=str(repo/'frontend')),name='frontend')
    return app


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--port',type=int,default=8891)
    args=parser.parse_args()
    import uvicorn
    uvicorn.run(build_app(args.data_dir),host='127.0.0.1',port=args.port,access_log=False)
