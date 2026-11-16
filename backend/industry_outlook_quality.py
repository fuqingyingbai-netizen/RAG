"""Offline outlook timing and candidate-inventory diagnostics.

Inventory entries never authorize a number, fact, score or model premise.
"""
import re
from datetime import date

VERSION = 'industry-outlook-v1-time-and-candidate-inventory'


def forecast_window(fact, scope):
    n = fact.get('numeric_context') or {}
    c = fact.get('fact_contract') or {}
    is_forecast = n.get('is_forecast') is True or n.get('value_nature') == 'forecast' or c.get('value_nature') == 'forecast'
    cutoff = str((scope or {}).get('as_of_date') or '')
    period = str(n.get('period') or c.get('period') or '').strip()
    if not is_forecast:
        return {'status': 'not_numeric_forecast', 'target_period': period}
    result = {'target_period': period, 'as_of_date': cutoff, 'use': 'forecast_not_observed_actual'}
    if not re.fullmatch(r'20\d{2}-\d{2}-\d{2}', cutoff):
        return {**result, 'status': 'cutoff_unknown'}
    try:
        date.fromisoformat(cutoff)
    except ValueError:
        return {**result, 'status': 'cutoff_unknown'}
    if re.fullmatch(r'20\d{2}-\d{2}-\d{2}', period):
        try:
            date.fromisoformat(period)
        except ValueError:
            return {**result, 'status': 'target_period_unknown'}
        return {**result, 'status': 'expired' if period < cutoff else 'current_or_future',
                'target_year':int(period[:4]),'years_from_cutoff':int(period[:4])-int(cutoff[:4])}
    # Only an explicit period is inspected. A publication year, URL or an
    # amount containing four digits is never promoted into a target year.
    match = re.fullmatch(r'(20\d{2})(?:年)?(?:\s*(?:-|—|–|至|到)\s*(20\d{2})(?:年)?)?', period)
    if not match:
        return {**result, 'status': 'target_period_unknown'}
    if match[2] and int(match[2]) < int(match[1]):
        return {**result, 'status':'target_period_unknown'}
    end = int(match[2] or match[1])
    return {**result, 'status': 'expired' if end < int(cutoff[:4]) else 'current_or_future',
            'target_year': end, 'years_from_cutoff': end-int(cutoff[:4])}


def question_matches(fact, question, pattern, scope):
    n = fact.get('numeric_context') or {}
    quote = str(fact.get('evidence_quote') or fact.get('fact') or '')
    text = quote+' '+str(n.get('metric') or '')
    if pattern in {'forecast','long_forecast'}:
        return n.get('is_forecast') is True or bool(re.search(r'预测|预计|展望', quote))
    if pattern == 'amount':
        return bool(re.search(r'规模|收入|营收|金额',text))
    if pattern == 'growth':
        return bool(re.search(r'增长|同比|CAGR|复合.*增长',text,re.I))
    if pattern == 'historical_series':
        return len(set(re.findall(r'20\d{2}(?=年)',quote))) >= 3
    if pattern == 'technical_measurement':
        return bool(re.search(r'实测|测试|成功率|延迟|吞吐|每任务成本|单位任务成本',text))
    if pattern == 'synthesis':
        return False
    return bool(re.search(pattern, text, re.I))


def candidate_inventory(payload, chapter):
    from industry_fact_contracts import CHAPTER_QUESTIONS, chapter_admitted
    from industry_source_quality import mentions_focus
    from industry_passages import passage_issues
    scope = payload.get('industry_scope') or {}
    buckets = {q: [] for q, _ in CHAPTER_QUESTIONS.get(chapter, [])}
    counts = {q: 0 for q in buckets}
    seen = set()
    for fact in payload.get('facts') or []:
        if not isinstance(fact,dict) or not fact.get('evidence_id') or fact.get('scope_match') != 'in_scope':
            continue
        if chapter_admitted(fact,chapter):
            continue
        c = fact.get('fact_contract') or {}
        if not c or c.get('report_admitted'):
            continue  # Background or another chapter's valid fact is not a rejected candidate.
        quote = str(fact.get('evidence_quote') or fact.get('fact') or '')
        if passage_issues(quote):
            continue  # A question, catalogue or clipped fragment is not missing research.
        context = quote+' '+str((fact.get('source_context') or {}).get('text') or '')
        if chapter not in {3,13} and not mentions_focus(context,scope):
            continue
        reasons = list(c.get('issues') or [])
        reviewable = [reason for reason in reasons if re.search(r'original_unit|numeric|untyped_quantity|metric_value|statistical_period|unlocated',reason)]
        if not reviewable:
            continue
        if chapter == 11 and forecast_window(fact,scope)['status'] == 'expired':
            continue
        url = str(fact.get('source_url') or '')
        if not re.match(r'^https?://[^\s<>]+$',url):
            continue
        for q, pattern in CHAPTER_QUESTIONS.get(chapter,[]):
            key = (q, fact['evidence_id'])
            if key in seen or not question_matches(fact,q,pattern,scope):
                continue
            seen.add(key);counts[q]+=1
            if len(buckets[q]) < 4:
                buckets[q].append({'evidence_id':fact['evidence_id'], 'url':url,
                    'title':str(fact.get('source_display_title') or fact.get('source_title') or '')[:180],
                    'issues':reviewable[:6], 'admitted_as_evidence':False})
    return [{'question':q, 'review_candidate_count':counts[q], 'review_candidates':buckets[q],
             'inventory_status':'candidate_review_required' if counts[q] else 'no_review_candidate_recorded',
             'absence_scope':'仅核对本轮保留的事实候选，不代表归档全文或公开资料不存在该信息'} for q in buckets]


def finding_key(claim):
    # Dedupe only the same explicit finding, not merely similar subject matter.
    text = str(claim.get('conclusion') or claim.get('text') or '')
    text = re.sub(r'\[E-[A-Za-z0-9-]+\]', '', text)
    return re.sub(r'[\s`*，,。；;：:！？!?（）()]', '', text)
