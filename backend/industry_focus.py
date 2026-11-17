"""Research depth only: never removes chapters or relaxes evidence review."""
import json
from pathlib import Path
CONFIG = json.loads(Path(__file__).with_name('industry_focus_modules.json').read_text(encoding='utf-8'))
VERSION = CONFIG['version']
MODULES = {row['name']: row for row in CONFIG['modules']}


def apply_focus(scope, modules):
    unknown = set(modules) - MODULES.keys()
    if unknown:
        raise ValueError('未知行业重点模块：' + '、'.join(sorted(unknown)))
    scope = dict(scope)
    scope['focus_policy_version'] = VERSION
    scope['focus_modules'] = list(dict.fromkeys(modules))
    return scope


def module_enabled(scope, name):
    if name == '投融资与资本市场' and scope.get('capital_market') == 'none':
        return False
    if name == '核心企业尽调':
        return bool(scope.get('named_companies'))
    return 'focus_modules' not in scope or name in scope['focus_modules']


def question_depth(scope, chapter, question):
    scope = scope or {}
    if (chapter in (8, 9) and scope.get('capital_market') == 'none') or (chapter == 12 and not scope.get('named_companies')):
        return 'excluded'
    if 'focus_modules' not in scope:
        return 'priority'  # Preserve historical checkpoints lacking a focus contract.
    return 'priority' if any(module_enabled(scope, name) and question in row['primary'].get(str(chapter), [])
                             for name, row in MODULES.items()) else 'basic'


def mapping(scope):
    return [{**row, 'selected': module_enabled(scope, row['name'])} for row in CONFIG['modules']]


def primary_module(scope, chapter, question):
    """Label a supplemental query with its selected owner, never a related module."""
    return next((name for name, row in MODULES.items()
                 if module_enabled(scope or {}, name) and question in row['primary'].get(str(chapter), [])), None)
