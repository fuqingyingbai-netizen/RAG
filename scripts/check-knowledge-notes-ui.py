"""Real editor + real notes routes, isolated SQLite and local assets; no cloud writes."""
import argparse
from functools import partial
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
import io
import json
import mimetypes
import re
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
    parser=argparse.ArgumentParser();parser.add_argument('--output-dir',type=Path,required=True);parser.add_argument('--assets-dir',type=Path,required=True);parser.add_argument('--writing-regression',action='store_true');parser.add_argument('--table-regression',action='store_true');parser.add_argument('--publish-regression',action='store_true');parser.add_argument('--project-regression',action='store_true');parser.add_argument('--reader-regression',action='store_true');parser.add_argument('--formats-dir',type=Path);parser.add_argument('--failure-regression',action='store_true');parser.add_argument('--root-regression',action='store_true');parser.add_argument('--preview-regression',action='store_true');parser.add_argument('--large-sheet',type=Path);args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix='note-qa-',ignore_cleanup_errors=True) as temp:
        patch=pytest.MonkeyPatch();generator=setup.__wrapped__(patch,Path(temp));state=next(generator)
        import company_memory
        patch.setattr(company_memory,'factory',lambda:state.db)
        for model in (company_memory.KnowledgeChatState,company_memory.KnowledgeChatThread,company_memory.KnowledgeChatMessage, company_memory.KnowledgeChatTask):model.__table__.create(state.db.kw['bind'])
        company_notes.recognize_image=lambda data:'现场测试流程：访谈、记录、复核。'
        p=project(state,'经验图文验证',category='手稿笔记')
        note=state.client.post('/company-knowledge/notes',json={'project_id':p['id']}).json()
        reader_config = None
        if getattr(args, 'reader_regression', False) or args.preview_regression or args.root_regression or args.failure_regression:
            import runpy
            reader_config = runpy.run_path(str(ROOT/('scripts/check-knowledge-failure-ui.py' if args.failure_regression else 'scripts/check-knowledge-root-ui.py' if args.root_regression else 'scripts/check-knowledge-preview-ui.py' if args.preview_regression else 'scripts/check-knowledge-reader-ui.py')))
            reader_config = reader_config['configure'](state, args, patch)
        class Handler(SimpleHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if self.path.startswith('/company-knowledge/'):return self.api()
                if self.path=='/full':
                    self.send_response(200);self.send_header('Content-Type','text/html;charset=utf-8');self.end_headers();self.wfile.write(full_html.encode());return
                if self.path=='/':
                    self.send_response(200);self.send_header('Content-Type','text/html;charset=utf-8');self.end_headers();self.wfile.write(html.encode());return
                if self.path.startswith(('/qa-vendor/','/webfonts/')):
                    path=args.assets_dir/Path(self.path).name;self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream');self.end_headers();self.wfile.write(path.read_bytes());return
                super().do_GET()
            def do_POST(self):self.api()
            def do_PATCH(self):self.api()
            def do_DELETE(self):self.api()
            def api(self):
                payload=self.rfile.read(int(self.headers.get('Content-Length',0)))
                response=reader_config['response'](self.path) if reader_config and self.command=='GET' else None
                if response is None:response=state.client.request(self.command,self.path,content=payload,headers={'Content-Type':self.headers.get('Content-Type','application/json')})
                self.send_response(response.status_code)
                for key,value in response.headers.items():
                    if key.lower() not in ('transfer-encoding','connection','content-encoding'):self.send_header(key,value)
                self.end_headers()
                try:self.wfile.write(response.content)
                except (BrokenPipeError,ConnectionAbortedError,ConnectionResetError):pass
        html='''<!doctype html><html lang="zh-CN" data-knowledge-theme="light"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/qa-vendor/element.css"><link rel="stylesheet" href="/qa-vendor/icons.css"><link rel="stylesheet" href="/company-knowledge.css"><link rel="stylesheet" href="/company-knowledge-universe.css"><link rel="stylesheet" href="/company-knowledge-glass.css"><link rel="stylesheet" href="/knowledge-note-editor.css"><style>body{margin:0;background:radial-gradient(ellipse at 15% 60%,#9cdbe5aa,transparent 60%),linear-gradient(120deg,#d5e6f7,#e8dff4);font-family:system-ui,sans-serif}.backdrop{padding:80px;color:#42687b;font-size:32px}</style></head><body><div class="backdrop">经验沉淀 · 项目空间</div><div id="app"><knowledge-note-editor v-if="opened" :note-id="noteId" :fetch-api="api" username="alice" @close="opened=false"></knowledge-note-editor><button v-else id="reopen" @click="opened=true">继续编辑</button></div><script src="/qa-vendor/vue.js"></script><script src="/qa-vendor/element.js"></script><script src="/knowledge-glass-optics.js"></script><script src="/knowledge-note-editor.js"></script><script>const app=Vue.createApp({components:{KnowledgeNoteEditor},data:()=>({opened:true,noteId:NOTEID}),methods:{api:(url,options)=>fetch(url,options)}});app.use(ElementPlus);window.app=app.mount('#app');</script></body></html>'''.replace('NOTEID',json.dumps(note['id']))
        styles=re.findall(r'href="(knowledge-(?:home-simple|palette|typography)\.[a-f0-9]{12}\.css)"',(ROOT/'frontend/index.html').read_text(encoding='utf-8'))
        html=html.replace('</head>',''.join('<link rel="stylesheet" href="/'+name+'">' for name in styles)+'</head>')
        full_html=html.replace('<knowledge-note-editor v-if="opened" :note-id="noteId" :fetch-api="api" username="alice" @close="opened=false"></knowledge-note-editor><button v-else id="reopen" @click="opened=true">继续编辑</button>', '<company-knowledge ref="knowledge"/>').replace('<script src="/knowledge-note-editor.js"></script>', '<script src="/knowledge-note-editor.js"></script><script src="/knowledge-document-viewer.js"></script><script src="/company-knowledge.js"></script>').replace('components:{KnowledgeNoteEditor}', 'components:{KnowledgeNoteEditor,CompanyKnowledge}')
        if args.failure_regression:full_html=full_html.replace('</head>','<link rel="stylesheet" href="/knowledge-workspace.css"></head>')
        server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(ROOT/'frontend')));threading.Thread(target=server.serve_forever,daemon=True).start()
        with sync_playwright() as playwright:
            print('QA: launching browser',flush=True);browser=playwright.chromium.launch(channel='msedge',headless=True);page=browser.new_page(viewport={'width':1440,'height':1000},accept_downloads=True);errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                print('QA: opening editor',flush=True);page.goto('http://127.0.0.1:'+str(server.server_port)+'/');expect(page.get_by_role('textbox',name='笔记正文')).to_be_visible()
                if getattr(args, 'reader_regression', False) or args.preview_regression or args.root_regression or args.failure_regression:
                    reader_config['check'](page, state, p, args, Path(temp), errors)
                    browser.close();server.shutdown();generator.close();patch.undo();return
                if args.project_regression:
                    check_project_and_publish(page,state,p,args,Path(temp),errors)
                    browser.close();server.shutdown();generator.close();patch.undo();return
                if args.publish_regression:
                    button=page.get_by_role('button',name='发布笔记',exact=True)
                    expect(button).to_be_disabled();expect(page.locator('.kn-writing-hint')).to_contain_text('先写正文或插入图片')
                    page.get_by_role('textbox',name='笔记标题').fill('只有标题');expect(button).to_be_disabled()
                    page.screenshot(path=str(args.output_dir/'empty-note.png'),animations='disabled')
                    page.get_by_role('textbox',name='笔记正文').fill('记录可复用的访谈经验，并在发布后进入经验沉淀。')
                    expect(button).to_be_enabled();button.click()
                    expect(page.locator('.kn-publication')).to_contain_text('正在建立索引',timeout=30000)
                    page.screenshot(path=str(args.output_dir/'published-note.png'))
                    page.goto('http://127.0.0.1:'+str(server.server_port)+'/full')
                    page.get_by_role('tab',name='经验沉淀',exact=True).click()
                    row=page.locator('.ckb-project-directory.ckb-project-row').first;expect(row).to_be_visible()
                    for width,height in [(1440,1000),(390,844)]:
                        page.set_viewport_size({'width':width,'height':height})
                        expect(row).to_be_visible();box=row.bounding_box();assert box['height']<180,box
                        assert page.evaluate('document.documentElement.scrollWidth')<=width
                        page.screenshot(path=str(args.output_dir/('project-row-'+str(width)+'.png')))
                    assert not errors,errors
                    print(json.dumps({'status':'passed','checks':['empty publish disabled','title-only disabled','text saved and published','project rows desktop/mobile'],'console_errors':errors},ensure_ascii=False))
                    browser.close();server.shutdown();generator.close();patch.undo();return
                if args.table_regression:
                    note_path='**/company-knowledge/notes/'+note['id']
                    page.route(note_path,lambda route:route.fulfill(status=422,json={'detail':'笔记格式不完整，请重试或恢复最近保存的草稿。'}) if route.request.method=='PATCH' else route.continue_())
                    body=page.get_by_role('textbox',name='笔记正文');body.fill('列表中的研究事项')
                    page.get_by_role('button',name='• 列表',exact=True).click();page.get_by_title('插入三行三列表格',exact=True).click()
                    expect(body.locator('li table')).to_have_count(1)
                    body.locator('th').first.click();page.keyboard.insert_text('列表里的表格也能保存')
                    page.get_by_role('button',name='下方加行',exact=True).click();page.get_by_role('button',name='右侧加列',exact=True).click()
                    expect(body.locator('tr')).to_have_count(4);expect(body.locator('tr').first.locator('th,td')).to_have_count(4)
                    page.get_by_role('button',name='保存',exact=True).click();expect(page.locator('.kn-save-status')).to_contain_text('保存失败')
                    expect(body).to_contain_text('列表里的表格也能保存');page.unroute(note_path)
                    page.get_by_role('button',name='重试保存',exact=True).click();expect(page.locator('.kn-save-status')).to_contain_text('草稿已保存',timeout=30000)
                    page.reload();expect(body.locator('li table')).to_have_count(1);expect(body).to_contain_text('列表里的表格也能保存')
                    with page.expect_download() as info:page.get_by_role('button',name='Word 文档',exact=False).click()
                    info.value.save_as(str(args.output_dir/'nested-table.docx'))
                    with page.expect_download() as info:page.get_by_role('button',name='MD ＋ 图片',exact=False).click()
                    info.value.save_as(str(args.output_dir/'nested-table.zip'))
                    page.get_by_role('button',name='发布笔记',exact=True).click();expect(page.locator('.kn-publication')).to_contain_text('正在建立索引')
                    page.screenshot(path=str(args.output_dir/'nested-table.png'),animations='disabled');assert not errors,errors
                    print(json.dumps({'status':'passed','checks':['table inside active list','4x4 expansion','server save/reopen','Word export','Markdown export','publish'],'console_errors':errors},ensure_ascii=False))
                    browser.close();server.shutdown();generator.close();patch.undo();return
                if args.writing_regression:
                    check_writing(page,state,note,args,Path(temp))
                    assert not errors,errors
                    print(json.dumps({'status':'passed','checks':['legacy image-only draft','visible continue-writing action','caption remains separate','typing immediately after upload','no duplicate empty paragraphs','multiple images preserved','server save/reopen','light/dark/mobile'],'console_errors':errors},ensure_ascii=False))
                    browser.close();server.shutdown();generator.close();patch.undo()
                    return
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


def check_writing(page,state,note,args,temp):
    picture=io.BytesIO();Image.new('RGB',(600,220),'#74aebe').save(picture,'PNG')
    base='/company-knowledge/notes/'+note['id']
    asset=state.client.post(base+'/images',files={'file':('legacy.png',picture.getvalue(),'image/png')}).json()
    original={'type':'doc','content':[{'type':'image','attrs':{'assetId':asset['id'],'width':80,'caption':'已有图片说明','ocrText':''}}]}
    response=state.client.patch(base,json={'revision':1,'title':'只有图片的历史草稿','content':original});assert response.status_code==200
    page.reload();body=page.get_by_role('textbox',name='笔记正文',exact=True)
    write=page.get_by_role('button',name='在图片下继续写正文 ↓',exact=True)
    expect(write).to_be_visible();write.click();page.keyboard.insert_text('照片后的第一段正文。')
    expect(body.locator('p')).to_contain_text(['照片后的第一段正文。'])
    expect(page.get_by_role('textbox',name='图片说明',exact=True)).to_have_value('已有图片说明')
    page.get_by_role('textbox',name='图片说明',exact=True).fill('单独修改的图片说明')
    page.get_by_role('textbox',name='图片说明',exact=True).press('Enter')
    write.click();write.click();assert body.locator('p').count()==2
    page.keyboard.insert_text('补充一段正文。');expect(body).to_contain_text('照片后的第一段正文。')
    # Upload an image and type without any arrow-key workaround or paragraph selection.
    file=temp/'new-image.png';file.write_bytes(picture.getvalue());page.locator('input[type=file]').set_input_files(str(file))
    expect(body.locator('.kn-image')).to_have_count(2,timeout=30000)
    page.wait_for_function("document.activeElement?.classList.contains('kn-prose')")
    page.keyboard.insert_text('新图后直接继续输入。');expect(body).to_contain_text('新图后直接继续输入。')
    expect(page.get_by_role('textbox',name='图片说明',exact=True).first).to_have_value('单独修改的图片说明')
    assert body.locator('figure').evaluate_all("figures=>figures.every(f=>f.nextElementSibling?.tagName==='P')")
    page.get_by_role('button',name='保存',exact=True).click();expect(page.locator('.kn-save-status')).to_contain_text('草稿已保存')
    saved=state.client.get(base).json()['content'];assert sum(node['type']=='image' for node in saved['content'])==2
    page.reload();body=page.get_by_role('textbox',name='笔记正文',exact=True);expect(body).to_contain_text('照片后的第一段正文。');expect(body).to_contain_text('新图后直接继续输入。')
    page.wait_for_function("[...document.querySelectorAll('.kn-image img')].length===2&&[...document.querySelectorAll('.kn-image img')].every(image=>image.complete&&image.naturalWidth>0)")
    for theme in ('light','dark'):
        page.evaluate('theme=>document.documentElement.dataset.knowledgeTheme=theme',theme)
        page.screenshot(path=str(args.output_dir/('continue-writing-'+theme+'.png')),animations='disabled')
    page.set_viewport_size({'width':390,'height':844});page.get_by_role('button',name='在图片下继续写正文 ↓',exact=True).first.click();page.keyboard.insert_text('手机宽度也可接着写。');expect(body).to_contain_text('手机宽度也可接着写。')
    assert page.evaluate('document.documentElement.scrollWidth')<=390
    page.screenshot(path=str(args.output_dir/'continue-writing-mobile.png'),animations='disabled')



def check_project_and_publish(page,state,p,args,temp,errors):
    from sqlalchemy import select
    from company_catalog import CompanyDocument,document_store
    from company_notes import CompanyNote
    import company_ingestion
    page.goto(page.url+'full');page.get_by_role('tab',name='经验沉淀',exact=True).click()
    page.get_by_role('button',name='进入项目：'+p['name'],exact=True).click()
    expect(page.get_by_role('heading',name=p['name'],exact=True)).to_be_visible()
    page.get_by_role('button',name='新建图文笔记',exact=True).click()
    title=page.get_by_role('textbox',name='笔记标题');expect(title).to_be_visible()
    title.fill('正文和图片发布验证')
    body=page.get_by_role('textbox',name='笔记正文');body.fill('有内容笔记：保存与发布的结果必须清楚。')
    picture=io.BytesIO();Image.new('RGB',(250,100),'#d6eefa').save(picture,'PNG');file=temp/'proof.png';file.write_bytes(picture.getvalue())
    page.locator('.kn-dialog input[type=file]').set_input_files(str(file));expect(body.locator('.kn-image img')).to_be_visible(timeout=30000)
    page.get_by_role('textbox',name='图片说明',exact=True).fill('用于核对图文归档的图片说明')
    # Let the server commit, then lose the HTTP response, exactly the ambiguous success case.
    def lose_response(route):
        response=route.fetch();assert response.status==200
        route.abort()
    page.route('**/company-knowledge/notes/*/publish',lose_response)
    page.get_by_role('button',name='发布笔记',exact=True).click()
    expect(page.get_by_role('button',name='已提交发布',exact=True)).to_be_disabled(timeout=30000)
    expect(page.locator('.kn-publication')).to_contain_text('发布提交成功')
    expect(page.locator('.kn-dialog .kn-error')).to_have_count(0)
    page.unroute('**/company-knowledge/notes/*/publish')
    with state.db() as db:
        note=db.scalar(select(CompanyNote).where(CompanyNote.title=='正文和图片发布验证'))
        assert note.project_id==p['id']
        doc=db.get(CompanyDocument,note.pending_document_id);doc_id=doc.id;key=doc.object_key
        doc.worker_id='qa-worker';db.commit()
    with __import__('zipfile').ZipFile(io.BytesIO(document_store().get_bytes(key))) as archive:
        assert '有内容笔记'.encode() in archive.read('word/document.xml')
        assert any(name.startswith('word/media/') for name in archive.namelist())
    company_ingestion.checkpoint(doc_id,'qa-worker',state='ready')
    with state.db() as db:
        doc=db.get(CompanyDocument,doc_id);doc.worker_id='';doc.lease_until=None;db.commit()
    expect(page.get_by_role('button',name='已发布',exact=True)).to_be_disabled(timeout=15000)
    expect(page.locator('.kn-publication')).to_contain_text('索引完成')
    page.screenshot(path=str(args.output_dir/'nonempty-publish-confirmed.png'),animations='disabled')
    page.locator('.kn-dialog .el-dialog__headerbtn').click()
    page.get_by_role('button',name='项目空间',exact=True).click()
    # The same settings entry and cancellation work in both independent collections.
    library=project(state,'资料库删除验证')
    page.reload()
    for name,tab in [(p['name'],'经验沉淀'),(library['name'],'资料库')]:
        page.get_by_role('tab',name=tab,exact=True).click()
        page.get_by_role('button',name='编辑项目：'+name,exact=True).click()
        dialog=page.locator('.ckb-project-dialog');expect(dialog).to_be_visible()
        dialog.get_by_role('button',name='删除项目',exact=True).click()
        confirm=page.locator('.el-message-box');expect(confirm).to_contain_text('确定删除项目“'+name+'”')
        confirm.get_by_role('button',name='取消',exact=True).click()
        expect(dialog).to_be_visible()
        assert name in [r['name'] for r in state.client.get('/company-knowledge/projects').json()['projects']]
        dialog.get_by_role('button',name='删除项目',exact=True).click()
        expect(confirm).to_contain_text('子目录')
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth')<=390
        page.screenshot(path=str(args.output_dir/('delete-'+tab+'.png')),animations='disabled')
        confirm.get_by_role('button',name='确认删除整个项目',exact=True).click()
        expect(dialog).not_to_be_visible(timeout=30000)
        expect(page.get_by_role('button',name='编辑项目：'+name,exact=True)).to_have_count(0)
        page.set_viewport_size({'width':1440,'height':1000})
    assert state.client.get('/company-knowledge/documents/'+doc_id+'/original').status_code==404
    assert not errors,errors
    print(json.dumps({'status':'passed','checks':['integrated parent API','text and image publication','server commit with lost response confirmed','ready polling','DOCX text and embedded image','cancel deletion preserves project','delete experience project with note','delete library project','mobile confirmation'],'console_errors':errors},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
