"""Chapter 12: reproducible company assessments, separated from evidence strength.

Scores describe observed outcomes under an explicit research rubric. They are
not credit ratings, estimated default probabilities or peer-market rankings.
Missing dimensions retain their original weights; no renormalized flattering
average is allowed. Original statements, not model prose, supply every input.
"""
import json
import re
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

from .company_business import build_business_package
from .company_diligence import exchange, folded, host_of, issuer_heading, period_of, LEGAL
from .company_evidence import document_pages, source_body
from .company_governance import build_governance_package, _table, refs, get, cited_evidence_ids, combined_refs
from .company_history import build_history_package, financial_rows, METRICS
from .company_management import build_management_package, latest_roles
from .company_risk_register import (
    build_risk_register, filing_cutoff, iso_date, later_than_research_cutoff,
    source_anchor, usable,
)

VERSION = 'company-assessment-v1'
TITLE = '综合评价'
NUMBER = r'[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
RUBRIC = [
    {'id': 'revenue', 'name': '收入延续与增长', 'weight': 20,
     'anchors': '1=收入归零或连续两次同比下降；2=本期收入同比下降但仍为正；3=同比持平或从零转收入；4=本期同比增长；5=连续两次年度同比增长。零收入研发阶段另评，不默认1分。'},
    {'id': 'earnings_cash', 'name': '盈利与经营现金流表现', 'weight': 25,
     'anchors': '1=归母净利润与经营现金流均为负；2=其中一项为负或为零；3=两项均正但至少一项同比下降；4=两项均正且均不下降；5=连续两次年度比较均满足4分。两者口径不同，不相除作为现金转化率。'},
    {'id': 'technology', 'name': '研发成果商业兑现', 'weight': 15,
     'anchors': '公司分按明确合并范围的研发成果/核心技术产品收入同期趋势评价，1—5锚点同收入趋势；不代表技术性能领先。项目级2=已到样品/试制，3=已披露量产/交付。没有公司范围商业贡献时，不取最好项目或项目数量代替公司分。'},
    {'id': 'funding', 'name': '近期融资执行', 'weight': 15,
     'anchors': '3=目标法人近期融资已完成并披露实际募集净额/到账；5=至少两个相互独立、不同年度融资周期均已完成及实际净额。拟议、批准、子公司融资、估值或授信额度不加分。无近期融资不代表能力差。此项不等于偿债能力。'},
    {'id': 'control', 'name': '财务报告内控结果', 'weight': 15,
     'anchors': '1=审计明确财务报告内控无效/否定；2=明确保留意见且有未消除缺陷；3=明确截至日重大方面有效；4=连续两年度明确有效。一般制度、定性缺陷标准、财务报表审计意见或“未发现”不替代内控有效性结论。'},
    {'id': 'team', 'name': '组织目标执行结果', 'weight': 10,
     'anchors': '明确全公司考核范围、原考核权重、期前批准目标和同期间实际结果：1=实际为零且目标正；2=未达标；3=达标；4=超目标。按原权重汇总，不以目标设置宽松推同业领先，也不推个人能力或因果归因。岗位、年龄、持股与任期不直接评分。'},
]


def decimal(value):
    try:
        n = Decimal(str(value).replace(',', '').replace('%', '').strip())
        return n if n.is_finite() else None
    except InvalidOperation:
        return None


def score_row(ident, score, reason, records, **extra):
    definition = next(r for r in RUBRIC if r['id'] == ident)
    return {**definition, 'score': score, 'reason': reason, 'records': records,
            'evidence_ids': sorted({e for r in records for e in r.get('evidence_ids', [])}),
            'evidence_basis': '原件所载披露；各记录的发行人自报/审计/程序范围另列，不按来源数量加分', **extra}


def _recent(cutoff, as_of):
    if not cutoff:
        return False
    if not as_of:
        return True
    end = date.fromisoformat(as_of)
    # This is an explicit research observation window, not a legal time limit.
    try:
        start = end.replace(year=end.year - 2)
    except ValueError:
        start = end.replace(year=end.year - 2, day=28)
    return start <= date.fromisoformat(cutoff) <= end


def financial_observations(source, base):
    """Recover the issuer's main accounting table, including integer amounts.

    No segment, subsidiary or three-month table is spliced into a group annual
    snapshot. Current/prior headers and row-local units must both be explicit.
    """
    pages = document_pages(source)
    period = period_of(source, pages)
    cutoff = filing_cutoff(pages)
    if not cutoff or not re.search(r'年度|半年度|中期', period):
        return []
    rows = []
    for p in pages[:55]:
        text = p['text']
        compact = re.sub(r'\s+', '', text)
        if not re.search(r'主要会计数据|主要会計數據|主要财务指标|主要財務指標', compact):
            continue
        header = re.search(r'(20\d{2})年(20\d{2})年本年比上年增减(?:(20\d{2})年)?', compact)
        interim = '半年度' in period or '中期' in period
        if not header and not (interim and '本报告期' in compact and '上年同期' in compact):
            continue
        if header and max(int(header[1]), int(header[2])) != int(cutoff[:4]):
            continue
        # The established parser handles flattened two-decimal amounts and
        # Markdown grids. Whitespace-aware matching adds integer tables.
        candidates = financial_rows(text, period)
        for metric in METRICS:
            label = r'\s*'.join(map(re.escape, metric))
            pattern = label + r'\s*[（(]\s*(?P<unit>元|千元|万元|百万元)\s*[）)]\s*(?P<a>' + NUMBER + r')\s+(?P<b>' + NUMBER + r')\s+(?P<yoy>[-+]?\d+(?:\.\d+)?%)'
            m = re.search(pattern, text)
            if not m:
                continue
            a, b = m['a'], m['b']
            if header and int(header[1]) < int(header[2]):
                a, b = b, a
            r = {'metric': metric, 'value': a, 'previous_value': b, 'unit': m['unit'],
                 'period': period, 'yoy': m['yoy']}
            if header and header[3] and int(header[3]) == int(cutoff[:4]) - 2:
                third = re.match(r'\s+(' + NUMBER + ')', text[m.end():])
                if third:
                    r['third_value'] = third[1]
                    r['third_period'] = header[3] + '年度'
            candidates = [x for x in candidates if x['metric'] != metric] + [r]
        for r in candidates:
            if any(decimal(r.get(k)) is None for k in ('value', 'previous_value')):
                continue
            value, previous = decimal(r['value']), decimal(r['previous_value'])
            recomputed = ((value / previous - 1) * 100) if previous > 0 else None
            printed = decimal(r.get('yoy'))
            mismatch = printed is not None and recomputed is not None and abs(printed - recomputed) > Decimal('0.06')
            rows.append({**base, **r, 'kind': 'financial_metric', 'entity': base['entity'],
                         'cutoff': cutoff, 'period_kind': 'interim' if interim else 'annual',
                         'page': p['page'], 'currency': '未另作跨币种换算',
                         'computed_yoy_pct': str(round(recomputed, 4)) if recomputed is not None else None,
                         'printed_yoy_conflict': mismatch,
                         'fact': r['metric'] + '：本期' + r['value'] + r['unit'] + '，上年同期' + r['previous_value'] + r['unit']
                         + ('；第三年度' + r['third_value'] + r['unit'] if r.get('third_value') else ''),
                         'mode': '发行人主要会计数据表；非银行流水或逐单交易独立核验'})
        if rows:
            break
    return rows


def _latest_metric(rows, metric):
    group = [r for r in rows if r['metric'] == metric]
    if not group:
        return [], '对应会计指标未取得'
    cutoff = max(r['cutoff'] for r in group)
    group = [r for r in group if r['cutoff'] == cutoff]
    signatures = {(decimal(r['value']), decimal(r['previous_value']), r['unit'], r['period_kind']) for r in group}
    if len(signatures) != 1 or any(r['printed_yoy_conflict'] for r in group):
        return group, '同截至日指标存在原文数值/单位/同比冲突，停止该分项评分'
    return group, ''


def _financial_scores(rows):
    selected, error = _latest_metric(rows, METRICS[0])
    if error:
        revenue = score_row('revenue', None, error, selected)
    else:
        r = selected[0];v, p, third = decimal(r['value']), decimal(r['previous_value']), decimal(r.get('third_value'))
        if v < 0 or p < 0 or (v == 0 and p == 0):
            revenue = score_row('revenue', None, '零收入研发阶段或异常负营业收入须按阶段另评，不强行套用成熟经营趋势分', selected)
        else:
            two_years = r['period_kind'] == 'annual' and third is not None and third > 0
            score = 1 if v == 0 or (two_years and v < p < third) else 2 if v < p else 3 if v == p or p == 0 else 5 if two_years and v > p > third else 4
            revenue = score_row('revenue', score, r['period'] + '本期与上年同期比较；' + ('连续两次年度比较' if two_years else '本轮只评价已得同期变化')
                                + '，收入' + _change(r) + '。不将规模大小或收入增长视为技术领先。', selected)
    profits, pe = _latest_metric(rows, METRICS[1]);cash, ce = _latest_metric(rows, METRICS[2])
    if pe or ce:
        earnings = score_row('earnings_cash', None, pe or ce, profits + cash)
    elif (profits[0]['cutoff'], profits[0]['period_kind'], profits[0]['unit']) != (cash[0]['cutoff'], cash[0]['period_kind'], cash[0]['unit']):
        earnings = score_row('earnings_cash', None, '归母净利润与经营现金流不是同一截至日/期间/单位，不拼接评分', profits + cash)
    else:
        a, b = profits[0], cash[0]
        pv, cv = decimal(a['value']), decimal(b['value'])
        pp, cp = decimal(a['previous_value']), decimal(b['previous_value'])
        if pv < 0 and cv < 0:
            score = 1
        elif pv <= 0 or cv <= 0:
            score = 2
        elif pv < pp or cv < cp:
            score = 3
        else:
            pt, ct = decimal(a.get('third_value')), decimal(b.get('third_value'))
            continuous = a['period_kind'] == 'annual' and pt is not None and ct is not None and pp > 0 and cp > 0 and pp >= pt > 0 and cp >= ct > 0
            score = 5 if continuous else 4
        earnings = score_row('earnings_cash', score,
            a['period'] + '归母净利润' + ('为负' if pv < 0 else '为零' if pv == 0 else '为正') + '，经营现金流净额'
            + ('为负' if cv < 0 else '为零' if cv == 0 else '为正') + '；与同口径上年同期比较，归母利润' + _change(a) + '、经营现金流' + _change(b)
            + '。两者不相除冒充合并现金转化率。', profits + cash)
    return [revenue, earnings]


def _change(record):
    current, previous = decimal(record['value']), decimal(record['previous_value'])
    direction = '下降' if current < previous else '增长' if current > previous else '持平'
    if previous <= 0:
        return direction + '（上期为零或负，不给常规同比百分比）'
    pct = abs((current / previous - 1) * 100).quantize(Decimal('.01'))
    return direction + (str(pct) + '%' if pct else '')


def internal_control_observations(source, base):
    records = []
    cutoff = filing_cutoff(document_pages(source))
    for p in document_pages(source):
        text = re.sub(r'\s+', '', p['text'])
        if not re.search(r'内部控制审计报告|財務報告內部控制審計', text):
            continue
        # Isolate the actual audit-opinion subsection. Definitions of possible
        # deficiencies and issuer self-assessments never become audit findings.
        section = re.split(r'(?:2、|四、)?(?:内部控制审计报告中的审议意见段|财务报告内部控制审计意见)', text)
        if len(section) < 2:
            continue
        opinion = section[-1][:1000]
        explicit_date = re.search(r'于(' + r'20\d{2}年\d{1,2}月\d{1,2}日' + ')', opinion)
        dt = iso_date(explicit_date[1]) if explicit_date else cutoff
        if not dt or not re.search(r'我们认为|发表意见.*认为', opinion):
            continue
        state = ('ineffective' if re.search(r'未能在所有重大方面保持有效|未在所有重大方面保持有效|财务报告内部控制无效', opinion)
                 else 'qualified' if re.search(r'除.{1,100}外.{1,100}有效', opinion)
                 else 'effective' if re.search(r'在所有重大方面保持了有效的财务报告内部控制', opinion) else None)
        if not state:
            continue
        quote = re.search(r'(?:我们认为|[^。]{2,50}会计师事务所[^。]{0,80}认为)[：:，,]?[^。]{5,450}。', opinion)
        records.append({**base, 'kind': 'internal_control_opinion', 'cutoff': dt, 'state': state,
                        'page': p['page'], 'period': dt + '财务报告内控',
                        'fact': quote[0] if quote else opinion[:450],
                        'mode': '年报所载内控审计意见；不扩展为全部非财务控制或团队能力评价'})
    return records


def control_score(records):
    if not records:
        return score_row('control', None, '未取得有明确截至日的财务报告内控审计结论；制度、自评和普通财务报表审计不代替', [])
    latest = max(r['cutoff'] for r in records)
    current = [r for r in records if r['cutoff'] == latest]
    states = {r['state'] for r in current}
    if len(states) != 1:
        return score_row('control', None, '同截至日内控意见冲突，需核对原件修订与审计范围', current)
    state = next(iter(states))
    prior_year = str(int(latest[:4]) - 1) + latest[4:]
    previous = [r for r in records if r['cutoff'] == prior_year]
    two = previous and {r['state'] for r in previous} == {'effective'}
    score = 1 if state == 'ineffective' else 2 if state == 'qualified' else 4 if two else 3
    return score_row('control', score, '截至' + latest + '原件所载财务报告内控结论为' + {'effective': '重大方面有效', 'ineffective': '无效', 'qualified': '保留意见'}[state]
                     + '；不等同经营效率、团队胜任或全集团全部合规均已验证。', current + (previous if state == 'effective' and two else []))


def funding_score(history, target, as_of, originals=None):
    originals = originals or {}
    completed = []
    for r in history.get('facts', []):
        quote = str(r.get('fact') or '')
        original = originals.get(r.get('source_url'))
        if not original or folded(quote) not in folded(source_body(original)[0]):
            continue
        if r.get('kind') != 'event' or not re.search(r'完成.*(?:配售|发行)|配售完成|资金到账', quote):
            continue
        if re.search(r'拟|尚未|尚待|将于|决议通过', quote):
            continue
        # Only issuer-owned completed actions; a child financing/IPO remains
        # a separate capital-status note, never the parent's financing grade.
        if re.search(r'(?:子公司|附属公司)[^。]{0,60}(?:完成|发行|配售)|被收购', quote) and target not in quote:
            continue
        dt = iso_date(r.get('period')) or iso_date(quote)
        if not _recent(dt, as_of):
            continue
        amount = re.search(r'(?:净额|net proceeds|到账)[^。；]{0,35}?(?:RMB|HKD|USD|人民币|港元|美元|\d[\d,.]*\s*(?:元|万元|千元|百万元|百万港元|亿元))', quote, re.I)
        if not amount or not re.search(r'\d', quote[amount.start():amount.start() + 80]):
            continue
        # Actual completion and its amount must occur in this same original
        # observation. A matching source EID cannot join different financings.
        completed.append({**r, 'funding_date': dt, 'amount_records': []})
    cycles = {}
    for r in completed:
        cycles.setdefault(r['funding_date'], r)
    if not cycles:
        return score_row('funding', None, '观察窗内未取得目标法人融资完成及实际募集净额/到账的对应披露；不据此认定缺乏融资能力', [])
    records = [r for r in cycles.values()]
    years = {r['funding_date'][:4] for r in records}
    score = 5 if len(years) >= 2 else 3
    support = records + [x for r in records for x in r['amount_records']]
    return score_row('funding', score, '目标法人近期融资执行已获完成及实际净额披露支持；'
                     + ('不同年度周期已去重' if score == 5 else '单年度融资周期不外推持续融资优势')
                     + '。本项不评价现金是否受限、债务到期覆盖或未来偿债能力。', support)


def capital_status_observations(sources, target, cards, as_of):
    sources = [s for s in sources if usable(s) and not later_than_research_cutoff(s, as_of)]
    relations = {}
    owned = []
    for s in sources:
        pages = document_pages(s)
        if not exchange(s) or not issuer_heading(pages, target):
            continue
        base = source_anchor(s, cards)
        owned.append((s, base))
        raw, _ = source_body(s)
        for m in re.finditer(r'分拆(?:所属|控股)?子公司\s*(' + LEGAL + ')', raw):
            name = m[1]
            relations[folded(name)] = {'entity': name, 'proof': {**base, 'kind': 'capital_subject_relation',
                'entity': name, 'fact': m[0], 'period': period_of(s, pages),
                'mode': '发行人原件明确分拆对象；不反推不同日期的持股比例'}}
    observations = []
    for s in sources:
        raw, _ = source_body(s);base = source_anchor(s, cards)
        if not base:
            continue
        pages = document_pages(s)
        root_owned = any(s is x for x, _ in owned)
        gov = host_of(s).endswith('.gov.cn')
        for entry in relations.values():
            name = entry['entity'];alias = re.sub(r'股份有限公司$|有限责任公司$|有限公司$', '', name)
            addressed = bool(re.search(r'(?m)^\s*' + re.escape(name) + r'\s*[:：]', raw))
            if not root_owned and not (gov and addressed):
                continue
            pieces = [{'page': p['page'], 'text': p['text']} for p in pages] if pages else [{'page': None, 'text': raw}]
            for p in pieces:
                sentences = re.split(r'(?<=[。；])\s*', re.sub(r'\s+', '', p['text']))
                for quote in sentences:
                    if not (alias in quote or (gov and addressed and '你公司' in quote)):
                        continue
                    if not re.search(r'分拆.*上市|发行注册程序|发行条件.*上市条件', quote):
                        continue
                    if re.search(r'拟终止|将终止|如.{0,50}终止|应当|可能|若发生', quote):
                        continue
                    state = ('terminated' if re.search(r'决定终止.*发行注册程序|(?:已|同意|决定)?终止.{0,35}(?:分拆|上市|发行注册)', quote)
                             else 'withdrawal_requested' if re.search(r'提交.*撤回|申请撤回', quote)
                             else 'approved' if re.search(r'符合发行条件.*上市条件|审议通过|批准|核准', quote) else None)
                    if not state:
                        continue
                    dates = re.findall(r'20\d{2}年\d{1,2}月\d{1,2}日', quote)
                    dt = iso_date(dates[0]) if dates else None
                    if gov and state == 'terminated':
                        signature = re.findall(r'(?m)^\s*(20\d{2}年\d{1,2}月\d{1,2}日)\s*$', raw)
                        if signature:
                            dt = iso_date(signature[-1])
                    if not dt or (as_of and dt > as_of):
                        continue
                    observations.append({**base, 'kind': 'capital_status', 'entity': name, 'date': dt,
                        'state': state, 'page': p['page'], 'fact': quote[:1100], 'relationship': entry['proof'],
                        'evidence_ids': list(dict.fromkeys(base['evidence_ids'] + entry['proof']['evidence_ids'])),
                        'mode': '该次程序的原文状态；不证明从未再次申请，不代表母公司已融资或技术领先'})
    latest = {}
    priority = {'approved': 1, 'withdrawal_requested': 2, 'terminated': 3}
    for r in observations:
        key = folded(r['entity'])
        if key not in latest or (r['date'], priority[r['state']]) > (latest[key]['date'], priority[latest[key]['state']]):
            latest[key] = r
    return list(latest.values()), list(relations.values())


def aggregate_scores(dimensions):
    if sum(d['weight'] for d in dimensions) != 100:
        raise ValueError('综合观察分的固定权重必须合计100')
    known = [d for d in dimensions if d['score'] is not None]
    if any(not 1 <= d['score'] <= 5 or not d['evidence_ids'] for d in known):
        raise ValueError('已评分项必须有1—5分及原件定位')
    contribution = sum(Decimal(str(d['score'])) * d['weight'] / 5 for d in known)
    missing = sum(d['weight'] for d in dimensions if d['score'] is None)
    return {'quality_score': float(contribution) if missing == 0 else None,
            'known_contribution': float(contribution), 'assessed_weight_pct': 100 - missing,
            'unassessed_weight_pct': missing,
            'possible_range': [float(contribution + Decimal(missing) / 5), float(contribution + missing)] if known else None,
            'formula': '已评分项贡献=Σ(分项分÷5×固定权重)；缺项仍占原权重，可能区间按缺项1—5分求界；不对已知项归一化，不把缺项填0或3。',
            'interpretation': '这是研究观察框架下的公司表现评价，不是证据覆盖分、信用等级或风险概率；区间不是统计置信区间。'}


def assessment_discovery_queries(target):
    return [{'module': TITLE, 'query': '"' + target + '" 分拆 子公司 上市 终止 撤回 最新进展',
             'search_tier': 'authority_first', 'include_domains': ['csrc.gov.cn', 'szse.cn', 'sse.com.cn', 'cninfo.com.cn', 'hkexnews.hk']},
            {'module': TITLE, 'query': '"' + target + '" 年度报告 主要会计数据 内部控制审计意见',
             'search_tier': 'authority_first', 'include_domains': ['szse.cn', 'sse.com.cn', 'cninfo.com.cn', 'hkexnews.hk']}]


def outcome_observations(sources, target, cards):
    """Company-scope outcomes can close currently missing scoring dimensions.

    A subsidiary amount or one successful project cannot silently become a
    company total. Execution targets require the issuer's complete assessment
    scope and original weights, rather than analyst-selected favorable goals.
    """
    tech, execution = [], []
    for s in sources:
        pages = document_pages(s)
        if not exchange(s) or not issuer_heading(pages, target):
            continue
        base = source_anchor(s, cards)
        cutoff = filing_cutoff(pages);period = period_of(s, pages)
        if not base or not cutoff:
            continue
        interim = '半年度' in period or '中期' in period
        end = date.fromisoformat(cutoff)
        months = 6 if interim else 12
        first_month_index = end.year * 12 + end.month - months
        start = date(first_month_index // 12, first_month_index % 12 + 1, 1).isoformat()
        for p in pages:
            text = p['text'];c = re.sub(r'\s+', '', text)
            h = re.search(r'(20\d{2})年(20\d{2})年(?:本年比上年增减|同比)', c)
            if (h and int(h[1]) > int(h[2]) and h[1] == cutoff[:4]
                    and re.search(r'全公司范围|公司整体口径|本集团合并口径', c)
                    and not re.search(r'子公司财务|分部财务', c)):
                for name in ('研发成果商业化收入', '研发成果转化产品收入', '核心技术产品收入'):
                    label = r'\s*'.join(map(re.escape, name))
                    m = re.search(label + r'\s*[（(](元|千元|万元|百万元)[）)]\s*(' + NUMBER + r')\s+(' + NUMBER + r')\s+([-+]?\d+(?:\.\d+)?%)', text)
                    if not m:
                        continue
                    a, b = decimal(m[2]), decimal(m[3])
                    yoy = (a / b - 1) * 100 if b and b > 0 else None
                    tech.append({**base, 'kind': 'technology_commercial_outcome', 'entity': target,
                                 'metric': name, 'period': period, 'period_kind': 'interim' if interim else 'annual',
                                 'cutoff': cutoff, 'unit': m[1], 'value': m[2], 'previous_value': m[3],
                                 'yoy': m[4], 'page': p['page'], 'fact': '公司范围；' + m[0],
                                 'printed_yoy_conflict': bool(yoy is not None and abs(yoy - decimal(m[4])) > Decimal('.06')),
                                 'mode': '发行人明确公司范围商业收入；不等于技术性能独立鉴定'})
            if not ('全公司目标考核范围' in c and '全部指标' in c):
                continue
            for table in p.get('tables') or []:
                if not table:
                    continue
                heads = [re.sub(r'\s+', '', str(v or '')) for v in table[0]]
                needed = ['指标', '目标', '实际', '单位', '目标批准日期', '责任主体', '考核权重(%)']
                normalized = [v.replace('（', '(').replace('）', ')') for v in heads]
                if not all(n in normalized for n in needed):
                    continue
                for row in table[1:]:
                    if len(row) != len(heads):
                        continue
                    r = dict(zip(normalized, [str(v or '').strip() for v in row]))
                    target_value, actual, weight = (decimal(r[n]) for n in ('目标', '实际', '考核权重(%)'))
                    approval = iso_date(r['目标批准日期'])
                    if (target_value is None or target_value <= 0 or actual is None or actual < 0
                            or weight is None or not 0 < weight <= 100 or not approval or approval >= start
                            or folded(r['责任主体']) != folded(target) or not r['单位']):
                        continue
                    execution.append({**base, 'kind': 'company_execution_outcome', 'entity': target,
                        'metric': r['指标'], 'target_value': str(target_value), 'actual_value': str(actual),
                        'unit': r['单位'], 'weight': str(weight), 'approval_date': approval,
                        'cutoff': cutoff, 'period': period, 'page': p['page'],
                        'goal_score': 1 if actual == 0 else 2 if actual < target_value else 3 if actual == target_value else 4,
                        'fact': '；'.join(r[n] for n in needed),
                        'mode': '发行人明确全公司目标范围/期前批准/责任主体/实际/原考核权重；不据此推个人因果归因'})
    return tech, execution


def execution_score(records, team_records):
    fallback = '已有岗位/任职及履历可说明配置；尚未取得全公司考核范围、期前目标批准、责任主体、同期间实际和完整原权重，不以任期、持股、年龄或亲属关系评分。'
    if not records:
        return score_row('team', None, fallback, team_records[:5])
    latest = max(r['cutoff'] for r in records)
    group = [r for r in records if r['cutoff'] == latest]
    unique = {}
    for r in group:
        key = (r['metric'], r['target_value'], r['actual_value'], r['unit'], r['weight'], r['approval_date'])
        unique.setdefault(key, r)
    group = list(unique.values())
    if len({r['metric'] for r in group}) != len(group) or sum(Decimal(r['weight']) for r in group) != 100:
        return score_row('team', None, '原件目标考核明细冲突或权重不完整，不选取有利指标重算公司执行分', group)
    value = sum(Decimal(r['weight']) * r['goal_score'] / 100 for r in group)
    return score_row('team', float(value), '公司期前批准目标的实际兑现按原考核权重汇总；只评价该目标体系的执行结果，不推同业领先、目标难度或管理者个人能力。', group)


def build_assessment_package(cleaned, target, sources=None, *, intake=None, industry=''):
    intake = dict(intake or {})
    requested = intake.get('as_of_date')
    as_of = iso_date(requested) if requested else date.today().isoformat()
    if not as_of:
        raise ValueError('公司评价的研究截至日无法识别，不能静默改用当前日期')
    intake['as_of_date'] = as_of
    source_list = [s for s in list(sources or []) if usable(s) and not later_than_research_cutoff(s, as_of)]
    cards = defaultdict(list)
    for c in cleaned.get('facts', []):
        if isinstance(c, dict):
            cards[str(c.get('source_url') or '')].append(c)
    anchors, financial, controls = [], [], []
    for s in source_list:
        base = source_anchor(s, cards)
        if not base:
            continue
        if exchange(s) and issuer_heading(document_pages(s), target):
            base = {**base, 'entity': target}
            anchors.append({**base, 'fact': '原件定位，评分事实由对应字段解析，不采用模型评分。', 'evidence_scope': 'target_direct'})
            financial += financial_observations(s, base)
            controls += internal_control_observations(s, base)
    financial = [r for r in financial if _recent(r['cutoff'], as_of)]
    controls = [r for r in controls if _recent(r['cutoff'], as_of)]
    clean = {**cleaned, 'facts': list(cleaned.get('facts', [])) + anchors}
    governance = build_governance_package(clean, target, source_list)
    history = build_history_package(clean, target, source_list, governance=governance)
    business = build_business_package(clean, target, source_list)
    management = build_management_package(clean, target, source_list)
    risk = build_risk_register(clean, target, source_list, industry=industry, intake=intake)
    dimensions = _financial_scores(financial)
    projects = [r for r in business['facts'] if r['kind'] == 'project' and not r.get('conflict')]
    project_scores = []
    for r in projects:
        actual = r.get('progress') or ''
        dates = [iso_date(v) for v in re.findall(r'20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日', actual)]
        if any(dt and dt > as_of for dt in dates):
            continue
        # Goals and promotional adjectives are never used as accomplished work.
        value = 3 if re.search(r'已.{0,10}(?:量产|交付|商业运营)|(?:技术|组件|产品|芯片|项目).{0,15}量产推广|投产|量产装车', actual) and not re.search(r'拟|预计|计划|将于|尚未|未能|停止|终止|暂停', actual) else 2 if re.search(r'样品|样机|试制|试运行|A样|B样', re.sub(r'\s+', '', actual)) else None
        if value:
            project_scores.append({**r, 'project_observation_score': value,
                                   'judgment': '项目阶段观察；不是公司技术领先/核心竞争力分，不从目标或量产宣传推独立性能验证。'})
    tech, execution = outcome_observations(source_list, target, cards)
    tech = [r for r in tech if _recent(r['cutoff'], as_of)]
    if tech:
        proxy = [{**r, 'metric': METRICS[0]} for r in tech]
        result = _financial_scores(proxy)[0]
        tech_dimension = score_row('technology', result['score'], '公司合并范围研发成果商业收入的同比兑现情况：' + result['reason']
                                   + ' 此分不等于技术性能、专利壁垒或同业领先程度。', tech)
    else:
        tech_dimension = score_row('technology', None,
            '已得项目可分别说明样品/试制或量产阶段；尚未取得公司范围研发成果商业贡献，不能取最好项目或按项目数量给全公司技术分。', project_scores[:3])
    tech_dimension['project_scores'] = project_scores
    dimensions.append(tech_dimension)
    originals = {str(get(s, 'url')): s for s in source_list if exchange(s) and issuer_heading(document_pages(s), target)}
    dimensions.append(funding_score(history, target, as_of, originals=originals))
    dimensions.append(control_score(controls))
    roster = latest_roles(management['facts'])
    team_records = [row for _, rows in roster for row in rows]
    execution = [r for r in execution if _recent(r['cutoff'], as_of)]
    dimensions.append(execution_score(execution, team_records))
    aggregate = aggregate_scores(dimensions)
    capital, relations = capital_status_observations(source_list, target, cards, as_of)
    facts = financial + controls + [r for d in dimensions for r in d['records']] + capital + [e['proof'] for e in relations] + team_records + project_scores
    # Keep only actually used risk records in this chapter. Detailed case,
    # recall scope and transaction tables remain in chapters 9—11.
    signals = []
    for entry in risk['entries']:
        mechanism = entry['kind']
        if mechanism in {r['kind'] for r in signals}:
            continue
        record = entry['fact_record']
        if mechanism == 'recall':
            newest = max((e for e in risk['entries'] if e['kind'] == mechanism), key=lambda e: e['fact_record']['publication_date'])
            entry = newest;record = entry['fact_record']
        signals.append({'kind': mechanism, 'label': entry['label'], 'assessment': entry['assessment'],
                        'followup': entry['followup'], 'evaluation_implication': _risk_implication(mechanism),
                        'fact_record': record, 'evidence_ids': entry['evidence_ids']})
        facts.append(record)
        if record.get('relationship'):
            facts.append(record['relationship'])
    unique = {}
    for r in facts:
        unique.setdefault((r.get('source_url'), r.get('page'), r.get('kind'), r.get('fact')), r)
    used_urls = {r.get('source_url') for r in unique.values()}
    limitations = []
    for s in source_list:
        if str(get(s, 'url')) not in used_urls:
            continue
        meta = get(s, 'source_metadata', {}) or {}
        extraction = meta.get('document_extraction') or {}
        omitted = int(extraction.get('omitted_pages') or 0)
        pending = extraction.get('needs_ocr_pages') or []
        if omitted or pending:
            b = source_anchor(s, cards)
            limitations.append({**b, 'kind': 'source_limitation', 'entity': target,
                'fact': '该原件仍有' + str(omitted) + '页未提取、' + str(len(pending)) + '页被标记需OCR；不能由局部可评分指标认定全文已验收。',
                'mode': '真实提取状态；未将原生PDF文字提取冒充机器OCR'})
    for r in limitations:
        unique[(r['source_url'], None, r['kind'], r['fact'])] = r
    gaps = [d['name'] + '：' + d['reason'] for d in dimensions if d['score'] is None]
    gaps += ['公开原件的程序/经营记录不能替代全部资金流水、客户交易、独立性能测试或事件损失核查；来源获取和OCR限制延续前章。']
    gaps += [r['source_title'] + '：' + r['fact'] for r in limitations]
    return {'version': VERSION, 'target_name': target, 'as_of_date': as_of,
            'rubric_basis': '本系统的可解释研究框架，权重为分析选择：经营与盈利45%、技术15%、融资15%、内控15%、团队10%；不是外部认证评分标准。观察窗采用研究截至日前两年，历史事件另列。',
            'score_direction': '公司表现分1—5，越高表示对应已观察表现较好；与风险分0—100越高风险越高严格分开。趋势档位不代表行业排名，变动幅度与金额需一起判断。',
            'dimensions': dimensions, 'aggregate': aggregate, 'financial_observations': financial,
            'capital_status': capital, 'risk_signals': signals, 'facts': list(unique.values()),
            'information_gaps': gaps, 'current_roles': team_records, 'source_limitations': limitations,
            'overall_judgment': ('可形成有依据的经营、融资及内控分项评价；仍须结合未评分维度和具体风险的集团重大性，部分正分不能替代推进条件核验。' if aggregate['assessed_weight_pct'] else '目前不能形成有依据的公司综合分项评分，先补充核心经营/执行结果原件。'),
            'diagnostic': {'scored_dimensions': sum(d['score'] is not None for d in dimensions),
                           'unscored_dimensions': sum(d['score'] is None for d in dimensions),
                           'financial_records': len(financial), 'project_observations': len(project_scores),
                           'capital_status_subjects': len(capital), 'risk_mechanisms': len(signals)}}


def render_assessment(p):
    a = p['aggregate']
    lines = ['## 12. ' + TITLE, '', '### 综合判断与评分口径', '', '评价截至：' + p['as_of_date'] + '；各指标数据期另列。', '', p['overall_judgment'], '',
             p['score_direction'], '', p['rubric_basis'], '']
    if not p['facts']:
        lines += ['本次已检索公开来源未形成可引用记录；不能补造公司分数，需按后续核查要求取得原件。', '']
    if a['quality_score'] is not None:
        lines += ['按已披露框架计算的公司综合观察分：' + str(a['quality_score']) + '/100。该数值仍需结合下述风险事项及适用范围理解。', '']
    elif a['possible_range']:
        lines += ['公司综合观察分暂不报单点值。已评分项原始贡献为' + str(a['known_contribution']) + '/100，未评分项仍占'
                  + str(a['unassessed_weight_pct']) + '%权重；按未评分项1—5分求得的可能区间为'
                  + '—'.join(map(str, a['possible_range'])) + '/100。该区间是待核项造成的数学边界，不能当作已实现分数或置信区间。', '']
    lines += [a['formula'], '', '### 分项评价与原件依据', '']
    lines += _table(['评估维度/固定权重', '1—5分', '判断依据及边界'],
                    [[d['name'] + ' ' + str(d['weight']) + '%', str(d['score']) if d['score'] is not None else '未评分',
                      d['reason'] + combined_refs(_sample(d['records'], 2))] for d in p['dimensions']])
    lines += ['', '### 已核经营变化、优势与制约', '']
    by_metric = {m: _latest_metric(p['financial_observations'], m) for m in METRICS}
    prof, prof_error = by_metric[METRICS[1]];cash, cash_error = by_metric[METRICS[2]]
    if (not prof_error and not cash_error and prof[0]['cutoff'] == cash[0]['cutoff']
            and prof[0]['period_kind'] == cash[0]['period_kind'] and prof[0]['unit'] == cash[0]['unit']
            and decimal(prof[0]['value']) > 0 and decimal(cash[0]['value']) > 0):
        lines += ['- 已观察到盈利与经营现金净流入并存，支持当期经营存在现金回流；仍需结合同比变化、受限资金与后续支出判断，不能直接推出现金充裕或全部业务真实。' + combined_refs([prof[0],cash[0]])]
    funding = next(d for d in p['dimensions'] if d['id'] == 'funding')
    if funding['score'] is not None:
        lines += ['- 已完成的融资体现近期资本执行结果；其募集净额、时间和主体见对应原件，不将该结果外推为所有子公司资金可自由调用。' + refs(funding['records'][0])]
    periods = {kind: max((r['cutoff'] for r in p['financial_observations'] if r['period_kind'] == kind), default='') for kind in ('annual', 'interim')}
    financial = _sample([r for r in p['financial_observations'] if r['cutoff'] == periods[r['period_kind']]], 6,
                        key=lambda r: (r['cutoff'], r['metric'], r['unit']))
    if financial:
        lines += ['', '经营指标按年度与中期分别列示，不把半年度数直接乘二或拿全年与半年增速相比较。', '']
        lines += _table(['原件期间/主体', '指标', '本期/上年同期（原单位）', '同口径变化/定位'],
                        [[r['period'] + '；' + r['entity'], r['metric'], r['value'] + ' / ' + r['previous_value'] + ' ' + r['unit'],
                          _change(r) + '；物理页' + str(r['page']) + refs(r)] for r in financial])
    projects = next(d for d in p['dimensions'] if d['id'] == 'technology')['project_scores']
    if projects:
        lines += ['', '项目阶段可以评价，但不能代表整个公司技术领先程度：', '']
        lines += _table(['项目/披露期', '项目观察分', '已达到阶段与边界'],
                        [[r['entity'] + '；' + r['period'], str(r['project_observation_score']),
                          r.get('progress', '') + '（公司披露，非独立性能测试）' + refs(r)] for r in projects[:3]])
    lines += ['', '### 历史资本事项的当前表述', '']
    if p['capital_status']:
        for r in p['capital_status']:
            state = {'terminated': '该次程序已终止', 'withdrawal_requested': '该次撤回申请已提出', 'approved': '原件记载该次审议/批准，后续完成另核'}[r['state']]
            lines += ['- ' + r['entity'] + '：' + r['date'] + '；' + state + '。' + refs(r)
                      + '不据历史过会/批准认定当前已上市或技术领先；未取得此后重新受理/完成原件时保留后续状态待核。']
    else:
        lines += ['本轮未形成可用于当前结论的资本程序状态原件；不把投资机构名单、媒体估值或历史过会当作当前融资/上市结果。']
    lines += ['', '### 核心制约与下一步判断条件', '']
    for r in p['risk_signals']:
        lines += ['- ' + r['label'] + '：' + r['evaluation_implication'] + refs(r['fact_record'])]
    if p['current_roles']:
        dates = sorted({r.get('as_of', '') for r in p['current_roles'] if r.get('as_of')})
        lines += ['', '团队配置已有岗位与任职记录，最近已得任职披露截至' + (dates[-1] if dates else '原件所列时点')
                  + '。这些记录不直接证明执行稳定性或人员能力评分。' + combined_refs(_sample(p['current_roles'], 2))]
    lines += ['', '下一阶段应围绕上列具体事项补足判断条件。尚未量化的安全整改、回收/资金影响和关键评价缺口不能被经营正分抵消；是否进入交易或投资决策应结合委托方具体条件，不预设通用TS禁签门槛。', '',
              '### 分项锚点', '']
    for d in p['dimensions']:
        lines += ['- ' + d['name'] + '：' + d['anchors']]
    if p.get('source_limitations'):
        lines += ['', '### 原件覆盖界限', '']
        lines += ['- ' + r['source_title'] + '：' + r['fact'] + refs(r) for r in p['source_limitations']]
    return '\n'.join(lines).strip()


def _risk_implication(kind):
    return {
        'recall': '已有生产商召回事项。安全整改覆盖、复发和成本尚待闭环，经营或技术项目正分不能作为质量安全已通过的证明；批次明细接续第十一章。',
        'recovery_obstacle': '已有具体案件回收障碍，胜诉/判赔金额与可回收现金分开。应核对回款和减值准备，未量化集团重要性前不任意扣一个等级。',
        'case_pending': '具体案件尚在程序或执行阶段；请求、判决和实收不等同，不先按败诉损失扣分，也不能因公司经营正分将其清除。',
        'labour_procedure': '用工争议公告需要后续请求、裁决与履行材料。人数、文化自报或流失率不能直接排除争议，也不据公告认定违法。',
        'purchase_accounting': '商誉账面与减值测试假设需对照并购后实际兑现；不能由历史增长、商誉比例或进行测试直接认定减值已发生或风险已消化。',
        'payment_pending': '未付款项须先核对原文原因、到期义务与后续支付。融资执行分不证明偿债无碍，也不把持票人未提示付款等同发行人无力偿付。',
        'related_funding': '关联借款按实际借款人、出借人、币种、用途与还款安排核对；子公司融资和备考额度不并入母公司已取得资金。',
    }.get(kind, '具体原件事项的范围和未闭环条件需接续核验，不用正分抹去或按信息缺口机械扣分。')


def _sample(records, limit, key=None):
    unique = {}
    for r in sorted(records, key=lambda x: str(x.get('cutoff') or x.get('as_of') or x.get('period') or ''), reverse=True):
        signature = key(r) if key else (r.get('source_url'), r.get('fact'))
        unique.setdefault(signature, r)
    return list(unique.values())[:limit]


def assessment_errors(text, p):
    errors = []
    if p['diagnostic']['scored_dimensions'] == 0:
        errors.append('尚无可按原件和锚点评价的公司分项，需人工复核')
    if [d['id'] for d in p['dimensions']] != [d['id'] for d in RUBRIC]:
        errors.append('综合评价维度不完整或顺序不一致')
    if aggregate_scores(p['dimensions']) != p['aggregate']:
        errors.append('分项与综合计算不一致')
    allowed = {e for r in p['facts'] for e in r.get('evidence_ids', [])}
    if set(cited_evidence_ids(text)) - allowed:
        errors.append('综合评价出现无原件定位的证据编号')
    return errors
