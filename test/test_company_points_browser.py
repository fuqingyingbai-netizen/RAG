"""Real Vue/Element Plus and real isolated points APIs, with synthetic accounts and files."""
from datetime import timedelta
from pathlib import Path
import json
import socket
import threading
import time

import pytest
import uvicorn
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import sync_playwright, expect

import auth
import company_points as p
from company_catalog import document_store
from test_company_points import system, points_postgres_schema, doc, capture


@pytest.fixture
def browser_system(system):
    s = system
    source = doc(s, title='合成研究资料.txt')
    document_store().put_bytes(source.object_key, b'Synthetic research evidence for isolated reading tests.', 'text/plain')
    capture(s, source)
    p.process_pending(s.db)
    token_bob = auth.create_access_token('bob', 'user', 0)
    token_admin = auth.create_access_token('admin', 'admin', 0)
    root = Path(__file__).resolve().parents[1]
    s.app.mount('/assets', StaticFiles(directory=str(root / 'frontend')), name='points-test-assets')

    @s.app.get('/points-test', response_class=HTMLResponse)
    def page(mode: str = 'personal'):
        bootstrap = json.dumps({'bob': token_bob, 'admin': token_admin, 'document_id': source.id,
                                'mode': mode}, ensure_ascii=False)
        return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="/assets/vendor/element-plus-2.14.7/index.css"><link rel="stylesheet" href="/assets/knowledge-points.css">
<style>body{margin:0;font:14px system-ui;background:#f5f7fa}#test-app{padding:12px;box-sizing:border-box}.reader-test{background:#fff;padding:20px}.ckb-reader-columns{padding:16px;border:1px solid #aaa;line-height:1.8}</style>
</head><body><div id="test-app"><points-center v-if="view==='personal'" :request="request" :current-user="user"></points-center><points-admin v-if="view==='admin'" :request="request"></points-admin><reader-harness v-if="view==='reader'"></reader-harness></div>
<script src="/assets/vendor/vue-3.5.44/vue.global.prod.js"></script><script src="/assets/vendor/element-plus-2.14.7/index.full.min.js"></script><script src="/assets/knowledge-points.js"></script>
<script>const config=BOOTSTRAP;localStorage.setItem('accessToken',config.mode==='admin'?config.admin:config.bob);
const request=(path,options={})=>fetch(path,{...options,headers:{Authorization:'Bearer '+localStorage.getItem('accessToken'),...options.headers}});
const ReaderHarness={mixins:[KnowledgePointsReader],data(){return {readerOpen:false,readerLoading:false,readerOriginalLoading:false,readerMode:'original',selectedDoc:null,readerBlob:null};},methods:{apiFetch:request,async open(){this.readerOpen=true;this.readerLoading=true;this.selectedDoc={id:config.document_id,can_read:true,format:'TXT'};const response=await request('/company-knowledge/documents/'+config.document_id+'/original');if(!response.ok)throw Error('Synthetic original failed');this.readerBlob=await response.blob();this.readerLoading=false;}},template:'<section class="reader-test"><button @click="open">打开测试资料</button><div class="ckb-reader-columns" v-if="readerOpen"><p>合成研究资料，供隔离阅读测试使用。</p><p>前台阅读并与正文交互后，积分由服务端判断。</p></div><p role="status">{{pointsReaderMessage}}</p></section>'};
Vue.createApp({components:{PointsCenter,PointsAdmin,ReaderHarness},data(){return {view:config.mode,user:{username:config.mode==='admin'?'admin':'bob'}};},methods:{request}}).use(ElementPlus).mount('#test-app');</script></body></html>'''.replace('BOOTSTRAP', bootstrap)

    s.app.mount('/', StaticFiles(directory=str(root / 'frontend'), html=True), name='points-full-ui')

    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(s.app, host='127.0.0.1', port=port, log_level='error', lifespan='off'))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, 'Isolated browser server did not start'
        time.sleep(.02)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='msedge', headless=True)
        s.browser = browser
        s.url = 'http://127.0.0.1:' + str(port)
        s.output = root / 'work' / 'points-validation'
        s.output.mkdir(parents=True, exist_ok=True)
        try:
            yield s
        finally:
            browser.close()
            server.should_exit = True
            thread.join(timeout=10)
            sock.close()
            assert not thread.is_alive(), 'Owned browser server did not stop'


@pytest.mark.browser
def test_personal_points_desktop_mobile_and_all_tabs(browser_system):
    s = browser_system
    page = s.browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(s.url + '/points-test')
    expect(page.get_by_role('heading', name='知识积分中心')).to_be_visible()
    expect(page.get_by_text('累计荣誉积分', exact=True)).to_be_visible()
    page.screenshot(path=str(s.output / 'personal-desktop.png'), full_page=True)
    page.get_by_role('tab', name='积分明细', exact=True).click()
    expect(page.get_by_role('combobox', name='积分类型', exact=True)).to_be_visible()
    page.get_by_role('tab', name='排行榜', exact=True).click()
    expect(page.get_by_role('cell', name='alice', exact=True)).to_be_visible()
    page.get_by_role('tab', name='积分规则', exact=True).click()
    expect(page.get_by_role('heading', name='等级门槛')).to_be_visible()
    page.set_viewport_size({'width': 390, 'height': 844})
    page.get_by_role('tab', name='积分概览', exact=True).click()
    expect(page.get_by_role('heading', name='今日奖励进度')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(s.output / 'personal-mobile.png'), full_page=True)
    assert errors == []
    page.close()


@pytest.mark.browser
def test_admin_changes_rules_and_adjusts_with_password_confirmation(browser_system):
    s = browser_system
    page = s.browser.new_page(viewport={'width': 1366, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(s.url + '/points-test?mode=admin')
    expect(page.get_by_role('heading', name='积分管理', exact=True)).to_be_visible()
    page.get_by_role('row').filter(has_text='alice').get_by_role('button', name='补发', exact=True).click()
    dialog = page.get_by_role('dialog', name='补发荣誉积分')
    dialog.get_by_label('调整原因').fill('Synthetic browser correction')
    dialog.get_by_role('button', name='验证身份并记账').click()
    prompt = page.locator('.el-message-box')
    expect(prompt).to_be_visible()
    prompt.locator('input').fill('admin-test-password')
    prompt.get_by_role('button', name='验证并记账').click()
    expect(dialog).not_to_be_visible()
    expect(page.get_by_role('row').filter(has_text='alice')).to_contain_text('20')
    page.get_by_role('tab', name='规则设置', exact=True).click()
    page.get_by_label('积分规则变更原因').fill('Synthetic next-day policy')
    page.get_by_role('button', name='保存规则', exact=True).click()
    expect(page.get_by_text('v2 · 待生效', exact=True)).to_be_visible()
    page.screenshot(path=str(s.output / 'admin-desktop.png'), full_page=True)
    page.set_viewport_size({'width': 390, 'height': 844})
    expect(page.get_by_role('textbox', name='等级1名称', exact=True)).to_have_value('初识')
    expect(page.get_by_role('spinbutton', name='等级2积分门槛', exact=True)).to_have_value('100')
    (s.output / 'admin-input-diagnostics.json').write_text(json.dumps(page.locator('.points-level-editor input').evaluate_all(
        '(inputs)=>inputs.map(e=>({value:e.value,color:getComputedStyle(e).color,width:e.getBoundingClientRect().width}))'), ensure_ascii=False, indent=2), encoding='utf-8')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(s.output / 'admin-mobile.png'), full_page=True)
    assert errors == []
    page.close()


@pytest.mark.browser
def test_real_reader_mixin_calls_server_and_earns_only_once(browser_system):
    s = browser_system
    page = s.browser.new_page(viewport={'width': 1000, 'height': 800})
    page.clock.install()
    page.goto(s.url + '/points-test?mode=reader')
    page.get_by_role('button', name='打开测试资料').click()
    expect(page.get_by_text('有效阅读可获积分；重复打开不重复计分。', exact=True)).to_be_visible()
    page.locator('.ckb-reader-columns').click()
    for step in range(3):
        s.clock[0] += timedelta(seconds=10)
        page.clock.run_for(10000)
        expect(page.get_by_role('status')).to_contain_text('本次有效阅读 +2 分' if step == 2 else '有效阅读 ' + str((step + 1) * 10) + ' 秒')
    assert s.client.get('/points/me').json()['total'] == 2
    page.get_by_role('button', name='打开测试资料').click()
    assert s.client.get('/points/me').json()['total'] == 2
    page.screenshot(path=str(s.output / 'reader-earned.png'), full_page=True)
    page.close()


@pytest.mark.browser
def test_full_application_home_card_and_account_menu_open_real_points_page(browser_system):
    s = browser_system
    page = s.browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    token = auth.create_access_token('bob', 'user', 0)
    page.clock.install()
    page.add_init_script('localStorage.setItem("accessToken",' + json.dumps(token) + ');')
    # Research/model services are outside this test; authentication and points use real routes.
    def research(route):
        if route.request.url.split('?', 1)[0].endswith('/research/home'):
            route.fulfill(json={'user': {'username': 'bob', 'display_name': ''},
                'summary': {'total': 0, 'running': 0, 'attention': 0, 'completed': 0, 'reports': 0},
                'recent_projects': [], 'recent_reports': [], 'recent_chats': [],
                'updated_at': '2026-11-16T02:00:00Z'})
        else:
            route.fulfill(json={'projects': [], 'items': [], 'total': 0, 'summary': {}})
    page.route('**/research/**', research)
    page.goto(s.url + '/')
    card = page.get_by_role('button', name='查看我的知识积分', exact=True)
    expect(card).to_be_visible(timeout=15000)
    expect(card.locator('strong')).to_have_text('0')
    uploaded = doc(s, owner=2, visibility='restricted', title='private-poll-refresh.txt')
    capture(s, uploaded)
    p.process_pending(s.db)
    page.clock.run_for(15000)
    expect(card.locator('strong')).to_have_text('10')
    uploaded = doc(s, owner=2, confidentiality='secret', visibility='restricted', title='private-manual-refresh.txt')
    capture(s, uploaded)
    p.process_pending(s.db)
    page.get_by_role('button', name='刷新首页', exact=True).click()
    expect(card.locator('strong')).to_have_text('20')
    card.click()
    expect(page.get_by_role('heading', name='知识积分中心', exact=True)).to_be_visible()
    page.get_by_role('button', name='账号菜单：bob', exact=True).click()
    page.get_by_role('button', name='我的积分', exact=True).click()
    expect(page.get_by_role('heading', name='知识积分中心', exact=True)).to_be_visible()
    page.screenshot(path=str(s.output / 'full-application-points.png'), full_page=True)
    assert errors == []
    page.close()
