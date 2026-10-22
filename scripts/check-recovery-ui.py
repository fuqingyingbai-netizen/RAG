"""Exercise recovery guidance using synthetic records and simulated services."""
import argparse
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
import threading
from types import SimpleNamespace

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from research_recovery import build_recovery


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets-dir', type=Path, default=ROOT / 'work/account-ui/vendor')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'work/recovery-ui')
    parser.add_argument('--browser-channel', default='msedge')
    args = parser.parse_args()
    os.environ['WORKFLOW_RESUME_ENABLED'] = 'true'
    args.output_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'frontend')))
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    base = f'http://127.0.0.1:{server.server_port}/'
    project = dict(id=1, title='隔离测试任务', target_name='演示行业', target_type='industry', industry='演示',
                   status='failed', created_at='2026-10-21T00:00:00', updated_at='2026-10-21T00:00:00')
    body = '# Saved fixture report\n\n已有正文不会被失败处理操作删除。'
    artifact = SimpleNamespace(id=7, project_id=1, artifact_type='desktop_report', title='已存研究报告',
        content=body, version=1, created_at=datetime(2026, 10, 21), object_key='',
        artifact_metadata={'docx_export_error': 'PRIVATE_PROVIDER_ERROR', 'knowledge_sync_status': 'failed'})
    source = SimpleNamespace(source_metadata={'extraction_status': 'failed'})
    trace = [{'stage': 'report', 'label': '正在生成报告', 'status': 'running'},
             {'stage': 'workflow', 'label': '工作流执行失败', 'status': 'error', 'detail': 'TimeoutError PRIVATE_TRACE_KEY'}]
    mutations, unexpected, errors = [], [], []
    allow_mutations = set()
    assets = {'vue.global.prod.js': 'vue.js', 'index.full.min.js': 'element.js', 'index.css': 'element.css',
              'marked.min.js': 'marked.js', 'all.min.css': 'icons.css'}

    def artifact_payload():
        return dict(id=7, project_id=1, artifact_type='desktop_report', title=artifact.title, version=1,
                    content='', object_key='', metadata=dict(artifact.artifact_metadata), created_at='2026-10-21T00:00:00')

    def route_request(route):
        request = route.request
        url = request.url
        if request.method != 'GET':
            mutations.append(url)
            if url not in allow_mutations:
                unexpected.append(url)
                return route.abort()
            if url == base + 'research/projects/1/run/stream':
                trace[-1]['detail'] = '429 rate limit PRIVATE_TRACE_KEY'
                return route.fulfill(content_type='text/event-stream', body='data: ' + json.dumps({'type': 'error', 'content': '模拟服务限流'}, ensure_ascii=False) + '\n\n')
            if url == base + 'research/artifacts/7/knowledge/retry':
                artifact.artifact_metadata['knowledge_sync_status'] = 'queued'
                return route.fulfill(json={'metadata': dict(artifact.artifact_metadata)})
            if url == base + 'research/projects/1/field-sources':
                return route.fulfill(status=400, json={'detail': '文档解析失败 PRIVATE_UPLOAD_ERROR'})
            unexpected.append(url)
            return route.abort()
        if url == base + 'auth/me':
            return route.fulfill(json={'username': 'recovery-fixture', 'role': 'user', 'must_change_password': False})
        if url == base + 'research/projects':
            return route.fulfill(json={'projects': [project]})
        if url == base + 'research/home':
            return route.fulfill(json={'user': {'username': 'recovery-fixture'}, 'summary': {'total': 1, 'running': 0, 'completed': 0, 'attention': 1},
                'recent_projects': [], 'recent_reports': [], 'updated_at': '2026-10-21T00:00:00Z'})
        if url == base + 'research/projects/1/detail':
            recovery = build_recovery(SimpleNamespace(status=project['status']), [source], [artifact], trace)
            return route.fulfill(json={'project': project, 'intake': {}, 'source_count': 1, 'artifact_count': 1,
                'artifacts': [artifact_payload()], 'sources': [], 'trace': trace, 'recovery': recovery})
        if url == base + 'research/projects/1/run-intake': return route.fulfill(json={'intake': {}})
        if url == base + 'research/projects/1/progress': return route.fulfill(json={'project': project, 'trace': trace})
        if url.startswith(base + 'research/repository?') or url == base + 'research/repository': return route.fulfill(json={'results': []})
        if url == base + 'research/artifacts/7/download':
            return route.fulfill(content_type='text/markdown; charset=utf-8', headers={'Content-Disposition': 'attachment; filename="fixture.md"'}, body=body)
        if url.startswith(base + 'research/projects/1/report-versions?'):
            record = artifact_payload() | {'record_label': '记录 001', 'is_latest': True, 'can_download': True,
                'origin_label': '系统生成', 'review_label': '', 'export_error': True}
            return route.fulfill(json={'records': [record], 'total': 1})
        if url == base + 'research/artifacts/7/preview':
            return route.fulfill(json={'content': body, 'has_preview': True, 'truncated': False})
        if url.startswith(base): return route.continue_()
        filename = url.rsplit('/', 1)[-1]
        asset = args.assets_dir / assets.get(filename, filename)
        return route.fulfill(path=str(asset)) if asset.is_file() else route.abort()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=args.browser_channel, headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
            context.route('**/*', route_request)
            context.add_init_script("localStorage.setItem('accessToken','synthetic-recovery-ui-only');")
            page = context.new_page(); page.on('pageerror', lambda error: errors.append(str(error))); page.goto(base)
            page.get_by_role('menuitem', name='任务管理', exact=True).click()
            page.locator('.task-table .el-table__row').get_by_role('button', name='查看', exact=True).click()
            panel = page.get_by_role('region', name='任务处理指引', exact=True)
            expect(panel).to_be_visible()
            for kind in ('workflow', 'parsing', 'export', 'knowledge'):
                expect(panel.locator(f'[data-kind="{kind}"]')).to_be_visible()
            expect(panel).to_contain_text('1 条来源记录、1 条研究报告正文记录、0 条建议书正文记录')
            expect(panel).not_to_contain_text('PRIVATE_')
            assert mutations == [], mutations
            panel.screenshot(path=str(args.output_dir / 'recovery-initial.png'), animations='disabled')
            panel.get_by_role('button', name='继续任务', exact=True).click()
            dialog = page.get_by_role('dialog', name='确认继续任务', exact=True)
            expect(dialog).to_contain_text('可能再次联网或调用付费模型')
            dialog.get_by_role('button', name='取消', exact=True).click()
            expect(dialog).not_to_be_visible(); assert mutations == []
            with page.expect_download() as download:
                panel.locator('[data-kind="export"]').get_by_role('button', name='下载已保存成果', exact=True).click()
            assert Path(download.value.path()).read_text(encoding='utf-8') == body
            panel.get_by_role('button', name='查看历史版本', exact=True).click()
            history = page.get_by_role('dialog', name='报告历史版本', exact=True)
            expect(history.locator('.rv-body')).to_contain_text('已有正文不会')
            history.get_by_role('button', name='关闭', exact=True).click()
            allow_mutations.add(base + 'research/artifacts/7/knowledge/retry')
            panel.get_by_role('button', name='重试入库', exact=True).click()
            expect(panel.locator('[data-kind="knowledge"]')).to_have_count(0)
            assert mutations == [base + 'research/artifacts/7/knowledge/retry']
            allow_mutations.add(base + 'research/projects/1/run/stream')
            panel.get_by_role('button', name='继续任务', exact=True).click()
            dialog.get_by_role('button', name='继续任务', exact=True).click()
            expect(panel.locator('[data-kind="workflow"]')).to_contain_text('请求受限')
            assert mutations.count(base + 'research/projects/1/run/stream') == 1
            expect(panel).to_contain_text('1 条研究报告正文记录')
            panel.get_by_role('button', name='补充资料', exact=True).click()
            expect(page.get_by_text('当前复核项目：隔离测试任务', exact=True)).to_be_visible()
            allow_mutations.add(base + 'research/projects/1/field-sources')
            page.locator('.review-panel').filter(has_text='专家访谈 / 走访一手资料').locator('input[type="file"]').set_input_files(
                {'name': 'fixture.txt', 'mimeType': 'text/plain', 'buffer': b'synthetic fixture'})
            page.get_by_role('button', name='上传并入库', exact=True).click()
            expect(page.locator('.review-current').get_by_text('本次文件解析未完成', exact=True)).to_be_visible()
            page.get_by_role('menuitem', name='任务管理', exact=True).click()
            page.locator('.task-table .el-table__row').get_by_role('button', name='查看', exact=True).click()
            expect(panel.locator('[data-kind="upload"]')).to_contain_text('保存情况以刷新后的系统记录为准')
            expect(panel).not_to_contain_text('PRIVATE_UPLOAD_ERROR')
            expect(page.locator('.el-message')).to_have_count(0, timeout=8000)
            for width in (1440, 1024, 390):
                page.set_viewport_size({'width': width, 'height': 900})
                expect(panel).to_be_visible()
                bounds = panel.bounding_box()
                assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width + 1, bounds
                assert panel.evaluate('el => el.scrollWidth <= el.clientWidth + 1')
                panel.screenshot(path=str(args.output_dir / f'recovery-{width}.png'), animations='disabled')
            assert artifact.content == body and artifact.version == 1
            assert not unexpected, unexpected
            assert not errors, errors
            browser.close()
            print('Recovery UI passed: four failure categories, saved counts, cancelled confirmation causes no run, existing body download, history, knowledge-only retry, confirmed simulated run, post-failure refresh, pre-save upload failure, review navigation and 3 viewports. Synthetic records/services only.')
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=5)


if __name__ == '__main__':
    main()
