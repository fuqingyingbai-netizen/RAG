"""Check the real assistant UI with synthetic API replies and no external calls."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def check_account_header(page, username, role):
    header = page.get_by_role('region', name='当前登录账号', exact=True)
    expect(header).to_have_count(1)
    expect(header).to_contain_text(username)
    expect(header).to_contain_text('管理员' if role == 'admin' else '普通用户')
    expect(page.locator('.sidebar-note, #sidebar-account')).to_have_count(0)
    for name in ('修改密码', '退出登录'):
        expect(page.get_by_role('button', name=name, exact=True)).to_have_count(1)
        expect(header.get_by_role('button', name=name, exact=True)).to_be_visible()
    bounds = header.bounding_box()
    assert bounds and bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= page.viewport_size['width'] + 1, bounds
    identity = header.locator('.topbar-identity').bounding_box()
    actions = header.locator('.topbar-account-actions').bounding_box()
    assert identity['x'] + identity['width'] <= actions['x'] + 1, (identity, actions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets-dir', type=Path, default=ROOT / 'work/account-ui/vendor')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'work/assistant-ui')
    parser.add_argument('--browser-channel', default='msedge')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'frontend')))
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    base = f'http://127.0.0.1:{server.server_port}/'
    requests = []
    identity = {'username': 'assistant-ui-only', 'role': 'user', 'must_change_password': False}
    reply = ('欢迎使用！可以按这个顺序开始：\n\n'
             '1. **提交尽调任务**：选择公司、人物或行业，填写研究对象与重点问题。\n'
             '2. **任务管理**：查看进度、下载报告，并检查待本人复核提示。\n'
             '3. **复核与一手资料**：修订报告、补充资料后再次生成。\n'
             '4. **溯源库**：核对来源记录与原文。\n'
             '5. **公司知识库**：阅读、提问及总结自己的项目。\n\n'
             '我也可以解释当前页面的操作方法。')
    navigation = [{'view': name, 'label': label} for name, label in [
        ('home', '个人首页'), ('submit', '提交尽调任务'), ('tasks', '任务管理'), ('review', '复核与一手资料'), ('sources', '溯源库'), ('company-knowledge', '公司知识库'), ('accounts', '账号管理')]]
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=args.browser_channel, headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 900})
            assets = {'vue.global.prod.js': 'vue.js', 'index.full.min.js': 'element.js', 'index.css': 'element.css', 'marked.min.js': 'marked.js', 'all.min.css': 'icons.css'}
            def route_request(route):
                url = route.request.url
                if url == base + 'auth/me':
                    return route.fulfill(json=identity)
                if url == base + 'research/projects': return route.fulfill(json={'projects': []})
                if url == base + 'research/home': return route.fulfill(json={'user': {'username': 'assistant-ui-only'}, 'summary': {'total': 0, 'running': 0, 'completed': 0, 'attention': 0}, 'recent_projects': [], 'recent_reports': [], 'updated_at': '2026-10-20T00:00:00Z'})
                if url.startswith(base + 'research/repository?'): return route.fulfill(json={'results': []})
                if url == base + 'company-knowledge/status': return route.fulfill(json={'configured': True, 'access_allowed': True, 'is_admin': identity['role'] == 'admin', 'username': identity['username']})
                if url.startswith(base + 'company-knowledge/documents?'): return route.fulfill(json={'documents': [], 'total_count': 0})
                if url == base + 'company-knowledge/my-projects': return route.fulfill(json={'projects': [], 'total_projects': 0, 'total_documents': 0})
                if url.startswith(base + 'company-knowledge/access-requests'): return route.fulfill(json={'requests': []})
                if url.startswith(base + 'admin/users?'): return route.fulfill(json={'items': [], 'total': 0, 'active_admin_count': 1})
                if url == base + 'research/assistant/stream':
                    requests.append(route.request.post_data_json)
                    events = [{'type': 'navigation', 'items': navigation}, {'type': 'content', 'content': reply}]
                    body = ''.join('data: ' + json.dumps(event, ensure_ascii=False) + '\n\n' for event in events) + 'data: [DONE]\n\n'
                    return route.fulfill(content_type='text/event-stream', body=body)
                if url.startswith(base): return route.continue_()
                filename = url.rsplit('/', 1)[-1]
                asset = args.assets_dir / assets.get(filename, filename)
                return route.fulfill(path=str(asset)) if asset.is_file() else route.abort()
            context.route('**/*', route_request)
            context.add_init_script("localStorage.setItem('accessToken','synthetic-ui-token'); localStorage.setItem('assistantPosition', '{\"right\":99999,\"bottom\":99999}');")
            page = context.new_page(); errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base)
            check_account_header(page, identity['username'], identity['role'])
            launcher = page.get_by_role('button', name='打开小助手', exact=True)
            expect(launcher).to_be_visible(); launcher.click()
            panel = page.get_by_role('dialog', name='AI 小助手', exact=True)
            expect(panel).to_be_visible(); expect(launcher).to_have_count(0)
            composer = panel.get_by_role('textbox', name='给小助手发送消息', exact=True)
            expect(composer).to_be_focused()
            panel.get_by_role('button', name='新人入门', exact=True).click()
            expect(panel.locator('.assistant-msg.bot').last).to_contain_text('公司知识库')
            user = panel.locator('.assistant-msg.user').last.bounding_box()
            assert user['width'] < panel.bounding_box()['width'] * .7, user
            expect(panel.locator('.assistant-navigation nav')).not_to_be_visible()
            assert requests[-1]['current_page'] == 'home'
            # Moving between real pages keeps the same thread and updates page help.
            handle = panel.locator('.assistant-drag-handle')
            bounds = handle.bounding_box(); page.mouse.move(bounds['x'] + 170, bounds['y'] + 30)
            page.mouse.down(); page.mouse.move(1400, 240, steps=8); page.mouse.up()
            for view, label in [('submit', '提交尽调任务'), ('tasks', '任务管理'), ('review', '复核与一手资料'), ('sources', '溯源库'), ('company-knowledge', '公司知识库'), ('home', '个人首页')]:
                message_count = panel.locator('.assistant-msg.user').count()
                page.locator('.el-menu-item[role="menuitem"]').filter(has_text=label).click()
                check_account_header(page, identity['username'], identity['role'])
                expect(panel).to_be_visible()
                expect(panel.locator('.assistant-msg.user')).to_have_count(message_count)
                panel.get_by_role('button', name='当前页面帮助', exact=True).click()
                expect(panel.get_by_role('button', name='当前页面帮助', exact=True)).to_be_enabled()
                assert requests[-1]['current_page'] == view
                expect(panel.locator('.assistant-msg.user')).to_have_count(message_count + 1)
                if view in ('home', 'company-knowledge'):
                    page.screenshot(path=str(args.output_dir / f'assistant-global-{view}.png'), animations='disabled')
                if view == 'company-knowledge':
                    panel.get_by_role('button', name='关闭小助手', exact=True).click()
                    page.set_viewport_size({'width': 390, 'height': 844})
                    check_account_header(page, identity['username'], identity['role'])
                    page.screenshot(path=str(args.output_dir / 'account-header-knowledge-mobile.png'), animations='disabled')
                    page.set_viewport_size({'width': 1440, 'height': 900})
                    launcher.click()
            expect(page.get_by_role('menuitem', name='账号管理', exact=True)).to_have_count(0)
            panel.locator('.assistant-navigation summary').click()
            expect(panel.get_by_role('button', name='个人首页', exact=True)).to_be_visible()
            expect(panel.get_by_role('button', name='账号管理', exact=True)).to_have_count(0)
            panel.locator('.assistant-navigation summary').click()
            # A long thread must scroll inside the feed while the composer stays fixed.
            for _ in range(2):
                panel.get_by_role('button', name='当前页面帮助', exact=True).click()
                expect(panel.get_by_role('button', name='当前页面帮助', exact=True)).to_be_enabled()
            feed = panel.locator('.assistant-messages')
            feed.evaluate('(el) => {el.scrollTop = 0}')
            jump = panel.get_by_role('button', name='回到最新消息', exact=True)
            expect(jump).to_be_visible(); jump.click(); expect(jump).to_have_count(0)
            composer.fill('第一行'); composer.press('Shift+Enter'); composer.type('第二行')
            expect(composer).to_have_value('第一行\n第二行')
            before = len(requests); composer.press('Enter')
            expect(composer).to_have_value('')
            expect(panel.get_by_role('button', name='新人入门', exact=True)).to_be_enabled()
            assert len(requests) == before + 1
            assert requests[-1]['message'] == '第一行\n第二行'
            # Put the window at its normal lower-right anchor for visual checks.
            handle = panel.locator('.assistant-drag-handle')
            bounds = handle.bounding_box(); page.mouse.move(bounds['x'] + 170, bounds['y'] + 30)
            page.mouse.down(); page.mouse.move(1400, 240, steps=8); page.mouse.up()
            for width, height in [(1440, 900), (1024, 768), (913, 1257), (390, 844), (390, 380), (1280, 460)]:
                page.set_viewport_size({'width': width, 'height': height})
                expect(composer).to_be_visible()
                dimensions = panel.evaluate('el => {const box=el.getBoundingClientRect(), input=el.querySelector(".assistant-input").getBoundingClientRect(), feed=el.querySelector(".assistant-messages");return {x:box.x,y:box.y,right:box.right,bottom:box.bottom,inputBottom:input.bottom,inputRight:input.right,viewport:innerHeight,feedHeight:feed.clientHeight,feedContent:feed.scrollHeight,rootOverflow:el.scrollHeight-el.clientHeight}}')
                assert dimensions['x'] >= 0 and dimensions['right'] <= width + 1, dimensions
                assert dimensions['y'] >= 0 and dimensions['bottom'] <= height + 1, dimensions
                assert dimensions['inputBottom'] <= dimensions['bottom'] and dimensions['inputRight'] <= dimensions['right'], dimensions
                assert dimensions['rootOverflow'] <= 1 and dimensions['feedContent'] > dimensions['feedHeight'], dimensions
                panel.screenshot(path=str(args.output_dir / f'assistant-{width}x{height}.png'), animations='disabled')
            page.set_viewport_size({'width': 1440, 'height': 900})
            panel.locator('.assistant-navigation summary').click()
            page.set_viewport_size({'width': 390, 'height': 380})
            expect(composer).to_be_visible()
            assert panel.evaluate('el => el.scrollHeight <= el.clientHeight + 1')
            panel.screenshot(path=str(args.output_dir / 'assistant-compact-navigation.png'), animations='disabled')
            page.set_viewport_size({'width': 1440, 'height': 900})
            expect(panel.get_by_role('button', name='任务管理', exact=True)).to_be_visible()
            panel.get_by_role('button', name='任务管理', exact=True).click()
            expect(panel).to_have_count(0)
            expect(page.get_by_role('heading', name='任务管理', exact=True, level=1)).to_be_visible()
            launcher.click(); expect(panel).to_be_visible()
            panel.get_by_role('button', name='关闭小助手', exact=True).click(); expect(panel).to_have_count(0)
            expect(launcher).to_be_focused()
            launcher.click(); composer.press('Escape'); expect(panel).to_have_count(0)
            for width in (1440, 1024, 390, 320):
                page.set_viewport_size({'width': width, 'height': 900})
                check_account_header(page, identity['username'], identity['role'])
            page.get_by_role('button', name='修改密码', exact=True).click()
            password_dialog = page.get_by_role('dialog', name='修改密码', exact=True)
            expect(password_dialog).to_be_visible()
            password_dialog.get_by_role('textbox', name='原密码', exact=True).fill('synthetic-current-password')
            password_dialog.press('Escape'); expect(password_dialog).not_to_be_visible()
            page.get_by_role('button', name='修改密码', exact=True).click()
            expect(password_dialog.get_by_role('textbox', name='原密码', exact=True)).to_have_value('')
            password_dialog.press('Escape'); expect(password_dialog).not_to_be_visible()
            context.close()
            # Admin-only entry is available on the account management page.
            identity['role'] = 'admin'
            identity['username'] = 'administrator-with-a-long-name-for-header-layout'
            admin_context = browser.new_context(viewport={'width': 1440, 'height': 900})
            admin_context.route('**/*', route_request)
            admin_context.add_init_script("localStorage.setItem('accessToken','synthetic-admin-token');")
            admin = admin_context.new_page(); admin.on('pageerror', lambda error: errors.append(str(error))); admin.goto(base)
            admin_launcher = admin.get_by_role('button', name='打开小助手', exact=True)
            admin.locator('.el-menu-item[role="menuitem"]').filter(has_text='账号管理').click()
            expect(admin.get_by_role('heading', name='账号管理', level=1, exact=True)).to_be_visible()
            check_account_header(admin, identity['username'], identity['role'])
            admin_launcher.click()
            admin_panel = admin.get_by_role('dialog', name='AI 小助手', exact=True)
            admin_panel.get_by_role('button', name='当前页面帮助', exact=True).click()
            expect(admin_panel.get_by_role('button', name='当前页面帮助', exact=True)).to_be_enabled()
            assert requests[-1]['current_page'] == 'accounts'
            admin_panel.locator('.assistant-navigation summary').click()
            expect(admin_panel.get_by_role('button', name='账号管理', exact=True)).to_be_visible()
            admin.screenshot(path=str(args.output_dir / 'assistant-global-accounts.png'), animations='disabled')
            admin_panel.get_by_role('button', name='关闭小助手', exact=True).click()
            for width in (1440, 1024, 390, 320):
                admin.set_viewport_size({'width': width, 'height': 900})
                check_account_header(admin, identity['username'], identity['role'])
                admin.screenshot(path=str(args.output_dir / f'account-header-admin-{width}.png'), animations='disabled')
            admin.get_by_role('button', name='退出登录', exact=True).click()
            expect(admin_launcher).to_have_count(0); expect(admin_panel).to_have_count(0)
            admin_context.close()
            # Mandatory password change remains outside the logged-in app shell.
            identity['must_change_password'] = True
            password_context = browser.new_context()
            password_context.route('**/*', route_request)
            password_context.add_init_script("localStorage.setItem('accessToken','synthetic-password-token');")
            password = password_context.new_page(); password.goto(base)
            expect(password.get_by_role('button', name='修改密码并继续', exact=True)).to_be_visible()
            expect(password.get_by_role('button', name='打开小助手', exact=True)).to_have_count(0)
            password_context.close()
            assert not errors, errors
            browser.close()
            print('Assistant/account header UI passed: all 7 signed-in pages, single top-right account area, no sidebar duplication, password entry/reset, logout, long usernames and 4 header viewports; shared assistant thread, role navigation and 6 panel viewports; synthetic replies only.')
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=5)


if __name__ == '__main__':
    main()
