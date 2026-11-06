"""Browser regression for first paint, body heading navigation and reader zoom."""
import argparse
import io
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from threading import Thread

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from company_watermark import ExportIdentity, export_copy

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--document', type=Path)
parser.add_argument('--output-dir', type=Path, required=True)
args = parser.parse_args()
args.output_dir.mkdir(parents=True, exist_ok=True)
if args.document:
    original = args.document.read_bytes()
else:
    from docx import Document
    doc = Document()
    doc.add_paragraph('目录')
    doc.add_paragraph('管理能力与风格评价\t8')
    doc.add_page_break()
    doc.add_heading('执行总结', 1)
    for n in range(18):
        doc.add_paragraph('示例正文，用于验证连续阅读。' * 8)
    doc.add_heading('管理能力与风格评价', 1)
    doc.add_paragraph('这里是正文标题后的内容，不是目录页。')
    doc.add_heading('摘要', 2)
    doc.add_paragraph('短标题也可以定位。')
    stream = io.BytesIO()
    doc.save(stream)
    original = stream.getvalue()
sample = export_copy(original, 'DOCX', 'test.docx', ExportIdentity('preview', 1, '2026-11-06', 'reader-test'))[0]
html = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/company-knowledge-glass.css"><style>html,body{margin:0;background:#e5eaf0}#app{height:94vh;width:95vw;margin:auto}</style></head><body><div id="app"></div><script src="/vendor/vue-3.5.44/vue.global.prod.js"></script><script src="/knowledge-document-viewer.js"></script><script>fetch('/sample.docx').then(r=>r.blob()).then(blob=>{window.readerApp=Vue.createApp({components:{KnowledgeDocumentViewer},data:()=>({blob:Vue.markRaw(blob)}),template:'<knowledge-document-viewer ref="viewer" :blob="blob" format="DOCX" identity="preview" trace="test" />'}).mount('#app')})</script></body></html>'''


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT / 'frontend'), **kw)

    def do_GET(self):
        if self.path in ['/test', '/sample.docx']:
            data = html.encode() if self.path == '/test' else sample
            self.send_response(200)
            self.send_header('Content-Type', 'text/html;charset=utf-8' if self.path == '/test' else 'application/octet-stream')
            self.end_headers()
            self.wfile.write(data)
        else:
            super().do_GET()

    def log_message(self, *a):
        pass


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
Thread(target=server.serve_forever, daemon=True).start()
with sync_playwright() as pw:
    browser = pw.chromium.launch(channel='msedge', headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    try:
        page.goto('http://127.0.0.1:' + str(server.server_port) + '/test')
        page.wait_for_function('window.readerApp?.$refs.viewer?.loading===false', timeout=60000)
        assert not page.evaluate('readerApp.$refs.viewer.error')
        frame = page.frames[1]
        rect = frame.locator('section.docx').first.evaluate('e=>e.getBoundingClientRect().toJSON()')
        iframe = page.locator('iframe').bounding_box()
        shot = page.screenshot(path=str(args.output_dir / 'initial.png'))
        picture = Image.open(io.BytesIO(shot)).convert('RGB')
        point = (round(iframe['x'] + rect['x'] + 5), round(iframe['y'] + max(0, rect['y']) + 5))
        assert min(picture.getpixel(point)) >= 248, 'First paper was laid out but not painted'
        # A white cover alone is not evidence that the report body can be read.
        assert frame.locator('article').all_text_contents(), 'Missing Word body'
        page.get_by_role('button', name='跳到正文', exact=True).click()
        frame.wait_for_function("[...document.querySelectorAll('section.docx')].some(p=>(p.querySelector('article')?.textContent||'').replace(/\\s/g,'').length>160&&p.getBoundingClientRect().top>=0&&p.getBoundingClientRect().top<40)")
        page.screenshot(path=str(args.output_dir / 'body.png'))
        page.get_by_role('button', name='重排预览', exact=True).click()
        heading = page.get_by_label('Word 章节目录')
        options = heading.locator('option').all_text_contents()[1:]
        checks = []
        for width, height, scale in [(1440, 1000, 1), (1100, 800, .8), (390, 844, 1)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.evaluate('s=>document.documentElement.style.zoom=s', str(scale))
            for title in [t for t in ['综合能力分析', '管理能力与风格评价', '摘要'] if t in options]:
                heading.select_option(label=title)
                frame.wait_for_function(r'''text=>{const h=CSS.highlights.get('source');if(!h)return false;const r=[...h][0],p=r.startContainer.parentElement.closest('p'),box=r.getBoundingClientRect();return p?.textContent.replace(/\s/g,'')===text.replace(/\s/g,'')&&box.top>=0&&box.bottom<innerHeight}''', arg=title)
                assert page.evaluate('scrollY') == 0, 'Heading navigation scrolled the surrounding page'
                checks.append({'width': width, 'scale': scale, 'heading': title})
            page.get_by_label('放大文档', exact=True).click()
            page.get_by_label('缩小文档', exact=True).click()
            page.screenshot(path=str(args.output_dir / ('reader-' + str(width) + '.png')))
        assert not errors, errors
        result = {'status': 'passed', 'first_paper_visible': True, 'body_heading_checks': checks, 'zoom': True, 'javascript_errors': errors}
        (args.output_dir / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))
    finally:
        browser.close()
        server.shutdown()
