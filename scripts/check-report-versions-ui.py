"""Exercise report history in a real browser using isolated accounts and storage."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets-dir', type=Path, default=ROOT / 'work/account-ui/vendor')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'work/report-versions-ui')
    parser.add_argument('--browser-channel', default='msedge')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    os.environ['PYTHON_DOTENV_DISABLED'] = '1'
    os.environ['DATABASE_URL'] = 'sqlite://'
    os.environ['JWT_SECRET_KEY'] = 'isolated-report-history-ui-only'
    sys.path.insert(0, str(ROOT / 'backend'))
    import auth
    from account_api import router as accounts
    from account_migrations import migrate_accounts
    from fastapi import Depends, FastAPI, HTTPException
    from fastapi.responses import Response
    from fastapi.staticfiles import StaticFiles
    from models import ResearchArtifact, ResearchProject, User
    from personal_home import create_home_router, stamp
    from playwright.sync_api import expect, sync_playwright
    from report_versions import create_report_versions_router
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    import uvicorn

    with tempfile.TemporaryDirectory(prefix='report-history-ui-') as temporary:
        engine = create_engine('sqlite:///' + str(Path(temporary) / 'test.db'), connect_args={'check_same_thread': False})
        migrate_accounts(engine)
        factory = sessionmaker(engine, expire_on_commit=False)
        with factory() as db:
            db.add_all([User(id=1, username='history-owner', role='user', password_hash=auth.get_password_hash('History-owner-123')),
                        User(id=2, username='history-other', role='user', password_hash='unused')])
            db.flush()
            db.add_all([ResearchProject(id=1, title='历史版本隔离验收', target_name='合成研究对象', created_by_id=1, status='completed'),
                        ResearchProject(id=2, title='其他账号私有任务', created_by_id=2, status='completed')])
            db.flush()
            for version in range(1, 14):
                body = f'# 系统记录{version:03d}\n\n本条记录的独立正文。'
                meta = {'delivery_status': 'review_draft'}
                if version == 2:
                    body = '# 本人修订正文\n\n这是记录002，不能下载成最新记录。'
                    meta.update(stage='human_review', original_filename='修订稿.docx')
                if version == 1:
                    body = '<script>window.__historyAttack=true</script><img src=x onerror="window.__historyAttack=true">\n\n# 安全预览正文'
                db.add(ResearchArtifact(id=version, project_id=1, artifact_type='desktop_report', title='预览验收报告',
                                        version=version, content=body, created_at=datetime(2026, 10, version),
                                        artifact_metadata=meta, created_by='human_review' if version == 2 else 'agent'))
            db.add(ResearchArtifact(id=101, project_id=1, artifact_type='proposal', title='预览验收建议书', version=1,
                                    content='# 独立建议书正文', artifact_metadata={'proposal_confirmation_status': 'pending'}))
            db.add(ResearchArtifact(id=102, project_id=2, artifact_type='desktop_report', title='其他账号私有报告', version=1, content='OTHER_PRIVATE_REPORT'))
            db.commit()
        app = FastAPI()
        def get_db():
            with factory() as db:
                yield db
        app.dependency_overrides[auth.get_db] = get_db
        def project_for(db, pid, user):
            project = db.get(ResearchProject, pid)
            if not project or (user.role != 'admin' and project.created_by_id != user.id):
                raise HTTPException(403, '无权访问该研究项目')
            return project
        app.include_router(accounts)
        app.include_router(create_home_router(lambda _: False))
        app.include_router(create_report_versions_router(project_for), prefix='/research')
        def project_dict(row):
            return {key: getattr(row, key) for key in ['id', 'title', 'target_name', 'target_type', 'industry', 'description', 'status']} | {'created_at': stamp(row.created_at), 'updated_at': stamp(row.updated_at)}
        @app.get('/research/projects')
        def projects(db=Depends(auth.get_db), user=Depends(auth.get_current_user)):
            return {'projects': [project_dict(row) for row in db.scalars(select(ResearchProject).where(ResearchProject.created_by_id == user.id))]}
        @app.get('/research/projects/{project_id}/detail')
        def detail(project_id: int, db=Depends(auth.get_db), user=Depends(auth.get_current_user)):
            return {'project': project_dict(project_for(db, project_id, user)), 'intake': {}, 'artifacts': [], 'sources': [], 'trace': []}
        @app.get('/research/artifacts/{artifact_id}/download')
        def download(artifact_id: int, db=Depends(auth.get_db), user=Depends(auth.get_current_user)):
            artifact = db.get(ResearchArtifact, artifact_id)
            project_for(db, artifact.project_id, user)
            return Response(artifact.content, media_type='text/plain', headers={'Content-Disposition': 'attachment; filename="selected-record.txt"'})
        app.mount('/', StaticFiles(directory=ROOT / 'frontend', html=True))
        listener = socket.socket(); listener.bind(('127.0.0.1', 0))
        server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
        worker = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True); worker.start()
        try:
            for _ in range(100):
                if server.started: break
                time.sleep(.1)
            assert server.started
            base = f'http://127.0.0.1:{listener.getsockname()[1]}/'
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel=args.browser_channel, headless=True)
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                assets = {'vue.global.prod.js': 'vue.js', 'index.full.min.js': 'element.js', 'index.css': 'element.css', 'marked.min.js': 'marked.js', 'all.min.css': 'icons.css'}
                def route_request(route):
                    if route.request.url.startswith(base): return route.continue_()
                    filename = route.request.url.rsplit('/', 1)[-1]
                    asset = args.assets_dir / assets.get(filename, filename)
                    if asset.is_file(): return route.fulfill(path=str(asset))
                    return route.abort()
                context.route('**/*', route_request)
                page = context.new_page(); errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base)
                page.get_by_role('button', name='普通用户', exact=True).click()
                page.get_by_role('textbox', name='用户名', exact=True).fill('history-owner')
                page.get_by_role('textbox', name='密码', exact=True).fill('History-owner-123')
                page.get_by_role('button', name='普通用户登录', exact=True).click()
                report = page.locator('.home-reports article').filter(has_text='预览验收报告')
                expect(report.get_by_text('记录 013', exact=True)).to_be_visible()
                report.get_by_role('button', name='历史版本', exact=True).click()
                dialog = page.get_by_role('dialog', name='报告历史版本', exact=True)
                expect(dialog).to_be_visible()
                expect(dialog.locator('.rv-body').get_by_role('heading', name='系统记录013', exact=True)).to_be_visible()
                expect(dialog.locator('.rv-table .el-table__body-wrapper tr')).to_have_count(10)
                dialog.locator('.rv-pagination .btn-next').click()
                expect(dialog.locator('.rv-table .el-table__body-wrapper tr')).to_have_count(3)
                row = dialog.locator('.rv-table .el-table__body-wrapper tr').filter(has_text='记录 002')
                row.get_by_role('button', name='查看', exact=True).click()
                expect(dialog.locator('.rv-body').get_by_role('heading', name='本人修订正文', exact=True)).to_be_visible()
                expect(dialog.locator('.rv-preview').get_by_text('原文件：修订稿.docx', exact=True)).to_be_visible()
                with page.expect_download() as event:
                    row.get_by_role('button', name='下载', exact=True).click()
                assert '记录002' in Path(event.value.path()).read_text(encoding='utf-8')
                page.screenshot(path=str(args.output_dir / 'history-desktop.png'), full_page=True, animations='disabled')
                row = dialog.locator('.rv-table .el-table__body-wrapper tr').filter(has_text='记录 001')
                row.get_by_role('button', name='查看', exact=True).click()
                expect(dialog.locator('.rv-body').get_by_role('heading', name='安全预览正文', exact=True)).to_be_visible()
                assert not page.evaluate('Boolean(window.__historyAttack)')
                assert dialog.locator('.rv-body script, .rv-body [onerror]').count() == 0
                dialog.get_by_text('项目建议书', exact=True).click()
                expect(dialog.locator('.rv-body').get_by_role('heading', name='独立建议书正文', exact=True)).to_be_visible()
                expect(dialog.locator('.rv-pagination')).to_have_count(0)
                page.set_viewport_size({'width': 390, 'height': 844})
                bounds = dialog.bounding_box(); assert bounds and bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= 391, bounds
                page.screenshot(path=str(args.output_dir / 'history-mobile.png'), full_page=True, animations='disabled')
                dialog.get_by_role('button', name='关闭', exact=True).click()
                expect(dialog).to_have_count(0)
                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.get_by_role('menuitem', name='任务管理', exact=True).click()
                page.locator('.task-table').get_by_role('button', name='查看', exact=True).click()
                page.locator('.task-expand').get_by_role('button', name='历史版本', exact=True).click()
                expect(dialog).to_be_visible()
                expect(dialog.locator('.rv-body').get_by_role('heading', name='系统记录013', exact=True)).to_be_visible()
                page.route('**/report-versions?*', lambda route: route.fulfill(status=503, content_type='application/json', body=json.dumps({'detail': '历史记录暂不可用'})))
                dialog.get_by_role('button', name='刷新记录', exact=True).click()
                expect(dialog.get_by_text('历史记录暂不可用', exact=True)).to_be_visible()
                expect(dialog.locator('.rv-body')).to_have_count(0)
                dialog.get_by_role('button', name='关闭', exact=True).click()
                page.get_by_role('button', name='退出登录', exact=True).click()
                expect(dialog).to_have_count(0)
                assert not errors, errors
                browser.close()
                print('Report history browser checks passed: home/task entry, record labels, pagination, exact old download, preview sanitization, type switch, mobile, errors and logout; isolated DB only.')
        finally:
            server.should_exit = True; worker.join(timeout=5); engine.dispose()


if __name__ == '__main__':
    main()
