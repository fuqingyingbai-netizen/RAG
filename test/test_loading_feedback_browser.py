"""Slow responses, tab races and page jumps in the real released application UI."""
import io
import json
import re
import time
from urllib.parse import urlparse,parse_qs
import pytest
from PIL import Image,ImageDraw
from playwright.sync_api import expect
import auth
from test_company_points import system,points_postgres_schema
from test_company_points_browser import browser_system

def begin(s,scenario,admin=False):
    page=s.browser.new_page(viewport={'width':1440,'height':1000},reduced_motion='reduce')
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    name='admin' if admin else 'bob';token=auth.create_access_token(name,'admin' if admin else 'user',0)
    page.add_init_script('localStorage.setItem("accessToken",'+json.dumps(token)+');')
    project={'id':'p','name':'合成加载回归项目','category':'项目经验' if scenario.startswith('notes') else '项目原件','owner':name,'owner_user_id':4 if admin else 2,'can_manage':True,'can_read':True,'department':'market','document_count':1 if scenario=='pdf' else 0,'folder_count':0,'confidentiality':'internal','visibility':'members','tags':[]}
    doc={'id':'pdf-check','title':'合成24页.pdf','format':'PDF','size':100,'state':'ready','can_read':True,'can_manage':True,'has_original':True,'category':'项目原件','knowledge_project_id':'p','folder_id':'','owner':name,'is_owner':True,'version':1,'is_current':True,'confidentiality':'internal','visibility':'members','tags':[],'date':'2026/11/16'}
    pending={};image=Image.new('RGB',(960,540),'white');ImageDraw.Draw(image).text((40,40),'Synthetic readable page / private preview test',fill='black');body=io.BytesIO();image.save(body,'PNG')
    def hold(key,route):pending.setdefault(key,[]).append(route)
    def kb(route):
        path=urlparse(route.request.url).path
        if scenario.startswith('notes') and path.endswith('/notes'):hold('notes',route);return
        if scenario=='chat' and '/conversations' in path:hold('chat',route);return
        if scenario=='recycle' and path.endswith('/recycle-bin'):route.fulfill(status=503,json={'detail':'合成回收站读取失败'});return
        if scenario=='pdf' and path.endswith('/page'):
            number=int(parse_qs(urlparse(route.request.url).query)['page'][0]);assert route.request.headers.get('accept')=='image/webp'
            if number!=1:hold(str(number),route);return
            route.fulfill(body=body.getvalue(),headers={'Content-Type':'image/png','X-Document-Pages':'24'});return
        if path.endswith('/status'):data={'configured':True,'access_allowed':True,'username':name,'is_admin':admin}
        elif path.endswith('/projects'):data={'projects':[project],'folders':[]}
        elif path.endswith('/documents'):data={'documents':[doc] if scenario=='pdf' else [],'total_count':1 if scenario=='pdf' else 0}
        elif path.endswith('/preview'):data={'references':[],'total':0}
        else:data={'documents':[],'notes':[],'projects':[],'folders':[],'sessions':[],'messages':[],'requests':[],'entries':[],'total_count':0}
        route.fulfill(json=data)
    page.route('**/company-knowledge/**',kb)
    page.route('**/points/read-sessions',lambda r:r.fulfill(json={'eligible':False,'reason':'隔离回归不计积分'}))
    def research(route):
        data={'user':{'username':name},'summary':{'total':0,'running':0,'completed':0,'attention':0},'recent_projects':[],'recent_reports':[]} if urlparse(route.request.url).path.endswith('/home') else {'projects':[],'items':[],'total':0}
        route.fulfill(json=data)
    page.route('**/research/**',research)
    page.goto(s.url+'/',wait_until='domcontentloaded')
    return page,pending,body.getvalue(),errors

def close(page,pending,errors):
    assert not errors,errors
    for routes in pending.values():
        for route in routes:
            try:route.abort()
            except Exception:pass
    page.close()

@pytest.mark.browser
@pytest.mark.parametrize('outcome',['success','failure'])
def test_personal_notes_wait_for_their_own_response(browser_system,outcome):
    page,pending,_,errors=begin(browser_system,'notes-'+outcome)
    page.get_by_role('button',name='打开公司知识库',exact=True).click()
    page.get_by_role('tab',name='经验沉淀',exact=True).click();page.get_by_role('button',name=re.compile('^我的笔记')).click()
    expect(page.get_by_text('正在加载笔记，请稍候…',exact=True)).to_be_visible()
    expect(page.locator('.ckb-table-empty')).to_have_count(0)
    assert pending['notes']
    if outcome=='success':
        pending['notes'].pop().fulfill(json={'notes':[{'id':'n','title':'迟到的合成笔记','project_id':'p','folder_id':'','revision':1,'index_state':'draft','updated_at':'2026-11-16T06:00:00Z'}]})
        expect(page.get_by_text('迟到的合成笔记',exact=True)).to_be_visible()
    else:
        pending['notes'].pop().fulfill(status=503,json={'detail':'合成笔记读取失败'})
        expect(page.get_by_role('alert').filter(has_text='合成笔记读取失败')).to_be_visible()
        expect(page.locator('.ckb-table-empty')).to_have_count(0)
    expect(page.get_by_text('正在加载笔记，请稍候…',exact=True)).to_have_count(0)
    close(page,pending,errors)

@pytest.mark.browser
def test_history_explains_session_list_and_message_reads(browser_system):
    page,pending,_,errors=begin(browser_system,'chat')
    page.get_by_role('button',name='打开公司知识库',exact=True).click();page.get_by_role('tab',name='智能问答',exact=True).click()
    expect(page.get_by_text('正在读取研究历史…',exact=True)).to_be_visible()
    expect(page.locator('.ckb-session-empty')).to_have_count(0);expect(page.locator('.ckb-chat-welcome')).to_have_count(0)
    snapshot={'sessions':[{'id':'old-session','title':'合成历史对话'}],'messages':[],'scope':'accessible','document_ids':[]}
    for route in pending['chat'][:]:route.fulfill(json=snapshot)
    pending['chat'].clear()
    expect(page.locator('.ckb-session-list button')).to_be_visible()
    page.locator('.ckb-session-list button').click()
    expect(page.get_by_text('正在读取对话内容，请稍候…',exact=True)).to_be_visible()
    expect(page.locator('.ckb-chat-welcome')).to_have_count(0)
    pending['chat'].pop().fulfill(json={**snapshot,'session_id':'old-session','messages':[{'id':1,'role':'user','text':'以前保存的问题','complete':True,'references':[]}]})
    expect(page.get_by_text('以前保存的问题',exact=True)).to_be_visible();expect(page.get_by_text('正在读取对话内容，请稍候…',exact=True)).to_have_count(0)
    close(page,pending,errors)

@pytest.mark.browser
def test_invitation_tab_keeps_loading_after_users_reply(browser_system):
    page,pending,_,errors=begin(browser_system,'account',admin=True)
    def accounts(route):pending.setdefault('users' if urlparse(route.request.url).path.endswith('/users') else 'invites',[]).append(route)
    page.route('**/admin/users?*',accounts);page.route('**/admin/invitations?*',accounts)
    page.get_by_role('menuitem',name='账号管理',exact=True).click()
    expect(page.locator('.account-management .el-loading-mask').first).to_be_visible()
    page.get_by_role('tab',name='邀请管理',exact=True).click()
    panel=page.get_by_role('tabpanel',name='邀请管理',exact=True)
    expect(panel.locator('.el-loading-mask')).to_be_visible()
    pending['users'].pop().fulfill(json={'items':[],'total':0,'active_admin_count':1})
    expect(panel.locator('.el-loading-mask')).to_be_visible()
    expect(panel.get_by_text('正在读取邀请…',exact=True)).to_be_visible()
    assert pending['invites']
    pending['invites'].pop().fulfill(json={'items':[],'total':0})
    expect(panel.locator('.el-loading-mask')).to_have_count(0)
    expect(panel.get_by_text('暂无邀请，点击上方按钮生成',exact=True)).to_be_visible()
    close(page,pending,errors)

@pytest.mark.browser
def test_recycle_read_failure_never_claims_empty(browser_system):
    page,pending,_,errors=begin(browser_system,'recycle')
    page.get_by_role('button',name='打开公司知识库',exact=True).click();page.get_by_role('button',name='回收站',exact=True).click()
    expect(page.get_by_text('合成回收站读取失败',exact=False)).to_be_visible()
    expect(page.get_by_text('回收站为空。',exact=True)).to_have_count(0)
    close(page,pending,errors)

@pytest.mark.browser
@pytest.mark.parametrize('admin',[False,True])
def test_points_tabs_have_readable_waiting_status(browser_system,admin):
    page,pending,_,errors=begin(browser_system,'points',admin=admin)
    endpoint='**/admin/points/rules' if admin else '**/points/leaderboard?*'
    page.route(endpoint,lambda r:pending.setdefault('points',[]).append(r))
    if admin:
        page.get_by_role('menuitem',name='账号管理',exact=True).click();page.get_by_role('tab',name='积分管理',exact=True).click()
        expect(page.locator('.points-admin .points-table tbody tr').first).to_be_visible()
        page.locator('.points-admin').get_by_role('tab',name='规则设置',exact=True).click()
    else:
        page.get_by_role('button',name='查看我的知识积分',exact=True).click();expect(page.locator('.points-summary')).to_be_visible()
        page.get_by_role('tab',name='排行榜',exact=True).click()
    status=page.get_by_text('正在读取积分管理数据，请稍候…' if admin else '正在读取积分页面，请稍候…',exact=True)
    expect(status).to_be_visible()
    deadline=time.monotonic()+5
    while not pending.get('points') and time.monotonic()<deadline:page.wait_for_timeout(25)
    assert pending['points']
    page.set_viewport_size({'width':390,'height':844});expect(status).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    route=pending['points'].pop();route.fulfill(response=route.fetch());expect(status).to_have_count(0)
    close(page,pending,errors)

@pytest.mark.browser
def test_pdf_jump_displays_target_without_waiting_for_offscreen_body(browser_system):
    page,pending,image,errors=begin(browser_system,'pdf');cancelled=[]
    page.on('requestfailed',lambda r:cancelled.append(r.url) if '/page?page=' in r.url else None)
    page.get_by_role('button',name='打开公司知识库',exact=True).click()
    page.get_by_role('button',name=re.compile('合成加载回归项目')).click()
    page.get_by_role('button',name='阅读',exact=True).click()
    expect(page.locator('.ckb-pdf-sheet[data-page="1"] img')).to_be_visible()
    expect(page.get_by_text(re.compile('第 2 页 · 正在加载'))).to_be_visible()
    page.get_by_role('spinbutton',name='跳转到页码',exact=True).fill('24');page.get_by_role('spinbutton',name='跳转到页码',exact=True).press('Enter')
    expect(page.get_by_text(re.compile('第 24 页 · 正在加载'))).to_be_visible(timeout=3000)
    assert pending['24'];pending['24'].pop().fulfill(body=image,headers={'Content-Type':'image/png'})
    expect(page.locator('.ckb-pdf-sheet[data-page="24"] img')).to_be_visible(timeout=3000)
    assert cancelled,'Offscreen response must be cancelled before page 24 is read'
    close(page,pending,errors)
