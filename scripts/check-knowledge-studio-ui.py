"""Exercise the production knowledge component with isolated synthetic API records."""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit
import wave
import zipfile
import sys

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def document_fixture():
    """Two full pages and a table, deliberately different from retrieval chunks."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/document.xml', '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>
          <w:p><w:pPr><w:spacing w:after="300"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="40"/><w:color w:val="245D78"/></w:rPr><w:t>研究项目 · 完整原件预览</w:t></w:r></w:p>
          <w:p><w:r><w:t>这是完整文档的第一段，保留标题、段落与表格。这段正文不在检索片段里。</w:t></w:r></w:p>
          <w:tbl><w:tblPr><w:tblBorders><w:top w:val="single" w:sz="4"/><w:left w:val="single" w:sz="4"/><w:bottom w:val="single" w:sz="4"/><w:right w:val="single" w:sz="4"/><w:insideH w:val="single" w:sz="4"/><w:insideV w:val="single" w:sz="4"/></w:tblBorders></w:tblPr><w:tblGrid><w:gridCol w:w="4000"/><w:gridCol w:w="4000"/></w:tblGrid><w:tr><w:tc><w:p><w:r><w:t>研究方法</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>访谈与资料核对</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
          <w:p><w:r><w:br w:type="page"/></w:r></w:p><w:p><w:r><w:t>第二页：完整上下文仍在，不是按检索片段拼接。</w:t></w:r></w:p>
          <w:p><w:hyperlink r:id="unsafe-link"><w:r><w:t>不可跳转的文档链接</w:t></w:r></w:hyperlink></w:p>
          <w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1100" w:right="1100" w:bottom="1100" w:left="1100"/></w:sectPr></w:body></w:document>''')
        archive.writestr('word/_rels/document.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="unsafe-link" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="javascript:parent.document.body.innerHTML=&quot;bad&quot;" TargetMode="External"/></Relationships>')
    sys.path.insert(0,str(ROOT/'backend'))
    from company_office_watermark import Package,mark_word
    from company_watermark import ExportIdentity
    package=Package(buffer.getvalue(),ExportIdentity('preview',1,'2026-11-04 00:00:00','synthetic-trace-only'))
    mark_word(package,None)
    return package.finish()


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--theme', choices=['light','dark'], default='light')
    parser.add_argument('--reader-only',action='store_true')
    parser.add_argument('--assets-dir', type=Path, default=ROOT / 'work/knowledge-redesign/vendor')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'work/knowledge-redesign')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name in ('vue.js', 'element.js', 'element.css', 'icons.css'):
        assert (args.assets_dir / name).is_file(), f'Missing cached browser asset: {name}'
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'frontend')))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    names = ['新能源汽车市场进入复盘', '访谈提纲与现场记录方法', '制造业供应链风险核对', '客户沟通与项目交付经验', '咨询项目启动清单', '行业背景研究笔记', '项目复盘分享录音', '案例讲解视频']
    categories = ['项目经验', '方法与模板', '案例复盘', '培训分享', '项目原件', '行业资料', '培训分享', '项目经验']
    docs = []
    for i in range(16):
        name, cat = names[i % 8], categories[i % 8]
        fmt = 'WAV' if i == 6 else 'WEBM' if i == 7 else ['PDF','DOCX','XLSX','PPTX','TXT','PNG','PDF','DOCX'][i % 8]
        docs.append(dict(id=f'doc-{i}', cloud_id=f'cloud-{i}', title='示例 · ' + name + (f'（{i+1}）' if i >= 8 else '') + '.' + fmt.lower(),
            format=fmt, size=240000, project='示例汽车研究项目' if i % 2 == 0 else '示例制造业项目', industry='汽车与出行' if i % 2 == 0 else '先进制造',
            category=cat, review='已复核' if i % 3 else '待复核', version=1, confidentiality='internal', confidentiality_label='内部', visibility='members',
            readers=[], is_owner=True, owner='preview', can_read=True, can_manage=True, has_original=True, state='ready', label='可检索',
            modified_at=(datetime(2026,11,3,tzinfo=timezone.utc)-timedelta(days=i)).isoformat(),
            created_at=(datetime(2026,11,2,tzinfo=timezone.utc)-timedelta(days=i)).isoformat(), tags=['行业背景', '市场进入'] if i % 2 == 0 else ['访谈方法', '项目管理'],
            description='演示资料：记录项目背景、研究方法和可复用的交付经验。用于隔离界面验收，不代表真实业务结论。',
            status_message='文字说明已可检索；未自动转写' if i in (6,7) else '解析与索引完成', media_kind='audio' if i == 6 else 'video' if i == 7 else ''))
    docs[8].update(can_read=False,can_manage=False,is_owner=False,tags=[],description='',label='需授权',confidentiality='secret',confidentiality_label='机密')
    projects=[dict(id=f'project-{i}',name=name,owner='preview',owner_user_id=1,industry='汽车与出行' if i==0 else '先进制造',category='项目经验' if i==0 else '方法与模板',review='待复核',confidentiality='internal',visibility='members',readers=[],tags=['行业背景'],description='将背景、访谈、研究成果归入同一个项目空间。',can_manage=True,created_at='2026-11-03T08:00:00Z',modified_at='2026-11-03T08:00:00Z') for i,name in enumerate(['示例汽车研究项目','示例制造业项目'])]
    folders=[dict(id='folder-report',project_id='project-0',parent_id='',name='报告'),dict(id='folder-audio',project_id='project-0',parent_id='',name='录音')]
    for i,doc in enumerate(docs):doc.update(knowledge_project_id=f'project-{i%2}',folder_id='',inherits_project=0)
    errors, unexpected, mutations, metrics = [], [], [], {}
    hide_cases = False
    pending_export, export_polls, pending_chat = None, 0, None
    assets = {'vue.global.prod.js':'vue.js', 'index.full.min.js':'element.js', 'index.css':'element.css', 'all.min.css':'icons.css'}
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(8000); output.writeframes(b'\0\0' * 8000)
    audio = buffer.getvalue()
    (args.output_dir / 'synthetic-audio.wav').write_bytes(audio)
    with sync_playwright() as playwright:
        print('Launching isolated browser',flush=True)
        browser = playwright.chromium.launch(channel='msedge', headless=True)
        # Produce a real, decodable WebM for the player test using bundled capture support.
        capture = browser.new_context(record_video_dir=str(args.output_dir / 'capture'), record_video_size={'width':320,'height':240})
        cp = capture.new_page(); cp.set_content('<body style="background:#16384a;color:#b3ecdf;font:24px sans-serif;padding:40px">Synthetic<br>case video</body>')
        cp.wait_for_timeout(700)
        recording = cp.video
        capture.close()
        video_path = recording.path()
        video = Path(video_path).read_bytes()
        print('Media fixtures ready',flush=True)
        page = browser.new_page(viewport={'width':1440,'height':960}, device_scale_factor=1)
        def page_error(error):
            errors.append(str(error)); print('Browser error: '+str(error),flush=True)
        page.on('pageerror', page_error)
        page.on('console',lambda msg: page_error(msg.text) if msg.type=='error' and not msg.text.startswith('Failed to load resource:') else None)
        page.add_init_script("if(window===window.top){localStorage.setItem('accessToken','synthetic-preview-only');localStorage.setItem('activeView','company-knowledge');}")

        def route_request(route):
            nonlocal pending_export, export_polls, pending_chat
            request, url = route.request, route.request.url
            path = urlsplit(url).path
            if not url.startswith(base):
                name = path.rsplit('/',1)[-1]
                if name in assets:
                    return route.fulfill(path=str(args.assets_dir / assets[name]))
                if name.endswith('.woff2') and (args.assets_dir / name).is_file():
                    return route.fulfill(path=str(args.assets_dir / name))
                if name == 'marked.min.js':
                    return route.fulfill(content_type='application/javascript', body='window.marked={parse:s=>s};')
                # Font requests are optional in the isolated fixture; no external service is used.
                return route.fulfill(status=200, body='')
            if path == '/auth/me':
                return route.fulfill(json={'id':1,'username':'preview','role':'admin','knowledge_access':True,'must_change_password':False})
            if path == '/research/projects': return route.fulfill(json=[])
            if path == '/research/home': return route.fulfill(status=503,json={'detail':'隔离验收仅加载公司知识库'})
            if path == '/research/assistant/state': return route.fulfill(json={'session_id':'preview','sessions':[],'messages':[]})
            if path == '/company-knowledge/status':
                return route.fulfill(json={'configured':True,'access_allowed':True,'is_admin':True,'username':'preview'})
            if path == '/company-knowledge/projects':
                if request.method=='GET':
                    rows=[]
                    for project in projects:
                        if hide_cases and project['category'] in ('项目经验','案例复盘','方法与模板','培训分享'):continue
                        project_docs=[d for d in docs if d.get('knowledge_project_id')==project['id']]
                        rows.append(dict(project,document_count=len(project_docs),ready_count=sum(d['state']=='ready' for d in project_docs),media_count=sum(bool(d['media_kind']) for d in project_docs),folder_count=sum(f['project_id']==project['id'] for f in folders)))
                    return route.fulfill(json={'projects':rows,'folders':deepcopy(folders)})
                body=request.post_data_json
                project=dict(body,id='project-'+str(len(projects)),owner='preview',owner_user_id=1,can_manage=True,created_at='2026-11-03T08:00:00Z',modified_at='2026-11-03T08:00:00Z',document_count=0,folder_count=0,ready_count=0,media_count=0)
                projects.append(project);mutations.append({'path':path,'body':body})
                return route.fulfill(status=201,json=project)
            if path.startswith('/company-knowledge/projects/'):
                bits=path.split('/');project_id=bits[3]
                if len(bits)==4:
                    project=next(p for p in projects if p['id']==project_id)
                    project.update(request.post_data_json);mutations.append({'path':path,'body':request.post_data_json})
                    return route.fulfill(json=project)
                if request.method=='POST':
                    body=request.post_data_json;folder=dict(id='folder-'+str(len(folders)),project_id=project_id,parent_id=body['parent_id'],name=body['name']);folders.append(folder)
                    return route.fulfill(status=201,json=folder)
                folder=next(f for f in folders if f['id']==bits[5])
                if request.method=='DELETE':folders.remove(folder);return route.fulfill(json={'deleted':True})
                folder['name']=request.post_data_json['name'];return route.fulfill(json=folder)
            if path == '/company-knowledge/documents':
                rows = [d for d in docs if not hide_cases or d['category'] not in ('项目经验','案例复盘','方法与模板','培训分享')]
                return route.fulfill(json={'documents':deepcopy(rows),'total_count':len(rows),'warning':''})
            if path == '/company-knowledge/my-projects':
                return route.fulfill(json={'project_count':2,'document_count':len(docs),'projects':[{'name':'示例汽车研究项目','industries':['汽车与出行'],'document_count':8},{'name':'示例制造业项目','industries':['先进制造'],'document_count':8}]})
            if path.startswith('/company-knowledge/access-requests'): return route.fulfill(json={'requests':[]})
            if path == '/company-knowledge/audit-events':
                return route.fulfill(json={'events':[{'id':'qa-event','project_id':'project-0','target_type':'project','target_id':'project-0','target_name':'示例项目','actor_username':'preview','action':'project.update','created_at':'2026-11-03T08:00:00Z','changes':{'description':{'before':'原始背景','after':'修正背景 <script>不执行</script>'}},'details':{}}], 'total':1,'page':1})
            if path.startswith('/company-knowledge/conversations'):
                if request.method != 'GET': mutations.append({'path':path,'body':request.post_data_json})
                return route.fulfill(json={'session_id':'preview-conversation' if request.method == 'POST' else '', 'sessions':[{'id':'preview-conversation','title':'示例 · 市场进入研究'}], 'messages':[], 'document_ids':request.post_data_json.get('document_ids',[]) if request.method == 'POST' else [],'scope':'accessible'})
            if path == '/company-knowledge/chat/stream':
                body = request.post_data_json
                mutations.append({'path':path,'body':body})
                events = [{'type':'progress','stage':'retrieving','label':'检索完成','finished':True,'detail':'命中 1 份文件、1 个片段。','elapsed_seconds':1}]
                if body['message'] == 'UI_TEST_ERROR':
                    events.append({'type':'error','message':'模拟连接中断，请重试。'})
                else:
                    events.extend([
                        {'type':'citations','citations':[{'id':'1','document_id':'cloud-1','title':docs[1]['title'],'text':'合成的访谈方法说明。'}]},
                        {'type':'answer_delta','text':'依据示例资料，可复用访谈提纲与项目复盘方法 [id_1]。\n\n| 要点 | 依据 |\n| --- | --- |\n| 访谈准备 | 项目说明 |'},
                        {'type':'saved'}, {'type':'done','usage':{}},
                    ])
                response=''.join('data: '+json.dumps(e,ensure_ascii=False)+'\n\n' for e in events)
                if body['message'] != 'UI_TEST_ERROR':
                    pending_chat=(route,response);return
                return route.fulfill(content_type='text/event-stream',body=response)
            if path.endswith('/preview'):
                return route.fulfill(json={'references':[{'id':'1','text':'隔离测试的解析片段。','title':'示例资料'}],'total':1})
            if path.endswith('/export-status'):
                export_polls += 1
                return route.fulfill(json={'stage':'converting' if export_polls == 1 else 'stamping','page':0 if export_polls == 1 else 89,'total_pages':0 if export_polls == 1 else 178})
            if path.endswith('/download'):
                pending_export = route
                return
            if path.endswith('/original'):
                doc = next(d for d in docs if d['id'] == path.split('/')[-2])
                if doc['format'] == 'DOCX':
                    return route.fulfill(body=document_fixture(),content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',headers={'X-Watermark-Trace':'synthetic-trace-only'})
                if doc['format'] in ('TXT','MD','CSV'):
                    return route.fulfill(body='完整文件正文，不是检索切片。\n第二段完整上下文。',content_type='text/plain;charset=utf-8')
                return route.fulfill(body=audio if doc['media_kind']=='audio' else video,content_type='audio/wav' if doc['media_kind']=='audio' else 'video/webm')
            if path.startswith('/company-knowledge/documents/') and request.method == 'PATCH':
                doc = next(d for d in docs if d['id'] == path.split('/')[-1]); doc.update(request.post_data_json)
                mutations.append({'path':path,'body':request.post_data_json})
                return route.fulfill(json=deepcopy(doc))
            if path == '/company-knowledge/uploads':
                from email.parser import BytesParser
                from email.policy import default
                message=BytesParser(policy=default).parsebytes(b'Content-Type: '+request.headers['content-type'].encode()+b'\r\n\r\n'+request.post_data_buffer)
                values={};filename='synthetic-audio.wav'
                for part in message.iter_parts():
                    name=part.get_param('name',header='content-disposition')
                    if name=='file':filename=part.get_filename()
                    else:values[name]=part.get_payload(decode=True).decode('utf8')
                project=next(p for p in projects if p['id']==values['project_id'])
                mutations.append({'path':path,'method':'POST','body':values})
                archive=not values.get('description','').strip()
                doc=deepcopy(docs[6]);doc.update(id='uploaded-'+str(len(docs)),title=filename,tags=project['tags'],description=values.get('description',''),project=project['name'],industry=project['industry'],category=project['category'],confidentiality=project['confidentiality'],visibility=project['visibility'],readers=project['readers'],knowledge_project_id=project['id'],folder_id=values['folder_id'],inherits_project=1,state='archived' if archive else 'ready',label='已归档' if archive else '可检索')
                docs.append(doc)
                return route.fulfill(status=202,json=doc)
            if path.startswith('/company-knowledge/') or path.startswith('/research/'):
                unexpected.append(path); return route.fulfill(status=404,json={'detail':'Unexpected isolated API'})
            return route.continue_()

        page.route('**/*',route_request)
        print('Opening production frontend',flush=True)
        page.goto(base,wait_until='networkidle')
        page.get_by_role('menuitem',name='公司知识库',exact=True).click()
        print('Company view opened',flush=True)
        expect(page.get_by_role('heading',name='让每一次研究，')).to_be_visible()
        expect(page.locator('.ckb-workbench')).to_have_attribute('data-theme','light')
        theme_toggle = page.get_by_role('button',name='切换知识库主题',exact=True)
        expect(theme_toggle).to_have_count(1)
        assert theme_toggle.inner_text() == ''
        system_style = '() => [".sidebar", ".company-knowledge-shell > .topbar", ".sidebar-logo"].map(s => { const c=getComputedStyle(document.querySelector(s)); return [c.backgroundColor,c.color,c.filter]; })'
        system_before = page.evaluate(system_style)
        theme_toggle.click()
        assert page.evaluate(system_style) == system_before, 'Knowledge theme changed system shell'
        expect(page.locator('.ckb-workbench')).to_have_attribute('data-theme','dark')
        assert page.evaluate('localStorage.getItem("companyKnowledgeTheme")') == 'dark'
        page.get_by_role('menuitem',name='个人首页',exact=True).click()
        assert page.evaluate('document.documentElement.dataset.knowledgeTheme') is None
        page.get_by_role('menuitem',name='公司知识库',exact=True).click()
        expect(page.locator('.ckb-workbench')).to_have_attribute('data-theme','dark')
        if args.theme == 'light': page.get_by_role('button',name='切换知识库主题',exact=True).click()
        expect(page.locator('.ckb-workbench')).to_have_attribute('data-theme',args.theme)
        page.get_by_role('button',name='操作记录',exact=True).click()
        audit=page.get_by_role('dialog',name='操作记录',exact=True)
        expect(audit).to_contain_text('preview')
        audit.locator('summary').click()
        expect(audit).to_contain_text('原始背景')
        expect(audit).to_contain_text('修正背景 <script>不执行</script>')
        expect(audit.locator('script')).to_have_count(0)
        page.screenshot(path=str(args.output_dir/'audit-desktop.png'),full_page=True,animations='disabled')
        audit.get_by_role('button',name='关闭',exact=True).click()
        expect(page.locator('.ckb-mini-file')).to_have_count(4)
        expect(page.locator('.ckb-mini-file .ckb-file-object')).to_have_count(4)
        page.get_by_role('button',name='暂停动效',exact=True).click()
        assert page.locator('.ckb-orbit-runner').evaluate('(el)=>getComputedStyle(el).animationName') == 'none'
        page.get_by_role('button',name='开启动效',exact=True).click()
        page.emulate_media(reduced_motion='reduce')
        assert page.locator('.ckb-orbit-runner').evaluate('(el)=>getComputedStyle(el).animationName') == 'none'
        page.emulate_media(reduced_motion='no-preference')
        expect(page.locator('.ckb-atlas-node')).to_have_count(4)
        page.locator('.ckb-atlas-results').click()
        expect(page.get_by_role('tab',name='资料库')).to_have_attribute('aria-selected','true')
        expect(page.locator('.ckb-library-sidebar > button.active')).to_have_text('研究成果0')
        page.get_by_role('tab',name='研究首页',exact=True).click()
        page.locator('.ckb-atlas-templates').click()
        expect(page.get_by_role('tab',name='案例库')).to_have_attribute('aria-selected','true')
        expect(page.locator('.ckb-library-sidebar > button.active')).to_contain_text('方法与模板')
        page.get_by_role('button',name='创建项目',exact=True).click()
        case_editor=page.get_by_role('dialog',name='创建项目',exact=True)
        assert case_editor.get_by_role('combobox',name='项目分类',exact=True).locator('option').all_text_contents() == ['项目经验','案例复盘','方法与模板','培训分享']
        expect(case_editor.get_by_role('combobox',name='项目分类',exact=True)).to_have_value('方法与模板')
        page.screenshot(path=str(args.output_dir/'case-project-create.png'),full_page=True,animations='disabled')
        case_editor.get_by_role('button',name='取消',exact=True).click()
        page.get_by_role('tab',name='资料库',exact=True).click()
        page.get_by_role('button',name='编辑项目：示例汽车研究项目',exact=True).click()
        existing_editor=page.get_by_role('dialog',name='项目设置',exact=True)
        assert existing_editor.get_by_role('combobox',name='项目分类',exact=True).locator('option').all_text_contents() == ['项目经验','案例复盘','方法与模板','培训分享']
        existing_editor.get_by_role('button',name='取消',exact=True).click()
        page.get_by_role('tab',name='研究首页',exact=True).click()
        page.screenshot(path=str(args.output_dir/'home-desktop.png'),full_page=True,animations='disabled')
        card=page.locator('.ckb-mini-file').nth(1)
        relative_top='e => e.getBoundingClientRect().top-e.parentElement.getBoundingClientRect().top'
        resting_top=card.evaluate(relative_top);card.hover();page.wait_for_timeout(300)
        assert abs(card.evaluate(relative_top)-resting_top)<1, 'Hover moved the card border outside its grid'
        page.screenshot(path=str(args.output_dir/'home-file-hover.png'),full_page=True,animations='disabled')
        page.locator('.ckb-mini-file').nth(1).click()
        original_frame = page.frame_locator('iframe.ckb-document-frame')
        expect(original_frame.locator('section.docx')).to_have_count(2)
        expect(original_frame.locator('table')).to_contain_text('访谈与资料核对')
        expect(original_frame.locator('a')).to_have_count(0)
        expect(original_frame.locator('.viewer-watermark').first).to_contain_text('preview')
        assert original_frame.locator('section.docx').first.evaluate("s=>(s.querySelector('header')?.getBoundingClientRect().height||0)<100"), 'Floating watermark enlarged the header'
        assert original_frame.locator('section.docx').first.evaluate("s=>s.querySelector('article').getBoundingClientRect().top-s.getBoundingClientRect().top<250"), 'Document content was pushed below the reading area'
        assert original_frame.locator('.viewer-watermark').first.evaluate("e=>e.style.backgroundImage.includes('data:image/svg+xml')"), 'Long documents need repeating preview watermarks'
        expect(page.locator('.ckb-document-loading')).to_have_count(0)
        reader_box=page.locator('.ckb-reader-dialog').bounding_box()
        assert reader_box['y']+reader_box['height'] <= page.viewport_size['height']+1
        assert original_frame.locator('body').evaluate("() => { try { return !!parent.document.body; } catch (_) { return false; } }") is False
        page.screenshot(path=str(args.output_dir/'word-original-desktop.png'),full_page=True,animations='disabled')
        if args.reader_only:
            page.get_by_role('button',name='放大文档',exact=True).click()
            expect(page.locator('.ckb-document-controls')).to_contain_text('110%')
            page.set_viewport_size({'width':390,'height':844})
            expect(page.locator('iframe.ckb-document-frame')).to_be_visible()
            page.screenshot(path=str(args.output_dir/'word-original-mobile.png'),full_page=True,animations='disabled')
            assert not errors,errors
            print(json.dumps({'reader':'passed','theme':args.theme,'errors':errors}),flush=True)
            browser.close();server.shutdown();server.server_close();return
        page.get_by_role('button',name='下载水印副本',exact=True).click()
        expect(page.locator('.ckb-download-progress')).to_contain_text('水印 89/178 项',timeout=10000)
        expect(page.locator('.ckb-download-progress progress')).to_have_attribute('value','89')
        page.screenshot(path=str(args.output_dir/'download-progress.png'),full_page=True,animations='disabled')
        assert pending_export is not None
        with page.expect_download() as exported:
            pending_export.fulfill(body=b'PK-synthetic-watermarked-copy',content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',headers={'X-Download-Filename':'QA_watermarked.docx'})
        assert exported.value.suggested_filename == 'QA_watermarked.docx'
        expect(page.get_by_role('button',name='下载水印副本',exact=True)).to_be_enabled()
        expect(page.locator('.ckb-download-progress')).to_have_count(0)
        page.get_by_role('button',name='Close this dialog').click()
        page.get_by_role('tab',name='资料库',exact=True).click()
        expect(page.locator('.ckb-project-directory')).to_have_count(2)
        page.screenshot(path=str(args.output_dir/'projects-desktop.png'),full_page=True,animations='disabled')
        page.get_by_role('button',name='创建项目',exact=True).click()
        editor=page.get_by_role('dialog',name='创建项目',exact=True)
        expect(page.locator('.ckb-glass-surface:visible.has-refraction')).to_have_count(1)
        page.wait_for_function('document.querySelector(".ckb-glass-surface.has-refraction feImage")?.getAttribute("href")?.startsWith("data:image/png;base64,")')
        page.screenshot(path=str(args.output_dir/'project-create-empty.png'),full_page=True,animations='disabled')
        page.locator('.ckb-dialog:visible').hover(position={'x':100,'y':90})
        page.wait_for_function('document.querySelector(".ckb-glass-surface").style.getPropertyValue("--kg-pointer-x") !== ""')
        page.emulate_media(reduced_motion='reduce',contrast='more')
        expect(page.locator('.ckb-glass-overlay:visible .ckb-glass-surface')).to_be_hidden()
        assert page.locator('.ckb-dialog:visible').evaluate('(e)=>getComputedStyle(e).animationName') == 'none'
        page.screenshot(path=str(args.output_dir/'project-create-accessible.png'),full_page=True,animations='disabled')
        page.emulate_media(reduced_motion='no-preference',contrast='no-preference')
        expect(page.locator('.ckb-glass-surface:visible.has-refraction')).to_have_count(1)
        assert editor.get_by_role('combobox',name='项目分类',exact=True).locator('option').all_text_contents() == ['项目原件','研究成果','访谈纪要','行业资料']
        editor.get_by_role('textbox',name='项目名称',exact=True).fill('QA 项目空间')
        editor.get_by_role('textbox',name='项目行业',exact=True).fill('AI Agent')
        editor.get_by_role('textbox',name='项目标签',exact=True).fill('行业背景，项目方法')
        editor.get_by_role('textbox',name='项目说明',exact=True).fill('用于检查空项目、子目录与属性继承。')
        page.screenshot(path=str(args.output_dir/'project-create.png'),full_page=True,animations='disabled')
        editor.get_by_role('button',name='创建空项目',exact=True).click()
        expect(page.locator('.ckb-directory-path')).to_contain_text('QA 项目空间')
        page.get_by_role('button',name='新建目录',exact=True).click()
        folder_dialog=page.get_by_role('dialog',name='新建目录',exact=True)
        folder_dialog.get_by_role('textbox',name='目录名称',exact=True).fill('录音')
        page.screenshot(path=str(args.output_dir/'folder-create.png'),full_page=True,animations='disabled')
        folder_dialog.get_by_role('button',name='创建目录',exact=True).click()
        page.locator('.ckb-subfolder-card > button').first.click()
        expect(page.locator('.ckb-directory-path')).to_contain_text('录音')
        page.get_by_role('button',name='新建目录',exact=True).click()
        folder_dialog.get_by_role('textbox',name='目录名称',exact=True).fill('访谈一')
        folder_dialog.get_by_role('button',name='创建目录',exact=True).click()
        page.get_by_role('button',name='编辑目录：访谈一',exact=True).click()
        rename=page.get_by_role('dialog',name='编辑目录',exact=True)
        rename.get_by_role('textbox',name='目录名称',exact=True).fill('访谈片段')
        rename.get_by_role('button',name='保存目录',exact=True).click()
        expect(rename).not_to_be_visible()
        expect(page.locator('.ckb-subfolder-card')).to_contain_text('访谈片段')
        page.screenshot(path=str(args.output_dir/'project-folders-desktop.png'),full_page=True,animations='disabled')
        page.get_by_role('tab',name='研究首页',exact=True).click()
        page.get_by_role('button',name='查找历史案例',exact=True).click()
        expect(page.get_by_role('tab',name='案例库')).to_have_attribute('aria-selected','true')
        page.get_by_role('button',name='浏览全部文件',exact=True).click()
        expect(page.locator('.ckb-case-card')).to_have_count(10)
        page.locator('.ckb-case-grid').evaluate('(el)=>el.getAnimations().forEach(a=>a.finish())')
        assert page.locator('.ckb-case-card').first.bounding_box()['height'] >= 350
        assert page.locator('.ckb-case-cover').first.bounding_box()['height'] >= 100
        page.screenshot(path=str(args.output_dir/'cases-desktop.png'),full_page=True,animations='disabled')
        page.get_by_role('combobox',name='筛选标签',exact=True).select_option('行业背景')
        page.get_by_label('开始日期',exact=True).fill('2026-11-02')
        page.get_by_label('结束日期',exact=True).fill('2026-11-02')
        expect(page.locator('.ckb-case-card')).to_have_count(1)
        page.get_by_role('button',name='重置',exact=True).click()
        card = page.locator('.ckb-case-card').filter(has_text='项目复盘分享录音').first
        card.get_by_role('button',name='播放与详情').click()
        audio_player = page.locator('audio')
        expect(audio_player).to_be_visible()
        page.wait_for_function('document.querySelector("audio").readyState >= 1')
        assert page.locator('audio').evaluate('(el)=>el.duration') == 1
        page.screenshot(path=str(args.output_dir/'audio-reader.png'),full_page=True,animations='disabled')
        page.get_by_role('button',name='Close this dialog').click()
        card.get_by_role('button',name='编辑信息',exact=True).click()
        dialog = page.get_by_role('dialog',name='文件设置')
        dialog.get_by_role('textbox',name='自定义标签',exact=True).fill('修正标签，行业背景')
        dialog.get_by_role('textbox',name='文字说明',exact=True).fill('已经修正的说明，可供后续查找。')
        page.screenshot(path=str(args.output_dir/'metadata-desktop.png'),full_page=True,animations='disabled')
        dialog.get_by_role('button',name='保存修改',exact=True).click()
        expect(dialog).not_to_be_visible()
        edited=next(d for d in docs if d['id']=='doc-6')
        assert edited['tags']==['修正标签','行业背景'] and '已经修正' in edited['description']
        page.locator('.ckb-case-card').filter(has_text='案例讲解视频').first.get_by_role('button',name='播放与详情').click()
        expect(page.locator('video')).to_be_visible()
        page.wait_for_function('document.querySelector("video").readyState >= 1')
        assert page.locator('video').evaluate('(el)=>el.duration') > 0
        page.screenshot(path=str(args.output_dir/'video-reader.png'),full_page=True,animations='disabled')
        page.get_by_role('button',name='Close this dialog').click()
        page.locator('.ckb-directory-path').get_by_role('button',name='项目空间',exact=True).click()
        page.locator('.ckb-project-directory').filter(has_text='示例汽车研究项目').locator('.ckb-project-door').click()
        page.get_by_role('button',name='上传文件',exact=True).click()
        dialog=page.get_by_role('dialog',name='上传到当前目录')
        dialog_background = page.locator('.ckb-dialog:visible').evaluate('(el)=>getComputedStyle(el).backgroundColor')
        assert dialog_background.startswith('rgba('), dialog_background
        assert 'blur(' in page.locator('.ckb-glass-surface:visible .ckb-glass-material').evaluate('(el)=>getComputedStyle(el).backdropFilter')
        assert page.locator('.ckb-glass-overlay:visible').count() == 1
        dialog.get_by_role('textbox',name='文字说明',exact=True).fill('音频说明测试')
        dialog.get_by_label('选择上传资料',exact=True).set_input_files(str(args.output_dir/'synthetic-audio.wav'))
        page.screenshot(path=str(args.output_dir/'upload-desktop.png'),full_page=True,animations='disabled')
        dialog.get_by_role('button',name='上传并归档',exact=True).click()
        expect(dialog.get_by_role('button',name='完成，查看资料')).to_be_visible()
        dialog.get_by_role('button',name='完成，查看资料').click()
        expect(dialog).not_to_be_visible()
        page.get_by_role('tab',name='研究首页',exact=True).click()
        page.get_by_role('button',name='比较资料结论',exact=True).click()
        expect(page.locator('.ckb-compare-intent')).to_be_visible()
        compare=page.get_by_role('button',name='比较选中资料（0）',exact=True)
        expect(compare).to_be_disabled()
        checks=page.locator('.ckb-file-gallery input[type=checkbox]')
        checks.nth(0).check();checks.nth(1).check()
        page.get_by_role('button',name='列表',exact=True).click()
        expect(page.locator('.ckb-document-table tbody input:checked')).to_have_count(2)
        page.screenshot(path=str(args.output_dir/'library-list-selected.png'),full_page=True,animations='disabled')
        page.get_by_role('button',name='卡片',exact=True).click()
        expect(page.locator('.ckb-file-gallery input:checked')).to_have_count(2)
        page.get_by_role('button',name='比较选中资料（2）',exact=True).click()
        expect(page.get_by_role('textbox',name='知识问答问题')).to_have_value('比较所选资料的结论差异，逐项列出依据与待复核事项。')
        expect(page.locator('.ckb-session-panel')).to_be_visible()
        expect(page.locator('.ckb-evidence-panel')).to_be_visible()
        composer=page.locator('.ckb-composer')
        edge='e=>getComputedStyle(e,"::before").animationName'
        assert composer.evaluate(edge)!='none'
        page.get_by_role('button',name='暂停动效',exact=True).click()
        assert composer.evaluate(edge)=='none'
        assert page.locator('.ckb-chat-space > span').evaluate('e=>getComputedStyle(e,"::before").animationName')=='none'
        page.get_by_role('button',name='开启动效',exact=True).click()
        page.emulate_media(reduced_motion='reduce')
        assert composer.evaluate(edge)=='none'
        page.emulate_media(reduced_motion='no-preference')
        draft=page.get_by_role('textbox',name='知识问答问题',exact=True)
        value=draft.input_value();draft.fill('');page.locator('.ckb-chat-header').click()
        expect(page.locator('.ckb-composer-signal')).to_contain_text('随时提问')
        assert composer.evaluate(edge)!='none', 'Input must also animate while idle'
        page.screenshot(path=str(args.output_dir/'chat-input-idle.png'),full_page=True,animations='disabled')
        draft.fill(value)
        expect(page.locator('.ckb-composer-signal')).to_contain_text('可以发送')
        page.screenshot(path=str(args.output_dir/'chat-desktop.png'),full_page=True,animations='disabled')
        page.get_by_role('button',name='发送问题',exact=True).click()
        expect(page.locator('.ckb-thinking-ribbon')).to_be_visible()
        expect(page.get_by_role('button',name='停止生成',exact=True)).to_be_visible()
        page.screenshot(path=str(args.output_dir/'chat-generating-desktop.png'),full_page=True,animations='disabled')
        assert pending_chat is not None
        pending_chat[0].fulfill(content_type='text/event-stream',body=pending_chat[1]);pending_chat=None
        expect(page.locator('.ckb-live-answer')).to_contain_text('依据示例资料')
        expect(page.get_by_role('button',name='复制回答',exact=True)).to_be_visible()
        expect(page.locator('.ckb-answer-table table')).to_be_visible()
        page.screenshot(path=str(args.output_dir/'chat-answer-desktop.png'),full_page=True,animations='disabled')
        page.locator('.ckb-citation').first.click()
        expect(page.frame_locator('iframe.ckb-document-frame').locator('section.docx')).to_have_count(2)
        page.get_by_role('button',name='检索片段',exact=False).click()
        expect(page.locator('.ckb-source-reader')).to_contain_text('隔离测试的解析片段')
        page.screenshot(path=str(args.output_dir/'citation-reader.png'),full_page=True,animations='disabled')
        page.get_by_role('button',name='Close this dialog').click()
        page.get_by_role('textbox',name='知识问答问题',exact=True).fill('UI_TEST_ERROR')
        page.get_by_role('button',name='发送问题',exact=True).click()
        expect(page.locator('.ckb-message-assistant .ckb-service-error')).to_contain_text('模拟连接中断')
        page.screenshot(path=str(args.output_dir/'chat-error-desktop.png'),full_page=True,animations='disabled')
        page.get_by_role('tab',name='资料库').click()
        page.get_by_role('button',name='浏览全部文件',exact=True).click()
        page.set_viewport_size({'width':1440,'height':900})
        page.screenshot(path=str(args.output_dir/'library-desktop.png'),full_page=True,animations='disabled')
        expect(page.locator('.ckb-file-card')).to_have_count(10)
        expect(page.locator('.ckb-file-card.locked input')).to_be_disabled()
        expect(page.locator('.ckb-file-card.kind-pdf')).not_to_have_count(0)
        expect(page.locator('.ckb-file-card.kind-sheet')).not_to_have_count(0)
        metrics['desktop_first_row']=page.locator('.ckb-file-card').first.bounding_box()
        assert metrics['desktop_first_row']['height'] >= 324
        for card in page.locator('.ckb-file-card').all():
            rect=card.bounding_box(); footer=card.locator('.ckb-file-footer').bounding_box()
            assert footer['y'] + footer['height'] <= rect['y'] + rect['height'] + 1, f'File actions clipped: card={rect}, footer={footer}'
        first_title = page.locator('.ckb-file-title').first.inner_text()
        page.get_by_role('button',name='下一页资料',exact=True).click()
        expect(page.locator('.ckb-file-card')).to_have_count(7)
        assert page.locator('.ckb-file-title').first.inner_text() != first_title
        page.get_by_role('button',name='上一页资料',exact=True).click()
        page.get_by_role('combobox',name='筛选标签',exact=True).select_option('行业背景')
        assert 0 < page.locator('.ckb-file-card').count() < 10
        page.get_by_role('textbox',name='搜索知识库资料',exact=True).fill('THIS_FILE_DOES_NOT_EXIST')
        expect(page.locator('.ckb-gallery-empty')).to_be_visible()
        page.screenshot(path=str(args.output_dir/'library-empty-filter.png'),full_page=True,animations='disabled')
        page.get_by_role('button',name='清除筛选',exact=True).click()
        page.get_by_role('button',name='列表',exact=True).click()
        page.screenshot(path=str(args.output_dir/'library-list-desktop.png'),full_page=True,animations='disabled')
        expect(page.locator('.ckb-document-table')).to_be_visible()
        page.get_by_role('button',name='卡片',exact=True).click()
        page.locator('.ckb-file-gallery').evaluate('(el)=>el.getAnimations().forEach(a=>a.finish())')
        metrics['desktop_table']=page.locator('.ckb-table-scroll').bounding_box()
        assert metrics['desktop_first_row']['y'] < 360,metrics
        page.set_viewport_size({'width':1366,'height':768})
        page.screenshot(path=str(args.output_dir/'library-short-desktop.png'),full_page=True,animations='disabled')
        metrics['short_first_row']=page.locator('.ckb-file-card').first.bounding_box()
        assert metrics['short_first_row']['y'] < 350,metrics
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(args.output_dir/'library-mobile.png'),full_page=True,animations='disabled')
        metrics['mobile_scroll_width']=page.evaluate('document.documentElement.scrollWidth')
        assert metrics['mobile_scroll_width'] <= 390
        help_box = page.locator('.assistant-fab').bounding_box()
        menu_box = page.locator('.mobile-nav-toggle').bounding_box()
        assert help_box and menu_box
        assert (help_box['y'] >= menu_box['y'] + menu_box['height'] or
                help_box['x'] + help_box['width'] <= menu_box['x'] or
                help_box['x'] >= menu_box['x'] + menu_box['width']), 'Help overlaps mobile navigation'
        page.get_by_role('tab',name='研究首页',exact=True).click()
        for cover in page.locator('.ckb-featured-cover').all():
            assert cover.bounding_box()['width'] > 150, 'Project cover collapsed inside flex card'
            art=cover.locator('.ckb-folder-object').bounding_box()
            frame=cover.bounding_box()
            assert art['x'] >= frame['x'] and art['x'] + art['width'] <= frame['x'] + frame['width']
        page.screenshot(path=str(args.output_dir/'home-mobile.png'),full_page=True,animations='disabled')
        assert page.evaluate('document.documentElement.scrollWidth') <= 390
        page.get_by_role('tab',name='案例库').click()
        page.screenshot(path=str(args.output_dir/'cases-mobile.png'),full_page=True,animations='disabled')
        assert page.evaluate('document.documentElement.scrollWidth') <= 390
        page.get_by_role('tab',name='研究问答',exact=True).click()
        page.screenshot(path=str(args.output_dir/'chat-mobile.png'),full_page=True,animations='disabled')
        assert page.evaluate('document.documentElement.scrollWidth') <= 390
        page.set_viewport_size({'width':1440,'height':900})
        page.get_by_role('tab',name='研究首页',exact=True).click()
        expect(page.locator('.ckb-mini-file')).not_to_have_count(4)
        page.locator('.ckb-home-bottom').scroll_into_view_if_needed()
        page.screenshot(path=str(args.output_dir/'home-files-desktop.png'),full_page=True,animations='disabled')
        for card in page.locator('.ckb-mini-file').all():
            assert card.bounding_box()['height'] >= 180
        page.get_by_role('tab',name='案例库').click()
        hide_cases = True
        page.get_by_role('button',name='刷新资料',exact=True).click()
        expect(page.locator('.ckb-project-directory')).to_have_count(0)
        expect(page.locator('.ckb-create-project-tile')).to_be_visible()
        page.screenshot(path=str(args.output_dir/'cases-empty-desktop.png'),full_page=True,animations='disabled')
        # Archive an audio file without repeating project metadata, then move/rename it in a nested folder.
        hide_cases=False
        page.get_by_role('tab',name='资料库',exact=True).click()
        page.get_by_role('button',name='刷新资料',exact=True).click()
        page.locator('.ckb-project-directory').filter(has_text='QA 项目空间').locator('.ckb-project-door').click()
        page.locator('.ckb-subfolder-card > button').first.click()
        expect(page.locator('.ckb-directory-path')).to_contain_text('录音')
        page.get_by_role('button',name='上传文件',exact=True).click()
        dialog=page.get_by_role('dialog',name='上传到当前目录')
        expect(dialog.get_by_role('textbox',name='自定义标签',exact=True)).to_have_count(0)
        dialog.get_by_label('选择上传资料',exact=True).set_input_files(str(args.output_dir/'synthetic-audio.wav'))
        dialog.get_by_role('button',name='上传并归档',exact=True).click()
        expect(dialog).to_contain_text('音视频已归档')
        dialog.get_by_role('button',name='完成，查看资料',exact=True).click()
        expect(dialog).not_to_be_visible()
        card=page.locator('.ckb-file-card').filter(has_text='synthetic-audio.wav')
        expect(card.locator('input[type=checkbox]')).to_be_disabled()
        page.screenshot(path=str(args.output_dir/'audio-archive-folder.png'),full_page=True,animations='disabled')
        card.get_by_role('button',name='播放',exact=True).click()
        expect(page.locator('audio')).to_be_visible()
        page.get_by_role('button',name='Close this dialog').click()
        card.get_by_role('button',name='管理资料',exact=True).click()
        editor=page.get_by_role('dialog',name='文件设置',exact=True)
        expect(editor.get_by_role('textbox',name='自定义标签',exact=True)).to_have_count(0)
        editor.get_by_role('textbox',name='文件名称',exact=True).fill('访谈归档.wav')
        nested=next(folder for folder in folders if folder['name']=='访谈片段')
        editor.get_by_role('combobox',name='归档目录',exact=True).select_option(nested['id'])
        page.screenshot(path=str(args.output_dir/'file-settings-inherited.png'),full_page=True,animations='disabled')
        editor.get_by_role('button',name='保存修改',exact=True).click()
        expect(editor).not_to_be_visible()
        page.locator('.ckb-subfolder-card > button').first.click()
        expect(page.locator('.ckb-file-title')).to_contain_text('访谈归档.wav')
        page.get_by_role('button',name='编辑项目',exact=True).click()
        project_editor=page.get_by_role('dialog',name='项目设置',exact=True)
        project_editor.get_by_role('textbox',name='项目名称',exact=True).fill('QA 项目空间 · 已编辑')
        project_editor.get_by_role('textbox',name='项目标签',exact=True).fill('行业背景，修正标签')
        project_editor.get_by_role('button',name='保存项目设置',exact=True).click()
        expect(project_editor).not_to_be_visible()
        expect(page.locator('.ckb-directory-path')).to_contain_text('已编辑')
        page.get_by_role('tab',name='资料库',exact=True).click()
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(args.output_dir/'projects-mobile.png'),full_page=True,animations='disabled')
        assert page.evaluate('document.documentElement.scrollWidth') <= 390
        page.locator('.ckb-project-directory').filter(has_text='已编辑').locator('.ckb-project-door').click()
        expect(page.locator('.ckb-directory-path')).to_contain_text('已编辑')
        page.screenshot(path=str(args.output_dir/'project-folders-mobile.png'),full_page=True,animations='disabled')
        assert page.evaluate('document.documentElement.scrollWidth') <= 390
        page.get_by_role('button',name='新建目录',exact=True).click()
        mobile_dialog=page.get_by_role('dialog',name='新建目录',exact=True)
        expect(mobile_dialog).to_be_visible()
        page.wait_for_function('''() => {
          const panel=document.querySelector('.ckb-folder-dialog');
          const surface=panel.parentElement.querySelector('.ckb-glass-surface');
          if (!surface) return false;
          const a=panel.getBoundingClientRect(),b=surface.getBoundingClientRect();
          return Math.abs(a.left-b.left)<2 && Math.abs(a.top-b.top)<2 && Math.abs(a.width-b.width)<2;
        }''')
        page.screenshot(path=str(args.output_dir/'folder-glass-mobile.png'),full_page=True,animations='disabled')
        mobile_dialog.get_by_role('button',name='取消',exact=True).click()
        assert not errors,errors
        assert not unexpected,unexpected
        (args.output_dir/'browser-check.json').write_text(json.dumps({'errors':errors,'unexpected':unexpected,'mutations':mutations,'metrics':metrics},ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'screenshots':len(list(args.output_dir.glob('*.png'))),'errors':errors,'metrics':metrics},ensure_ascii=True))
        browser.close()
    server.shutdown();server.server_close()


if __name__=='__main__':
    main()
