"""Industry-only scope, evidence and scoring contracts shared by its pipeline."""

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from datetime import date
from typing import Any
from urllib.parse import urlsplit, parse_qsl, urlencode

INDUSTRY_POLICY_VERSION = 'industry-scope-v3'
INDUSTRY_RISK_VERSION = 'industry-risk-v13-subject-boundaries'
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
    from industry_risk import attach_risk_support
    return attach_risk_support({'overall_score': None, 'risk_level': 'unknown',
            'dimensions': [{'name': name, 'score': None, 'level': 'unknown', 'reason': reason,
                            'evidence_ids': [], 'evidence_sources': []} for name in active_risk_dimensions(scope)],
            'key_risks': [], 'unknowns': [reason], 'recommended_followups': ['补充行业统计、监管文件和可比企业披露。']}, [], scope)


def normalize_risk(parsed: Any, facts: list[dict], scope: dict | None = None) -> dict:
    result = dict(parsed) if isinstance(parsed, dict) else unknown_risk()
    evidence = {str(f.get('evidence_id')): f for f in facts if f.get('evidence_id')
                and f.get('eligible_for_risk_scoring') is not False and f.get('eligible_for_report') is not False
                and f.get('scope_match') == 'in_scope'}
    supplied_rows = result.get('dimensions')
    supplied = {d.get('name'): d for d in supplied_rows if isinstance(d, dict)} if isinstance(supplied_rows, list) else {}
    dimensions = []
    unknowns = list(result.get('unknowns') or [])
    if (scope or {}).get('capital_market') == 'none':
        capital_words = ('资本热度', '估值', '投融资', '二级市场', '融资数据库')
        unknowns = [note for note in unknowns if not any(word in str(note) for word in capital_words)]
        result['recommended_followups'] = [note for note in result.get('recommended_followups', [])
                                           if not any(word in str(note) for word in capital_words)]
    for name in active_risk_dimensions(scope):
        row = dict(supplied.get(name) or {})
        supplied_ids = row.get('evidence_ids') if isinstance(row.get('evidence_ids'), list) else []
        ids = list(dict.fromkeys(eid for eid in supplied_ids if isinstance(eid, str) and eid in evidence))
        # One company's condition is a sample, never proof of an industry-wide score.
        ids = [eid for eid in ids if evidence[eid].get('evidence_scope') in {'industry_level', 'segment_level', 'capital_market'}]
        score = row.get('score')
        ids = [eid for eid in ids if risk_fact_applicable(evidence[eid], name)]
        reason_ids = set(re.findall(EVIDENCE_ID_PATTERN, str(row.get('reason') or ''), re.I))
        invalid_reason_ids = reason_ids - set(ids)
        numeric_cards = {eid: {'validation': evidence[eid].get('numeric_validation') or {},
                               'context': evidence[eid].get('numeric_context') or {}} for eid in ids}
        unverified_numbers = [n for n in numeric_mentions(str(row.get('reason') or ''))
                              if not any(numeric_supported(n, eid, numeric_cards) for eid in ids)]
        semantic_issues = claim_semantic_issues(str(row.get('reason') or ''), [evidence[eid] for eid in ids])
        if not ids or invalid_reason_ids or unverified_numbers or semantic_issues or isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 100:
            candidates = [eid for eid, fact in evidence.items() if risk_fact_applicable(fact, name)]
            prior_diagnostic = row.get('validation_diagnostic') if score is None and row.get('unknown_cause') else None
            prior_diagnostic = dict(prior_diagnostic) if isinstance(prior_diagnostic, dict) else None
            cause = ('no_applicable_evidence' if not candidates else 'model_abstained' if score is None and row.get('level') == 'unknown'
                     else 'missing_model_citations' if not supplied_ids
                     else 'invalid_citations' if not ids else 'invalid_reason_citations' if invalid_reason_ids
                     else 'unverified_reason_numbers' if unverified_numbers
                     else semantic_issues[0]['code'] if semantic_issues else 'invalid_score')
            if candidates and prior_diagnostic:
                # An already rejected score is not a new model abstention.
                # Keep the original attempt for audit, without restoring its
                # score or passing the rejected reason to report writers.
                cause = ('reassessment_required' if row['unknown_cause'] == 'no_applicable_evidence'
                         else row['unknown_cause'])
            audit = prior_diagnostic or {'original_reason': str(supplied.get(name, {}).get('reason') or '')[:3000],
                       'original_score': score, 'rejection_cause': cause, 'supplied_evidence_ids': list(supplied_ids)[:30],
                       'admissible_evidence_ids': ids, 'invalid_reason_evidence_ids': sorted(invalid_reason_ids),
                       'unverified_numbers': list(dict.fromkeys(unverified_numbers)), 'semantic_issues': semantic_issues}
            if prior_diagnostic:
                audit.setdefault('rejection_cause', row['unknown_cause'])
                audit['admissible_evidence_ids'] = [eid for eid in audit.get('supplied_evidence_ids', [])
                    if isinstance(eid, str) and eid in evidence and risk_fact_applicable(evidence[eid], name)]
            explanations = {'no_applicable_evidence':'本次评分证据包没有适用的行业事实',
                'evidence_budget_excluded':'全库有适用候选，但评分预算未保留，需先复核选材',
                'missing_model_citations':'模型未提供评分证据编号', 'invalid_citations':'评分引用没有适用的行业事实',
                'invalid_reason_citations':'评分理由引用了未授权或不适用的编号',
                'unverified_reason_numbers':'评分理由含未通过对应指标校验的数值', 'invalid_score':'模型评分值不符合0至100的风险分格式',
                'model_abstained':'模型认为现有证据不足，保留unknown',
                'reassessment_required':'适用资料发生变化，需重新评估，不能自动恢复原分值',
                'forecast_presented_as_actual':'评分理由未保留对应数值的预测属性',
                'source_corroboration_overstated':'评分理由声称多源印证，但引用来源不足或来自同一发布方'}
            explanation = explanations.get(cause, next((i['message'] for i in semantic_issues if i['code'] == cause), '评分证据不符合适用边界'))
            row = {'name': name, 'score': None, 'level': 'unknown', 'reason': explanation + '，暂不评分。',
                   'evidence_ids': [], 'evidence_sources': [], 'unknown_cause': cause,
                   'candidate_evidence_count': len(candidates),
                   'validation_diagnostic': audit}
            unknowns.append(name + '：' + row['reason'])
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
    from industry_risk import attach_risk_support
    return attach_risk_support(result, facts, scope)


RISK_MODULES = {
    '政策与监管风险': {'政策与监管'}, '市场增长与需求风险': {'市场规模与增长'},
    '竞争格局与集中度风险': {'竞争格局与代表企业'}, '商业化与盈利模式风险': {'商业模式与盈利逻辑'},
    '技术迭代与替代风险': {'技术路线对比', '技术演进与平台生态'},
    '资本热度与估值风险': {'投融资与资本市场'},
}


def risk_fact_applicable(fact: dict, name: str) -> bool:
    from industry_grounding import sample_boundary
    from industry_fact_contracts import risk_admitted
    if not risk_admitted(fact, name):
        return False
    if sample_boundary(fact):
        return False
    if (fact.get('eligible_for_risk_scoring') is False or fact.get('eligible_for_report') is False
            or fact.get('scope_match') != 'in_scope'
            or fact.get('evidence_scope') not in {'industry_level', 'segment_level', 'capital_market'}):
        return False
    if name in RISK_MODULES and fact.get('module') not in RISK_MODULES[name]:
        return False
    if name == '竞争格局与集中度风险':
        return bool(re.search(r'竞争|市场份额|市占率|集中度|CR\d|HHI|垄断|进入壁垒|头部|寡头',
                              str(fact.get('fact') or ''), re.I))
    return True


def risk_fact_text(fact: dict) -> str:
    """A single verified numeric context cannot authorize other numbers in its quote."""
    if fact.get('fact_contract'):
        return fact['fact_contract'].get('statement') or '该信息点未通过陈述准入，保留审计，不用于结论。'
    context = fact.get('numeric_context') or {}
    if (fact.get('numeric_validation') or {}).get('passed') is True:
        return (f'{"预测/目标值：" if context.get("is_forecast") else "来源报告值："}{context.get("period", "")} {context.get("geography", "")} '
                f'{context.get("metric", "")}：{context.get("value", "")}{context.get("unit", "")}；'
                f'口径：{context.get("definition", "")}。')
    from industry_grounding import complete_excerpt
    if fact.get('claim_type') == 'source_excerpt':
        # Only the located quote authorizes writing; the rest is audit material.
        return complete_excerpt(fact.get('evidence_quote') or fact.get('fact')) or '来源摘录未形成完整句子，需核对原文。'
    return str(fact.get('fact') or '')


def risk_repair_package(payload: dict, normalized: dict, limit: int = 18000) -> dict:
    """Repair only rejected scores with retained candidates, using complete JSON."""
    eligible = {'missing_model_citations', 'invalid_citations', 'invalid_reason_citations',
                'unverified_reason_numbers', 'invalid_score', 'forecast_presented_as_actual', 'source_corroboration_overstated',
                'growth_rate_kind_conflict', 'growth_benchmark_missing', 'business_screening_rule_unsupported',
                'allocation_inference_unsupported', 'integration_inference_unsupported', 'commercial_certainty_unsupported',
                'statistic_asof_rebased', 'rate_unit_conflict', 'publisher_attribution_unsupported', 'roadmap_as_current_state'}
    requests = []
    mapping = payload.get('dimension_evidence_ids') or {}
    for row in normalized.get('dimensions', []):
        diagnostic = row.get('validation_diagnostic') or {}
        # A deliberate model abstention is not an invitation to manufacture a score.
        if (row.get('unknown_cause') not in eligible or diagnostic.get('original_score') is None
                or not mapping.get(row.get('name'))):
            continue
        requests.append({'name': row['name'], 'previous_score': diagnostic['original_score'],
            'previous_reason': str(diagnostic.get('original_reason') or '')[:500],
            'failure': row['unknown_cause'],
            'semantic_issues': diagnostic.get('semantic_issues', [])[:5],
            'unverified_numbers': [str(n)[:80] for n in diagnostic.get('unverified_numbers', [])[:10]],
            'invalid_reason_evidence_ids': [str(e)[:64] for e in diagnostic.get('invalid_reason_evidence_ids', [])[:12]]})
    result = {'dimensions_to_repair': requests, 'facts': [], 'dimension_evidence_ids': {}}
    while len(json.dumps(result, ensure_ascii=False)) > limit and requests:
        requests.pop()
    groups = [[f for f in payload.get('facts', []) if f.get('evidence_id') in mapping.get(r['name'], [])] for r in requests]
    ordered, seen = [], set()
    for index in range(max((len(g) for g in groups), default=0)):
        for group in groups:
            if index < len(group) and group[index]['evidence_id'] not in seen:
                original = group[index]
                seen.add(original['evidence_id'])
                ordered.append({key: original.get(key) for key in ('evidence_id', 'fact', 'module', 'source_url',
                    'numeric_context', 'numeric_validation', 'allowed_numbers', 'source_document_key')})
    for fact in ordered:
        result['facts'].append(fact)
        retained = {f['evidence_id'] for f in result['facts']}
        result['dimension_evidence_ids'] = {r['name']: [eid for eid in mapping[r['name']] if eid in retained] for r in requests}
        if len(json.dumps(result, ensure_ascii=False)) > limit:
            result['facts'].pop()
            break
    retained = {f['evidence_id'] for f in result['facts']}
    result['dimension_evidence_ids'] = {r['name']: [eid for eid in mapping[r['name']] if eid in retained] for r in requests}
    result['dimensions_to_repair'] = [r for r in requests if result['dimension_evidence_ids'].get(r['name'])]
    return result


def risk_level(score: float) -> str:
    return 'low' if score < 40 else 'medium' if score < 70 else 'high' if score < 85 else 'critical'


def delivery_review_reasons(scope: dict, risk: dict, degradations: list) -> list[dict]:
    """Writing and assessment completion are separate from citation integrity."""
    disabled = ({8, 9} if scope.get('capital_market') == 'none' else set()) | ({12} if not scope.get('named_companies') else set())
    reasons = []
    for note in degradations:
        if not isinstance(note, dict):
            continue
        chapter = note.get('chapter')
        if isinstance(chapter, str) and chapter.isdigit():
            chapter = int(chapter)
        if chapter in disabled or (chapter is not None and chapter not in range(1, 15)):
            continue
        message = str(note.get('message') or '').strip()
        if message:
            code=('chapter_analysis_pending_review' if note.get('review_type')=='statement_synthesis_review' else
                  'chapter_generation_degraded' if chapter is not None else 'report_generation_degraded')
            reasons.append({'code': code,
                            'chapter': chapter, 'message': message})
    dimensions = {d.get('name'): d for d in (risk.get('dimensions') or []) if isinstance(d, dict)}
    for name in active_risk_dimensions(scope):
        row = dimensions.get(name) or {}
        score = row.get('score')
        assessed = (isinstance(score, (float, int)) and not isinstance(score, bool) and 0 <= score <= 100
                    and row.get('level') in {'low', 'medium', 'high', 'critical'} and bool(row.get('evidence_ids')))
        if not assessed:
            reason = str(row.get('reason') or '未取得有效的评分结果。').strip()
            reasons.append({'code': 'risk_assessment_incomplete', 'chapter': 14, 'dimension': name,
                            'unknown_cause': row.get('unknown_cause') or 'assessment_unavailable',
                            'message': f'{name}尚未完成有效评估：{reason}'})
    distinct = {}
    for reason in reasons:
        key = (reason['code'], reason.get('chapter'), reason.get('dimension'), reason['message'])
        distinct.setdefault(key, reason)
    return list(distinct.values())


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
    from industry_fact_contracts import chapter_admitted
    from report_agents.industry_template import INDUSTRY_REPORT_OUTLINE
    chapter_index = next((i for i, (t, _) in enumerate(INDUSTRY_REPORT_OUTLINE, 1) if t == title), 0)
    scopes = chapter_scopes(title)
    expected = CHAPTER_MODULES.get(title, ())
    candidates = []
    excluded = {str(url).rstrip('/') for url in excluded_urls or []}
    for original in payload.get('facts') or []:
        if not isinstance(original, dict):
            continue
        fact = dict(original)
        if not chapter_admitted(fact, chapter_index):
            continue
        if fact.get('eligible_for_report') is False or fact.get('scope_match') != 'in_scope':
            continue
        if fact.get('evidence_scope') not in scopes or str(fact.get('source_url') or '').rstrip('/') in excluded:
            continue
        if title == '行业核心公司主体全面尽调' and fact.get('company_role') != 'requested_due_diligence':
            continue
        from industry_grounding import passage_tasks
        tasks = passage_tasks(fact)
        blob = ' '.join(str(fact.get(k) or '') for k in ('fact', 'source_title', 'module'))
        module_match = fact.get('module') in expected
        keywords = [word for item in requirements for word in re.split(r'[/｜、，\s]+', item) if len(word) >= 2]
        hits = sum(word in blob for word in keywords)
        derived = title in {'摘要', '行业判断与综合评估', '综合评估', '信息来源', '后续研究点'}
        task_match = bool(tasks & ({'产业链分层'} if '产业链' in title else
                                  {'技术测试条件', '技术性能', '技术成本'} if title == '技术路线对比' else set()))
        if not module_match and not hits and not derived and not task_match:
            continue
        # Structured facts must not lose to source excerpts merely because the
        # excerpt inherits a publisher score while the cleaner omits it.
        structured = fact.get('claim_type') != 'source_excerpt'
        verified_numeric = fact.get('numeric_validation', {}).get('passed') is True
        candidates.append((int(task_match), int(module_match), int(structured), int(verified_numeric), hits,
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
    try:
        from .industry_evidence import diverse_evidence
    except ImportError:
        from industry_evidence import diverse_evidence
    # Reserve a card per chapter task before general diversity; otherwise twelve
    # macro statistics can crowd every test condition or chain definition out.
    task_names = ({'产业链分层'} if '产业链' in title else
                  {'技术测试条件', '技术性能', '技术成本'} if title == '技术路线对比' else set())
    reserved, covered = [], set()
    for fact in focused:
        present = passage_tasks(fact) & task_names
        if present - covered:
            reserved.append(fact); covered |= present
    # Reserve the chapter's actual questions before the generic twelve-card cap.
    # Policy purpose clauses must not displace duties, nor amounts their rates.
    from industry_analysis import complete_plan
    contracted = [f for f in focused if f.get('fact_contract')]
    if contracted:
        question_ids = complete_plan({'facts':contracted}, chapter_index, [])
        question_cards = [next(f for f in contracted if f['evidence_id']==eid) for eid in question_ids]
        reserved = question_cards + [f for f in reserved if f not in question_cards]
    remaining = [f for f in focused if f not in reserved]
    focused = reserved + diverse_evidence(remaining,payload.get('evidence_requirements') or [],max(0,12-len(reserved)))
    # Put evidence first and omit the full ledger; bounded model prompts must not
    # be consumed by metadata before the actual fact cards are reached.
    coverage=(payload.get('evidence_coverage') or {}).get('requirements',[])
    questions=[{'question':r['question'],'status':r['status'],'verified_fact_count':len(r.get('verified_evidence_ids',[]))}
               for r in coverage if r['module'] in expected or title in {'摘要','综合评估','后续研究点'}]
    return {'facts': focused, 'industry_scope': payload.get('industry_scope') or {},
            'selection_coverage': {'candidate_count':len(candidates), 'selected_count':len(focused),
                'task_candidates': {name:sum(name in passage_tasks(row[-1]) for row in candidates) for name in sorted(task_names)},
                'task_selected': {name:sum(name in passage_tasks(f) for f in focused) for name in sorted(task_names)},
                'absence_scope':'仅反映本章保留的证据，不代表全部来源或公开资料不存在该信息'},
            'research_questions_status':questions,
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
    dimensions = [{k:v for k,v in d.items() if k not in {'validation_diagnostic', 'evidence_support', 'assessment_confidence'}} for d in risk.get('dimensions', [])
                  if d.get('evidence_ids') and set(d['evidence_ids']) <= allowed]
    scoped_risk = {'dimensions': dimensions, 'overall_score': risk.get('overall_score') if include_all else None,
                  'risk_level': risk.get('risk_level') if include_all else 'unknown',
                  'unknowns': risk.get('unknowns', []) if include_all else [],
                  'scoring_caveat': (risk.get('risk_transparency') or {}).get('notice', ''),
                  'aggregation_caveat': (risk.get('risk_transparency') or {}).get('aggregation_notice', '') if include_all else ''}
    return {**package, 'facts': facts}, scoped_risk


def bounded_package(package: dict, limit: int = 20000) -> str:
    """Keep JSON intact under a prompt budget, prioritizing concise fact cards."""
    result = {**package, 'facts': []}
    for original in package.get('facts', []):
        fields = {'evidence_id','fact','source_url','source_title','source_type','source_grade','provider','publisher',
            'date','published_date','original_source_url','original_publisher','module','category','claim_type','evidence_scope','scope_match','company_role',
            'industry_name','segment_name','attribution_boundary','sample_boundary_reason','cleaning_method',
            'is_structured_evidence','evidence_quote','evidence_quote_verified','numeric_context','numeric_validation',
            'eligible_for_report','eligible_for_risk_scoring','requires_human_review','allowed_numbers','source_document_key','provenance',
            'fact_contract', 'summary_lineage'}
        fact = {k:v for k,v in original.items() if k in fields}
        # Diagnostic model prose must never re-enter a writer's evidence input.
        fact.pop('original_model_fact', None)
        if isinstance(fact.get('provenance'),dict):
            fact['provenance']={**fact['provenance'], 'locator':{k:v for k,v in (fact['provenance'].get('locator') or {}).items() if k!='quote'}}
        # Keep the original card in the audit library; writers receive the
        # authorized metric or complete located passage, never a raw page tail.
        fact['fact'] = risk_fact_text(fact)
        if len(fact['fact']) > 900:
            from industry_grounding import complete_excerpt
            fact['fact'] = complete_excerpt(fact['fact'],900) or '较长原文待核对，暂不转述。'
        fact['evidence_quote'] = (fact['fact'] if fact.get('fact_contract') else str(fact.get('evidence_quote') or '')[:650])
        result['facts'].append(fact)
        if len(json.dumps(result, ensure_ascii=False)) > limit:
            result['facts'].pop(); break
    return json.dumps(result, ensure_ascii=False)


def summary_package(packages: dict, sections: dict, scope: dict, limit: int = 14000) -> dict:
    """Reuse accepted chapter statements, not merely a raw card's citation."""
    from industry_fact_contracts import chapter_admitted
    from industry_analysis import statement_lineage_present
    groups = []
    for index in (4, 6, 7, 3, 10, 11, 13, 14, 2, 5, 12):
        raw = packages.get(index, {})
        package = json.loads(raw) if isinstance(raw, str) else raw
        cited = set(re.findall(r'\bE-[A-Z0-9-]{6,}\b', sections.get(index, ''), re.I))
        rows = []
        for fact in package.get('facts', []):
            if fact.get('evidence_id') not in cited:
                continue
            contract = fact.get('fact_contract')
            if contract:
                statement = contract.get('statement') or ''
                if (not chapter_admitted(fact, 1) or not statement
                        or not statement_lineage_present(fact, sections.get(index, ''), package, index)):
                    continue
                fact = {**fact, 'summary_lineage': {'chapter': index, 'statement_sha256': contract['statement_sha256']}}
            rows.append(fact)
        rows.sort(key=lambda f: (f.get('claim_type') != 'source_excerpt',
                                  f.get('numeric_validation', {}).get('passed') is True), reverse=True)
        groups.append(rows)
    facts, seen = [], set()
    for offset in range(max((len(g) for g in groups), default=0)):
        for group in groups:
            if offset >= len(group):
                continue
            original = group[offset]
            key = re.sub(r'\s+', '', str(original.get('fact') or ''))
            if not key or key in seen:
                continue
            seen.add(key)
            # Remove raw page metadata and long image lists from synthesis prompts.
            fields = ('evidence_id', 'fact', 'source_url', 'source_title', 'module', 'claim_type',
                      'evidence_scope', 'scope_match', 'numeric_context', 'numeric_validation',
                      'attribution_boundary', 'eligible_for_risk_scoring', 'fact_contract', 'summary_lineage')
            facts.append({k: original[k] for k in fields if k in original})
    return json.loads(bounded_package({'facts': facts, 'industry_scope': scope}, limit))


def industry_excerpt(text: str, module: str, limit: int) -> str:
    """Preserve original context near data/business passages instead of only page headers."""
    text = str(text or '')
    if len(text) <= limit:
        return text
    patterns = [r'\d[\d,.]*\s*(?:%|％|亿元|万元|亿美元|万美元|万亿元)',
                r'商业模式|盈利模式|收入结构|订阅|按量计费|毛利率|净利率']
    if module != '商业模式与盈利逻辑':
        patterns = patterns[:1]
    if module in {'技术路线对比','技术演进与平台生态'}:
        patterns.append(r'统一硬件|统一软件|测试环境|测试条件|测试模型|吞吐量|首\s*token|token/s|单位.{0,12}成本')
    if module in {'细分赛道与产业链','行业定义与边界'}:
        patterns.append(r'上游.{0,180}中游.{0,180}下游')
    matches = []
    for priority, pattern in enumerate(reversed(patterns)):
        for match in re.finditer(pattern, text):
            start, end = max(0, match.start()-180), min(len(text), match.end()+230)
            matches.append((priority, start, end))
    # Include the introduction for subject/date anchors; gaps remain explicit.
    ranges = [(0, min(200, limit))]
    marker = '\n[不连续原文片段]\n'
    used = ranges[0][1]
    for _, start, end in sorted(matches):
        if any(start < b and end > a for a, b in ranges):
            continue
        if used + end-start + len(marker) > limit:
            continue
        ranges.append((start, end)); used += end-start + len(marker)
        if len(ranges) >= 4:
            break
    return marker.join(text[a:b] for a, b in sorted(ranges)) if len(ranges) > 1 else text[:limit]


def industry_cleaning_sources(sources: list, per_module: int = 6) -> list:
    """Select extraction candidates by module relevance and usable data, not authority alone."""
    groups = {}
    for source in sources:
        module = (source.source_metadata or {}).get('module', '其他')
        groups.setdefault(module, []).append(source)
    selected = []
    for module, rows in groups.items():
        def score(source):
            content = str(source.content or source.summary or '')
            title = str(source.title or '')
            business = bool(re.search(r'商业模式|盈利模式|收入结构|订阅|按量计费', title + content)) if module == '商业模式与盈利逻辑' else False
            data = bool(re.search(r'\d[\d,.]*\s*(?:%|％|亿元|万元|亿美元|万美元|万亿元)', content))
            return (business, data, float(source.credibility_score or 0))
        rows.sort(key=score, reverse=True)
        selected.extend(rows[:per_module])
    return selected


def company_filing_source(source: Any) -> bool:
    title = str(source.title or '')
    if source.source_type == 'filing' or re.search(r'招股书|招股说明书', title):
        return True
    if not re.search(r'年报|年度报告', title):
        return False
    return bool(re.search(r'公司|股份|集团|有限公司', title) or not re.search(r'行业|产业|市场|技术|监管', title))


FORECAST_MARKERS = r'预测|预计|预估|估计|有望|或将|情景|假设|目标|锚定|力争|争取|第[一二三]步到20\d{2}年|forecast|projected|estimated'


def local_forecast_attribute(quote: str, metric: str, value, unit: str):
    """Bind nature to the metric/value clause, not a later forecast in its quote.

    Returns None for no pairing or contradictory repeated pairs. This is a
    conservative text rule, not a verification of the source's methodology.
    """
    from industry_passages import numeric_temporal_attribute
    nature = numeric_temporal_attribute(quote, metric, value, unit)
    return nature == 'forecast' if nature else None


def extract_industry_source_facts(sources: list, scope: dict) -> list[dict]:
    """Extract small, verbatim cards from stored body text, never search summaries.

    A numeric context is complete only when the same sentence names its subject,
    metric, region, period and value. Missing context remains pending verification.
    This validates attribution/units, not the publisher's underlying methodology.
    """
    facts = []
    subjects = [scope.get('industry_name'), *scope.get('segments', [])]
    metric_pattern = r'市场规模|核心产业规模|产业规模|营业收入|营收|收入|毛利率|净利率|渗透率|市场份额|占比|复合增长率|CAGR|同比增长率|同比增长|同比增幅|增长速度|增长率|增速|吞吐量|首\s*token\s*(?:响应)?延迟|推理成功率'
    business_pattern = r'订阅|按量计费|按调用量|商业模式|盈利模式|收入结构|收费模式|服务收费'
    from industry_grounding import source_metadata, metric_period_region, sample_boundary, TASK_PATTERNS
    for source in sources:
        from industry_evidence import stored_body
        body = stored_body(source).replace('\x00', '')
        if not body.strip() or not str(source.url or '').startswith(('https://', 'http://')):
            continue
        meta = source.source_metadata or {}
        seen, selected = set(), []
        # Keep original sentence boundaries; no concatenation across PDF pages or snippets.
        from industry_passages import atomic_passages
        sentences = list(atomic_passages(body))
        scope_anchor = next((s.strip() for s in sentences if 12<=len(s.strip())<=650 and
                             any(str(n).lower() in s.lower() for n in subjects if n)), '')
        for sentence in sentences:
            quote = re.sub(r'\s+', ' ', sentence).strip(' -*#\t')
            if not 12 <= len(quote) <= 650 or quote in seen:
                continue
            relevant_source = any(str(n).lower() in (str(source.title or '')+' '+body[:600]).lower() for n in subjects if n)
            from industry_fact_contracts import TASK_PATTERNS as STATEMENT_TASKS
            task_match = any(re.search(p,quote,re.I) for p in (*TASK_PATTERNS.values(), *STATEMENT_TASKS.values()))
            if not any(str(n).lower() in quote.lower() for n in subjects if n) and not (relevant_source and task_match):
                continue
            if any(word in quote for word in ('如果需要', '以下是基于', '摘要要点', '免责声明', '不连续原文片段')):
                continue
            seen.add(quote)
            base = {'fact': quote, 'evidence_quote': quote, 'source_title': source.title,
                    'source_url': source.url, 'module': meta.get('module') or '其他',
                    'evidence_scope': meta.get('evidence_scope') or 'industry_level',
                    'industry_name': scope.get('industry_name'), 'category': 'industry',
                    'scope_anchor_quote':scope_anchor,
                    'claim_type': 'fact', 'is_structured_evidence': True,
                    'cleaning_method': 'industry_rule', 'evidence_quote_verified': True,
                    'confidence': min(.9, float(source.credibility_score or 50) / 100), **source_metadata(source)}
            if any(re.search(p,quote,re.I) for p in TASK_PATTERNS.values()):
                base['module'] = '细分赛道与产业链' if re.search(TASK_PATTERNS['产业链分层'],quote) else '技术路线对比'
                if base['module'] == '技术路线对比' and re.search(r'实测|横评|测试', str(source.title or '')):
                    self_report = re.search(r'本公司|我司|本平台|自持|旗下|自研|为.{0,20}服务商代表',body[:3500])
                    base['claim_type'] = 'vendor_benchmark' if self_report and source.source_type not in {'government','regulatory'} else 'benchmark_sample'
                    base['requires_human_review'] = True
            if company_filing_source(source) or sample_boundary(base):
                base['evidence_scope'] = 'representative_company'
            numeric_cards = []
            for number in re.finditer(NUMBER_PATTERN, quote):
                prefix = quote[:number.start()]
                metrics = list(re.finditer(metric_pattern, prefix, re.I))
                if not metrics or number.start() - metrics[-1].end() > 45:
                    continue
                metric = metrics[-1]
                # Do not associate a second unrelated number with the preceding metric.
                earlier = list(re.finditer(NUMBER_PATTERN, prefix[metric.end():]))
                if earlier:
                    # A dated base-to-target construction authorizes two
                    # independent cards. Other neighbouring quantities do not.
                    bridge = prefix[metric.end()+earlier[-1].end():]
                    if not re.fullmatch(r'\s*(?:增长|增|升|提高|下降|减少)(?:至|到)\s*20\d{2}年(?:的)?\s*', bridge):
                        continue
                definition = re.split(r'[，,：:]', prefix[:metric.end()])[-1].strip()
                value_match = re.fullmatch(r'([+-]?[\d,.]+)\s*(.*)', number.group())
                period, region = metric_period_region(quote, metric.group(), value_match[1], value_match[2])
                context = {'metric': metric.group(), 'value': value_match[1], 'unit': value_match[2],
                           'definition': definition if any(str(n).lower() in definition.lower() for n in subjects if n) else '',
                           'geography': region, 'period': period,
                           'is_forecast': local_forecast_attribute(quote, metric.group(), value_match[1], value_match[2]) is True}
                if not context['definition']:
                    from industry_grounding import growth_definition
                    context['definition'] = growth_definition(quote, metric.group(), value_match[1], value_match[2])
                numeric_cards.append({**base, 'numeric_context': context})
            if numeric_cards:
                selected.extend(numeric_cards[:3])
            elif task_match or (meta.get('module') == '商业模式与盈利逻辑' and re.search(business_pattern, quote)):
                # Isolate qualitative business evidence from unrelated page-level numbers.
                selected.append(base)
        # Reserve qualitative conditions/chain passages as well as numeric
        # cards; early market statistics must not consume the entire source.
        from industry_grounding import passage_tasks
        reserved, covered = [], set()
        for card in selected:
            tasks = passage_tasks(card)
            if tasks - covered:
                reserved.append(card); covered |= tasks
        facts.extend((reserved + [c for c in selected if c not in reserved])[:10])
    return facts


def summary_length(section: str) -> int:
    """Count visible summary prose; source IDs and link destinations are not prose."""
    body = '\n'.join(section.splitlines()[1:])
    body = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', body)
    body = re.sub(r'\bE-[A-Z0-9-]{6,}\b', '', body, flags=re.I)
    return len(re.sub(r'[\s#*\[\]［］]', '', body))


def validate_docx_package(payload: bytes) -> dict:
    """Check exported document integrity independently of optional page rendering."""
    import io
    import zipfile
    from xml.etree import ElementTree
    with zipfile.ZipFile(io.BytesIO(payload)) as package:
        if package.testzip() is not None:
            raise ValueError('Word导出文件损坏，ZIP校验失败。')
        for name in ('[Content_Types].xml', '_rels/.rels', 'word/document.xml'):
            ElementTree.fromstring(package.read(name))
        body = ElementTree.fromstring(package.read('word/document.xml'))
        paragraphs = body.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p')
        if not paragraphs or not ''.join(body.itertext()).strip():
            raise ValueError('Word导出文件缺少正文。')
    return {'docx_integrity_status': 'passed', 'docx_paragraph_count': len(paragraphs)}


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


NUMBER_UNITS = r'%|％|万亿元|万亿美元|亿元|万元|亿美元|万美元|美元|人民币元|元|EB|PB|TB|GB|MB|EFLOPS|PFLOPS|TFLOPS|tokens?/s|ms|毫秒|项|家|台|篇|个'
NUMBER_PATTERN = rf'(?<![A-Za-z0-9_.+\-])[+-]?\d[\d,.]*\s*(?i:{NUMBER_UNITS})(?![A-Za-z0-9_])'
EVIDENCE_ID_PATTERN = r'(?<![A-Z0-9-])E-[A-Z0-9-]{6,}(?![A-Z0-9-])'


def numeric_scan_text(text: str) -> str:
    """Mask identifiers without joining adjacent words or moving claim positions."""
    mask = lambda m: ' ' * len(m[0])
    text = re.sub(EVIDENCE_ID_PATTERN, mask, text, flags=re.I)
    return re.sub(r'(?:https?|structured)://[^\s<>\[\]()，。；、！？]+', mask, text, flags=re.I)


def numeric_mentions(text: str) -> list[str]:
    """Find claim numbers, never hexadecimal IDs or URL/link destinations."""
    return re.findall(NUMBER_PATTERN, numeric_scan_text(text))


def number_key(value: str) -> tuple | None:
    match = re.fullmatch(rf'([+-]?[\d,.]+)\s*({NUMBER_UNITS})', value.strip(), re.I)
    if not match:
        return None
    try:
        amount = Decimal(match[1].replace(',', ''))
    except InvalidOperation:
        return None
    unit = match[2].replace('％', '%')
    if unit in ('万亿元', '亿元', '万元'):
        amount *= Decimal({'万亿元': '1000000000000', '亿元': '100000000', '万元': '10000'}[unit]); unit = '人民币元'
    elif unit in ('万亿美元', '亿美元', '万美元'):
        amount *= Decimal({'万亿美元': '1000000000000', '亿美元': '100000000', '万美元': '10000'}[unit]); unit = '美元'
    elif unit in ('元', '人民币元'):
        unit = '人民币元'
    elif unit.upper() in ('EB', 'PB', 'TB', 'GB', 'MB'):
        amount *= Decimal(1000) ** {'MB':2, 'GB':3, 'TB':4, 'PB':5, 'EB':6}[unit.upper()]; unit = 'bytes_decimal'
    elif unit.upper() in ('EFLOPS', 'PFLOPS', 'TFLOPS'):
        amount *= Decimal(1000) ** {'TFLOPS':4, 'PFLOPS':5, 'EFLOPS':6}[unit.upper()]; unit = 'FLOPS'
    return amount, unit


def numeric_supported(number: str, eid: str, numeric: dict) -> bool:
    card = numeric.get(eid, {})
    if card.get('validation', {}).get('passed') is not True:
        return False
    context = card.get('context') or {}
    # A verified metric validates that metric only, never all numbers on a page.
    value = str(context.get('value', '')) + str(context.get('unit', ''))
    return number_key(number) is not None and number_key(number) == number_key(value)


def source_document_key(url: str) -> str:
    """Collapse transport, fragment and tracking variants, preserving document query IDs."""
    try:
        parts = urlsplit(str(url or '').strip())
        if parts.scheme.lower() not in {'http', 'https'} or not parts.hostname:
            return ''
        host = parts.hostname.lower().removeprefix('www.')
        if parts.port and parts.port not in {80, 443}:
            host += ':' + str(parts.port)
        query = sorted((key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                       if not key.lower().startswith('utm_') and key.lower() not in {'spm', 'from', 'fbclid', 'gclid'})
        return host + (parts.path.rstrip('/') or '/') + ('?' + urlencode(query) if query else '')
    except ValueError:
        return ''


def claim_semantic_issues(text: str, facts: list[dict]) -> list[dict]:
    """Conservative claim checks; passing is not proof of all prose semantics."""
    by_id = {f['evidence_id']: f for f in facts if f.get('evidence_id')}
    issues = []
    for line in text.splitlines():
        cited = set(re.findall(EVIDENCE_ID_PATTERN, line, re.I))
        rows = [f for eid, f in by_id.items() if not cited or eid in cited]
        numeric = {f['evidence_id']: {'context': f.get('numeric_context') or {},
                                    'validation': f.get('numeric_validation') or {}} for f in rows}
        # Labels must travel with the number, not an unrelated prediction later in the line.
        for clause in re.split(r'[，；;。！？\n]|(?<!\d),|,(?!\d)', numeric_scan_text(line)):
            for number in numeric_mentions(clause):
                supporting = [f for f in rows if numeric_supported(number, f['evidence_id'], numeric)]
                if (supporting and all((f.get('numeric_context') or {}).get('is_forecast') is True for f in supporting)
                        and not re.search(r'预测|预计|预估|估计|有望|或将|情景|假设|目标|锚定|力争|争取|forecast|projected|estimated', clause, re.I)):
                    issues.append({'code':'forecast_presented_as_actual', 'number':number,
                        'evidence_ids':[f['evidence_id'] for f in supporting],
                        'message':f'预测值{number}未在同一分句保留预测、预估或目标标记。'})
        claims = list(re.finditer(r'多源(?:预测|数据|信息|证据)?(?:一致|印证|验证)|多(?:家机构|个来源|个独立来源|方)(?:预测|数据|信息)?(?:一致|印证|验证)|\d+\s*(?:源|家机构|个独立来源)(?:数据|预测)?一致|交叉(?:验证|印证)|相互印证', line))
        claims = [m for m in claims if not re.search(r'未|无|不能|尚不|缺少|缺乏|不足|待|不构成|不代表|不等于|并非', line[max(0,m.start()-10):m.start()])]
        claims = [m for m in claims if not re.match(r'性?(?:尚待|待|需)(?:核验|验证|确认)', line[m.end():])]
        if claims:
            keys = {source_document_key(f.get('source_url', '')) for f in rows} - {''}
            # Conservative publisher grouping, including portal/mobile subdomains.
            # This is not a full public-suffix or original-research identity resolver.
            publishers = set()
            for key in keys:
                host = key.split('/')[0].split(':')[0]
                labels = host.split('.')
                suffix = '.'.join(labels[-2:])
                depth = 3 if suffix in {'com.cn','gov.cn','org.cn','net.cn','edu.cn','ac.cn','co.uk','org.uk','com.au','co.jp'} else 2
                publishers.add(host if all(x.isdecimal() for x in labels) else '.'.join(labels[-depth:]))
            from industry_assertions import independent_origin_keys
            origins = independent_origin_keys(rows)
            required = max([2] + [int(m[1]) for m in re.finditer(r'(\d+)\s*(?:源|家机构|个独立来源)(?:数据|预测)?一致', line)])
            if len(publishers) < required or len(origins) < required:
                issues.append({'code':'source_corroboration_overstated', 'document_count':len(keys),
                    'publisher_count':len(publishers), 'origin_count':len(origins), 'required_count':required,
                    'evidence_ids':[f['evidence_id'] for f in rows],
                    'message':'多源印证声明未满足所称数量的不同发布方及原始出处；同文转载、多卡片或同站不同网页不足以证明来源独立。'})
    from industry_claims import claim_contract_issues
    issues.extend(claim_contract_issues(text, facts))
    return list({json.dumps(issue, sort_keys=True, ensure_ascii=False): issue for issue in issues}.values())


def mark_unverified_numbers(section: str, facts: list[dict]) -> str:
    numeric = {f.get('evidence_id'): {'validation': f.get('numeric_validation') or {},
                                    'context': f.get('numeric_context') or {}} for f in facts}
    lines = []
    for line in section.splitlines():
        numbers = numeric_mentions(line)
        ids = re.findall(r'\bE-[A-Z0-9-]{6,}\b', line, flags=re.I)
        if numbers and '待核验' not in line and any(not any(numeric_supported(n, eid, numeric) for eid in ids) for n in numbers):
            line = re.sub(r'已验证|已核验', '待核验', line)
            note = '（数值口径待核验，不用于行业合计或评分）'
            if line.strip().startswith('|') and line.rstrip().endswith('|'):
                # Keep the annotation inside the last cell, never add a column.
                line = line.rstrip()[:-1].rstrip() + ' ' + note + ' |'
            else:
                line += ' ' + note
        lines.append(line)
    return '\n'.join(lines)


def annotate_fact(fact: dict, scope: dict) -> dict:
    item = dict(fact)
    from industry_grounding import sample_boundary, metric_period_region
    boundary = sample_boundary(item)
    if boundary:
        item.update(evidence_scope='representative_company', eligible_for_risk_scoring=False,
                    attribution_boundary=boundary, sample_boundary_reason=boundary)
    from industry_claims import public_source_type
    origin = public_source_type(item.get('source_url'))
    if origin == 'web_search' and str(item.get('source_url') or '').startswith(('http://', 'https://')) and (
            item.get('source_type') in {'government', 'regulatory', 'court', 'filing'} or item.get('source_grade') == 'A'):
        item['source_type'] = origin
        item['source_grade'] = 'C'
        item['source_classification_warning'] = '标题或正文不能证明官方来源，按实际域名降级。'
    if (item.get('cleaning_method') == 'llm' and item.get('evidence_quote_verified') is True
            and item.get('evidence_quote') and (item.get('numeric_context') or numeric_mentions(str(item.get('fact') or '')))):
        quote = str(item['evidence_quote']).strip()
        if quote != str(item.get('fact') or '').strip():
            item['original_model_fact'] = item.get('original_model_fact') or item.get('fact')
            item['fact'] = quote
            item['grounding_status'] = 'numeric_source_quote'
    blob = ' '.join(str(item.get(key) or '') for key in ('fact', 'evidence_quote', 'source_title'))
    if item.get('cleaning_method')=='industry_rule' and item.get('evidence_quote_verified') is True:
        blob += ' '+str(item.get('scope_anchor_quote') or '')
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
    if (item.get('cleaning_method') in {'industry_rule', 'llm'} and item.get('evidence_quote_verified') is True
            and isinstance(item.get('numeric_context'), dict)):
        context = dict(item['numeric_context'])
        if not context.get('definition'):
            from industry_grounding import growth_definition
            context['definition'] = growth_definition(item.get('evidence_quote'), context.get('metric'),
                                                       context.get('value'), str(context.get('unit') or ''))
        nature = local_forecast_attribute(str(item.get('evidence_quote') or ''), str(context.get('metric') or ''),
                                          context.get('value'), str(context.get('unit') or ''))
        if nature is not None:
            context['is_forecast'] = nature
        quote = str(item.get('evidence_quote') or '')
        # Chart footnotes can label a named year after several plotted values.
        # Preserve that warning without guessing which unlabeled value pairs.
        years = set(re.findall(r'20\d{2}', str(context.get('period') or '')))
        for note in re.finditer(r'(20\d{2})\s*年?(?:数据)?\s*(?:为|系|是)\s*(?:预估|预测|预计|估计|目标)值?', quote):
            if years == {note[1]}:
                context['is_forecast'] = True
        local_period, local_region = metric_period_region(str(item.get('evidence_quote') or ''), str(context.get('metric') or ''), context.get('value'), str(context.get('unit') or ''))
        if local_region:
            context['geography'] = local_region
        # A cutoff year or publication year is not the metric's statistical year.
        claimed_years = re.findall(r'20\d{2}',str(context.get('period') or ''))
        if claimed_years and any(y not in str(item.get('evidence_quote') or '') for y in claimed_years):
            context['period'] = ''
            item['period_validation_warning'] = '数值引文未给出所填统计期，不能以报告截止日期补齐。'
        elif local_period and (not context.get('period') or len(set(claimed_years))==1):
            context['period'] = local_period
        if (re.fullmatch(r'20\d{2}-\d{2}-\d{2}', str(context.get('period') or ''))
                and str(context['period']) not in quote):
            context['period'] = str(context['period'])[:4] if str(context['period'])[:4] in quote else ''
            item['period_validation_warning'] = '引文未提供具体月日，仅保留可定位的年度，不补成年末日期。'
        from industry_passages import numeric_temporal_attribute
        if (numeric_temporal_attribute(quote, str(context.get('metric') or ''), context.get('value'), str(context.get('unit') or '')) == 'estimate'
                and scope.get('as_of_date') and str(context.get('period') or '')[:4] > str(scope['as_of_date'])[:4]):
            context['is_forecast'] = True
        item['numeric_context'] = context
    identity = str(item.get('source_url') or '') + '\n' + str(item.get('fact') or '')
    if item.get('cleaning_method') == 'industry_rule':
        identity += '\nindustry_rule\n' + json.dumps(item.get('numeric_context') or {}, sort_keys=True, ensure_ascii=False)
    elif item.get('cleaning_method') == 'llm' and item.get('numeric_context') and item.get('evidence_quote_verified') is True:
        identity += '\nllm_numeric_quote\n' + json.dumps(item.get('numeric_context') or {}, sort_keys=True, ensure_ascii=False)
    item['evidence_id'] = 'E-' + hashlib.sha256(identity.encode()).hexdigest()[:12].upper()
    numeric = item.get('numeric_context') if isinstance(item.get('numeric_context'), dict) else {}
    numerical = bool(numeric or numeric_mentions(blob)
                     or re.search(r'\d[\d,.]*\s*(?:亿|万|CAGR|PE|PB|PS)', numeric_scan_text(blob), re.I))
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
        if expected_number is None and numeric.get('value') is not None:
            missing.append('unsupported_numeric_unit')
        grounded = item.get('cleaning_method') in {'industry_rule', 'llm'}
        if grounded and item.get('evidence_quote_verified') is not True:
            missing.append('unverified_evidence_quote')
        if expected_number is not None:
            grounded = item.get('cleaning_method') in {'industry_rule', 'llm'}
            evidence = str(item.get('evidence_quote') or '') if grounded else str(item.get('fact') or '') + ' ' + str(item.get('evidence_quote') or '')
            quote_numbers = numeric_mentions(evidence)
            if not any(number_key(n) == expected_number for n in quote_numbers):
                missing.append('value_not_in_evidence_quote')
            if grounded:
                anchor = re.sub(r'\s+', '', str(numeric.get('metric') or ''))
                for name in [*names, numeric.get('geography')]:
                    if name: anchor = anchor.replace(str(name), '')
                compact_quote = re.sub(r'\s+', '', evidence)
                if anchor and anchor not in compact_quote:
                    missing.append('metric_not_in_evidence_quote')
                elif anchor:
                    # The matching value must follow this metric, without a different
                    # number intervening. A shared sentence is not shared attribution.
                    paired = False
                    for metric_match in re.finditer(re.escape(anchor), compact_quote):
                        tail = compact_quote[metric_match.end():]
                        next_number = re.search(NUMBER_PATTERN, tail)
                        if (next_number and next_number.start() <= 60
                                and not re.search(r'[。；;]', tail[:next_number.start()])
                                and number_key(next_number.group()) == expected_number):
                            paired = True
                            break
                    if not paired:
                        missing.append('metric_value_not_paired')
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
    compact = bool(payload.get('fact_contract_version'))
    indexed = {}
    referenced = set()
    cited_ids = set()
    chapter_ids = {}
    facts = [f for f in payload.get('facts', []) if isinstance(f, dict)]
    originals = {f.get('evidence_id'): f for f in facts if f.get('evidence_id')}
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
        if index in {14, 16}:
            # This chapter is rendered from the validated risk artifact, not a
            # model prompt. Its exact referenced facts define its source set.
            selected = [f for f in facts if f.get('evidence_id') in mentioned and f.get('eligible_for_report') is not False
                        and (index != 16 or (f.get('scope_match') == 'in_scope'
                             and (f.get('provenance') or {}).get('locator', {}).get('status') == 'verified'))]
            chapter_ids[index] = [f['evidence_id'] for f in selected]
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
            record = indexed.setdefault(eid, {'fact': {**originals.get(eid, {}), **fact}, 'chapters': set(), 'url': url})
            record['chapters'].add(index)
            referenced.add(url)
    compact_groups = {}
    for eid, record in indexed.items():
        fact = record['fact']
        locator = ((fact.get('provenance') or {}).get('locator') or {})
        location = ('原文位置：' + str(locator.get('start')) + '–' + str(locator.get('end'))) if locator.get('status') == 'verified' else '原文定位待核验'
        version = str(locator.get('body_version_id') or ('sha256:'+locator['body_sha256'] if locator.get('body_sha256') else '正文版本待核验'))
        publication = cell(fact.get('published_date') or fact.get('date') or fact.get('fact_date') or '日期待核验')
        from industry_grounding import display_source_title, source_markdown_link
        source = cell(display_source_title(fact.get('source_title'))) + '<br>' + record['url'] + '<br>发布：' + publication + '<br>' + location + ' / ' + version
        chapters = '、'.join(str(n) for n in sorted(record['chapters']))
        from industry_assertions import reader_evidence_excerpt
        from urllib.parse import urlsplit
        excerpt = reader_evidence_excerpt(fact)
        if compact:
            support_chapters = record['chapters'] - {16}
            if not support_chapters:
                continue  # Candidate titles/links/locators already live in task references.
            source = source_markdown_link(fact.get('source_title'), record['url']) + '<br>发布：' + publication
            short_hash = str(locator.get('body_sha256') or '')[:12] or '待核验'
            chapters = '、'.join(map(str,sorted(support_chapters)))
            compact_groups.setdefault((record['url'],source),[]).append((f'{eid}（第{chapters}章）',f'{eid}：{location}；指纹前缀：{short_hash}'))
        else:
            rows.append(f'| {eid}（第{chapters}章） | {source} | {cell(excerpt or "完整原文见定位；本摘录不足以单独形成判断，待核验。")} | {cell(fact.get("publisher") or fact.get("provider") or urlsplit(record["url"]).hostname or fact.get("source_type") or "保存来源正文")} / {cell(fact.get("source_grade"))} |')
    for (_, source), entries in compact_groups.items():
        for start in range(0,len(entries),4):
            batch=entries[start:start+4]
            rows.append('| '+'<br>'.join(e[0] for e in batch)+' | '+source+' | '+'<br>'.join(e[1] for e in batch)+' |')
    lines = ['## 15. 信息来源（自动生成审计索引）', '',
             '本索引列出章节正文实际引用且属于对应证据包的事实编号；同一来源的不同事实可支持多个章节。', '',
             '第16章的候选原文链接用于安排核验，不表示其已支持风险评分或事实结论。', '',
             '| 证据编号及支持章节 | 原始来源与定位 | 信息点 | 获取方式与信源等级 |',
             '| --- | --- | --- | --- |', *rows, '',
             f'> 已纳入章节证据包的唯一来源：{len(referenced)} / 清洗事实库可追溯来源：{len(total_sources)}。', '']
    if compact:
        lines = ['## 15. 信息来源（自动生成审计索引）', '',
                 '陈述见对应章节，本节保留可点击原文及定位，不重复正文。完整正文快照、SHA256和定位记录保存在该报告关联的清洗事实库与结论证据台账。指纹前缀只用于识别，不能替代完整哈希核验。', '',
                 '本节仅列第1至14章实际引用；第16章候选的标题、链接和位置见任务材料索引，不能据候选作评分或事实结论。', '',
                 '| 证据编号及支持章节 | 原始来源与发布日期 | 定位识别 |', '| --- | --- | --- |', *rows, '',
                 f'> 正文及核验任务实际引用来源：{len(referenced)}；来源数量不等于研究独立性。', '']
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
                                         'fact': str(f.get('fact', ''))[:900], 'context': f.get('numeric_context') or {},
                                         'evidence_quote': f.get('evidence_quote',''), 'source_title':f.get('source_title',''),
                                         'claim_type':f.get('claim_type'), 'module':f.get('module'),
                                         'date':f.get('date'), 'published_date':f.get('published_date'),
                                         'original_source_url':f.get('original_source_url'), 'original_publisher':f.get('original_publisher'),
                                         'publisher':f.get('publisher'),
                                         'source_url': f.get('source_url', ''), 'evidence_scope': f.get('evidence_scope'),
                                         'eligible_for_risk_scoring': f.get('eligible_for_risk_scoring')}
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
        if chapter == 15:
            continue
        end = chapters[position + 1].start() if position + 1 < len(chapters) else len(report)
        body = report[match.end():end]
        body = re.split(r'(?m)^## (?:集中式待核验清单|报告编制说明)', body)[0]
        if chapter == 1 and summary_length(report[match.start():end]) > 600:
            errors.append('摘要正文超过600字，需要压缩并保留事实引用。')
        ids = set(re.findall(r'\bE-[A-Z0-9-]{6,}\b', body, flags=re.I))
        chapter_map = diagnostic.get('chapter_evidence_ids', {})
        allowed = set(chapter_map.get(chapter, chapter_map.get(str(chapter), [])) or [])
        if chapter in {1, 14}:
            allowed = valid
        missing = ids - allowed
        if missing:
            errors.append(f'第{chapter}章引用了不属于本章的证据编号：' + '、'.join(sorted(missing)))
        if ids & allowed and chapter < 15:
            cited_chapters += 1
        if chapter not in disabled and chapter != 16 and len(re.sub(r'\s+', '', body)) >= 120 and not ids & allowed:
            errors.append(f'第{chapter}章存在分析正文但缺少有效证据编号。')
        if chapter in {3, 4, 6, 7} and not ids & allowed:
            errors.append(f'核心第{chapter}章缺少有效政策、规模、竞争或技术证据。')
        if re.search(r'(?:不存在|没有|无)(?:任何)?(?:行业风险|监管风险|技术风险)', body):
            errors.append(f'第{chapter}章存在确定无风险的越界结论。')
        from text_integrity import text_issues
        if text_issues(body):
            errors.append(f'第{chapter}章存在乱码或缺字标记，需核对原文后重新编排。')
        # Candidate source titles are retrieval metadata, not report claims.
        # Their IDs remain subject to the chapter allow-list above.
        claim_body = re.split(r'(?m)^候选核验编号清单：',body,maxsplit=1)[0] if chapter == 16 else body
        for line in claim_body.splitlines():
            if chapter == 16:
                line=re.sub(r'精选\d+/\d+个核验入口', '精选核验入口',line)
            if chapter == 14 and re.match(r'^本轮\d+个启用风险维度中',line.strip()):
                continue  # Deterministic assessment counts are not source statistics.
            line_ids = set(re.findall(EVIDENCE_ID_PATTERN, line, re.I)) & allowed
            numeric = diagnostic.get('numeric_evidence', {})
            cards = [{'evidence_id':eid, 'source_url':numeric.get(eid, {}).get('source_url', ''),
                      'evidence_scope':numeric.get(eid, {}).get('evidence_scope'),
                      'eligible_for_risk_scoring':numeric.get(eid, {}).get('eligible_for_risk_scoring'),
                      'fact':numeric.get(eid,{}).get('fact',''), 'evidence_quote':numeric.get(eid,{}).get('evidence_quote',''),
                      'source_title':numeric.get(eid,{}).get('source_title',''), 'claim_type':numeric.get(eid,{}).get('claim_type'),
                      'date':numeric.get(eid,{}).get('date'), 'published_date':numeric.get(eid,{}).get('published_date'),
                      'original_source_url':numeric.get(eid,{}).get('original_source_url'), 'original_publisher':numeric.get(eid,{}).get('original_publisher'),
                      'publisher':numeric.get(eid,{}).get('publisher'),
                      'numeric_context':numeric.get(eid, {}).get('context') or {},
                      'numeric_validation':numeric.get(eid, {}).get('validation') or {}} for eid in line_ids]
            for issue in claim_semantic_issues(line, cards):
                errors.append(f'第{chapter}章语义核验：' + issue['message'])
            numbers = numeric_mentions(line)
            if not numbers:
                continue
            for number in numbers:
                supported = any(numeric_supported(number, eid, numeric) for eid in line_ids)
                if not supported and '待核验' not in line:
                    errors.append(f'第{chapter}章数值 {number} 缺少同一行的有效口径证据或待核验标注。')
        from industry_claims import table_completeness_issues
        for issue in table_completeness_issues(body):
            errors.append(f'第{chapter}章表格核验：'+issue['message'])
    if not valid or cited_chapters < 4:
        errors.append('至少四个研究章节需要引用有效事实，当前证据覆盖不足。')
    market_ids = set((diagnostic.get('chapter_evidence_ids') or {}).get(4,
                     (diagnostic.get('chapter_evidence_ids') or {}).get('4', [])))
    market_body = re.search(r'(?ms)^##\s*4[.、．][^\n]*\n(.*?)(?=^##\s*5[.、．]|\Z)', report)
    market_ids &= set(re.findall(r'\bE-[A-Z0-9-]{6,}\b', market_body[1], re.I)) if market_body else set()
    numeric = diagnostic.get('numeric_evidence') or {}
    if any(numeric_mentions(str(numeric.get(eid, {}).get('fact') or '')) for eid in market_ids):
        if not any(numeric.get(eid, {}).get('validation', {}).get('passed') is True for eid in market_ids):
            errors.append('市场规模章节尚无口径完整的数值证据，仅可作为待复核稿交付。')
    if '研究边界与口径' not in report:
        errors.append('缺少研究边界与口径。')
    bodies = {}
    for position, match in enumerate(chapters):
        chapter = int(match[1])
        if chapter == 15 or chapter in disabled:
            continue
        end = chapters[position+1].start() if position+1 < len(chapters) else len(report)
        body = re.split(r'(?m)^## (?:集中式待核验清单|报告编制说明)', report[match.end():end])[0]
        key = re.sub(r'\s+', '', body)
        if len(key) >= 120 and key in bodies:
            errors.append(f'第{chapter}章与第{bodies[key]}章正文完全重复，尚未完成各自章节任务。')
        bodies[key] = chapter
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
    from industry_evidence import evidence_requirements, fact_requirement_ids
    from industry_grounding import sample_boundary
    groups = {}
    for fact in facts:
        if not isinstance(fact, dict) or fact.get('eligible_for_risk_scoring') is False or fact.get('scope_match') != 'in_scope':
            continue
        if fact.get('evidence_scope') not in {'industry_level', 'segment_level', 'capital_market'}:
            continue
        if sample_boundary(fact):
            continue
        if (fact.get('module') == '竞争格局与代表企业'
                and not risk_fact_applicable(fact, '竞争格局与集中度风险')):
            continue
        groups.setdefault(fact.get('module') or '其他', []).append(fact)
    for rows in groups.values():
        rows.sort(key=lambda f: (f.get('claim_type') != 'source_excerpt',
                                 f.get('numeric_validation', {}).get('passed') is True,
                                 float(f.get('quality_score') or 0)), reverse=True)
        requirements = evidence_requirements([rows[0].get('module')])
        metric_ids = {id(f):set(fact_requirement_ids(f, requirements, True)) for f in rows}
        document_keys = {id(f):source_document_key(f.get('source_url', '')) for f in rows}
        ordered, covered, documents = [], set(), set()
        while rows and len(ordered) < limit:
            def rank(pair):
                index, fact = pair
                return (fact.get('claim_type') != 'source_excerpt',
                        bool(metric_ids[id(fact)] - covered),
                        bool(document_keys[id(fact)] and document_keys[id(fact)] not in documents),
                        (fact.get('numeric_context') or {}).get('is_forecast') is not True,
                        fact.get('numeric_validation', {}).get('passed') is True, -index)
            index, fact = max(enumerate(rows), key=rank)
            rows.pop(index); ordered.append(fact)
            covered.update(metric_ids[id(fact)])
            documents.add(document_keys[id(fact)])
        rows[:] = ordered + rows
    result = []
    offset = 0
    while len(result) < limit:
        items = [rows[offset] for rows in groups.values() if offset < len(rows)]
        if not items:
            break
        result.extend(items[:limit - len(result)])
        offset += 1
    return result
