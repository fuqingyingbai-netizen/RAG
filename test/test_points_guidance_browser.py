"""Full released Vue shell; isolated points DB and synthetic knowledge responses only."""
from pathlib import Path
import json,time
from urllib.parse import urlparse
import pytest
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import expect
import auth
from test_company_points import system,points_postgres_schema
from test_company_points_browser import browser_system

@pytest.fixture
def guidance(browser_system):
    s=browser_system
    root=Path(__file__).resolve().parents[1]
    runtime=root/'work/points-guidance-release-20261119/runtime/frontend'
    assert runtime.is_dir(),'Build the verified frontend snapshot with build_assets.py first'
    s.app.routes[-1].app=StaticFiles(directory=runtime,html=True)
    page=s.browser.new_page(viewport={'width':1440,'height':1000},reduced_motion='reduce')
    errors=[];writes=[];state={'fail_points':False,'uploaded':False,'upload_failure':False,'point_reads':0}
    page.on('pageerror',lambda e:errors.append(str(e)))
    token=auth.create_access_token('bob','user',0)
    page.add_init_script('localStorage.setItem("accessToken",'+json.dumps(token)+');')
    project={'id':'guide-project','name':'合成快捷入口项目','category':'项目原件','owner':'bob','owner_user_id':2,'can_manage':True,'can_read':True,'department':'market','document_count':0,'folder_count':0,'confidentiality':'internal','visibility':'members','tags':[]}
    doc={'id':'guide-upload','title':'合成上传.txt','format':'TXT','size':80,'state':'ready','label':'已可检索','status_message':'入库完成','can_read':True,'can_manage':True,'has_original':True,'category':'项目原件','department':'market','knowledge_project_id':'','folder_id':'','owner':'bob','is_owner':True,'version':1,'is_current':True,'confidentiality':'internal','visibility':'members','tags':[],'date':'2026/11/19'}
    def route(req):
        path=urlparse(req.request.url).path
        if path=='/points/me':
            state['point_reads']+=1
            if state['fail_points']:req.fulfill(status=503,json={'detail':'合成积分服务暂不可用'});return
            req.continue_();return
        if path=='/research/home':req.fulfill(json={'user':{'username':'bob'},'summary':{'total':0,'running':0,'completed':0,'attention':0},'recent_projects':[],'recent_reports':[],'updated_at':'2026-11-19T04:00:00Z'});return
        if path.startswith('/company-knowledge/'):
            if req.request.method!='GET':
                writes.append({'method':req.request.method,'path':path})
                if path=='/company-knowledge/uploads':
                    if state['upload_failure']:req.fulfill(status=503,json={'detail':'合成上传失败，请重试'});return
                    state['uploaded']=True;req.fulfill(status=202,json=doc);return
                req.abort();return
            if path.endswith('/status'):data={'configured':True,'access_allowed':True,'username':'bob','account_id':2,'is_admin':False}
            elif path.endswith('/projects'):data={'projects':[project],'folders':[]}
            elif path.endswith('/documents'):data={'documents':[doc] if state['uploaded'] else [],'total_count':1 if state['uploaded'] else 0}
            elif path.endswith('/my-projects'):data={'project_count':1,'document_count':0,'projects':[project]}
            else:data={'notes':[],'sessions':[],'messages':[],'requests':[],'events':[],'documents':[],'total':0}
            req.fulfill(json=data);return
        if path.startswith('/research/'):req.fulfill(json={'projects':[],'items':[],'total':0});return
        req.continue_()
    page.route('**/*',route)
    s.output=root/'work/points-guidance-release-20261119/browser'
    s.output.mkdir(exist_ok=True)
    try:yield s,page,state,errors,writes
    finally:
        page.close()
        assert not errors,errors

def start(s,page):
    page.goto(s.url,wait_until='domcontentloaded')
    expect(page.locator('.points-home-card')).to_be_visible(timeout=15000)

@pytest.mark.browser
@pytest.mark.parametrize('width,color',[(1440,'light'),(390,'light'),(375,'light'),(390,'dark')])
def test_home_card_layout_and_independent_buttons(guidance,width,color):
    s,page,state,errors,writes=guidance
    page.set_viewport_size({'width':width,'height':900});page.emulate_media(color_scheme=color)
    start(s,page);card=page.locator('.points-home-card')
    expect(card.locator('.points-home-score')).to_be_visible()
    for name in ['去阅读资料','上传资料','查看积分']:
        button=card.get_by_role('button',name=name,exact=True)
        box=button.bounding_box();assert box['height']>=44
        assert button.evaluate('(b)=>{const r=b.getBoundingClientRect();return b.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert card.locator('button button').count()==0
    page.screenshot(path=str(s.output/f'home-{width}-{color}.png'),full_page=True)
    assert writes==[]

@pytest.mark.browser
def test_home_stale_failure_and_retry_keep_navigation_available(guidance):
    s,page,state,errors,writes=guidance;start(s,page)
    card=page.locator('.points-home-card');expect(card.locator('.points-home-score')).to_be_visible()
    old=card.locator('.points-home-score').inner_text();state['fail_points']=True
    page.get_by_role('button',name='刷新首页',exact=True).click()
    expect(card.get_by_text('刷新失败，显示上次积分。',exact=False)).to_be_visible()
    assert card.locator('.points-home-score').inner_text()==old
    state['fail_points']=False;card.get_by_role('button',name='重试积分',exact=True).click()
    expect(card.get_by_role('button',name='重试积分',exact=True)).to_have_count(0)
    card.get_by_role('button',name='去阅读资料',exact=True).click()
    expect(page.get_by_role('tab',name='总资料库',exact=False)).to_have_attribute('aria-selected','true')
    assert writes==[]

@pytest.mark.browser
def test_initial_points_failure_does_not_block_upload_entry(guidance):
    s,page,state,errors,writes=guidance;state['fail_points']=True;start(s,page)
    expect(page.get_by_text('积分暂不可用，仍可正常阅读和上传。',exact=False)).to_be_visible()
    page.locator('.points-home-card').get_by_role('button',name='上传资料',exact=True).click()
    expect(page.get_by_role('dialog',name='上传文件',exact=True)).to_be_visible()
    assert writes==[]

@pytest.mark.browser
@pytest.mark.parametrize('kind,label',[('read','去阅读'),('upload','去上传'),('note','去写笔记')])
def test_points_center_shortcuts_and_existing_tabs(guidance,kind,label):
    s,page,state,errors,writes=guidance;start(s,page)
    page.get_by_role('button',name='查看积分',exact=False).click()
    expect(page.get_by_role('heading',name='积分中心',exact=True)).to_be_visible()
    expect(page.get_by_text('尽调任务暂不计分。',exact=False)).to_be_visible()
    for tab in ['积分明细','排行榜','积分规则','积分概览']:
        page.get_by_role('tab',name=tab,exact=True).click()
    page.get_by_role('button',name=label,exact=True).click()
    if kind=='upload':expect(page.get_by_role('dialog',name='上传文件',exact=True)).to_be_visible()
    elif kind=='note':expect(page.get_by_role('button',name='新建图文笔记',exact=True)).to_be_visible()
    else:expect(page.get_by_role('tab',name='总资料库',exact=False)).to_have_attribute('aria-selected','true')
    assert writes==[],'Opening notes or upload must not create any content'

@pytest.mark.browser
@pytest.mark.parametrize('failure',[False,True])
def test_upload_feedback_only_after_a_saved_receipt(guidance,failure):
    s,page,state,errors,writes=guidance;state['upload_failure']=failure;start(s,page)
    page.locator('.points-home-card').get_by_role('button',name='上传资料',exact=True).click()
    dialog=page.get_by_role('dialog',name='上传文件',exact=True)
    dialog.get_by_label('选择上传资料',exact=True).set_input_files({'name':'合成上传.txt','mimeType':'text/plain','buffer':b'Synthetic knowledge contribution for isolated UI checks.'})
    dialog.get_by_role('button',name='上传并归档',exact=True).click()
    expect(dialog.get_by_role('alert')).to_contain_text('请选择所属部门')
    assert writes==[],'A shortcut must preserve the existing required department validation'
    dialog.get_by_role('combobox',name='上传所属部门／栏目',exact=True).select_option('market')
    dialog.get_by_role('button',name='上传并归档',exact=True).click()
    if failure:
        expect(dialog.get_by_text('合成上传失败，请重试',exact=True)).to_be_visible()
        expect(dialog.get_by_role('button',name='查看积分处理结果',exact=True)).to_have_count(0)
    else:
        expect(dialog.get_by_text('上传成功不等于积分已到账。',exact=False)).to_be_visible()
        page.screenshot(path=str(s.output/'upload-feedback.png'),full_page=True)
        dialog.get_by_role('button',name='查看积分处理结果',exact=True).click()
        expect(page.get_by_role('heading',name='积分中心',exact=True)).to_be_visible()
    assert writes==[{'method':'POST','path':'/company-knowledge/uploads'}]

@pytest.mark.browser
def test_repeated_navigation_and_transient_failure_soak(guidance):
    s,page,state,errors,writes=guidance;start(s,page)
    started=time.monotonic();cycles=0
    while cycles<20 or time.monotonic()-started<60:
        page.get_by_role('button',name='查看积分',exact=False).click()
        expect(page.get_by_role('heading',name='积分中心',exact=True)).to_be_visible()
        page.get_by_role('button',name='去阅读',exact=True).click()
        expect(page.get_by_role('tab',name='总资料库',exact=False)).to_have_attribute('aria-selected','true')
        assert page.locator('.points-home-card').count()==0
        page.get_by_role('menuitem',name='个人首页',exact=True).click()
        expect(page.locator('.points-home-card')).to_be_visible()
        state['fail_points']=cycles%3==0
        page.get_by_role('button',name='刷新首页',exact=True).click()
        if state['fail_points']:
            expect(page.get_by_role('button',name='重试积分',exact=True)).to_be_visible()
            state['fail_points']=False;page.get_by_role('button',name='重试积分',exact=True).click()
        cycles+=1
    assert writes==[]
    (s.output/'soak.json').write_text(json.dumps({'cycles':cycles,'seconds':round(time.monotonic()-started,2),'point_reads':state['point_reads'],'browser_errors':errors,'unexpected_writes':writes},indent=2))
