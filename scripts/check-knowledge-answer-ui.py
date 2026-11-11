"""Loopback-only browser checks for the real answer renderer; no business data."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import threading

from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    source=(ROOT/'frontend/company-knowledge.js').read_text(encoding='utf-8')
    answer=re.search(r'<div class="ckb-live-answer ckb-answer-markdown"[^>]+></div>',source)[0]
    html='''<!doctype html><html lang="zh-CN" data-knowledge-theme="light"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>知识库回答显示验收</title>
<link rel="stylesheet" href="company-knowledge.css"><link rel="stylesheet" href="knowledge-workspace.css">
<style>body{margin:0;padding:24px;background:var(--ku-day-surface-soft);font-family:Arial,"Microsoft YaHei",sans-serif}#app.ckb-workbench{max-width:900px;margin:0 auto}.ckb-message{margin:0;background:var(--ku-day-surface);border:1px solid var(--ku-day-line);border-radius:14px;padding:24px}.ckb-answer-heading{margin-bottom:20px;color:var(--ku-day-ink-strong)}@media(max-width:600px){body{padding:12px}.ckb-message{padding:18px}}</style>
<main id="app" class="ckb-workbench"><article class="ckb-message ckb-message-assistant">
<div class="ckb-answer-heading"><span>知识助手</span><small>回答完成</small></div>
<div v-if="legacy" class="ckb-live-answer">{{message.text}}</div><template v-else>'''+answer+'''</template>
</article></main>
<script src="vendor/vue-3.5.44/vue.global.prod.js"></script><script src="vendor/marked-18.1.2/marked.umd.js"></script>
<script src="vendor/purify-3.4.17.min.js"></script><script src="safe-markdown.js"></script><script src="company-knowledge.js"></script>
<script>window.qa=Vue.createApp({data(){return {legacy:true,message:{text:'',references:[]}}},methods:{renderAnswer:CompanyKnowledge.methods.renderAnswer,openAnswerCitation:CompanyKnowledge.methods.openAnswerCitation,openCitation(group){window.openedCitation=group}}}).mount('#app');</script></html>'''
    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path=='/':
                payload=html.encode();self.send_response(200);self.send_header('Content-Type','text/html;charset=utf-8')
                self.end_headers();self.wfile.write(payload)
            else:super().do_GET()
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(ROOT/'frontend')))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    text='''## 项目摘要（基于本轮资料）

### 一、项目背景
- 封装技术用于安放、固定、密封和保护芯片，并连接芯片内部与外部电路[id_1][id_2]。
- 三维封装的具体技术效果需要逐项核对资料，**不能把目标写成已经实现**[id_1]。

### 二、核心业务与技术内容
- 专利提供一种塑封材料过孔结构，包括金属焊盘、金属层和介质层[id_2]。
- 未披露的参数应标为未找到依据，不根据相邻产品补齐[id_11]。

### 三、数据核对
| 指标 | 数值 | 来源 |
| --- | --- | --- |
| 样本数量 | 120 个 | [id_1] |
| 对应期间 | 未找到依据 | [id_2] |
'''
    references=[{'id':str(i),'title':'测试资料（同名）','document_id':'file-'+str(i)} for i in (1,2,11)]
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1080});errors=[];external=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('request',lambda request:external.append(request.url) if not request.url.startswith('http://127.0.0.1:') else None)
        page.goto('http://127.0.0.1:'+str(server.server_port));page.wait_for_function('window.qa')
        page.evaluate('(message)=>qa.message=message',{'text':text,'references':references})
        page.screenshot(path=str(args.output_dir/'before.png'),full_page=True)
        page.evaluate('qa.legacy=false')
        body=page.locator('.ckb-answer-markdown')
        expect(body.locator('h2')).to_have_text('项目摘要（基于本轮资料）')
        expect(body.locator('h3')).to_have_count(3);expect(body.locator('li')).to_have_count(4)
        expect(body.locator('table tbody tr')).to_have_count(2)
        assert '[id_' not in body.inner_text() and '###' not in body.inner_text()
        page.screenshot(path=str(args.output_dir/'desktop.png'),full_page=True)
        body.get_by_role('button',name='查看来源 1：测试资料（同名）',exact=True).first.click()
        assert page.evaluate('window.openedCitation.references[0].id')=='1'
        target=body.get_by_role('button',name='查看来源 11：测试资料（同名）',exact=True)
        target.focus();page.keyboard.press('Enter')
        assert page.evaluate('window.openedCitation.references[0].id')=='11'
        assert page.evaluate('window.openedCitation.document_id')=='file-11'
        page.set_viewport_size({'width':390,'height':980})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(args.output_dir/'mobile.png'),full_page=True)
        page.evaluate("document.documentElement.dataset.knowledgeTheme='dark'")
        page.screenshot(path=str(args.output_dir/'dark.png'),full_page=True)
        payload='## 安全核对\n<img src="https://invalid.example/exfil" onerror="window.PWNED=1"><script>window.PWNED=2</script>\n[危险链接](javascript:alert(1))\n[id_99]\n\n```text\n[id_1]\n<img src=x onerror=attack()>\n```'
        page.evaluate('(message)=>qa.message=message',{'text':payload,'references':references})
        expect(body.locator('img,script,svg,[onerror],a[href^="javascript:"]')).to_have_count(0)
        expect(body).to_contain_text('[未核验引用 99]');expect(body.locator('button')).to_have_count(0)
        expect(body.locator('code')).to_contain_text('[id_1]')
        assert page.evaluate('window.PWNED===undefined')
        page.evaluate('(message)=>qa.message=message',{'text':'## 流式标题\n\n','references':references})
        for part in ['- 第一条','资料[id_1]\n','- 第二条资料','[id_2]。']:
            page.evaluate('(part)=>qa.message.text+=part',part)
        expect(body.locator('li')).to_have_count(2);expect(body.locator('button')).to_have_count(2)
        performance=page.evaluate('''(text)=>{const message={text,references:qa.message.references};qa.renderAnswer(message);const start=performance.now();for(let i=0;i<1000;i++)qa.renderAnswer(message);return {cached_1000_renders_ms:performance.now()-start};}''',text)
        touch=browser.new_page(viewport={'width':390,'height':980},is_mobile=True,has_touch=True)
        touch.goto(page.url);touch.wait_for_function('window.qa')
        touch.evaluate('(message)=>{qa.message=message;qa.legacy=false}',{'text':text,'references':references})
        touch_button=touch.locator('.ckb-inline-citation').first
        expect(touch_button).to_be_visible()
        assert touch_button.bounding_box()['height']>=44
        assert touch.evaluate('document.documentElement.scrollWidth<=innerWidth')
        touch.screenshot(path=str(args.output_dir/'touch-mobile.png'),full_page=True)
        assert not errors and not external,(errors,external)
        result={'status':'passed','checks':['headings/lists/emphasis/tables','exact fragment citation by mouse/keyboard','390px no page overflow','light/dark','untrusted HTML/URL/image isolation','unknown citation visibly unverified','code sample unchanged','streaming updates','cached repeated render'],
            'performance':performance,'console_errors':errors,'external_requests':external}
        (args.output_dir/'browser-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False),flush=True);browser.close()
    server.shutdown();server.server_close()


if __name__=='__main__':main()
