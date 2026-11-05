"""Full app, real local guide API, isolated data; no production writes or models."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading

import pytest
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'test')]
from test_company_workspace import setup, project
import research_api
from models import User, AssistantState, AssistantThread, AssistantMessage


def main():
    expect.set_options(timeout=30000)
    parser = argparse.ArgumentParser(); parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--frontend-dir', type=Path, default=ROOT/'frontend')
    args = parser.parse_args(); args.output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='assistant-guide-', ignore_cleanup_errors=True) as temp:
        patch = pytest.MonkeyPatch(); fixture = setup.__wrapped__(patch, Path(temp)); state = next(fixture)
        import company_memory
        patch.setattr(company_memory, 'factory', lambda: state.db)
        for model in (company_memory.KnowledgeChatState, company_memory.KnowledgeChatThread, company_memory.KnowledgeChatMessage):
            model.__table__.create(state.db.kw['bind'])
        state.client.app.include_router(research_api.router)
        def db_session():
            with state.db() as db: yield db
        state.client.app.dependency_overrides[research_api.get_db] = db_session
        state.client.app.dependency_overrides[research_api.get_current_user] = lambda: state.user
        patch.setattr(research_api.research_workflow, '_get_assistant_model', lambda: None)
        for model in (AssistantState, AssistantThread, AssistantMessage): model.__table__.create(state.db.kw['bind'])
        with state.db() as db:
            db.add(User(id=1, username='alice', role='user', password_hash='synthetic')); db.commit()
        p = project(state, 'test', category='手稿笔记')
        folder = state.client.post('/company-knowledge/projects/' + p['id'] + '/folders', json={'name':'访谈'}).json()
        note = state.client.post('/company-knowledge/notes', json={'project_id':p['id'], 'folder_id':folder['id']}).json()
        requests = []
        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                if self.path == '/auth/me': return self.send_json({'username':'alice','role':'user','knowledge_access':True})
                if self.path.startswith('/company-knowledge/') or self.path.startswith('/research/assistant/'): return self.api()
                if self.path.startswith('/research/'):
                    return self.send_json({'projects':[], 'results':[], 'summary':{}, 'recent_projects':[], 'recent_reports':[]})
                if self.path.startswith('/script.') and self.path.endswith('.js'):
                    payload = (args.frontend_dir / 'script.js').read_text(encoding='utf-8-sig').replace('createApp({', 'window.qaApp = createApp({', 1).encode()
                    self.send_response(200); self.send_header('Content-Type','text/javascript'); self.end_headers(); self.wfile.write(payload); return
                super().do_GET()
            def do_POST(self): self.api()
            def do_PATCH(self): self.api()
            def send_json(self, value):
                self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(json.dumps(value).encode())
            def api(self):
                payload = self.rfile.read(int(self.headers.get('Content-Length',0)))
                if self.path == '/research/assistant/stream': requests.append(json.loads(payload))
                response = state.client.request(self.command, self.path, content=payload, headers={'Content-Type': self.headers.get('Content-Type','application/json')})
                if self.path == '/research/assistant/stream': print('Guide API: '+str(response.status_code),flush=True)
                self.send_response(response.status_code)
                for key, value in response.headers.items():
                    if key.lower() not in ('transfer-encoding','connection','content-encoding'): self.send_header(key,value)
                self.end_headers()
                try: self.wfile.write(response.content)
                except (BrokenPipeError,ConnectionAbortedError,ConnectionResetError): pass
        server = ThreadingHTTPServer(('127.0.0.1',0), partial(Handler,directory=str(args.frontend_dir)))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        errors = []
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel='msedge',headless=True)
                page = browser.new_page(viewport={'width':1440,'height':1000})
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.add_init_script("localStorage.setItem('accessToken','synthetic');localStorage.setItem('activeView','company-knowledge');")
                page.goto(f'http://127.0.0.1:{server.server_port}/')
                page.get_by_role('menuitem',name='公司知识库',exact=True).click()
                expect(page.locator('.ckb-workbench')).to_be_visible()
                page.wait_for_function('window.qaApp?.$refs.knowledgeWorkspace?.projectDirectories.length > 0')
                page.evaluate('([id,folder])=>{const k=qaApp.$refs.knowledgeWorkspace;k.mode="cases";k.openDirectory(k.projectDirectories.find(p=>p.id===id),folder)}',[p['id'],folder['id']])
                page.wait_for_function('folder=>qaApp.$refs.knowledgeWorkspace.activeFolderId===folder',arg=folder['id'])
                launcher = page.get_by_role('button',name='打开小助手',exact=True)
                launcher.click(); panel=page.get_by_role('dialog',name='AI 小助手',exact=True)
                composer=panel.get_by_role('textbox',name='给小助手发送消息',exact=True)
                composer.fill('我新建的笔记保存在这个目录下面吗？'); composer.press('Enter')
                expect(panel.locator('.assistant-msg.bot').last).to_contain_text('test / 访谈')
                assert requests[-1]['knowledge_context']['folder_id']==folder['id']
                panel.get_by_role('button',name='本次更新',exact=True).click()
                expect(panel.locator('.assistant-msg.bot').last).to_contain_text('2026.11.05.1')
                panel.get_by_role('button',name='关闭小助手',exact=True).click()
                page.evaluate('id=>qaApp.$refs.knowledgeWorkspace.noteEditorId=id',note['id'])
                expect(page.get_by_role('textbox',name='笔记正文')).to_be_visible()
                # A high z-index alone is insufficient: the underlying modal's
                # focus trap must not steal the assistant's typing focus.
                launcher.click(); expect(panel).to_be_visible()
                composer.fill('上传图片后怎么继续写正文？'); composer.press('Enter')
                expect(panel.locator('.assistant-msg.bot').last).to_contain_text('在图片下继续写正文')
                assert requests[-1]['knowledge_context']['note_id']==note['id']
                box=panel.bounding_box()
                assert page.evaluate('([x,y])=>!!document.elementFromPoint(x,y)?.closest(".assistant-panel")',[box['x']+30,box['y']+35])
                for theme in ('light','dark'):
                    page.evaluate('theme=>document.documentElement.dataset.knowledgeTheme=theme',theme)
                    page.screenshot(path=str(args.output_dir/f'assistant-over-note-{theme}.png'),animations='disabled')
                page.set_viewport_size({'width':390,'height':844})
                expect(composer).to_be_visible(); composer.fill('表格只有3乘3吗？')
                expect(panel.get_by_role('button',name='发送',exact=True)).to_be_enabled(); composer.press('Enter')
                expect(panel.locator('.assistant-msg.bot').last).to_contain_text('下方加行')
                box=panel.bounding_box(); assert box['x']>=0 and box['x']+box['width']<=391
                page.screenshot(path=str(args.output_dir/'assistant-mobile.png'),animations='disabled')
                panel.get_by_role('button',name='关闭小助手',exact=True).click()
                expect(page.get_by_role('textbox',name='笔记正文')).to_be_visible()
                page.set_viewport_size({'width':1440,'height':1000})
                page.evaluate('qaApp.$refs.knowledgeWorkspace.noteEditorId=""')
                for view in ('home','workbench','tasks','review','sources','company-knowledge'):
                    page.evaluate('view=>qaApp.activeView=view',view)
                    expect(launcher).to_be_visible(); launcher.click(); expect(composer).to_be_visible()
                    panel.get_by_role('button',name='关闭小助手',exact=True).click()
                assert not errors, errors
                result={'status':'passed','verified_directory':True,'real_local_guide_api':True,'above_note_modal':True,'modal_typing':True,'mobile':True,'all_business_pages':True,'javascript_errors':errors}
                (args.output_dir/'verification.json').write_text(json.dumps(result,indent=2)); print(json.dumps(result),flush=True)
                browser.close()
        except Exception:
            (args.output_dir/'errors.json').write_text(json.dumps(errors,ensure_ascii=False))
            print('Browser errors: ' + json.dumps(errors,ensure_ascii=False),flush=True)
            if 'page' in locals():
                try: page.screenshot(path=str(args.output_dir/'failure.png'),animations='disabled')
                except Exception: pass
            raise
        finally:
            server.shutdown(); server.server_close(); state.client.close(); fixture.close(); patch.undo()


if __name__=='__main__': main()
