"""Check task filters in the real frontend with synthetic, read-only API replies."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import threading

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets-dir', type=Path, default=ROOT / 'work/account-ui/vendor')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'work/task-filters-ui')
    parser.add_argument('--browser-channel', default='msedge')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'frontend')))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f'http://127.0.0.1:{server.server_port}/'
    cases = [('星辰制造项目', 'company', 'completed'), ('人物失败项目', 'person', 'failed'),
             ('机器人行业项目', 'industry', 'collecting'), ('报告生成项目', 'industry', 'report_generating'),
             ('人物待继续项目', 'person', 'paused'), ('行业新任务', 'industry', 'draft'),
             ('历史诊断项目', 'company', 'diagnostic'), ('兼容旧任务', 'company', 'future_state'),
             ('规划项目', 'company', 'planning'), ('机器人完成项目', 'industry', 'completed')]
    cases += [(f'已完成公司项目{i}', 'company', 'completed') for i in range(11, 31)]
    projects = [dict(id=i, title=title, target_name=title, target_type=target, status=status, industry='演示行业',
                     created_at='2026-10-20T00:00:00', updated_at='2026-10-20T00:00:00')
                for i, (title, target, status) in enumerate(cases, 1)]
    errors, mutations = [], []
    assets = {'vue.global.prod.js': 'vue.js', 'index.full.min.js': 'element.js', 'index.css': 'element.css',
              'marked.min.js': 'marked.js', 'all.min.css': 'icons.css'}

    def route_request(route):
        request = route.request
        url = request.url
        if request.method != 'GET':
            mutations.append(url)
            return route.abort()
        if url == base + 'auth/me':
            return route.fulfill(json={'username': 'task-filter-ui', 'role': 'user', 'must_change_password': False})
        if url == base + 'research/projects':
            return route.fulfill(json={'projects': projects})
        if url == base + 'research/home':
            return route.fulfill(json={'user': {'username': 'task-filter-ui'},
                'summary': {'total': len(projects), 'running': 3, 'completed': 22, 'attention': 5},
                'recent_projects': [projects[0] | {'state_label': '已完成', 'is_running': False}],
                'recent_reports': [], 'updated_at': '2026-10-20T00:00:00Z'})
        match = re.fullmatch(re.escape(base) + r'research/projects/(\d+)/(detail|progress)', url)
        if match:
            project = next((item for item in projects if item['id'] == int(match[1])), None)
            if project is None:
                return route.fulfill(status=404, json={'detail': '模拟任务已移出列表'})
            return route.fulfill(json={'project': project, 'artifacts': [], 'sources': [], 'trace': [], 'intake': {}})
        if url.startswith(base):
            return route.continue_()
        filename = url.rsplit('/', 1)[-1]
        asset = args.assets_dir / assets.get(filename, filename)
        return route.fulfill(path=str(asset)) if asset.is_file() else route.abort()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=args.browser_channel, headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.route('**/*', route_request)
            context.add_init_script("localStorage.setItem('accessToken','synthetic-task-filter-ui');")
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base)

            def navigate(label):
                page.get_by_role('menuitem', name=label, exact=True).click()

            def choose(name, value):
                page.locator('.task-filter-select').filter(has=page.get_by_role('combobox', name=name, exact=True)).click()
                page.get_by_role('option', name=value, exact=True).click()

            navigate('任务管理')
            rows = page.locator('.task-table .el-table__row')
            expect(rows).to_have_count(12)
            expect(page.get_by_role('cell', name='已完成', exact=True).first).to_be_visible()
            page.locator('.btn-next').click()
            expect(page.locator('.el-pager .is-active')).to_have_text('2')
            choose('任务状态', '已完成')
            expect(page.locator('.el-pager .is-active')).to_have_text('1')
            choose('研究类型', '行业研究')
            expect(rows).to_have_count(1)
            expect(rows.first).to_contain_text('机器人完成项目')
            search = page.get_by_role('textbox', name='搜索任务', exact=True)
            search.fill('机器人'); expect(rows).to_have_count(1)
            search.fill('不存在的任务')
            expect(page.get_by_text('暂无符合筛选条件的任务，请调整或清空筛选', exact=True)).to_be_visible()
            page.get_by_role('button', name='清空筛选', exact=True).click()
            expect(rows).to_have_count(12)
            choose('任务状态', '进行中')
            expect(rows).to_have_count(3)
            expect(page.get_by_role('cell', name='资料收集', exact=True)).to_be_visible()
            expect(page.get_by_role('cell', name='报告生成', exact=True)).to_be_visible()
            expect(page.get_by_role('cell', name='研究规划', exact=True)).to_be_visible()
            choose('任务状态', '其他状态')
            expect(rows).to_have_count(1)
            expect(page.get_by_role('cell', name='待处理', exact=True)).to_be_visible()
            page.get_by_role('button', name='清空筛选', exact=True).click()
            search.fill('执行失败'); expect(rows).to_have_count(1)
            expect(rows.first).to_contain_text('人物失败项目')
            page.get_by_role('button', name='清空筛选', exact=True).click()

            choose('任务状态', '已完成'); choose('研究类型', '公司研究'); search.fill('星辰')
            navigate('复核与一手资料')
            review_rows = page.locator('.review-project-table .el-table__row')
            expect(review_rows).to_have_count(1)
            review_rows.get_by_role('button', name='复核', exact=True).click()
            expect(page.get_by_text('当前复核项目：星辰制造项目', exact=True)).to_be_visible()
            expect(page.get_by_role('button', name='二阶段再生成', exact=True)).to_be_enabled()
            choose('任务状态', '执行失败')
            expect(page.get_by_role('button', name='二阶段再生成', exact=True)).to_be_disabled()
            page.get_by_role('button', name='清空筛选', exact=True).click()
            choose('任务状态', '执行失败'); choose('研究类型', '人物研究')
            navigate('个人首页')
            page.get_by_role('button', name='查看任务', exact=True).click()
            expect(rows.first).to_contain_text('星辰制造项目')
            expect(page.get_by_role('button', name='清空筛选', exact=True)).to_be_disabled()
            expect(page.locator('.task-expand')).to_be_visible()
            # A polling refresh must not leave a now-empty last page selected.
            choose('任务状态', '已完成')
            page.locator('.btn-next').click()
            expect(page.locator('.el-pager .is-active')).to_have_text('2')
            projects[:] = projects[:1]
            navigate('复核与一手资料'); navigate('任务管理')
            expect(rows).to_have_count(1)
            expect(page.locator('.el-pager .is-active')).to_have_text('1')

            for width in (1440, 1024, 390):
                page.set_viewport_size({'width': width, 'height': 900})
                for control in page.locator('.task-filter-controls > *').all():
                    bounds = control.bounding_box()
                    assert bounds and bounds['width'] > 20 and 0 <= bounds['x'] and bounds['x'] + bounds['width'] <= width + 1, bounds
                page.screenshot(path=str(args.output_dir / f'task-filters-{width}.png'), full_page=True, animations='disabled')
            assert not errors, errors
            assert not mutations, mutations
            browser.close()
            print('Task filter UI passed: combined filters, Chinese keyword/status, active/unknown states, pagination reset/clamp, shared review filters, hidden review safety, home entry reset and 3 viewport sizes; synthetic read-only replies only.')
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=5)


if __name__ == '__main__':
    main()
