"""Industry-only scope, evidence and scoring contracts shared by its pipeline."""

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from datetime import date
from typing import Any

INDUSTRY_POLICY_VERSION = 'industry-scope-v2'
INDUSTRY_RISK_DIMENSIONS = (
    '政策与监管风险', '市场增长与需求风险', '竞争格局与集中度风险',
    '商业化与盈利模式风险', '技术迭代与替代风险', '资本热度与估值风险', '数据口径与证据可靠性风险',
)


def split_values(value: Any) -> list[str]:
    values = value if isinstance(value, list) else re.split(r'[、,，;；/\n]+', str(value or ''))
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def normalize_scope(project: Any, normalized: dict, raw: dict) -> dict:
    saved = raw.get('industry_scope') if isinstance(raw.get('industry_scope'), dict) else {}
    assumptions = []
    industry = str(normalized.get('industry') or normalized.get('target_name') or project.target_name).strip()
    if raw.get('industry_segments'):
        segments = split_values(raw['industry_segments'])
    elif 'industry_focus' in raw:
        segments = split_values(raw['industry_focus'])
    else:
        segments = split_values(saved.get('segments'))
    if not segments:
        description = str(normalized.get('special_requirements') or '')
        match = re.search(r'(?:重点看|重点研究|关注赛道)[：:\s]*(.+?)(?:[。；;\n]|$)', description)
        if match:
            segments = split_values(re.sub(r'\s*(?:以及|和|及)\s*', '、', match.group(1)))
            segments = ['AI应用' if item.replace(' ', '').lower() == 'ai应用' else item for item in segments]
    if not segments:
        segments = [industry]
        assumptions.append('未指定细分赛道，按主行业概览；不同赛道的市场规模不直接合计。')
    geography = str(raw.get('geography') or normalized.get('region') or saved.get('geography') or '').strip()
    if not geography:
        geography = '中国大陆'
        assumptions.append('未指定地域，默认中国大陆市场。')
    cutoff = str(raw.get('as_of_date') or saved.get('as_of_date') or '').strip()
    if not cutoff:
        cutoff = date.today().isoformat()
        assumptions.append('未指定数据截止日，以首次规范化时的日期为截点。')
    # Do not accept an invalid or ambiguous month-only reporting date.
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', cutoff):
        raise ValueError('数据截止日必须为 YYYY-MM-DD。')
    date.fromisoformat(cutoff)
    purpose = str(raw.get('research_purpose') or saved.get('purpose') or '').strip()
    if not purpose:
        blob = str(normalized.get('special_requirements') or '') + str(normalized.get('research_type') or '')
        purpose = next((label for words, label in (
            (('投资', '投前', '估值', '融资'), '投资判断'), (('战略', '规划', '布局'), '战略研究'),
            (('尽调', '合规', '风险'), '尽调支持'),
        ) if any(word in blob for word in words)), '日常了解')
        assumptions.append('研究用途由任务描述推断，请在研究边界中核对。')
    include_capital = raw.get('include_capital_markets')
    if include_capital is not None and not isinstance(include_capital, bool):
        raise ValueError('资本市场开关必须为布尔值。')
    capital = ('summary' if include_capital else 'none') if include_capital is not None else saved.get('capital_market')
    if capital not in {'none', 'summary'}:
        capital = 'summary' if purpose == '投资判断' else 'none'
        assumptions.append('资本市场范围根据研究用途推断。')
    retained_defaults = {
        '未指定细分赛道': segments == saved.get('segments'),
        '未指定地域': geography == saved.get('geography'),
        '未指定数据截止日': cutoff == saved.get('as_of_date'),
        '研究用途': purpose == saved.get('purpose'),
        '资本市场范围': capital == saved.get('capital_market'),
    }
    assumptions.extend(note for note in saved.get('assumptions', [])
                       if any(note.startswith(prefix) and unchanged for prefix, unchanged in retained_defaults.items()))
    assumptions = list(dict.fromkeys(assumptions))
    return {
        'industry_name': industry, 'segments': segments,
        'excluded_segments': split_values(raw.get('excluded_segments', saved.get('excluded_segments'))),
        'geography': geography, 'as_of_date': cutoff, 'purpose': purpose, 'capital_market': capital,
        'named_companies': split_values(raw['focus_entities']) if 'focus_entities' in raw else split_values(saved.get('named_companies')),
        'scope_confidence': 'medium' if assumptions else 'high', 'assumptions': assumptions,
        'policy_version': INDUSTRY_POLICY_VERSION,
    }


def scope_fingerprint(intake: dict, source_only: bool = False) -> str:
    scope = intake.get('industry_scope') or {}
    payload = {
        'policy_version': INDUSTRY_POLICY_VERSION,
        'target_name': re.sub(r'\s+', '', str(intake.get('target_name') or '')).lower(),
        'scope': {key: scope.get(key) for key in ('industry_name', 'segments', 'excluded_segments', 'geography',
                   'as_of_date', 'purpose', 'capital_market', 'named_companies')},
        'modules': sorted(set(intake.get('focus_modules') or [])),
        'search_queries': sorted(set(intake.get('search_queries') or [])),
        'focus_questions': sorted(set(intake.get('focus_questions') or [])),
        'special_requirements': intake.get('special_requirements') or '',
    }
    for key in ('segments', 'excluded_segments', 'named_companies'):
        payload['scope'][key] = sorted(set(payload['scope'].get(key) or []))
    if source_only:
        payload = {key: payload[key] for key in ('policy_version', 'target_name', 'scope')}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def source_in_current_run(source: Any, fingerprint: str) -> bool:
    meta = source.source_metadata or {}
    # Uploaded and reviewed first-party evidence is rechecked during cleaning.
    if source.source_type in {'upload', 'manual'} or meta.get('stage') in {'initial_upload', 'human_review', 'second_stage'}:
        return True
    return meta.get('industry_scope_fingerprint') == fingerprint


def chapter_scopes(title: str) -> set[str]:
    if '二级市场' in title or '投融资' in title:
        return {'capital_market', 'representative_company', 'industry_level', 'segment_level'}
    if any(word in title for word in ('摘要', '风险', '评估', '投资机会', '竞争', '公司', '企业', '技术路线', '信息来源', '后续')):
        return {'industry_level', 'segment_level', 'representative_company', 'capital_market'}
    return {'industry_level', 'segment_level'}


def active_risk_dimensions(scope: dict | None = None) -> tuple[str, ...]:
    return tuple(name for name in INDUSTRY_RISK_DIMENSIONS
                 if not ((scope or {}).get('capital_market') == 'none' and name == '资本热度与估值风险'))


def unknown_risk(reason: str = '未取得可审计的行业评分，需补充有效证据。', scope: dict | None = None) -> dict:
    return {'overall_score': None, 'risk_level': 'unknown',
            'dimensions': [{'name': name, 'score': None, 'level': 'unknown', 'reason': reason,
                            'evidence_ids': [], 'evidence_sources': []} for name in active_risk_dimensions(scope)],
            'key_risks': [], 'unknowns': [reason], 'recommended_followups': ['补充行业统计、监管文件和可比企业披露。']}


def normalize_risk(parsed: Any, facts: list[dict], scope: dict | None = None) -> dict:
    result = dict(parsed) if isinstance(parsed, dict) else unknown_risk()
    evidence = {str(f.get('evidence_id')): f for f in facts if f.get('evidence_id')
                and f.get('eligible_for_risk_scoring') is not False and f.get('eligible_for_report') is not False
                and f.get('scope_match') == 'in_scope'}
    supplied = {d.get('name'): d for d in result.get('dimensions', []) if isinstance(d, dict)}
    dimensions = []
    unknowns = list(result.get('unknowns') or [])
    if (scope or {}).get('capital_market') == 'none':
        capital_words = ('资本热度', '估值', '投融资', '二级市场', '融资数据库')
        unknowns = [note for note in unknowns if not any(word in str(note) for word in capital_words)]
        result['recommended_followups'] = [note for note in result.get('recommended_followups', [])
                                           if not any(word in str(note) for word in capital_words)]
    for name in active_risk_dimensions(scope):
        row = dict(supplied.get(name) or {})
        ids = list(dict.fromkeys(eid for eid in row.get('evidence_ids', []) if isinstance(eid, str) and eid in evidence))
        # One company's condition is a sample, never proof of an industry-wide score.
        ids = [eid for eid in ids if evidence[eid].get('evidence_scope') in {'industry_level', 'segment_level', 'capital_market'}]
        score = row.get('score')
        modules = {
            '政策与监管风险': {'政策与监管'}, '市场增长与需求风险': {'市场规模与增长'},
            '竞争格局与集中度风险': {'竞争格局与代表企业'}, '商业化与盈利模式风险': {'商业模式与盈利逻辑'},
            '技术迭代与替代风险': {'技术路线对比', '技术演进与平台生态'},
            '资本热度与估值风险': {'投融资与资本市场'},
        }
        ids = [eid for eid in ids if name not in modules or evidence[eid].get('module') in modules[name]]
        if not ids or isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 100:
            row = {'name': name, 'score': None, 'level': 'unknown', 'reason': '缺少有效且适用的行业证据编号，暂不评分。',
                   'evidence_ids': [], 'evidence_sources': []}
            unknowns.append(name + '：缺少有效评分证据。')
        else:
            row.update(name=name, evidence_ids=ids, level=risk_level(score),
                       evidence_sources=[evidence[eid].get('source_url', '') for eid in ids])
        dimensions.append(row)
    result['dimensions'] = dimensions
    scores = [d['score'] for d in dimensions if d['score'] is not None]
    # A partial score must not suggest that missing dimensions were checked.
    result['overall_score'] = round(sum(scores) / len(scores), 1) if len(scores) == len(dimensions) else None
    result['risk_level'] = risk_level(result['overall_score']) if result['overall_score'] is not None else 'unknown'
    result['unknowns'] = list(dict.fromkeys(unknowns))
    result['applicable_dimensions'] = list(active_risk_dimensions(scope))
    result['assessed_dimension_count'] = len(scores)
    return result


def risk_level(score: float) -> str:
    return 'low' if score < 40 else 'medium' if score < 70 else 'high' if score < 85 else 'critical'


CHAPTER_MODULES = {
    '行业基础定义与产业链全景': ('行业定义与边界', '细分赛道与产业链'),
    '政策环境分析与近期政策摘录': ('政策与监管',),
    '市场规模与增长预测': ('市场规模与增长',),
    '行业热度形成': ('市场规模与增长', '政策与监管', '投融资与资本市场'),
    '竞争格局': ('竞争格局与代表企业', '细分赛道与产业链'),
    '技术路线对比': ('技术路线对比', '技术演进与平台生态'),
    '行业投融资全景': ('投融资与资本市场',),
    '二级市场情绪': ('投融资与资本市场',),
    '投资机会': ('市场规模与增长', '竞争格局与代表企业', '商业模式与盈利逻辑'),
    '前景展望': ('市场规模与增长', '技术演进与平台生态', '政策与监管'),
    '行业核心公司主体全面尽调': ('核心企业尽调',),
    '风险核查': ('行业风险与不确定性', '政策与监管'),
}


def select_chapter_evidence(payload: dict, title: str, requirements: list[str], excluded_urls=None) -> dict:
    scopes = chapter_scopes(title)
    expected = CHAPTER_MODULES.get(title, ())
    candidates = []
    excluded = {str(url).rstrip('/') for url in excluded_urls or []}
    for original in payload.get('facts') or []:
        if not isinstance(original, dict):
            continue
        fact = dict(original)
        if fact.get('eligible_for_report') is False or fact.get('scope_match') != 'in_scope':
            continue
        if fact.get('evidence_scope') not in scopes or str(fact.get('source_url') or '').rstrip('/') in excluded:
            continue
        if title == '行业核心公司主体全面尽调' and fact.get('company_role') != 'requested_due_diligence':
            continue
        blob = ' '.join(str(fact.get(k) or '') for k in ('fact', 'source_title', 'module'))
        module_match = fact.get('module') in expected
        keywords = [word for item in requirements for word in re.split(r'[/｜、，\s]+', item) if len(word) >= 2]
        hits = sum(word in blob for word in keywords)
        derived = title in {'摘要', '行业判断与综合评估', '综合评估', '信息来源', '后续研究点'}
        if not module_match and not hits and not derived:
            continue
        # Structured facts must not lose to source excerpts merely because the
        # excerpt inherits a publisher score while the cleaner omits it.
        structured = fact.get('claim_type') != 'source_excerpt'
        verified_numeric = fact.get('numeric_validation', {}).get('passed') is True
        candidates.append((int(module_match), int(structured), int(verified_numeric), hits,
                           float(fact.get('quality_score') or fact.get('confidence') or 0), fact))
    candidates.sort(key=lambda row: row[:-1], reverse=True)
    focused = []
    seen = set()
    # A source may support different facts/chapters. Repeated identical facts may not.
    for *_, fact in candidates:
        key = fact.get('evidence_id') or (fact.get('source_url'), fact.get('fact'))
        if key in seen:
            continue
        seen.add(key)
        focused.append(fact)
        if len(focused) >= 12:
            break
    # Put evidence first and omit the full ledger; bounded model prompts must not
    # be consumed by metadata before the actual fact cards are reached.
    return {'facts': focused, 'industry_scope': payload.get('industry_scope') or {},
            'information_gaps': (payload.get('information_gaps') or [])[:20]}


def package_risk_evidence(package: dict, payload: dict, risk: dict, include_all: bool = False) -> tuple[dict, dict]:
    """Carry validated risk facts into synthesis chapters; other chapters see only their own risks."""
    facts = list(package.get('facts') or [])
    by_id = {f.get('evidence_id'): f for f in payload.get('facts', []) if isinstance(f, dict)
             and f.get('eligible_for_report') is not False and f.get('scope_match') == 'in_scope'}
    if include_all:
        existing = {f.get('evidence_id') for f in facts}
        for dimension in risk.get('dimensions', []):
            for eid in dimension.get('evidence_ids', []):
                if eid in by_id and eid not in existing:
                    facts.append(by_id[eid]); existing.add(eid)
    allowed = {f.get('evidence_id') for f in facts}
    dimensions = [d for d in risk.get('dimensions', []) if d.get('evidence_ids')
                  and set(d['evidence_ids']) <= allowed]
    scoped_risk = {'dimensions': dimensions, 'overall_score': risk.get('overall_score') if include_all else None,
                  'risk_level': risk.get('risk_level') if include_all else 'unknown',
                  'unknowns': risk.get('unknowns', []) if include_all else []}
    return {**package, 'facts': facts}, scoped_risk


def bounded_package(package: dict, limit: int = 20000) -> str:
    """Keep JSON intact under a prompt budget, prioritizing concise fact cards."""
    result = {**package, 'facts': []}
    for original in package.get('facts', []):
        fact = dict(original)
        fact['fact'] = str(fact.get('fact') or '')[:900]
        fact['evidence_quote'] = str(fact.get('evidence_quote') or '')[:500]
        result['facts'].append(fact)
        if len(json.dumps(result, ensure_ascii=False)) > limit:
            result['facts'].pop(); break
    return json.dumps(result, ensure_ascii=False)


def unique_search_queries(rows: list[dict], seen: set) -> list[dict]:
    distinct = []
    for row in rows:
        key = (re.sub(r'\s+', ' ', str(row.get('query') or '')).strip().casefold(),
               tuple(sorted(row.get('include_domains') or [])), tuple(sorted(row.get('exclude_domains') or [])))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        distinct.append(row)
    return distinct


NUMBER_PATTERN = r'\d[\d,.]*\s*(?:%|％|亿元|万元|亿美元|万美元)'


def number_key(value: str) -> tuple | None:
    match = re.fullmatch(r'([\d,.]+)\s*(%|％|亿元|万元|亿美元|万美元)', value.strip())
    if not match:
        return None
    try:
        amount = Decimal(match[1].replace(',', ''))
    except InvalidOperation:
        return None
    unit = match[2].replace('％', '%')
    if unit in ('亿元', '万元'):
        amount *= Decimal('100000000' if unit == '亿元' else '10000'); unit = '人民币元'
    elif unit in ('亿美元', '万美元'):
        amount *= Decimal('100000000' if unit == '亿美元' else '10000'); unit = '美元'
    return amount, unit


def numeric_supported(number: str, eid: str, numeric: dict) -> bool:
    card = numeric.get(eid, {})
    if card.get('validation', {}).get('passed') is not True:
        return False
    context = card.get('context') or {}
    # A verified metric validates that metric only, never all numbers on a page.
    value = str(context.get('value', '')) + str(context.get('unit', ''))
    return number_key(number) is not None and number_key(number) == number_key(value)


def mark_unverified_numbers(section: str, facts: list[dict]) -> str:
    numeric = {f.get('evidence_id'): {'validation': f.get('numeric_validation') or {},
                                    'context': f.get('numeric_context') or {}} for f in facts}
    lines = []
    for line in section.splitlines():
        numbers = re.findall(NUMBER_PATTERN, line)
        ids = re.findall(r'\bE-[A-Z0-9-]{6,}\b', line, flags=re.I)
        if numbers and '待核验' not in line and any(not any(numeric_supported(n, eid, numeric) for eid in ids) for n in numbers):
            line += ' （数值口径待核验，不用于行业合计或评分）'
        lines.append(line)
    return '\n'.join(lines)


def annotate_fact(fact: dict, scope: dict) -> dict:
    item = dict(fact)
    blob = ' '.join(str(item.get(key) or '') for key in ('fact', 'evidence_quote', 'source_title'))
    declared = str(item.get('scope_match') or '')
    names = [scope.get('industry_name'), *scope.get('segments', []), *scope.get('named_companies', [])]
    actual_match = any(str(name).lower().replace(' ', '') in blob.lower().replace(' ', '') for name in names if name)
    if declared not in {'out_of_scope', 'ambiguous', 'uncertain'}:
        item['scope_match'] = 'in_scope' if actual_match else 'uncertain'
    if any(str(segment).lower() in blob.lower() for segment in scope.get('excluded_segments', []) if segment):
        item['scope_match'] = 'out_of_scope'
    source_date = str(item.get('date') or item.get('fact_date') or '').strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', source_date):
        try:
            if date.fromisoformat(source_date) > date.fromisoformat(scope['as_of_date']):
                item['scope_match'] = 'out_of_scope'
        except (ValueError, KeyError):
            pass
    if item['scope_match'] != 'in_scope':
        item['eligible_for_report'] = False
        item['eligible_for_risk_scoring'] = False
    if item.get('evidence_scope') == 'capital_market' and scope.get('capital_market') == 'none':
        item['eligible_for_report'] = False
        item['eligible_for_risk_scoring'] = False
    item['evidence_id'] = 'E-' + hashlib.sha256(
        (str(item.get('source_url') or '') + '\n' + str(item.get('fact') or '')).encode()
    ).hexdigest()[:12].upper()
    numeric = item.get('numeric_context') if isinstance(item.get('numeric_context'), dict) else {}
    numerical = bool(re.search(r'\d[\d,.]*\s*(?:%|％|亿元|万元|亿美元|万美元|亿|万|CAGR|PE|PB|PS)', blob, re.I))
    if numerical:
        required = ('metric', 'unit', 'geography', 'period', 'definition')
        missing = [key for key in required if not numeric.get(key)]
        if numeric.get('value') is None or isinstance(numeric.get('value'), bool) or numeric.get('value') == '':
            missing.append('value')
        if not item.get('source_url'):
            missing.append('source_url')
        if numeric.get('geography') and scope.get('geography'):
            aliases = {'中国': '中国大陆', 'china': '中国大陆', 'mainlandchina': '中国大陆',
                       'usa': '美国', 'unitedstates': '美国', 'us': '美国', 'europe': '欧洲', 'eu': '欧盟'}
            def region_key(value):
                key = re.sub(r'\s+', '', str(value)).lower()
                return aliases.get(key, key)
            requested, actual = region_key(scope['geography']), region_key(numeric['geography'])
            if not any(word in requested for word in ('全球', 'global', 'worldwide')) and actual not in requested:
                missing.append('geography_scope_match')
        period_years = re.findall(r'20\d{2}', str(numeric.get('period') or ''))
        if 'is_forecast' in numeric and not isinstance(numeric['is_forecast'], bool):
            missing.append('is_forecast_boolean')
        expected_number = number_key(str(numeric.get('value', '')) + str(numeric.get('unit', '')))
        if expected_number is not None:
            quote_numbers = re.findall(NUMBER_PATTERN, str(item.get('fact') or '') + ' ' + str(item.get('evidence_quote') or ''))
            if not any(number_key(n) == expected_number for n in quote_numbers):
                missing.append('value_not_in_evidence_quote')
        cutoff = str(scope.get('as_of_date') or '')
        if period_years and cutoff and numeric.get('is_forecast') is not True and max(period_years) > cutoff[:4]:
            missing.append('period_after_cutoff')
        item['numeric_validation'] = {'passed': not missing, 'missing_fields': missing}
        if missing:
            item['eligible_for_risk_scoring'] = False
            item['attribution_boundary'] = '数值口径不完整，按原来源摘录并标注待核验；不用于合计、增长计算或评分。'
    if item.get('evidence_scope') == 'representative_company':
        item['eligible_for_risk_scoring'] = False
    return item


def append_evidence_index(report: str, payload: dict, outline: list, packages: dict | None = None) -> tuple[str, dict]:
    """Index the same evidence packages that writers received, including valid reuse."""
    rows = []
    referenced = set()
    cited_ids = set()
    chapter_ids = {}
    facts = [f for f in payload.get('facts', []) if isinstance(f, dict)]
    total_sources = {f.get('source_url') for f in facts if f.get('eligible_for_report') is not False and f.get('source_url')}
    for index, (title, requirements) in enumerate(outline, 1):
        if index == 15:
            continue
        package = (packages or {}).get(index)
        if isinstance(package, str):
            try:
                package = json.loads(package)
            except ValueError:
                package = None
        selected = package.get('facts', []) if isinstance(package, dict) else select_chapter_evidence(payload, title, requirements)['facts']
        chapter_ids[index] = [f.get('evidence_id') for f in selected if f.get('evidence_id')]
        chapter_match = re.search(rf'(?ms)^##\s*{index}[.、．][^\n]*\n(.*?)(?=^##\s*\d+[.、．]|\Z)', report)
        mentioned = set(re.findall(r'\bE-[A-Z0-9-]{6,}\b', chapter_match[1], re.I)) if chapter_match else set()
        for fact in selected:
            eid = str(fact.get('evidence_id') or '')
            url = str(fact.get('source_url') or '')
            if not eid or not url or not url.startswith(('https://', 'http://', 'structured://')):
                continue
            cited_ids.add(eid)
            if eid not in mentioned:
                continue
            def cell(value):
                return re.sub(r'\s+', ' ', str(value or '待标注')).replace('|', '/')[:160]
            rows.append(f'| [{eid}]({url}) | 第 {index} 章 | {cell(fact.get("fact"))} | {cell(fact.get("provider") or fact.get("source_type"))} / {cell(fact.get("source_grade"))} |')
            referenced.add(url)
    lines = ['## 15. 信息来源（自动生成审计索引）', '',
             '本索引列出章节正文实际引用且属于对应证据包的事实编号；同一来源的不同事实可支持多个章节。', '',
             '| 证据编号与原始来源 | 支持章节 | 信息点 | 获取工具与信源等级 |',
             '| --- | --- | --- | --- |', *rows, '',
             f'> 已纳入章节证据包的唯一来源：{len(referenced)} / 清洗事实库可追溯来源：{len(total_sources)}。', '']
    if not rows:
        lines.insert(3, '本次未形成可引用来源，报告需复核并补充研究。')
    pattern = r'(?ms)^##\s*15[.、．][^\n]*\n.*?(?=^##\s*16[.、．]|\Z)'
    updated, count = re.subn(pattern, lambda _: '\n'.join(lines) + '\n', report)
    if count == 0:
        marker = re.search(r'(?m)^##\s*16[.、．]', report)
        position = marker.start() if marker else len(report)
        updated = report[:position] + '\n'.join(lines) + '\n' + report[position:]
    return updated, {'referenced_sources': len(referenced), 'total_fact_sources': len(total_sources),
                     'evidence_ids': sorted(cited_ids), 'chapter_evidence_ids': chapter_ids,
                     'numeric_evidence': {f['evidence_id']: {'validation': f.get('numeric_validation') or {},
                                         'fact': str(f.get('fact', ''))[:900], 'context': f.get('numeric_context') or {}}
                                          for f in facts if f.get('evidence_id') in cited_ids}}


def delivery_errors(report: str, diagnostic: dict, scope: dict) -> list[str]:
    chapters = list(re.finditer(r'(?m)^##\s*(\d{1,2})[.、．]\s*[^\n]*', report))
    present = [int(match.group(1)) for match in chapters]
    errors = []
    if present != list(range(1, 17)):
        errors.append('行业报告目录必须为完整且不重复的16章。')
    valid = set(diagnostic.get('evidence_ids') or [])
    disabled = ({8, 9} if scope.get('capital_market') == 'none' else set()) | ({12} if not scope.get('named_companies') else set())
    cited_chapters = 0
    for position, match in enumerate(chapters):
        chapter = int(match.group(1))
        if chapter >= 15:
            continue
        end = chapters[position + 1].start() if position + 1 < len(chapters) else len(report)
        body = report[match.end():end]
        ids = set(re.findall(r'\bE-[A-Z0-9-]{6,}\b', body, flags=re.I))
        chapter_map = diagnostic.get('chapter_evidence_ids', {})
        allowed = set(chapter_map.get(chapter, chapter_map.get(str(chapter), [])) or [])
        if chapter in {1, 14}:
            allowed = valid
        missing = ids - allowed
        if missing:
            errors.append(f'第{chapter}章引用了不属于本章的证据编号：' + '、'.join(sorted(missing)))
        if ids & allowed:
            cited_chapters += 1
        if chapter not in disabled and len(re.sub(r'\s+', '', body)) >= 120 and not ids & allowed:
            errors.append(f'第{chapter}章存在分析正文但缺少有效证据编号。')
        if chapter in {3, 4, 6, 7} and not ids & allowed:
            errors.append(f'核心第{chapter}章缺少有效政策、规模、竞争或技术证据。')
        if re.search(r'(?:不存在|没有|无)(?:任何)?(?:行业风险|监管风险|技术风险)', body):
            errors.append(f'第{chapter}章存在确定无风险的越界结论。')
        for line in body.splitlines():
            numbers = re.findall(NUMBER_PATTERN, line)
            if not numbers:
                continue
            line_ids = set(re.findall(r'\bE-[A-Z0-9-]{6,}\b', line, flags=re.I)) & allowed
            numeric = diagnostic.get('numeric_evidence', {})
            for number in numbers:
                supported = any(numeric_supported(number, eid, numeric) for eid in line_ids)
                if not supported and '待核验' not in line:
                    errors.append(f'第{chapter}章数值 {number} 缺少同一行的有效口径证据或待核验标注。')
    if not valid or cited_chapters < 4:
        errors.append('至少四个研究章节需要引用有效事实，当前证据覆盖不足。')
    if '研究边界与口径' not in report:
        errors.append('缺少研究边界与口径。')
    return list(dict.fromkeys(errors))


def trace_snapshot(events: list[dict], limit: int = 2000) -> tuple[list[dict], dict]:
    """Keep individual industry events plus full-run counts when history is bounded."""
    rows = [dict(event) for event in events if isinstance(event, dict)]
    counts = {}
    for event in rows:
        key = str(event.get('status') or 'unknown')
        counts[key] = counts.get(key, 0) + 1
    actual = [row for row in rows if not row.get('heartbeat')]
    return rows[-limit:], {'total_event_count': len(rows), 'event_status_counts': counts,
                          'last_backend_event_timestamp': max((str(row.get('timestamp') or '') for row in actual), default=''),
                          'history_truncated': len(rows) > limit}


def balanced_risk_facts(facts: list[dict], limit: int = 60) -> list[dict]:
    groups = {}
    for fact in facts:
        if not isinstance(fact, dict) or fact.get('eligible_for_risk_scoring') is False or fact.get('scope_match') != 'in_scope':
            continue
        if fact.get('evidence_scope') not in {'industry_level', 'segment_level', 'capital_market'}:
            continue
        groups.setdefault(fact.get('module') or '其他', []).append(fact)
    result = []
    offset = 0
    while len(result) < limit:
        items = [rows[offset] for rows in groups.values() if offset < len(rows)]
        if not items:
            break
        result.extend(items[:limit - len(result)])
        offset += 1
    return result
