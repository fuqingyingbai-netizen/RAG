"""Render the user manual from the same catalog used by the assistant."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render():
    catalog = json.loads((ROOT / 'backend/guide_catalog.json').read_text(encoding='utf-8'))
    lines = ['# 系统使用指南', '',
             '本指南与小助手共用一份功能目录，按实际页面和后端规则维护。操作路径、权限和限制以当前版本为准；部署配置、真实任务状态和业务资料请在相应页面核对。', '',
             f'本次核对基线：`{catalog["reviewed_base"]}`。包含 {len(catalog["topics"])} 个功能主题。管理员专属内容已单独标记，小助手会按当前登录角色过滤。', '',
             '## 功能目录', '']
    for page, item in catalog['pages'].items():
        lines.append(f'- [{item["title"]}](#{page})')
    for page, item in catalog['pages'].items():
        lines += ['', f'<a id="{page}"></a>', '', '## ' + item['title'], '', item['summary']]
        for topic in catalog['topics']:
            if topic['page'] != page:
                continue
            lines += ['', f'<a id="{topic["id"]}"></a>', '', '### ' + topic['title'] + ('（仅管理员）' if topic['roles'] == ['admin'] else ''), '', topic['body'], '',
                      '也可以这样问：' + '、'.join('“' + alias + '”' for alias in topic['aliases'][:4]) + '。']
    lines += ['', '---', '', '本文由 `scripts/build-system-guide.py` 从 `backend/guide_catalog.json` 生成。更新功能时请修改目录并重新生成，维护流程见 [指南维护说明](SYSTEM_GUIDE_MAINTENANCE.md)。', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Fail if the committed manual differs from the catalog.')
    args = parser.parse_args()
    target = ROOT / 'docs/SYSTEM_USER_GUIDE.md'
    expected = render()
    if args.check:
        if not target.exists() or target.read_text(encoding='utf-8') != expected:
            raise SystemExit('System guide is stale; run python scripts/build-system-guide.py')
        print('System guide matches the assistant catalog')
    else:
        target.write_text(expected, encoding='utf-8')
        print('Updated docs/SYSTEM_USER_GUIDE.md')
