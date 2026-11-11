"""Local browser acceptance: real image/media APIs and simulated slow upload transport."""
import argparse
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from tempfile import TemporaryDirectory

os.environ['PYTHON_DOTENV_DISABLED']='1'
os.environ['DATABASE_URL']='sqlite://'
os.environ['JWT_SECRET_KEY']='local-media-acceptance-only'
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'test')]
import pytest
from PIL import Image
from playwright.sync_api import sync_playwright, expect
from test_company_workspace import setup, upload, project
from company_watermark import ffmpeg_binary, run
from company_catalog import CompanyDocument
from models import User


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output-dir',required=True,type=Path);args=parser.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix='media-acceptance-',ignore_cleanup_errors=True) as temporary:
        temp=Path(temporary);patch=pytest.MonkeyPatch();patch.setenv('COMPANY_KNOWLEDGE_MEDIA_CACHE',str(temp/'cache'))
        generator=setup.__wrapped__(patch,temp);state=next(generator)
        import company_memory
        patch.setattr(company_memory,'factory',lambda:state.db)
        for model in (company_memory.KnowledgeChatState,company_memory.KnowledgeChatThread,company_memory.KnowledgeChatMessage,company_memory.KnowledgeChatTask):
            model.__table__.create(state.db.kw['bind'])
        with state.db() as db:db.add(User(id=1,username='alice',role='user',password_hash='unused'));db.commit()
        output=io.BytesIO();image=Image.new('RGB',(1200,700),'#e5eff8')
        from PIL import ImageDraw
        ImageDraw.Draw(image).text((70,90),'KNOWLEDGE MEDIA PREVIEW / ORIGINAL IMAGE',fill='#234567');image.save(output,'PNG')
        picture=upload(state,name='original-image.png',payload=output.getvalue()).json()
        p=project(state,'影音验收项目')
        video_file=temp/'video.mp4'
        run([ffmpeg_binary(),'-nostdin','-v','error','-y','-f','lavfi','-i','color=c=steelblue:s=320x180:r=24',
             '-f','lavfi','-i','anullsrc=r=44100:cl=stereo','-t','4','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(video_file)],timeout=40)
        video=upload(state,name='playback.mp4',payload=video_file.read_bytes(),project_id=p['id']).json()
        audio_file=temp/'audio.mp3'
        run([ffmpeg_binary(),'-nostdin','-v','error','-y','-f','lavfi','-i','sine=frequency=440:duration=3','-c:a','libmp3lame',str(audio_file)],timeout=30)
        audio=upload(state,name='recording.mp3',payload=audio_file.read_bytes(),description='这是一段测试音频的人工说明。').json()
        requests=[];upload_gate=threading.Event()
        class Handler(SimpleHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if self.path=='/qa':
                    self.send_response(200);self.send_header('Content-Type','text/html;charset=utf-8');self.end_headers();self.wfile.write(html.encode());return
                if self.path.startswith('/company-knowledge/'):return self.api()
                return super().do_GET()
            def do_POST(self):self.api()
            def do_HEAD(self):
                if self.path.startswith('/company-knowledge/'):return self.api()
                return super().do_HEAD()
            def api(self):
                if self.path=='/company-knowledge/status':
                    data=json.dumps({'configured':True,'access_allowed':True,'is_admin':False,'username':'alice','account_id':1}).encode()
                    self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
                body=self.rfile.read(int(self.headers.get('Content-Length',0)))
                response=state.client.request(self.command,self.path,content=body,headers={
                    'Content-Type':self.headers.get('Content-Type','application/json'),'Cookie':self.headers.get('Cookie',''),
                    **({'Range':self.headers['Range']} if self.headers.get('Range') else {})})
                requests.append({'path':self.path,'method':self.command,'status':response.status_code,'range':self.headers.get('Range')})
                if self.path=='/company-knowledge/uploads':upload_gate.wait(30)
                self.send_response(response.status_code)
                for key,value in response.headers.items():
                    if key.lower() not in {'transfer-encoding','connection','content-encoding'}:self.send_header(key,value)
                self.end_headers()
                if self.command!='HEAD':
                    try:self.wfile.write(response.content)
                    except (BrokenPipeError,ConnectionAbortedError,ConnectionResetError):pass
        html='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="/vendor/element-plus-2.14.7/index.css"><link rel="stylesheet" href="/company-knowledge.css"><link rel="stylesheet" href="/company-knowledge-glass.css"><link rel="stylesheet" href="/knowledge-workspace.css">
<style>body{margin:0;background:#eef3fa;font-family:system-ui,sans-serif}</style></head><body><div id="app"><company-knowledge ref="knowledge"/></div>
<script src="/vendor/vue-3.5.44/vue.global.prod.js"></script><script src="/vendor/element-plus-2.14.7/index.full.min.js"></script><script src="/knowledge-glass-optics.js"></script><script src="/knowledge-document-viewer.js"></script><script src="/company-knowledge.js"></script>
<script>localStorage.setItem('accessToken','acceptance-user');const a=Vue.createApp({components:{CompanyKnowledge}});a.use(ElementPlus);window.app=a.mount('#app');</script></body></html>'''
        server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(ROOT/'frontend')))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        errors=[]
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True,channel='msedge');page=browser.new_page(viewport={'width':1440,'height':1000})
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}/qa');page.wait_for_function('window.app?.$refs.knowledge.service.configured')
            def open_doc(row):page.evaluate('(doc)=>app.$refs.knowledge.openDocument(doc)',row)
            open_doc(picture);expect(page.locator('.ckb-image-canvas img')).to_be_visible()
            assert page.locator('.ckb-image-canvas img').evaluate('(e)=>e.naturalWidth')==1200
            expect(page.get_by_role('button',name='下载',exact=True)).to_be_visible()
            page.get_by_role('button',name='放大图片').click();expect(page.locator('.ckb-image-controls')).to_contain_text('125%')
            page.screenshot(path=str(args.output_dir/'image-desktop.png'),full_page=True)
            page.evaluate('app.$refs.knowledge.readerOpen=false');page.wait_for_timeout(350)
            open_doc(video)
            try:page.wait_for_function('document.querySelector("video")?.readyState>=2',timeout=45000)
            except Exception:
                page.screenshot(path=str(args.output_dir/'video-failure.png'),full_page=True)
                (args.output_dir/'video-failure.json').write_text(json.dumps({'requests':requests,'errors':errors,'state':page.evaluate('({url:app.$refs.knowledge.readerUrl,error:app.$refs.knowledge.readerOriginalError,message:app.$refs.knowledge.readerMediaMessage,video:document.querySelector("video")?.error?.code,cookie:document.cookie})')},ensure_ascii=False,indent=2),encoding='utf-8')
                raise
            assert page.locator('video').evaluate('(e)=>e.duration')>3
            assert page.get_by_placeholder('搜索解析文字（含扫描件识别文字）…').count()==0
            assert page.locator('#ckb-reader-question-input').count()==0
            expect(page.get_by_role('button',name='补充说明',exact=True)).to_be_visible()
            sidebar=page.locator('.ckb-reader-question').bounding_box();assert sidebar['height']<500
            page.locator('video').evaluate('(e)=>{e.currentTime=2;e.play()}')
            page.wait_for_function('document.querySelector("video").currentTime>2.1')
            page.locator('video').evaluate('(e)=>e.pause()')
            page.screenshot(path=str(args.output_dir/'video-desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(args.output_dir/'video-mobile.png'),full_page=True)
            page.set_viewport_size({'width':1440,'height':1000});page.evaluate('app.$refs.knowledge.readerOpen=false');page.wait_for_timeout(350)
            open_doc(audio);page.wait_for_function('document.querySelector("audio")?.readyState>=2',timeout=30000)
            expect(page.get_by_text('根据文字说明提问',exact=True)).to_be_visible()
            page.screenshot(path=str(args.output_dir/'audio-desktop.png'),full_page=True)
            page.evaluate('app.$refs.knowledge.readerOpen=false');page.wait_for_timeout(350)
            # Throttle a real multipart XHR; hold its receipt after the real server saves it.
            cdp=page.context.new_cdp_session(page)
            cdp.send('Network.enable')
            cdp.send('Network.emulateNetworkConditions',{'offline':False,'latency':50,'downloadThroughput':10*1024*1024,'uploadThroughput':512*1024})
            page.evaluate("""()=>{const c=app.$refs.knowledge;c.startUpload();c.uploadForm.department='market';c.stagedFiles=[new File([new Uint8Array(2*1024*1024).fill(65)],'slow.txt')];c.uploadFiles()}""")
            expect(page.locator('.ckb-upload-progress')).to_be_visible()
            page.get_by_role('button',name='收起，继续操作',exact=True).click();expect(page.locator('.ckb-upload-tray')).to_be_visible()
            page.locator('.ckb-upload-tray').click()
            page.wait_for_function('app.$refs.knowledge.uploadCurrent?.saving')
            expect(page.locator('.ckb-upload-progress')).to_contain_text('服务器正在保存')
            page.screenshot(path=str(args.output_dir/'upload-desktop.png'),full_page=True)
            upload_gate.set()
            page.wait_for_function('!app.$refs.knowledge.uploadBusy')
            assert not errors,errors
            browser.close()
        server.shutdown();state.client.close();generator.close();patch.undo()
        result={'browser_errors':errors,'requests':requests,'checks':['original image decoded','image zoom','video metadata and playback','video seek','audio playback','media-specific controls','compact sidebar','upload minimize/reopen','no browser exceptions']}
        (args.output_dir/'browser.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'checks':len(result['checks']),'browser_errors':errors,'output':str(args.output_dir)},ensure_ascii=False))


if __name__=='__main__':main()
