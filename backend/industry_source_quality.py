"""Offline source-selection and qualification helpers for industry reports."""
import hashlib
import re
from urllib.parse import urlparse

VERSION = 'industry-source-quality-v2-focus-and-context'


def focus_terms(scope):
    parent = str((scope or {}).get('industry_name') or '').strip().casefold()
    terms = []
    for value in (scope or {}).get('segments') or []:
        value = str(value).strip()
        if not value or value.casefold() == parent:
            continue
        terms.append(value)
        if re.search(r'智能体|\bagents?\b|agentic', value, re.I):
            terms.extend(('智能体', 'agent', 'agents', 'agentic'))
    return list(dict.fromkeys(terms))


def mentions_focus(text, scope):
    terms = focus_terms(scope)
    return not terms or any(re.search(r'(?<![A-Za-z])'+re.escape(t)+r'(?![A-Za-z])', str(text), re.I)
                           if re.fullmatch(r'[A-Za-z]+', t) else t.casefold() in str(text).casefold()
                           for t in terms)


def source_qualifications(fact, scope):
    quote = str(fact.get('evidence_quote') or fact.get('fact') or '')
    context = str((fact.get('source_context') or {}).get('text') or quote)
    focus = 'core' if mentions_focus(context, scope) else 'background'
    issues = []
    path = urlparse(str(fact.get('source_url') or '')).path
    n = fact.get('numeric_context') or {}
    # A localized foreign-currency forecast is a review candidate until its
    # original unit is available in a located original source. Never multiply
    # every translated figure, or accept an unbound "verified" metadata flag.
    localized = bool(re.search(r'/(?:zh(?:-cn)?|cn|chinese)(?:/|$)', path, re.I))
    if localized and re.search(r'美元|USD', str(n.get('unit') or ''), re.I) and (
            n.get('is_forecast') is True or re.search(r'预测|预计|展望|forecast', quote, re.I)):
        issues.append('localized_currency_forecast_original_unit_unverified')
    return {'version': VERSION, 'requested_focus': focus,
            'focus_terms': focus_terms(scope), 'issues': issues}


def bound_policy_context(fact, body):
    """Bound applicability clauses to the same source snapshot as the quotation."""
    fact.pop('policy_context', None)
    loc = (fact.get('provenance') or {}).get('locator') or {}
    start, end = loc.get('start'), loc.get('end')
    if not (body and loc.get('status') == 'verified' and type(start) is int and type(end) is int
            and 0 <= start < end <= len(body) and hashlib.sha256(body.encode()).hexdigest() == loc.get('body_sha256')):
        return
    if not re.search(r'应当|不得|办法|条例|规定|通过|施行', body[start:end]):
        return
    spans = []
    for m in re.finditer(r'[^。；;\n]{1,380}[。；;]?', body):
        text = m[0].strip()
        if re.search(r'适用本|不适用本|适用范围|公众提供|未向.{0,12}公众|(?:通过|施行|公布).{0,15}20\d{2}|20\d{2}年\d{1,2}月\d{1,2}日.{0,15}(?:通过|施行)', text):
            left = m.start()+len(m[0])-len(m[0].lstrip())
            spans.append({'start': left, 'end': left+len(text), 'quote': text})
        if len(spans) >= 6:
            break
    if spans:
        fact['policy_context'] = {'body_sha256': loc['body_sha256'], 'spans': spans,
                                  'text': '\n'.join(s['quote'] for s in spans),
                                  'use': 'applicability_and_date_roles_only'}


def bound_context(fact):
    context = fact.get('policy_context') or {}
    loc = (fact.get('provenance') or {}).get('locator') or {}
    spans = context.get('spans') or []
    # Never trust arbitrary model-supplied context or a context from another body.
    if context.get('body_sha256') != loc.get('body_sha256') or not spans:
        return ''
    if any(type(s.get('start')) is not int or type(s.get('end')) is not int
           or s['start'] < 0 or s['end']-s['start'] != len(str(s.get('quote') or '')) for s in spans):
        return ''
    return '\n'.join(str(s['quote']) for s in spans)


def analysis_issues(claim, facts, chapter):
    text = str(claim.get('text') or '')
    issues = []
    canonical = ' '.join(str(f.get('fact_contract', {}).get('statement') or f.get('evidence_quote') or '') for f in facts)
    if chapter in {3, 13}:
        for f in facts:
            quote = str(f.get('evidence_quote') or '')
            # A passage dated "passed ... now promulgated" does not date the
            # promulgation. Keep the distinct legal event roles separate.
            for date in re.findall(r'(20\d{2}年\d{1,2}月\d{1,2}日)(?=.{0,8}通过)', quote):
                if re.search(re.escape(date)+r'.{0,8}(?:公布|发布|颁布)', text) and not re.search(
                        re.escape(date)+r'[，,\s]*(?:正式|予以|对外)?[，,\s]*(?:公布|发布|颁布)', bound_context(f)):
                    issues.append('analysis_passage_date_promoted_to_promulgation')
            ctx = bound_context(f)
            if '公众' in ctx and re.search(r'适用本|不适用本', ctx) and re.search(r'应当|必须|需要|须', text):
                if not re.search(r'公众|适用范围|适用主体|适用条件|适用前提', text):
                    issues.append('analysis_policy_applicability_missing')
    if chapter in {4, 11, 14}:
        contexts = [f.get('numeric_context') or {} for f in facts]
        bounds = [f.get('fact_contract', {}).get('comparator') or n.get('comparator')
                  for f, n in zip(facts, contexts)]
        if sum(b in {'>', '>=', '<', '<='} for b in bounds) >= 2 and re.search(r'逐年扩大|逐年增长|连续增长|构成可比|同口径端点', text):
            issues.append('analysis_bounds_do_not_establish_trend')
        if re.search(r'同口径端点|构成可比起终|可比序列', text) and not re.search(r'同口径|可比', canonical):
            issues.append('analysis_comparability_unverified')
    if re.search(r'\blocal_scope\b|原稿句子|原段其余|本次复核明确认可', text):
        issues.append('analysis_internal_review_metadata')
    return issues


def prioritize_source_cards(cards, scope):
    """Reserve focus and still-current outlook before each source's ten-card cap."""
    cutoff = str((scope or {}).get('as_of_date') or '')[:4]
    def rank(card):
        text = str(card.get('evidence_quote') or '')
        future = bool(cutoff.isdigit() and any(int(y) > int(cutoff) for y in re.findall(r'20\d{2}', text))
                      and re.search(r'预测|预计|展望|将|增至|增长至|forecast', text, re.I))
        return (mentions_focus(text, scope), future, bool(re.search(r'CR[345]|集中度|付费|任务成功率|调用成本|工具权限', text, re.I)))
    return sorted(cards, key=rank, reverse=True)


def scope_label(scope):
    terms = [str(s).strip() for s in (scope or {}).get('segments') or [] if str(s).strip()]
    parent = str((scope or {}).get('industry_name') or '').strip()
    return '、'.join(terms) if terms and terms != [parent] else parent
