"""Exercise department navigation against the actual frontend and disposable knowledge APIs."""
import argparse
import importlib.util
import json
import re
from pathlib import Path
import threading
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect
import uvicorn

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8896)
    args = parser.parse_args()
    args.artifacts.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('isolated_audit', ROOT/'scripts/manual/knowledge_audit_app.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = module.build_app(args.artifacts/('data-'+str(time.time_ns())))
    from database import SessionLocal
    from company_catalog import CompanyDocument, CompanyProject, document_store
    from sqlalchemy import select
    with SessionLocal() as db:
        for p in db.scalars(select(CompanyProject)):
            p.department = {'owned':'project','other':'market','private':'expert'}.get(p.id, '')
        for d in db.scalars(select(CompanyDocument)):
            d.department = {'owned':'project','other':'market','private':'expert'}.get(d.knowledge_project_id, '')
        if not db.get(CompanyDocument, 'legacy-root'):
            document_store().put_bytes('audit/legacy.txt', b'legacy evidence', 'text/plain')
            db.add(CompanyDocument(id='legacy-root', index_id='audit-index', title='历史独立资料.txt', format='TXT',
                owner='alice', owner_user_id=1, state='ready', cloud_id='legacy-cloud', is_root=1,
                confidentiality='internal', visibility='members', object_key='audit/legacy.txt'))
        db.commit()
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port, log_level='error'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{args.port}'
    for _ in range(100):
        if server.started:
            break
        time.sleep(.1)
    assert server.started
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width':1600, 'height':1000}, accept_downloads=True)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/auth/me', lambda route: route.fulfill(json={'id':1,'username':'alice','role':'user',
                'is_active':True,'knowledge_access':True,'must_change_password':False}))
            page.route('**/projects', lambda route: route.continue_() if '/company-knowledge/' in route.request.url else route.fulfill(json=[]))
            page.route('**/assistant/state', lambda route: route.fulfill(json={'messages':[],'sessions':[]}))
            page.add_init_script("localStorage.setItem('accessToken','audit-browser-only');localStorage.setItem('activeView','company-knowledge');")
            page.goto(base+'/audit/login/alice')
            page.goto(base+'/index.html', wait_until='domcontentloaded')
            page.get_by_role('button',name='打开公司知识库',exact=True).click()
            expect(page.get_by_role('tab',name='总资料库',exact=True)).to_be_visible(timeout=30000)
            page.get_by_role('tab',name='知识库首页',exact=True).click()
            expect(page.locator('.ckb-simple-home')).to_be_visible()
            page.screenshot(path=str(args.artifacts/'home.png'), full_page=True)
            expect(page.get_by_text('公共资料部',exact=True)).to_have_count(0)
            page.get_by_role('menuitem',name='市场部',exact=True).click()
            expect(page.get_by_label('筛选所属部门／栏目',exact=True)).to_have_value('market')
            expect(page.get_by_role('tablist',name='知识库视图',exact=True)).not_to_be_visible()
            expect(page.get_by_role('navigation',name='当前部门位置',exact=True)).to_contain_text('市场部')
            expect(page.get_by_role('button',name='检索本部门资料',exact=False)).to_be_visible()
            page.get_by_role('button',name='本部门全部文件',exact=False).click()
            expect(page.locator('.ckb-library-heading h2')).to_have_text('本部门全部文件')
            page.get_by_role('button',name='全部资料',exact=False).first.click()
            expect(page.locator('.ckb-heading-count')).to_contain_text('1 个项目')
            page.get_by_role('button',name='创建项目',exact=True).click()
            project_dialog = page.get_by_role('dialog',name='创建项目',exact=True)
            expect(project_dialog.get_by_label('项目所属部门／栏目',exact=True)).to_have_value('market')
            name='部门验收项目-'+str(int(time.time()))
            project_dialog.get_by_label('项目名称',exact=True).fill(name)
            with page.expect_response(lambda r:r.url.endswith('/company-knowledge/projects') and r.request.method=='POST') as response:
                project_dialog.get_by_role('button',name='创建空项目',exact=True).click()
            project = response.value.json()
            assert project['department']=='market'
            expect(project_dialog).not_to_be_visible()
            page.get_by_role('button',name='新建目录',exact=True).click()
            folder_dialog=page.get_by_role('dialog',name='新建目录',exact=True)
            folder_dialog.get_by_label('目录名称',exact=True).fill('部门子目录')
            folder_dialog.get_by_role('button',name='创建目录',exact=True).click()
            expect(folder_dialog).not_to_be_visible()
            page.locator('.ckb-subfolder-card').filter(has_text='部门子目录').locator('button').first.click()
            page.get_by_role('button',name='上传文件',exact=True).click()
            upload_dialog=page.get_by_role('dialog',name='上传文件',exact=True)
            expect(upload_dialog.get_by_label('上传所属部门／栏目',exact=True)).to_have_value('market')
            expect(upload_dialog.get_by_label('上传所属部门／栏目',exact=True)).to_be_disabled()
            upload_dialog.get_by_label('选择上传资料',exact=True).set_input_files({'name':'部门继承验收.txt','mimeType':'text/plain','buffer':'部门继承验收原文'.encode()})
            with page.expect_response(lambda r:r.url.endswith('/company-knowledge/uploads') and r.request.method=='POST') as response:
                upload_dialog.get_by_role('button',name='上传并归档',exact=True).click()
            doc=response.value.json()
            assert doc['department']=='market' and doc['knowledge_project_id']==project['id'] and doc['folder_id']
            upload_dialog.get_by_role('button',name='完成，查看资料',exact=True).click()
            expect(upload_dialog).not_to_be_visible()
            page.get_by_role('button',name='向当前目录提问',exact=False).click()
            expect(page.locator('.ckb-chat-workspace')).to_be_visible()
            expect(page.locator('.ckb-evidence-panel')).to_contain_text('市场部')
            page.get_by_label('知识问答问题',exact=True).fill('请总结当前资料')
            page.get_by_role('button',name='发送问题',exact=True).click()
            expect(page.locator('.ckb-chat-feed')).to_contain_text('隔离验收回答',timeout=30000)
            evidence=page.request.get(base+'/audit/evidence',headers={'Authorization':'Bearer audit-alice'}).json()
            assert evidence['last_question']['document_ids']==[doc['id']]
            page.get_by_role('button',name='返回资料位置',exact=False).click()
            expect(page.locator('.ckb-library-heading')).to_contain_text('部门子目录')
            # Existing original preview and download must continue to work.
            page.get_by_role('button',name='阅读',exact=True).click()
            reader=page.locator('.ckb-reader-dialog')
            expect(reader).to_be_visible()
            expect(reader.locator('.ckb-reader-original-error')).to_have_count(0)
            with page.expect_download() as downloaded:
                reader.get_by_role('button',name='下载水印副本',exact=True).first.click()
            assert downloaded.value.failure() is None
            reader.locator('.el-dialog__headerbtn').click()
            page.get_by_role('button',name='返回公司知识库',exact=True).click()
            expect(page.get_by_role('tablist',name='知识库视图',exact=True)).to_be_visible()
            page.get_by_role('tab',name='总资料库',exact=True).click()
            expect(page.get_by_label('筛选所属部门／栏目',exact=True)).to_have_value('')
            page.get_by_role('button',name='上传文件',exact=True).click()
            expect(upload_dialog.get_by_label('上传所属部门／栏目',exact=True)).to_have_value('')
            upload_dialog.get_by_label('选择上传资料',exact=True).set_input_files({'name':'专家独立验收.txt','mimeType':'text/plain','buffer':b'expert evidence'})
            upload_dialog.get_by_role('button',name='上传并归档',exact=True).click()
            expect(upload_dialog).to_contain_text('请选择所属部门')
            upload_dialog.get_by_label('上传所属部门／栏目',exact=True).select_option('expert')
            with page.expect_response(lambda r:r.url.endswith('/company-knowledge/uploads') and r.request.method=='POST') as response:
                upload_dialog.get_by_role('button',name='上传并归档',exact=True).click()
            standalone=response.value.json()
            assert standalone['department']=='expert' and standalone['is_root']==1
            upload_dialog.get_by_role('button',name='完成，查看资料',exact=True).click()
            page.get_by_role('menuitem',name=re.compile(r'^专家(?:部)?资料$')).click()
            expect(page.locator('.ckb-root-file-row')).to_contain_text('专家独立验收.txt')
            page.get_by_role('button',name='返回公司知识库',exact=True).click()
            page.get_by_role('tab',name='总资料库',exact=True).click()
            page.get_by_label('筛选所属部门／栏目',exact=True).select_option('unassigned')
            expect(page.locator('.ckb-root-file-row')).to_contain_text('历史独立资料.txt')
            page.get_by_role('menuitem',name='市场部',exact=True).click()
            page.get_by_role('button',name='进入项目：他人共享项目',exact=True).click()
            expect(page.get_by_role('button',name='上传文件',exact=True)).to_be_disabled()
            expect(page.get_by_role('button',name='新建目录',exact=True)).to_be_disabled()
            page.get_by_role('menuitem',name='市场部',exact=True).click()
            page.screenshot(path=str(args.artifacts/'department-desktop.png'), full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(args.artifacts/'department-mobile.png'), full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth')<=390
            assert not errors,errors
            result={'status':'passed','real_frontend':True,'real_knowledge_routes':True,'synthetic_providers':True,
                'department_inheritance':True,'explicit_chat_scope':True,'original_download':True,'readonly_controls':True,
                'root_department_required':True,'department_tabs_hidden':True,'global_tabs_restored':True,
                'department_scope_labels':True,'mobile_overflow':False,'page_errors':errors}
            (args.artifacts/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(result,ensure_ascii=False))
            browser.close()
    finally:
        server.should_exit=True
        thread.join(timeout=5)


if __name__=='__main__':
    main()
