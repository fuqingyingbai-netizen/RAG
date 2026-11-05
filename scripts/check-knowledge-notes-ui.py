"""Real editor + real notes routes, isolated SQLite and local assets; no cloud writes."""
import argparse
from functools import partial
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading

import pytest
from PIL import Image,ImageDraw
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'test')]
from test_company_workspace import setup,project
import company_notes


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output-dir',type=Path,required=True);parser.add_argument('--assets-dir',type=Path,required=True);args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix='note-qa-',ignore_cleanup_errors=True) as temp:
        patch=pytest.MonkeyPatch();generator=setup.__wrapped__(patch,Path(temp));state=next(generator)
        import company_memory
        patch.setattr(company_memory,'factory',lambda:state.db)
        for model in (company_memory.KnowledgeChatState,company_memory.KnowledgeChatThread,company_memory.KnowledgeChatMessage):model.__table__.create(state.db.kw['bind'])
        company_notes.recognize_image=lambda data:'现场测试流程：访谈、记录、复核。'
        p=project(state,'经验图文验证',category='手稿笔记')
        note=state.client.post('/company-knowledge/notes',json={'project_id':p['id']}).json()
        class Handler(SimpleHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if self.path.startswith('/company-knowledge/'):return self.api()
                if self.path=='/full':
                    self.send_response(200);self.send_header('Content-Type','text/html;charset=utf-8');self.end_headers();self.wfile.write(full_html.encode());return
                if self.path=='/':
                    self.send_response(200);self.send_header('Content-Type','text/html;charset=utf-8');self.end_headers();self.wfile.write(html.encode());return
                if self.path.startswith('/qa-vendor/'):
                    path=args.assets_dir/Path(self.path).name;self.send_response(200);self.send_header('Content-Type','text/css' if path.suffix=='.css' else 'text/javascript');self.end_headers();self.wfile.write(path.read_bytes());return
                super().do_GET()
            def do_POST(self):self.api()
            def do_PATCH(self):self.api()
            def api(self):
                payload=self.rfile.read(int(self.headers.get('Content-Length',0)))
                response=state.client.request(self.command,self.path,content=payload,headers={'Content-Type':self.headers.get('Content-Type','application/json')})
                self.send_response(response.status_code)
                for key,value in response.headers.items():
                    if key.lower() not in ('transfer-encoding','connection','content-encoding'):self.send_header(key,value)
                self.end_headers();self.wfile.write(response.content)
        html='''<!doctype html><html lang="zh-CN" data-knowledge-theme="light"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/qa-vendor/element.css"><link rel="stylesheet" href="/qa-vendor/icons.css"><link rel="stylesheet" href="/company-knowledge.css"><link rel="stylesheet" href="/company-knowledge-universe.css"><link rel="stylesheet" href="/knowledge-note-editor.css"><style>body{margin:0;background:radial-gradient(ellipse at 15% 60%,#9cdbe5aa,transparent 60%),linear-gradient(120deg,#d5e6f7,#e8dff4);font-family:system-ui,sans-serif}.backdrop{padding:80px;color:#42687b;font-size:32px}</style></head><body><div class="backdrop">经验沉淀 · 项目空间</div><div id="app"><knowledge-note-editor v-if="opened" :note-id="noteId" :fetch-api="api" username="alice" @close="opened=false"></knowledge-note-editor><button v-else id="reopen" @click="opened=true">继续编辑</button></div><script src="/qa-vendor/vue.js"></script><script src="/qa-vendor/element.js"></script><script src="/knowledge-note-editor.js"></script><script>const app=Vue.createApp({components:{KnowledgeNoteEditor},data:()=>({opened:true,noteId:NOTEID}),methods:{api:(url,options)=>fetch(url,options)}});app.use(ElementPlus);window.app=app.mount('#app');</script></body></html>'''.replace('NOTEID',json.dumps(note['id']))
        full_html=html.replace('<knowledge-note-editor v-if="opened" :note-id="noteId" :fetch-api="api" username="alice" @close="opened=false"></knowledge-note-editor><button v-else id="reopen" @click="opened=true">继续编辑</button>', '<company-knowledge/>').replace('<script src="/knowledge-note-editor.js"></script>', '<script src="/knowledge-note-editor.js"></script><script src="/company-knowledge.js"></script>').replace('components:{KnowledgeNoteEditor}', 'components:{KnowledgeNoteEditor,CompanyKnowledge}')
        server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(ROOT/'frontend')));threading.Thread(target=server.serve_forever,daemon=True).start()
        with sync_playwright() as playwright:
            print('QA: launching browser',flush=True);browser=playwright.chromium.launch(channel='msedge',headless=True);page=browser.new_page(viewport={'width':1440,'height':1000},accept_downloads=True);errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                print('QA: opening editor',flush=True);page.goto('http://127.0.0.1:'+str(server.server_port)+'/');expect(page.get_by_role('textbox',name='笔记正文')).to_be_visible()
                print('QA: editor ready',flush=True);page.get_by_role('textbox',name='笔记标题').fill('一线访谈 · 可复用经验')
                body=page.get_by_role('textbox',name='笔记正文');body.fill('先确认研究目标，再记录事实与判断。')
                page.get_by_role('button',name='加粗',exact=True).click();page.keyboard.type(' 需要核对关键结论。');page.get_by_role('button',name='加粗',exact=True).click()
                page.get_by_title('插入三行三列表格',exact=True).click();expect(body.locator('table')).to_have_count(1)
                body.locator('th').first.click();page.keyboard.type('研究事项');page.get_by_role('button',name='下方加行',exact=True).click();expect(body.locator('tr')).to_have_count(4)
                picture=Image.new('RGB',(800,360),'#e4f5fa');draw=ImageDraw.Draw(picture);draw.rounded_rectangle((30,40,770,320),20,fill='#2e718e');draw.text((70,140),'FIELD NOTES / INTERVIEW -> REVIEW',fill='white');out=io.BytesIO();picture.save(out,'PNG');imagefile=Path(temp)/'现场记录.png';imagefile.write_bytes(out.getvalue())
                body.click();page.keyboard.press('Control+End');page.keyboard.press('ArrowDown');page.keyboard.press('Enter')
                page.route('**/company-knowledge/notes/'+note['id']+'/images',lambda route:route.abort())
                page.locator('input[type=file]').set_input_files(str(imagefile));expect(page.get_by_role('button',name='重新上传',exact=True)).to_be_visible()
                page.unroute('**/company-knowledge/notes/'+note['id']+'/images');page.get_by_role('button',name='重新上传',exact=True).click()
                expect(body.locator('.kn-image img')).to_be_visible(timeout=30000);expect(body.locator('.kn-image img')).to_have_js_property('complete',True)
                page.get_by_role('textbox',name='图片说明',exact=True).fill('现场工作流程示意，访谈结束后进行交叉复核。')
                page.get_by_role('combobox',name='图片宽度',exact=True).select_option('60')
                handle=page.get_by_role('button',name='拖动调整图片宽度',exact=True);handle.scroll_into_view_if_needed();rect=handle.bounding_box();page.mouse.move(rect['x']+10,rect['y']+10);page.mouse.down();page.mouse.move(rect['x']+40,rect['y']+10);page.mouse.up()
                assert page.locator('.kn-image').evaluate('e=>e.style.width')!='60%'
                page.get_by_role('combobox',name='图片宽度',exact=True).select_option('60')
                page.get_by_role('button',name='识别图片文字',exact=True).click();expect(page.get_by_role('textbox',name='图片识别文字',exact=True)).to_have_value('现场测试流程：访谈、记录、复核。')
                page.get_by_role('textbox',name='图片识别文字',exact=True).fill('人工校正：访谈 → 记录 → 复核。')
                page.get_by_role('button',name='保存',exact=True).click();expect(page.locator('.kn-save-status')).to_contain_text('草稿已保存',timeout=30000)
                page.screenshot(path=str(args.output_dir/'note-editor-light.png'))
                assert page.locator('.kn-prose .kn-image').evaluate('e=>e.style.width')=='60%'
                # Close and open against the backend to prove this is not browser-only state.
                page.get_by_role('button',name='Close this dialog').click();page.get_by_role('button',name='继续编辑',exact=True).click()
                expect(page.get_by_role('textbox',name='笔记标题')).to_have_value('一线访谈 · 可复用经验')
                expect(page.get_by_role('textbox',name='图片说明',exact=True)).to_have_value('现场工作流程示意，访谈结束后进行交叉复核。')
                # Dropped files and clipboard screenshots use the real multipart image endpoint.
                payload=list(out.getvalue())
                page.evaluate('''bytes=>{const dt=new DataTransfer();dt.items.add(new File([new Uint8Array(bytes)],'drop.png',{type:'image/png'}));document.querySelector('.kn-prose').dispatchEvent(new DragEvent('drop',{dataTransfer:dt,bubbles:true,cancelable:true,clientX:500,clientY:400}));}''',payload)
                expect(page.locator('.kn-image')).to_have_count(2)
                body.locator('p').last.click();page.keyboard.press('End')
                page.evaluate('''bytes=>{const dt=new DataTransfer();dt.items.add(new File([new Uint8Array(bytes)],'paste.png',{type:'image/png'}));document.querySelector('.kn-prose').dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));}''',payload)
                expect(page.locator('.kn-image')).to_have_count(3)
                page.get_by_role('button',name='保存',exact=True).click();expect(page.locator('.kn-save-status')).to_contain_text('草稿已保存')
                page.evaluate("document.documentElement.dataset.knowledgeTheme='dark';document.body.style.background='#101c2f'")
                page.screenshot(path=str(args.output_dir/'note-editor-dark.png'))
                with page.expect_download() as info:page.get_by_role('button',name='Word 文档',exact=False).click()
                info.value.save_as(str(args.output_dir/'note-export.docx'))
                with page.expect_download() as info:page.get_by_role('button',name='MD ＋ 图片',exact=False).click()
                info.value.save_as(str(args.output_dir/'note-export.zip'))
                page.get_by_role('button',name='发布笔记',exact=True).click();expect(page.locator('.kn-publication')).to_contain_text('正在建立索引')
                # Simulated offline save must show an error and retain text, then recover on retry.
                page.route('**/company-knowledge/notes/'+note['id'],lambda route:route.abort() if route.request.method=='PATCH' else route.continue_())
                page.get_by_role('textbox',name='笔记标题').fill('断网后仍保留的标题');expect(page.locator('.kn-save-status')).to_contain_text('保存失败',timeout=15000)
                assert page.get_by_role('textbox',name='笔记标题').input_value()=='断网后仍保留的标题'
                page.unroute('**/company-knowledge/notes/'+note['id']);page.get_by_role('button',name='重试保存').click();expect(page.locator('.kn-save-status')).to_contain_text('草稿已保存')
                # Optimistic conflict cannot overwrite edits from another window.
                remote=state.client.get('/company-knowledge/notes/'+note['id']).json();state.client.patch('/company-knowledge/notes/'+note['id'],json={'revision':remote['revision'],'title':'另一窗口修改','content':remote['content']})
                page.get_by_role('textbox',name='笔记标题').fill('本窗口冲突内容');expect(page.locator('.kn-save-status')).to_contain_text('其他窗口已有更新',timeout=15000)
                assert state.client.get('/company-knowledge/notes/'+note['id']).json()['title']=='另一窗口修改'
                page.screenshot(path=str(args.output_dir/'note-conflict.png'))
                page.set_viewport_size({'width':390,'height':844});page.evaluate("document.documentElement.dataset.knowledgeTheme='light'");assert page.evaluate('document.documentElement.scrollWidth')<=390
                expect(page.get_by_role('textbox',name='笔记标题')).to_be_visible();page.screenshot(path=str(args.output_dir/'note-editor-mobile.png'))
                # The production collection entry must create in the active experience project.
                full=browser.new_page(viewport={'width':1440,'height':1000});full.on('pageerror',lambda error:errors.append(str(error)))
                full.goto('http://127.0.0.1:'+str(server.server_port)+'/full');full.get_by_role('tab',name='经验沉淀',exact=True).click()
                full.get_by_role('button',name='新建图文笔记',exact=True).click();expect(full.get_by_role('textbox',name='笔记正文')).to_be_visible(timeout=30000)
                full.get_by_role('textbox',name='笔记标题').fill('入口与草稿验证');full.get_by_role('textbox',name='笔记正文').fill('从经验沉淀直接创建笔记。')
                full.get_by_role('button',name='保存',exact=True).click();expect(full.locator('.kn-save-status')).to_contain_text('草稿已保存');full.get_by_role('button',name='Close this dialog').click()
                full.locator('.ckb-note-drafts>summary').click();expect(full.locator('.ckb-note-drafts')).to_contain_text('入口与草稿验证')
                full.get_by_role('button',name='入口与草稿验证',exact=False).click();expect(full.get_by_role('textbox',name='笔记正文')).to_contain_text('从经验沉淀直接创建笔记。')
                full.screenshot(path=str(args.output_dir/'note-entry-integration.png'));full.close()
                assert not errors,errors
                print(json.dumps({'status':'passed','checks':['rich text','editable table','image upload','paste screenshot','drop image','resize','caption','OCR correction','server autosave/reopen','DOCX export','MD ZIP export','publish','offline retry','conflict protection','light/dark/mobile'],'console_errors':errors},ensure_ascii=False))
            except Exception as error:
                print('FAIL:',str(error),flush=True);page.screenshot(path=str(args.output_dir/'failure.png'));print('Browser errors:',errors);raise
            finally:browser.close()
        server.shutdown();generator.close();patch.undo()


if __name__=='__main__':main()
