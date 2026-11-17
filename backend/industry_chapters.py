"""Industry chapter selection, independent of shared source ownership."""
import hashlib
import json
from pathlib import Path

_RAW = Path(__file__).with_suffix('.json').read_bytes()
_CONFIG = json.loads(_RAW)
CHAPTERS = _CONFIG['chapters']
VERSION = _CONFIG['version'] + '-' + hashlib.sha256(
    json.dumps(_CONFIG, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]
AUTO = {c['chapter'] for c in CHAPTERS if not c['selectable']}
_BY_ID = {c['id']: c for c in CHAPTERS if c['selectable']}
assert [c['chapter'] for c in CHAPTERS] == list(range(1, 17))
assert len(_BY_ID) == 12


def validate_selection(values):
    if not isinstance(values, list) or not values:
        raise ValueError('请至少选择一个行业主体章节。')
    if any(not isinstance(v, str) or v not in _BY_ID for v in values):
        raise ValueError('行业章节选择无效，请刷新目录后重新选择。')
    return [c['id'] for c in CHAPTERS if c['id'] in values and c['selectable']]


def report_chapters(scope=None):
    scope = scope or {}
    if 'selected_chapters' not in scope:
        return list(range(1, 17))  # Saved module-based projects retain their original outline.
    values = scope['selected_chapters']
    if not isinstance(values, list) or not values or any(type(n) is not int or n not in range(2, 14) for n in values):
        raise ValueError('保存的行业章节选择无效，请重新选择。')
    return sorted(set(values) | AUTO)


def research_modules(numbers):
    return list(dict.fromkeys(m for c in CHAPTERS if c['chapter'] in numbers for m in c['research_modules']))


def apply_selection(normalized, raw):
    scope = normalized['industry_scope']
    values = raw.get('industry_chapter_ids')
    saved = raw.get('industry_scope') or {}
    if values is None and 'selected_chapters' in saved:
        values = [c['id'] for c in CHAPTERS if c['chapter'] in report_chapters(saved) and c['selectable']]
    if values is None:
        return
    if raw.get('industry_template_version') not in (None, '', VERSION):
        raise ValueError('行业章节目录已更新，请刷新后重新提交。')
    ids = validate_selection(values)
    numbers = [_BY_ID[v]['chapter'] for v in ids]
    if 12 in numbers and not scope.get('named_companies'):
        raise ValueError('选择核心公司尽调时，请填写需要尽调的核心企业名称。')
    if set(numbers) & {8, 9} and scope.get('capital_market') == 'none':
        raise ValueError('选择投融资或二级市场章节时，请开启资本市场范围。')
    scope['selected_chapters'] = numbers
    scope['chapter_template_version'] = VERSION
    normalized['industry_chapter_ids'] = ids
    normalized['industry_template_version'] = VERSION
    normalized['focus_modules'] = research_modules(numbers)
    if scope.get('capital_market') == 'none':
        normalized['focus_modules'] = [m for m in normalized['focus_modules'] if m != '投融资与资本市场']


def public_config():
    return {'version': VERSION, 'chapters': [
        {'chapter': c['chapter'], 'value': c['id'], 'label': f"第{c['chapter']}章 {c['title']}",
         'selectable': c['selectable'], 'requirements': c['requirements']}
        for c in CHAPTERS],
        'defaults': [c['id'] for c in CHAPTERS if c['default_selected']],
        'automatic': [c['id'] for c in CHAPTERS if not c['selectable']]}
