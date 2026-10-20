"""Run the real account UI against an isolated local DB and test-only research stub."""
import argparse
from datetime import datetime, timedelta
import hashlib
import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import auth
from account_api import router
from account_migrations import migrate_accounts
from models import AccountAudit, AccountInvitation, ResearchArtifact, ResearchProject, User
from personal_home import create_home_router, stamp


def personal_home_only(page, base, output, browser, configure_context):
    """Real home API/UI, fixture-only research details and downloads."""
    expect(page.get_by_role('heading', name='个人首页', exact=True)).to_be_visible()
    expect(page.locator('[data-metric="total"] strong')).to_have_text('1')
    expect(page.locator('.personal-home').get_by_text('管理员自己的研究', exact=True).first).to_be_visible()
    expect(page.locator('.personal-home').get_by_text('其他用户私有项目', exact=True)).to_have_count(0)
    page.locator('.home-projects article').first.get_by_role('button', name='查看任务', exact=True).click()
    expect(page.get_by_role('heading', name='任务管理', exact=True, level=1)).to_be_visible()
    expect(page.locator('.task-table').get_by_text('管理员自己的研究', exact=True).first).to_be_visible()
    expect(page.locator('.task-table .task-expand')).to_be_visible()
    for width in [1366, 1024]:
        page.set_viewport_size({'width': width, 'height': 900})
        actions = page.locator('.task-row-actions').first
        expect(actions.get_by_role('button', name='查看', exact=True)).to_be_visible()
        bounds = actions.bounding_box()
        assert bounds and 0 <= bounds['x'] and bounds['x'] + bounds['width'] <= width, bounds
        page.screenshot(path=str(output / f'task-layout-{width}.png'), full_page=True, animations='disabled')
    page.set_viewport_size({'width': 1440, 'height': 1000})
    page.get_by_role('menuitem', name='个人首页', exact=True).click()
    page.get_by_role('button', name='新建任务', exact=True).click()
    expect(page.get_by_role('heading', name='新建尽调任务', exact=True)).to_be_visible()
    page.get_by_role('menuitem', name='个人首页', exact=True).click()
    page.screenshot(path=str(output / 'personal-home-admin.png'), full_page=True, animations='disabled')
    member_context = browser.new_context(viewport={'width': 1440, 'height': 1000})
    configure_context(member_context)
    member = member_context.new_page()
    home_errors = []
    member.on('pageerror', lambda error: home_errors.append(str(error)))
    mutations = []
    member.on('request', lambda request: mutations.append(request.url) if request.method != 'GET' and '/research/' in request.url else None)
    member.goto(base)
    member.get_by_role('button', name='普通用户', exact=True).click()
    member.get_by_role('textbox', name='用户名', exact=True).fill('ui-member')
    member.get_by_role('textbox', name='密码', exact=True).fill('Ui-member-password-123')
    member.get_by_role('button', name='普通用户登录', exact=True).click()
    expect(member.get_by_role('heading', name='个人首页', exact=True)).to_be_visible()
    expect(member.locator('[data-metric="total"] strong')).to_have_text('13')
    expect(member.locator('[data-metric="running"] strong')).to_have_text('1')
    expect(member.locator('[data-metric="completed"] strong')).to_have_text('1')
    expect(member.locator('[data-metric="attention"] strong')).to_have_text('11')
    expect(member.get_by_role('menuitem', name='账号管理', exact=True)).to_have_count(0)
    expect(member.locator('.home-shortcuts').get_by_role('button', name='账号管理', exact=False)).to_have_count(0)
    expect(member.locator('.personal-home').get_by_text('管理员自己的研究', exact=True)).to_have_count(0)
    expect(member.locator('.personal-home').get_by_text('其他用户私有项目', exact=True)).to_have_count(0)
    expect(member.get_by_text('待复核稿', exact=True)).to_be_visible()
    expect(member.get_by_text('建议书待确认', exact=True)).to_be_visible()
    report = member.locator('.home-reports article').filter(has_text='本人的行业报告')
    expect(report).to_have_count(1)
    expect(report.get_by_text('记录 002', exact=True)).to_be_visible()
    with member.expect_download() as download_event:
        report.get_by_role('button', name='下载', exact=True).click()
    assert Path(download_event.value.path()).read_text(encoding='utf-8') == '隔离测试报告正文'
    member.screenshot(path=str(output / 'personal-home-desktop.png'), full_page=True, animations='disabled')
    member.route(base + 'research/home', lambda route: route.fulfill(status=503, content_type='application/json', body=json.dumps({'detail': '暂时无法读取任务'}, ensure_ascii=False)))
    member.get_by_role('button', name='刷新首页', exact=True).click()
    expect(member.get_by_text('刷新失败，以下为上次加载的数据。暂时无法读取任务', exact=True)).to_be_visible()
    expect(member.locator('[data-metric="total"] strong')).to_have_text('13')
    member.unroute(base + 'research/home')
    member.get_by_role('button', name='刷新首页', exact=True).click()
    expect(member.get_by_text('刷新失败，以下为上次加载的数据。暂时无法读取任务', exact=True)).not_to_be_visible()
    member.set_viewport_size({'width': 390, 'height': 844})
    toggle = member.get_by_role('button', name='展开导航', exact=True)
    expect(toggle).to_have_attribute('aria-expanded', 'false')
    expect(member.get_by_role('menuitem', name='个人首页', exact=True)).not_to_be_visible()
    assert member.locator('.personal-home').bounding_box()['y'] < 320
    member.screenshot(path=str(output / 'personal-home-mobile.png'), full_page=True, animations='disabled')
    member.screenshot(path=str(output / 'personal-home-mobile-first-screen.png'), animations='disabled')
    assert member.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    toggle.click()
    expect(member.get_by_role('button', name='收起导航', exact=True)).to_have_attribute('aria-expanded', 'true')
    member.get_by_role('menuitem', name='任务管理', exact=True).click()
    expect(member.get_by_role('heading', name='任务管理', exact=True, level=1)).to_be_visible()
    expect(member.get_by_role('button', name='展开导航', exact=True)).to_have_attribute('aria-expanded', 'false')
    expect(member.get_by_text('表格可左右滑动，查看全部信息和操作。', exact=True)).to_be_visible()
    assert member.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    member.get_by_role('button', name='展开导航', exact=True).click()
    member.get_by_role('button', name='收起导航', exact=True).press('Escape')
    expect(member.get_by_role('button', name='展开导航', exact=True)).to_have_attribute('aria-expanded', 'false')
    member.get_by_role('button', name='展开导航', exact=True).click()
    member.get_by_role('menuitem', name='个人首页', exact=True).click()
    for width in [768, 320]:
        member.set_viewport_size({'width': width, 'height': 900})
        expect(member.get_by_role('button', name='展开导航', exact=True)).to_be_visible()
        assert member.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        member.screenshot(path=str(output / f'personal-home-{width}.png'), full_page=True, animations='disabled')
    empty_context = browser.new_context(viewport={'width': 1280, 'height': 900})
    configure_context(empty_context)
    empty = empty_context.new_page()
    empty.on('pageerror', lambda error: home_errors.append(str(error)))
    empty.goto(base)
    empty.get_by_role('button', name='普通用户', exact=True).click()
    empty.get_by_role('textbox', name='用户名', exact=True).fill('ui-empty')
    empty.get_by_role('textbox', name='密码', exact=True).fill('Ui-member-password-123')
    empty.get_by_role('button', name='普通用户登录', exact=True).click()
    expect(empty.get_by_text('还没有创建任务', exact=True)).to_be_visible()
    expect(empty.get_by_text('还没有研究成果', exact=True)).to_be_visible()
    empty.screenshot(path=str(output / 'personal-home-empty.png'), full_page=True, animations='disabled')
    empty.route(base + 'research/home', lambda route: route.fulfill(status=503, content_type='application/json', body=json.dumps({'detail': '暂时无法读取任务'}, ensure_ascii=False)))
    empty.reload()
    expect(empty.get_by_text('暂时无法读取任务', exact=True)).to_be_visible()
    expect(empty.locator('.home-metrics')).to_have_count(0)
    assert mutations == [], mutations
    assert not home_errors, home_errors


def seed_home(db, admin):
    member = User(username='ui-member', role='user', display_name='张同事', password_hash=auth.get_password_hash('Ui-member-password-123'))
    other = User(username='ui-other', role='user', password_hash='unused-fixture-hash')
    db.add_all([member, other, User(username='ui-empty', role='user', password_hash=auth.get_password_hash('Ui-member-password-123'))])
    db.flush()
    db.add_all([ResearchProject(id=1, title='管理员自己的研究', created_by_id=admin.id, status='completed', updated_at=datetime(2026, 9, 1)),
                ResearchProject(id=2, title='其他用户私有项目', created_by_id=other.id, status='completed', updated_at=datetime(2026, 10, 21))])
    for pid in range(3, 16):
        db.add(ResearchProject(id=pid, title=f'我的研究任务{pid}', target_type='industry', created_by_id=member.id,
                               status={15:'collecting', 14:'completed', 13:'paused', 12:'failed'}.get(pid, 'draft'), updated_at=datetime(2026, 10, 20, 0, pid)))
    db.flush()
    for aid, pid, title, kind, version, day, metadata in [
        (301, 1, '管理员研究报告', 'desktop_report', 1, 1, {}),
        (302, 14, '本人的行业报告', 'desktop_report', 1, 18, {}),
        (303, 14, '本人的行业报告', 'desktop_report', 2, 20, {'delivery_status': 'review_draft'}),
        (304, 14, '本人的项目建议书', 'proposal', 1, 20, {'proposal_confirmation_status': 'pending'}),
        (305, 2, '其他用户私有报告', 'desktop_report', 1, 21, {}),
    ]:
        db.add(ResearchArtifact(id=aid, project_id=pid, title=title, artifact_type=kind, version=version,
                                content='隔离测试报告正文', created_at=datetime(2026, 10, day), artifact_metadata=metadata))


def verify_admin_password(page):
    prompt = page.get_by_role('dialog', name='验证管理员身份')
    expect(prompt).to_be_visible()
    prompt.locator('input').fill('Ui-admin-password-123')
    prompt.get_by_role('button', name='验证并继续').click()


def management_only(page, base, output):
    """Exercise seeded accounts only; do not create or consume invitations."""
    def account_row(name):
        return page.locator('#pane-users .el-table__body-wrapper tr').filter(has_text=name)
    def choose_role(label):
        page.locator('#pane-users .el-select').first.click()
        page.get_by_role('option', name=label, exact=True).click()
    secret = page.get_by_role('textbox', name='复制内容')
    employee = account_row('ui-employee')
    expect(employee).to_be_visible()
    employee.get_by_role('button', name='编辑资料', exact=True).click()
    profile = page.get_by_role('dialog', name='编辑账号资料')
    expect(profile.get_by_role('textbox', name='资料用户名')).to_be_disabled()
    profile.get_by_role('textbox', name='账号姓名').fill('张同事')
    profile.get_by_role('textbox', name='账号备注').fill('项目联络人\n周五复核')
    profile.screenshot(path=str(output / 'account-profile-dialog.png'), animations='disabled')
    profile.get_by_role('button', name='保存资料', exact=True).click()
    expect(profile).not_to_be_visible()
    expect(employee.get_by_text('张同事 · 普通账号', exact=True)).to_be_visible()
    employee.get_by_role('button', name='编辑资料', exact=True).click()
    expect(profile.get_by_role('textbox', name='账号备注')).to_have_value('项目联络人\n周五复核')
    profile.get_by_role('textbox', name='账号姓名').fill('未保存的姓名')
    profile.get_by_role('button', name='取消', exact=True).click()
    expect(employee.get_by_text('张同事 · 普通账号', exact=True)).to_be_visible()
    page.get_by_role('textbox', name='搜索账号', exact=True).fill('周五复核')
    page.get_by_role('button', name='搜索', exact=True).click()
    expect(employee).to_be_visible()
    page.get_by_role('textbox', name='搜索账号', exact=True).fill('不存在的同事')
    page.get_by_role('button', name='搜索', exact=True).click()
    expect(page.get_by_text('暂无匹配账号', exact=True)).to_be_visible()
    page.get_by_role('textbox', name='搜索账号', exact=True).fill('')
    page.get_by_role('button', name='搜索', exact=True).click()
    expect(employee).to_be_visible()
    page.screenshot(path=str(output / 'account-actions-desktop.png'), full_page=True, animations='disabled')
    employee.locator('.el-switch').click()
    expect(employee.get_by_role('switch')).to_be_checked()
    employee.get_by_role('button', name='停用', exact=True).click()
    page.get_by_role('button', name='确定', exact=True).click()
    expect(employee.get_by_text('已停用', exact=True)).to_be_visible()
    employee.locator('td').last.screenshot(path=str(output / 'account-actions-disabled.png'), animations='disabled')
    def choose_state(label):
        page.locator('#pane-users .el-select').nth(1).click()
        page.get_by_role('option', name=label, exact=True).click()
    employee.get_by_role('button', name='归档账号', exact=True).click()
    page.get_by_role('dialog', name='归档账号', exact=True).get_by_role('button', name='取消', exact=True).click()
    expect(employee).to_be_visible()
    employee.get_by_role('button', name='归档账号', exact=True).click()
    page.get_by_role('button', name='确认归档', exact=True).click()
    expect(employee).to_have_count(0)
    choose_state('已归档')
    expect(employee.get_by_text('已归档', exact=True)).to_be_visible()
    expect(employee.get_by_role('button', name='启用', exact=True)).to_have_count(0)
    expect(employee.get_by_role('button', name='重置密码', exact=True)).to_have_count(0)
    page.screenshot(path=str(output / 'account-archived-desktop.png'), full_page=True, animations='disabled')
    employee.get_by_role('button', name='恢复账号', exact=True).click()
    page.get_by_role('dialog', name='恢复归档账号', exact=True).get_by_role('button', name='取消', exact=True).click()
    expect(employee).to_be_visible()
    employee.get_by_role('button', name='恢复账号', exact=True).click()
    page.get_by_role('dialog', name='恢复归档账号', exact=True).get_by_role('button', name='恢复', exact=True).click()
    expect(employee).to_have_count(0)
    choose_state('未归档（全部）')
    expect(employee.get_by_text('已停用', exact=True)).to_be_visible()
    expect(employee.get_by_text('张同事 · 普通账号', exact=True)).to_be_visible()
    employee.get_by_role('button', name='启用', exact=True).click()
    page.get_by_role('button', name='确定', exact=True).click()
    expect(employee.get_by_text('正常', exact=True)).to_be_visible()
    employee.get_by_role('button', name='重置密码', exact=True).click()
    page.get_by_role('button', name='重置', exact=True).click()
    verify_admin_password(page)
    expect(secret).to_be_visible()
    assert len(secret.input_value()) >= 8
    page.get_by_role('button', name='已保存，关闭').click()
    employee.get_by_role('button', name='提升为管理员').click()
    page.get_by_role('button', name='确认提升').click()
    verify_admin_password(page)
    expect(employee).to_have_count(0)
    choose_role('管理员')
    employee = account_row('ui-employee')
    expect(employee.get_by_role('button', name='降为普通账号', exact=True)).to_be_visible()
    employee.get_by_role('button', name='停用', exact=True).click()
    page.get_by_role('button', name='确定', exact=True).click()
    verify_admin_password(page)
    expect(employee.get_by_text('已停用', exact=True)).to_be_visible()
    employee.get_by_role('button', name='启用', exact=True).click()
    page.get_by_role('button', name='确定', exact=True).click()
    verify_admin_password(page)
    expect(employee.get_by_text('正常', exact=True)).to_be_visible()
    employee.get_by_role('button', name='降为普通账号').click()
    page.get_by_role('button', name='确认降级').click()
    # Cancelling identity verification leaves the account unchanged.
    page.get_by_role('dialog', name='验证管理员身份').get_by_role('button', name='取消').click()
    expect(employee).to_be_visible()
    employee.get_by_role('button', name='降为普通账号').click()
    page.get_by_role('button', name='确认降级').click()
    verify_admin_password(page)
    expect(employee).to_have_count(0)
    own = account_row('ui-admin')
    expect(own.get_by_role('button', name='停用', exact=True)).to_be_disabled()
    expect(own.get_by_role('button', name='降为普通账号')).to_be_disabled()
    expect(own.get_by_text('最后一个启用的管理员', exact=True)).to_be_visible()
    page.screenshot(path=str(output / 'admin-management-desktop.png'), full_page=True, animations='disabled')
    page.set_viewport_size({'width': 390, 'height': 844})
    expect(page.get_by_role('heading', name='账号管理', exact=True).first).to_be_visible()
    page.screenshot(path=str(output / 'admin-management-mobile.png'), full_page=True, animations='disabled')
    page.set_viewport_size({'width': 1440, 'height': 1000})
    page.get_by_role('tab', name='操作日志', exact=True).click()
    page.get_by_role('textbox', name='日志操作人', exact=True).fill('ui-admin')
    page.get_by_role('textbox', name='日志操作对象', exact=True).fill('张同事')
    page.locator('#pane-audits .el-select').click()
    page.get_by_role('option', name='编辑账号资料', exact=True).click()
    rows = page.locator('#pane-audits .el-table__body-wrapper tr')
    expect(rows).to_have_count(1)
    expect(rows.get_by_text('修改姓名、备注', exact=True)).to_be_visible()
    page.get_by_placeholder('开始日期', exact=True).fill('2020-01-01')
    page.get_by_placeholder('结束日期', exact=True).fill('2099-12-31')
    page.get_by_placeholder('结束日期', exact=True).press('Enter')
    page.get_by_role('button', name='查询', exact=True).click()
    expect(rows).to_have_count(1)
    page.screenshot(path=str(output / 'account-audits-desktop.png'), full_page=True, animations='disabled')
    page.get_by_role('textbox', name='日志操作对象', exact=True).fill('不存在的同事')
    page.get_by_role('button', name='查询', exact=True).click()
    expect(page.get_by_text('暂无匹配的操作日志', exact=True)).to_be_visible()
    page.get_by_role('button', name='重置筛选', exact=True).click()
    expect(page.get_by_role('textbox', name='日志操作对象', exact=True)).to_have_value('')
    expect(page.get_by_text('暂无匹配的操作日志', exact=True)).not_to_be_visible()
    page.set_viewport_size({'width': 390, 'height': 844})
    page.screenshot(path=str(output / 'account-audits-mobile.png'), full_page=True, animations='disabled')
    page.set_viewport_size({'width': 1440, 'height': 1000})
    page.get_by_role('tab', name='邀请管理', exact=True).click()
    invitations = page.locator('#pane-invitations .el-table__body-wrapper tr')
    expect(invitations).to_have_count(3)
    active = invitations.filter(has_text='可使用')
    expect(active.get_by_role('button', name='删除', exact=True)).to_have_count(0)
    expect(active.get_by_role('button', name='撤销', exact=True)).to_be_visible()
    page.screenshot(path=str(output / 'invitation-delete-desktop.png'), full_page=True, animations='disabled')
    for status in ['已撤销', '已使用']:
        invitation = invitations.filter(has_text=status)
        invitation.get_by_role('button', name='删除', exact=True).click()
        page.get_by_role('dialog', name='删除邀请', exact=True).get_by_role('button', name='取消', exact=True).click()
        expect(invitation).to_be_visible()
        invitation.get_by_role('button', name='删除', exact=True).click()
        page.get_by_role('button', name='确认删除', exact=True).click()
        expect(invitation).to_have_count(0)
    expect(invitations).to_have_count(1)
    page.get_by_role('tab', name='操作日志', exact=True).click()
    page.get_by_role('button', name='重置筛选', exact=True).click()
    page.locator('#pane-audits .el-select').click()
    page.get_by_role('option', name='删除邀请', exact=True).click()
    expect(page.locator('#pane-audits .el-table__body-wrapper tr')).to_have_count(2)
    expect(page.locator('#pane-audits .el-table__body-wrapper tr').filter(has_text='ui-employee')).to_have_count(1)
    page.screenshot(path=str(output / 'invitation-deleted-audit.png'), full_page=True, animations='disabled')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-channel", default="msedge")
    parser.add_argument("--output-dir", default=str(ROOT / "work" / "account-ui"))
    parser.add_argument("--assets-dir", help="Optional local cache: vue.js, element.js/css, marked.js, icons.css")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--local-management-only', action='store_true', help='Use seeded accounts and skip invitation flows')
    mode.add_argument('--personal-home-only', action='store_true', help='Verify personal home with isolated fixture research data')
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="account-ui-") as temporary:
        engine = create_engine("sqlite:///" + str(Path(temporary) / "test.db"), connect_args={"check_same_thread": False})
        migrate_accounts(engine)
        factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
        # Isolated process and DB: these credentials never belong to a real account.
        auth.SECRET_KEY = "ui-acceptance-only-random-secret-" + str(time.time_ns())
        with factory() as db:
            admin = User(username="ui-admin", role="admin", password_hash=auth.get_password_hash("Ui-admin-password-123"))
            db.add(admin)
            if args.local_management_only:
                db.add(User(username='ui-employee', role='user', password_hash=auth.get_password_hash('Ui-member-password-123')))
                db.flush()
                employee_id = db.scalar(select(User.id).where(User.username == 'ui-employee'))
                for index, state in enumerate(['active', 'used', 'revoked']):
                    invitation = AccountInvitation(token_hash=hashlib.sha256((str(index) * 43).encode()).hexdigest(),
                        created_by_id=admin.id, expires_at=datetime.utcnow() + timedelta(hours=6),
                        used_at=datetime.utcnow() if state == 'used' else None,
                        used_by_id=employee_id if state == 'used' else None,
                        revoked_at=datetime.utcnow() if state == 'revoked' else None)
                    db.add(invitation); db.flush()
                    db.add(AccountAudit(actor_id=admin.id, invitation_id=invitation.id, action='invitation_created'))
                    if state != 'active':
                        db.add(AccountAudit(actor_id=admin.id, invitation_id=invitation.id,
                            target_user_id=employee_id if state == 'used' else None,
                            action='invitation_used' if state == 'used' else 'invitation_revoked'))
            if args.personal_home_only:
                db.flush()
                seed_home(db, admin)
            db.commit()
        app = FastAPI()
        app.include_router(router)
        app.include_router(create_home_router(lambda pid: args.personal_home_only and pid == 15))
        def get_db():
            with factory() as db:
                yield db
        app.dependency_overrides[auth.get_db] = get_db
        @app.get("/research/projects")
        def projects(user=Depends(auth.get_current_user), db=Depends(auth.get_db)):
            if not args.personal_home_only:
                return {"projects": []}
            query = select(ResearchProject)
            if user.role != 'admin':
                query = query.where(ResearchProject.created_by_id == user.id)
            return {"projects": [project_dict(row) for row in db.scalars(query.order_by(ResearchProject.updated_at.desc()))]}
        def project_dict(row):
            return {key: getattr(row, key) for key in ['id','title','target_name','target_type','industry','description','status']} | {'created_at': stamp(row.created_at), 'updated_at': stamp(row.updated_at)}
        @app.get('/research/projects/{project_id}/detail')
        @app.get('/research/projects/{project_id}/progress')
        def detail(project_id: int, user=Depends(auth.get_current_user), db=Depends(auth.get_db)):
            project = db.get(ResearchProject, project_id)
            if not project or (user.role != 'admin' and project.created_by_id != user.id):
                raise HTTPException(404)
            return {'project': project_dict(project), 'intake': {}, 'source_count': 0, 'artifact_count': 0, 'sources': [], 'artifacts': [], 'trace': []}
        @app.get('/research/artifacts/{artifact_id}/download')
        def download(artifact_id: int, user=Depends(auth.get_current_user), db=Depends(auth.get_db)):
            artifact = db.get(ResearchArtifact, artifact_id)
            project = db.get(ResearchProject, artifact.project_id) if artifact else None
            if not project or (user.role != 'admin' and project.created_by_id != user.id):
                raise HTTPException(404)
            return Response(artifact.content, media_type='text/plain', headers={'Content-Disposition': 'attachment; filename="home-report.txt"'})
        app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(.1)
            assert server.started, "Isolated UI server did not start"
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel=args.browser_channel, headless=True)
                assets = {
                    "https://unpkg.com/vue@3/dist/vue.global.prod.js": "vue.js",
                    "https://unpkg.com/element-plus/dist/index.full.min.js": "element.js",
                    "https://unpkg.com/element-plus/dist/index.css": "element.css",
                    "https://cdn.jsdelivr.net/npm/marked/marked.min.js": "marked.js",
                    "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css": "icons.css",
                }
                def configure_context(context):
                    if args.assets_dir:
                        for url, filename in assets.items():
                            asset = Path(args.assets_dir) / filename
                            content_type = "text/css" if filename.endswith("css") else "application/javascript"
                            context.route(url, lambda route, request, file=asset, mime=content_type: route.fulfill(path=str(file), content_type=mime))
                        def font_route(route):
                            font = Path(args.assets_dir) / route.request.url.rsplit("/", 1)[-1]
                            route.fulfill(path=str(font), content_type="font/woff2") if font.exists() else route.abort()
                        context.route("**/webfonts/*", font_route)
                errors = []
                admin_context = browser.new_context(viewport={"width": 1440, "height": 1000})
                configure_context(admin_context)
                page = admin_context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                base = f"http://127.0.0.1:{port}/"
                page.goto(base)
                page.get_by_role("button", name="管理员", exact=True).click()
                expect(page.get_by_role("button", name="邀请注册", exact=True)).to_have_count(1)
                page.get_by_role("textbox", name="用户名", exact=True).fill("ui-admin")
                page.get_by_role("textbox", name="密码", exact=True).fill("Ui-admin-password-123")
                page.get_by_role("button", name="管理员登录", exact=True).click()
                if args.personal_home_only:
                    personal_home_only(page, base, output, browser, configure_context)
                    assert not errors, errors
                    browser.close()
                    print('Personal home browser checks passed: login landing, private data, latest report versions/review labels, downloads, paginated task opening, empty/error states, mobile layout; no research started')
                    return
                page.get_by_role("menuitem", name="账号管理").click()
                if args.local_management_only:
                    management_only(page, base, output)
                    assert not errors, errors
                    browser.close()
                    print('Local account browser checks passed: profiles, audit filters, permissions, archive/restore/cancellation, used/revoked invitation deletion/cancellation and retained logs, last-admin protection, responsive layout; registration flows skipped')
                    return
                page.get_by_role("tab", name="邀请管理").click()
                expect(page.get_by_role("spinbutton", name="邀请有效期（小时）")).to_have_value("6")
                page.get_by_role("button", name="生成邀请码").click()
                secret = page.get_by_role("textbox", name="复制内容")
                expect(secret).to_be_visible()
                link = secret.input_value()
                assert len(link) == 43 and '://' not in link
                page.get_by_role("button", name="已保存，关闭").click()
                member_context = browser.new_context(viewport={"width": 1280, "height": 900})
                configure_context(member_context)
                member = member_context.new_page()
                member.on("pageerror", lambda error: errors.append(str(error)))
                member.goto(base)
                member.get_by_role('button', name='普通用户', exact=True).click()
                member.get_by_role('button', name='邀请注册', exact=True).click()
                member.get_by_role('textbox', name='邀请码', exact=True).fill(link)
                member.get_by_role('textbox', name='用户名', exact=True).click()
                expect(member.get_by_role("button", name="普通用户注册", exact=True)).to_be_visible()
                expect(member.get_by_text("邀请有效，到期时间：", exact=False)).to_be_visible()
                assert "invite=" not in member.url
                member.get_by_role("textbox", name="用户名", exact=True).fill("ui-employee")
                member.get_by_role("textbox", name="密码", exact=True).fill("Ui-member-password-123")
                member.get_by_role("textbox", name="确认密码", exact=True).fill("Ui-member-password-123")
                member.get_by_role("button", name="普通用户注册", exact=True).click()
                expect(member.get_by_text("ui-employee", exact=True)).to_be_visible()
                expect(member.get_by_role("menuitem", name="账号管理")).to_have_count(0)
                page.get_by_role("tab", name="账号列表").click()
                expect(page.get_by_role("cell").filter(has_text="ui-employee")).to_be_visible()
                page.locator(".el-switch").click()
                expect(page.get_by_text("账号已更新", exact=True)).to_be_visible()
                expect(page.get_by_role("switch")).to_be_checked()
                page.screenshot(path=str(output / "accounts-desktop.png"), full_page=True, animations="disabled")
                page.get_by_role("button", name="停用", exact=True).click()
                page.get_by_role("button", name="确定", exact=True).click()
                expect(page.get_by_text("已停用", exact=True).first).to_be_visible()
                member.reload()
                expect(member.get_by_role("button", name="普通用户", exact=True)).to_be_visible()
                page.get_by_role("button", name="启用", exact=True).click()
                page.get_by_role("button", name="确定", exact=True).click()
                page.get_by_role("button", name="重置密码", exact=True).click()
                page.get_by_role("button", name="重置", exact=True).click()
                verify_admin_password(page)
                expect(secret).to_be_visible()
                temporary_password = secret.input_value()
                page.get_by_role("button", name="已保存，关闭").click()
                member.get_by_role("button", name="普通用户", exact=True).click()
                member.get_by_role("textbox", name="用户名", exact=True).fill("ui-employee")
                member.get_by_role("textbox", name="密码", exact=True).fill(temporary_password)
                member.get_by_role("button", name="普通用户登录", exact=True).click()
                expect(member.get_by_role("heading", name="请修改临时密码")).to_be_visible()
                member.get_by_role("textbox", name="临时密码", exact=True).fill(temporary_password)
                member.get_by_role("textbox", name="新密码", exact=True).fill("Ui-changed-password-456")
                member.get_by_role("textbox", name="确认新密码", exact=True).fill("Ui-changed-password-456")
                member.get_by_role("button", name="修改密码并继续", exact=True).click()
                expect(member.get_by_role("menuitem", name="任务管理")).to_be_visible()
                # Check ordinary password change dialog as well.
                member.get_by_role("button", name="修改密码", exact=True).click()
                member.get_by_role("textbox", name="原密码", exact=True).fill("Ui-changed-password-456")
                member.get_by_role("textbox", name="新密码", exact=True).fill("Ui-final-password-789")
                member.get_by_role("textbox", name="确认新密码", exact=True).fill("Ui-final-password-789")
                member.get_by_role("button", name="保存新密码", exact=True).click()
                expect(member.get_by_role("dialog", name="修改密码")).not_to_be_visible()
                # Administrator invitations derive the role from the link.
                page.get_by_role("tab", name="邀请管理").click()
                page.locator("#pane-invitations .el-select").click()
                page.get_by_role("option", name="管理员", exact=True).click()
                page.get_by_role("button", name="生成邀请码").click()
                verify_admin_password(page)
                expect(secret).to_be_visible()
                admin_link = secret.input_value()
                page.get_by_role("button", name="已保存，关闭").click()
                invited_context = browser.new_context(viewport={"width": 1280, "height": 900})
                configure_context(invited_context)
                invited = invited_context.new_page()
                invited.on("pageerror", lambda error: errors.append(str(error)))
                invited.goto(base)
                invited.get_by_role('button', name='管理员', exact=True).click()
                invited.get_by_role('button', name='邀请注册', exact=True).click()
                invited.get_by_role('textbox', name='邀请码', exact=True).fill(admin_link)
                invited.get_by_role('textbox', name='用户名', exact=True).click()
                expect(invited.get_by_role("button", name="管理员注册", exact=True)).to_be_visible()
                invited.get_by_role("textbox", name="用户名", exact=True).fill("ui-new-admin")
                invited.get_by_role("textbox", name="密码", exact=True).fill("Admin123")
                invited.get_by_role("textbox", name="确认密码", exact=True).fill("Admin123")
                invited.get_by_role("button", name="管理员注册", exact=True).click()
                expect(invited.get_by_role("menuitem", name="账号管理")).to_be_visible()
                # Elevation invalidates the member's current session.
                page.get_by_role("tab", name="账号列表").click()
                page.get_by_role("button", name="提升为管理员", exact=True).click()
                page.get_by_role("button", name="确认提升", exact=True).click()
                verify_admin_password(page)
                expect(page.get_by_role("cell").filter(has_text="ui-employee")).to_have_count(0)
                member.reload()
                expect(member.get_by_role("button", name="管理员", exact=True)).to_be_visible()
                member.get_by_role("button", name="管理员", exact=True).click()
                member.get_by_role("textbox", name="用户名", exact=True).fill("ui-employee")
                member.get_by_role("textbox", name="密码", exact=True).fill("Ui-final-password-789")
                member.get_by_role("button", name="管理员登录", exact=True).click()
                expect(member.get_by_role("menuitem", name="账号管理")).to_be_visible()
                # Second invitation: validate the revocation UI and invalid-link state.
                page.get_by_role("tab", name="邀请管理").click()
                page.get_by_role("button", name="生成邀请码").click()
                verify_admin_password(page)
                expect(secret).to_be_visible()
                revoked_link = secret.input_value()
                page.get_by_role("button", name="已保存，关闭").click()
                page.get_by_role("button", name="撤销", exact=True).click()
                page.get_by_role("button", name="撤销", exact=True).last.click()
                expect(page.get_by_text("已撤销", exact=True)).to_be_visible()
                page.screenshot(path=str(output / "invitations-desktop.png"), full_page=True, animations="disabled")
                mobile_context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
                configure_context(mobile_context)
                mobile = mobile_context.new_page()
                mobile.on("pageerror", lambda error: errors.append(str(error)))
                mobile.goto(base + '#invite=' + revoked_link)
                expect(mobile.get_by_text("邀请码无效、已过期、已撤销或已使用", exact=True)).to_be_visible()
                mobile.screenshot(path=str(output / "registration-mobile.png"), full_page=True)
                assert not errors, errors
                browser.close()
                print("Account browser acceptance passed: default 6 hours, ordinary/admin invitation registration, promotion, grants, disable/enable, password changes, revoke, mobile layout")
                print(f"Screenshots: {output}")
        finally:
            server.should_exit = True
            worker.join(timeout=10)
            listener.close()
            engine.dispose()


if __name__ == "__main__":
    main()
