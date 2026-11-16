"""Actual released Vue surface with controlled slow catalogue responses, no production data."""
import json
import re
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect
import auth
from test_company_points import system, points_postgres_schema
from test_company_points_browser import browser_system


@pytest.mark.browser
@pytest.mark.parametrize('outcome', ['file', 'empty', 'error'])
def test_directory_with_subfolders_explains_wait_and_resolves_loading(browser_system, outcome):
    s = browser_system
    page = s.browser.new_page(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    token = auth.create_access_token('bob', 'user', 0)
    view = {'mode': 'library', 'projectDisplay': 'contents', 'activeProjectId': 'p'}
    page.add_init_script('localStorage.setItem("accessToken",'+json.dumps(token)+');localStorage.setItem("activeView","company-knowledge");localStorage.setItem("companyKnowledgeView:bob",'+json.dumps(json.dumps(view))+');')
    pending = []
    project = {'id':'p','name':'加载状态合成项目','category':'项目原件','owner':'bob','owner_user_id':2,'can_manage':True,'can_read':True,'department':'market','document_count':1,'folder_count':1,'confidentiality':'internal','visibility':'members','tags':[]}
    folder = {'id':'folder','name':'合成子目录','project_id':'p','parent_id':''}
    def kb(route):
        path = urlparse(route.request.url).path
        if path == '/company-knowledge/documents':
            pending.append(route)
            return
        if path.endswith('/status'):
            route.fulfill(json={'configured':True,'access_allowed':True,'username':'bob','is_admin':False})
        elif path.endswith('/projects'):
            route.fulfill(json={'projects':[project],'folders':[folder]})
        else:
            route.fulfill(json={'documents':[],'notes':[],'projects':[],'folders':[],'sessions':[],'messages':[],'requests':[],'total_count':0})
    page.route('**/company-knowledge/**', kb)
    def research(route):
        if urlparse(route.request.url).path.endswith('/home'):
            route.fulfill(json={'user':{'username':'bob'},'summary':{'total':0,'running':0,'completed':0,'attention':0},'recent_projects':[],'recent_reports':[]})
        else:
            route.fulfill(json={'projects':[],'items':[],'total':0})
    page.route('**/research/**', research)
    page.goto(s.url+'/', wait_until='domcontentloaded')
    page.get_by_role('button',name='打开公司知识库',exact=True).click()
    page.get_by_role('button',name=re.compile('加载状态合成项目')).click()
    expect(page.get_by_role('heading', name=project['name'], exact=True)).to_be_visible()
    expect(page.get_by_text('合成子目录', exact=True)).to_be_visible()
    loading = page.get_by_text('正在加载当前目录的资料，请稍候…', exact=True)
    expect(loading).to_be_visible()
    expect(page.locator('.ckb-document-table')).to_have_attribute('aria-busy','true')
    expect(page.get_by_text('当前目录暂无资料。', exact=True)).to_have_count(0)
    assert page.locator('.ckb-loading-spinner').first.evaluate('e=>getComputedStyle(e).animationName') == 'none'
    page.screenshot(path=str(s.output/('directory-loading-'+outcome+'.png')), full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    expect(loading).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert len(pending) == 1
    document = {'id':'loaded-file','title':'合成资料.txt','format':'TXT','size':30,'state':'ready','can_read':True,'can_manage':True,'category':'项目原件','knowledge_project_id':'p','folder_id':'','owner':'bob','version':1,'is_current':True,'confidentiality':'internal','visibility':'members','tags':[],'date':'2026/11/16','modified_at':'2026-11-16T06:00:00Z'}
    if outcome == 'error':
        pending.pop().fulfill(status=503,json={'detail':'合成资料请求失败，请重试'})
        expect(page.get_by_role('alert').filter(has_text='合成资料请求失败')).to_be_visible()
    else:
        pending.pop().fulfill(json={'documents':[document] if outcome=='file' else [],'total_count':1 if outcome=='file' else 0})
        if outcome == 'file':
            expect(page.get_by_text(document['title'],exact=True)).to_be_visible()
            expect(page.locator('.ckb-document-table')).to_have_attribute('aria-busy','false')
            page.get_by_role('button',name='刷新',exact=True).click()
            expect(page.get_by_text('正在更新资料，已加载的内容仍可查看…',exact=True)).to_be_visible()
            expect(page.get_by_text(document['title'],exact=True)).to_be_visible()
            expect(page.locator('.ckb-catalogue-skeleton')).to_have_count(0)
            assert len(pending)==1
            pending.pop().fulfill(json={'documents':[document],'total_count':1})
            expect(page.get_by_text('正在更新资料，已加载的内容仍可查看…',exact=True)).to_have_count(0)
    expect(loading).to_have_count(0)
    assert errors == []
    page.close()
