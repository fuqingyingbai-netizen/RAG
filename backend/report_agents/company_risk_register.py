"""Company chapter 11: source-bound events, assessments and checklist coverage.

The template is a set of questions. A source ID, a model's score and a
search result are deliberately insufficient to answer any of those questions.
"""
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from .company_diligence import (
    LEGAL, build_diligence_package, exchange, folded, host_of, issuer_heading,
    period_of,
)
from .company_evidence import document_pages, source_body
from .company_governance import EID, get, refs, _table, cited_evidence_ids, combined_refs
from .company_judicial import build_judicial_package, displayed_case_key
from .company_people import build_people_package

VERSION = 'company-risk-register-v2-case-display-references'
TITLE = '风险核查'
CATEGORIES = ('组织与管理风险', '业务与运营风险', '行业特殊风险')
BAD_FETCH = {'failed', 'fetch_timeout', 'invalid_pdf_response', 'blocked_or_challenge',
             'wrong_page_or_homepage', 'empty', 'wrong_page'}
SECTOR_TERMS = {
    '消费行业': r'消费|食品|饮料|零售|服装|家电',
    '医药/医疗器械行业': r'医药|医疗|制药|生物医',
    '硬科技行业': r'硬科技|半导体|芯片|机器人|集成电路',
    '新能源行业': r'新能源|光伏|锂电|储能|风电',
}
DATE = r'(20\d{2})\s*[年/-]\s*(\d{1,2})\s*[月/-]\s*(\d{1,2})\s*日?'


def dictionary():
    return json.loads(Path(__file__).with_name('company_risk_dictionary.json').read_text(encoding='utf-8'))


def iso_date(value):
    m = re.search(DATE, str(value or ''))
    if not m:
        return None
    try:
        return date(*(int(x) for x in m.groups())).isoformat()
    except ValueError:
        return None


def usable(source):
    meta = get(source, 'source_metadata', {}) or {}
    raw, origin = source_body(source)
    status = str(meta.get('fetch_status') or meta.get('acquisition_status') or '').lower()
    return (origin != 'discovery_summary' and status not in BAD_FETCH
            and meta.get('target_article_matched') is not False
            and not re.search(r'访问验证|安全验证|Access Denied|captcha|网站防火墙', raw, re.I))


def publication_date(source, raw):
    # The publication label in the actual article wins over the index/URL year.
    m = re.search(r'(?:发布时间|发布日期|发布日)\s*[:：]?\s*(' + DATE + ')', raw)
    if m:
        return iso_date(m[1])
    meta = get(source, 'source_metadata', {}) or {}
    return iso_date(meta.get('publication_date') or get(source, 'published_date') or '')


def source_anchor(source, cards):
    url = str(get(source, 'url') or '')
    matches = [c for c in cards.get(url, []) if EID.fullmatch(str(c.get('evidence_id') or ''))]
    # One source may support many atomic facts; none of their model prose is
    # imported here. The card supplies only the archive locator.
    if matches:
        eid = str(matches[0]['evidence_id'])
    elif url and usable(source):
        # The cleaner may omit the entire notice. Recovered original fields
        # still get a deterministic source locator, independent of model prose.
        seed = '\n'.join(re.sub(r'\s+', ' ', str(v or '').strip()) for v in (url, get(source, 'title'), ''))
        eid = 'E-' + hashlib.sha256(seed.encode()).hexdigest()[:12].upper()
    else:
        return None
    return {'source_url': url, 'source_title': str(get(source, 'title') or ''),
            'evidence_id': eid, 'evidence_ids': [eid]}


def filing_cutoff(pages):
    """Use the issuer's actual consolidated balance-sheet date, not FY=Dec31."""
    for page in pages:
        text = page['text']
        heading = re.search(r'合并(?:及(?:母)?公司)?资产负债表|CONSOLIDATED\s+STATEMENT\s+OF\s+FINANCIAL\s+POSITION|CONSOLIDATED(?:\s+AND\s+COMPANY)?\s+BALANCE\s+SHEETS?', text, re.I)
        if not heading:
            continue
        area = text[heading.end():heading.end() + 900]
        if not re.search(r'单位|人民币|流动资产|流動資產|RMB|HK\$|USD|Assets|ASSETS', area):
            continue  # a contents page is not a balance-sheet heading
        # Some issuers put the date before "consolidated and company balance
        # sheets". The nearby native date still binds the statement itself.
        preceding = text[max(0, heading.start() - 100):heading.start()]
        before_dates = list(re.finditer(DATE, preceding))
        chinese = before_dates[-1] if before_dates else re.search(DATE, area)
        if chinese:
            return iso_date(chinese[0])
        english = re.search(r'\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+20\d{2}\b', area, re.I)
        if english:
            return datetime.strptime(english[0], '%d %B %Y').date().isoformat()
    return None


def later_than_research_cutoff(source, as_of):
    if not as_of:
        return False
    raw, _ = source_body(source)
    dates = [publication_date(source, raw), filing_cutoff(document_pages(source))]
    meta = get(source, 'source_metadata', {}) or {}
    dates += [iso_date(r.get('value')) for r in meta.get('visual_reviews', [])
              if r.get('status') == 'reviewed' and r.get('kind') == 'document_signature_date']
    # An exchange URL's later date is a conservative exclusion signal, never
    # presented as a verified publication date in the report.
    if exchange(source):
        url = str(get(source, 'url') or '')
        path_date = re.search(r'/(20\d{2})/(\d{2})(\d{2})/', url)
        if not path_date:
            path_date = re.search(r'/(20\d{2})-(\d{2})-(\d{2})/', url)
        if path_date:
            dates.append(iso_date('-'.join(path_date.groups())))
    return any(d and d > as_of for d in dates)


def subsidiary_relations(target, sources, cards, as_of=None):
    """Read dated issuer subsidiary tables, not a name prefix or co-mention."""
    rows = []
    for source in sources:
        if not usable(source) or not exchange(source) or later_than_research_cutoff(source, as_of):
            continue
        pages = document_pages(source)
        base = source_anchor(source, cards)
        if not base or not issuer_heading(pages, target):
            continue
        period = period_of(source, pages)
        cutoff = filing_cutoff(pages)
        if not cutoff:
            continue
        if as_of and cutoff > as_of:
            continue
        for p in pages:
            t = p['text']
            if not all(x in folded(t) for x in ('在子公司中的权益', '企业集团的构成', '持股比例', '直接', '间接')):
                continue
            for line in t.splitlines():
                m = re.match(r'\s*(' + LEGAL + r')\s*[*＊]?\s+(.+)', line)
                if not m:
                    continue
                tail = re.sub(r'\s+注\s*\d+.*$', '', m[2]).strip()
                pct = re.search(r'\s+(\d{1,3}(?:\.\d+)?|[-—])\s+(\d{1,3}(?:\.\d+)?|[-—])\s*$', tail)
                if not pct:
                    continue
                direct, indirect = pct.groups()
                nature = re.search(r'\s(制造|生产|加工|投资控股|manufacturing|investment holding)\s', ' ' + m[2], re.I)
                values = [float(x) for x in (direct, indirect) if x not in {'-', '—'}]
                if not values or any(x > 100 for x in values) or sum(values) > 100.01:
                    continue
                rows.append({**base, 'kind': 'relationship', 'parent': target,
                             'entity': m[1], 'page': p['page'], 'as_of': cutoff,
                             'direct_pct': direct, 'indirect_pct': indirect,
                             'business_nature': nature[1] if nature else '',
                             'fact': re.sub(r'\s+', ' ', line).strip(),
                             'boundary': '报告截至日的子公司关系；空栏不自动补零，不能证明之后股权未变化。'})
    return rows


def recall_events(source, base):
    """Parse manufacturer / campaign / model groups from the original notice.

    Shared defects after the final manufacturer apply only when the remedy
    explicitly names all manufacturers. Distinct campaign descriptions stay
    local. A plan is never represented as an accident, fine or completed repair.
    """
    raw, _ = source_body(source)
    host = host_of(source)
    if not usable(source) or not (host == 'gov.cn' or host.endswith('.gov.cn')):
        return [], 'not_usable_primary_notice'
    if not re.search(r'备案.{0,12}召回计划|发布.{0,12}召回公告', raw):
        return [], 'no_recall_plan_body'
    publication = publication_date(source, raw)
    if not publication:
        return [], 'publication_date_unbound'
    # Manufacturers must appear in the heading before the legal preamble.
    lead = re.split(r'根据|依据|\n\s*[一二三四五六七八九十]+[、．.]', raw)[0]
    names = re.findall(LEGAL, lead)
    manufacturers = list(dict.fromkeys(n.strip('* •\n ') for n in names))
    if not manufacturers:
        return [], 'manufacturer_unbound'
    sections = re.split(r'(?m)^\s*[一二三四五六七八九十]+[、．.]\s*', raw)
    if len(sections) == 1:
        sections = [raw]
    else:
        sections = sections[1:]
    parsed = []
    shared = re.search(r'(本次召回范围内[^\n]+)', raw)
    for section in sections:
        head = section.splitlines()[0] if section.splitlines() else ''
        owner = next((n for n in manufacturers if folded(head) == folded(n)), None)
        if not owner and len(manufacturers) == 1:
            owner = manufacturers[0]
        if not owner:
            continue
        number = re.search(r'召回编号\s*([A-Za-z]\d{4}[A-Za-z]\d{4}[A-Za-z]?)', section)
        scopes = []
        # DATE contains capture groups; named fields avoid positional guessing.
        pattern = (r'(?P<start>20\d{2}年\s*\d{1,2}月\s*\d{1,2}日)\s*(?:至|到)\s*'
                   r'(?P<end>20\d{2}年\s*\d{1,2}月\s*\d{1,2}日)\s*(?:期间)?生产的\s*'
                   r'(?P<model>[^。；\n]{1,150}?)\s*[，,]\s*共计\s*(?P<quantity>[\d,]+)\s*(?P<unit>辆|台|件)')
        for m in re.finditer(pattern, section):
            start, end = iso_date(m['start']), iso_date(m['end'])
            if re.search(r'20\d{2}年\s*\d{1,2}月', m['model']):
                # Two production periods sharing one total need a different
                # table shape; do not quietly attach their total to one period.
                return [], 'recall_body_requires_manual_scope_review'
            if not start or not end or start > end or end > publication:
                continue
            scopes.append({'production_from': start, 'production_to': end,
                           'product_scope': m['model'].strip(),
                           'reported_quantity': int(m['quantity'].replace(',', '')),
                           'unit': m['unit'], 'evidence_quote': m[0]})
        if not scopes:
            continue
        defect = re.search(r'(本次召回范围内[^\n]+)', section)
        remedy = re.search(re.escape(owner) + r'[^\n]{0,160}?(?:免费|无偿)[^\n]+', section)
        # Shared description follows the last manufacturer's batch. Its
        # free-remedy sentence must explicitly include all named manufacturers.
        shared_remedy = (next((line for line in raw.splitlines()
                              if '免费' in line and all(n in line for n in manufacturers)), '')
                         if len(manufacturers) > 1 else '')
        if not defect and shared and shared_remedy:
            defect_text = shared[1].strip()
        else:
            defect_text = defect[1].strip() if defect else ''
        remedy_text = shared_remedy or (remedy[0].strip() if remedy else '')
        if not defect_text or not remedy_text:
            continue
        effective = re.search(r'自\s*(' + DATE + r')\s*起', section)
        if not effective:
            effective = re.search(r'自\s*(' + DATE + r')\s*起', raw[:raw.find('一、')] if '一、' in raw else raw)
        effective_date = iso_date(effective[1]) if effective else publication if '自即日起' in section else None
        investigation = '在国家市场监督管理总局启动缺陷调查情况下开展' in section
        meta = get(source, 'source_metadata', {}) or {}
        parsed.append({**base, 'kind': 'recall', 'entity': owner,
                       'publication_date': publication, 'effective_date': effective_date,
                       'recall_number': number[1] if number else None, 'scope_parts': scopes,
                       'defect_quote': defect_text, 'remedy_quote': remedy_text,
                       'under_defect_investigation': investigation,
                       'acquisition_method': meta.get('acquisition_method') or 'retrieved_primary_page',
                       'fact': owner + '；' + '；'.join(s['evidence_quote'] for s in scopes) + '；' + defect_text,
                       'closure': '未取得本批次召回完成率、实际事故数及损失核验',
                       'boundary': '召回计划及潜在后果，不等于已发生事故、行政处罚或整改全部完成；跨批次可能重叠，不合计为独立车辆。'})
    return parsed, 'parsed' if parsed else 'recall_body_requires_manual_scope_review'


def _entry(kind, label, record, assessment, followup, *, state='observed_event', priority='专项核查', category=None):
    key = '|'.join(str(record.get(k) or '') for k in ('source_url', 'entity', 'case_description', 'recall_number', 'fact'))
    return {'id': 'R-' + hashlib.sha256((kind + key).encode()).hexdigest()[:12].upper(),
            'kind': kind, 'label': label, 'origin': 'extension',
            'category': category or CATEGORIES[1], 'state': state,
            'fact_record': record, 'assessment': assessment,
            'priority': priority, 'company_severity': '尚待核实集团重大性',
            'score': None, 'followup': followup,
            'evidence_ids': list(record.get('evidence_ids') or [record['evidence_id']])}


def recall_discovery_queries(sources, target, seen=None):
    """Bounded manufacturer searches, derived only from issuer-owned tables.

    A parent's legal name alone misses notices issued to its manufacturers.
    A co-mentioned counterparty or a matching brand prefix is insufficient.
    """
    seen = seen if seen is not None else set()
    if len(seen) >= 4:
        return []
    relations = subsidiary_relations(target, list(sources), defaultdict(list))
    # Names already in retrieved notice headings are relevant candidates, but
    # become searchable subsidiaries only with an independent issuer-table link.
    notice_names = set()
    for source in sources:
        base = source_anchor(source, defaultdict(list))
        if base and usable(source) and '召回' in str(get(source, 'title')):
            events, _ = recall_events(source, base)
            notice_names.update(folded(r['entity']) for r in events)
    ordered = sorted(relations, key=lambda r: (folded(r['entity']) not in notice_names, -int(r['as_of'][:4])))
    candidates = [{'entity': target, 'source_url': '', 'fact': '目标法人'}] + ordered
    queries = []
    for r in candidates:
        key = folded(r['entity'])
        if key in seen:
            continue
        # Non-manufacturing investment vehicles are not selected merely
        # because they occur in the same subsidiary table.
        if (r['entity'] != target and key not in notice_names
                and not re.search(r'制造|生产|加工|manufactur', r.get('business_nature', ''), re.I)):
            continue
        seen.add(key)
        queries.append({'module': TITLE, 'query': '"' + r['entity'] + '" 召回 缺陷调查 整改 召回编号',
                        'search_tier': 'authority_first', 'include_domains': ['samr.gov.cn', 'samrdprc.org.cn'],
                        'evidence_scope': 'target_direct' if r['entity'] == target else 'related_entity_context',
                        'recall_entity': r['entity'], 'recall_relationship_source': r['source_url']})
        if len(seen) >= 4:
            break
    return queries


def _judicial_entries(records):
    selected = {}
    # Prefer the more recent original report for the same exact description;
    # parallel claims/subjects are not merged merely because they share an EID.
    for r in records:
        if r.get('kind') not in {'disclosed_case', 'labour'}:
            continue
        description = re.sub(r'^\s*\d+[.、．]\s*', '', str(r.get('case_description') or ''))
        key = (r['kind'], folded(r.get('case_number') or description), str(r.get('amount') or ''))
        if key not in selected or record_rank(r) > record_rank(selected[key]):
            selected[key] = r
    entries = []
    for r in selected.values():
        if r['kind'] == 'labour':
            entries.append(_entry('labour_procedure', '用工争议程序', r,
                '当事人角色及开庭/送达公告已披露；存在应诉核查事项，尚不能据公告认定违法用工、败诉或赔偿责任。',
                '按案号核对请求金额、实际用工主体、送达和后续裁决/履行。', state='procedure_pending'))
            continue
        text = str(r.get('result') or '') + str(r.get('execution') or '')
        if re.search(r'暂无财产可供执行|无可供执行财产|未发现可供执行财产', text):
            entries.append(_entry('recovery_obstacle', '案件执行与回收障碍', r,
                '原件披露具体案件存在财产执行障碍，相关判决回收具有不确定性；追偿方不据此变成失信被执行人。需核对障碍所指主体、可回收金额及最新进度。',
                '核对执行案卷、对方资产及回款、坏账准备和后续恢复执行；依涉案主体与金额评估集团重要性。', priority='优先核对回收'))
        elif re.search(r'执行中|审理|仲裁|状书往来', str(r.get('stage')) + text):
            entries.append(_entry('case_pending', '未结案件与程序进展', r,
                '原件列明该案尚处程序或执行阶段；诉讼请求、判决金额和执行回款应分开，不能直接当作损失或集团整体风险等级。',
                '核对最新程序/回款、金额币种与当事人责任；不与其他时期同案重复累计。', state='procedure_pending'))
    return entries


def record_rank(record):
    explicit = iso_date(record.get('as_of'))
    if explicit:
        return explicit
    year = re.search(r'20\d{2}', str(record.get('period') or ''))
    if year:
        return year[0] + ('-06-30' if re.search(r'中期|半年度', str(record.get('period'))) else '-12-31')
    return ''


def checklist_requirements(item):
    """Minimum corroboration; template labels are not matching keywords."""
    ident = item['id']
    if ident in {'ORG-08', 'ORG-09'}:
        return '具体岗位胜任、任用程序及关联人干预证据；年龄/亲属关系本身不足以认定能力或任人唯亲。'
    if ident in {'ORG-11', 'ORG-15', 'ORG-16', 'ORG-18', 'ORG-20'}:
        return '员工/离职口径、主动被动及岗位分层、原因调查和同口径基准；净减员、口号或自报满意度不能替代。'
    if ident in {'OPS-03', 'OPS-04', 'OPS-05', 'OPS-06', 'OPS-11'}:
        return '同期间渠道库存、终端销售/退货、回款、客户或用户去重明细及收入确认；目标/批发量不能证明压货或刷单。'
    if ident in {'OPS-01', 'OPS-02', 'OPS-08', 'CON-01'}:
        return '可定位的审计/监管认定或交易凭证矛盾及主体、期间、金额；媒体币种错字和资料缺失不能证明企业造假。'
    if ident in {'OPS-07', 'OPS-09', 'OPS-10', 'OPS-12', 'OPS-19', 'TEC-02', 'TEC-03'}:
        return '具体型号/技术里程碑、量产或第三方测试与承诺对照；宣传图、研发金额、渗透空间不能证明参数造假或壁垒高低。'
    if ident == 'OPS-22':
        return '实际用工主体、请求/裁决、履行情况及覆盖期；劳动仲裁开庭送达不等于违法或败诉。'
    if ident == 'OPS-24':
        return '同主体同期间现金流、受限现金、债务到期及授信可用性；大额支出、未付账项或融资史不足以单独判违约。'
    if item['sector']:
        return '已核实的相应业务范围、具体事件及对应经营/技术/合规原件；行业标签不能证明该词条已经发生。'
    if ident.startswith('ORG-'):
        return '具体决策/授权、执行结果、岗位职责、制度实际运行及多方核验；创始人主导、业务数量或制度存在不能单独证明。'
    return '对应主体、期间和具体事件的原始经营/监管/司法材料及后续处理；不能仅凭关键词或信息缺口认定发生。'


def build_risk_register(cleaned, target, sources=None, *, industry='', intake=None, query_attempts=None, displayed_judicial=None):
    sources = list(sources or [])
    intake = intake or {}
    as_of = iso_date(intake.get('as_of_date'))
    cards = defaultdict(list)
    for c in cleaned.get('facts') or []:
        if isinstance(c, dict):
            cards[str(c.get('source_url') or '')].append(c)
    anchor_cards = []
    for s in sources:
        if not cards[str(get(s, 'url') or '')]:
            anchor = source_anchor(s, cards)
            if anchor:
                anchor_cards.append({**anchor, 'fact': '原件定位，具体主体/事件由原文解析后验证。'})
    cleaned = {**cleaned, 'facts': list(cleaned.get('facts') or []) + anchor_cards}
    relations = subsidiary_relations(target, sources, cards, as_of)
    by_child = defaultdict(list)
    for r in relations:
        by_child[folded(r['entity'])].append(r)
    entries, facts, coverage = [], [], []
    counts = Counter()
    for s in sources:
        raw, _ = source_body(s)
        if '召回' not in (str(get(s, 'title') or '') + raw):
            continue
        base = source_anchor(s, cards)
        if not base:
            counts['recall_without_archive_anchor'] += 1
            coverage.append({'source_url': str(get(s, 'url') or ''),
                             'source_title': str(get(s, 'title') or ''),
                             'kind': 'recall_query',
                             'state': 'not_usable_primary_notice' if not usable(s) else 'archive_anchor_missing',
                             'fetch_status': (get(s, 'source_metadata', {}) or {}).get('fetch_status'),
                             'evidence_ids': [],
                             'fact': '来源未取得有效原文/归档定位；不能证明没有召回。'})
            continue
        events, state = recall_events(s, base)
        coverage.append({**base, 'kind': 'recall_query', 'state': state,
                         'fetch_status': (get(s, 'source_metadata', {}) or {}).get('fetch_status'),
                         'fact': '本条是来源获取/解析状态，不代表全部召回记录或无召回。'})
        for r in events:
            if as_of and r['publication_date'] > as_of:
                counts['future_recall_notice'] += 1
                continue
            direct = folded(r['entity']) == folded(target)
            links = by_child[folded(r['entity'])]
            if not direct and not links:
                counts['unproven_manufacturer_relationship'] += 1
                continue
            if links:
                preceding = [x for x in links if x['as_of'] <= r['publication_date']]
                link = max(preceding, key=lambda x: x['as_of']) if preceding else min(links, key=lambda x: x['as_of'])
                r['relationship'] = link
                r['relationship_timing'] = '公告前截至日关系' if preceding else '事后报告截至日关系，事件当日关系未证'
                r['evidence_ids'] = list(dict.fromkeys(r['evidence_ids'] + link['evidence_ids']))
                facts.append(link)
            r['subject_scope'] = '目标法人直接事件' if direct else '有截至日关系证据的制造主体；事件时股权和母公司责任另核'
            facts.append(r)
            entries.append(_entry('recall', '产品质量与安全召回', r,
                '主管部门已公告该生产商召回及潜在安全后果，应优先跟踪整改覆盖和有效性。'
                + ('公告明确在缺陷调查下开展，不能省略监管调查背景。' if r['under_defect_investigation'] else '')
                + '潜在后果按原文保留；公告不能证明已有事故、罚款或集团已发生同额损失。',
                '按召回编号/车型及VIN核验完成率、复发、事故与成本；核对当前制造主体关系和集团实际承担金额。',
                priority='优先核对安全整改'))
    # Rebuild from source documents at the risk stage; do not trust stale
    # project attributes or the first 60 cleaned claims.
    admissible = [s for s in sources if usable(s) and not later_than_research_cutoff(s, as_of)]
    counts['sources_after_research_cutoff'] = sum(later_than_research_cutoff(s, as_of) for s in sources)
    judicial = build_judicial_package(cleaned, target, admissible, query_attempts=query_attempts)
    diligence = build_diligence_package(cleaned, target, admissible, prior_packages={'judicial': judicial}, intake=intake)
    people = build_people_package(cleaned, target, admissible)
    entries += _judicial_entries(judicial['facts'])
    context = []
    context_seen = {}
    # These disclosures expose a mechanism to examine, but do not establish a
    # default or an impairment. Keep unlike bases separate in the risk register.
    context_kinds = {'purchase_accounting', 'accounting_consideration', 'payment_pending', 'related_funding', 'pro_forma'}
    for r in diligence['facts']:
        if r['kind'] not in context_kinds:
            continue
        key = (r['source_url'], r.get('entity'), r['kind'], folded(r.get('fact')))
        if key in context_seen:
            old = context_seen[key]
            old['pages'] = sorted(set(old.get('pages', [old.get('page')]) + [r.get('page')]) - {None})
            continue
        clone = dict(r)
        context_seen[key] = clone
        context.append(clone)
    for kind, label, assessment, followup in (
        ('purchase_accounting', '并购商誉与估值敏感性', '原件列示购买会计/商誉事项，未来回收受现金流和估值假设影响；减值测试、历史确认或商誉比例不等于已经减值。', '按当前现金产生单位、账面值、测试假设和敏感性核对；不得跨主体或拿年度与半年度增速直接定级。'),
        ('payment_pending', '未付款项及流动性核查', '原件存在未付/未使用披露；是否逾期、原因及后续兑付仍须逐项核实，不能仅凭未付字样认定违约。', '核对原文原因、到期义务、后续付款和现金流覆盖；应收未提示付款与发行人无力付款分开。'),
        ('related_funding', '关联资金与偿还安排', '原件披露具体关联融资；借款人、出借人、币种、余额/额度和时期应逐笔核对，关联往来本身不证明挪用或隐性关联。', '核对实际借款主体、用途、资金流水、定价/审批和还款；备考授信不当实际提款。'),
    ):
        rows = [r for r in context if r['kind'] == kind]
        if rows:
            # One bounded assessment per mechanism, all distinct supporting
            # observations retained in the structured packet, no paragraph spam.
            representative = max(rows, key=lambda r: (record_rank(r), '年度报告' in str(r.get('period'))))
            entry = _entry(kind, label, representative, assessment, followup, state='indicator_to_verify')
            entry['supporting_records'] = rows
            entry['evidence_ids'] = sorted({e for r in rows for e in r.get('evidence_ids', [])})
            entries.append(entry)
    for e in entries:
        facts.append(e['fact_record'])
        facts.extend(e.get('supporting_records', []))
    # Workforce evidence supplies context to questions, not a turnover-risk
    # verdict without a comparable denominator and benchmark.
    people_context = [r for r in people['facts'] if r['kind'] in {'turnover', 'training', 'workforce'}]
    facts += people_context
    scope = str(industry or intake.get('industry') or '')
    active = {sector for sector, pattern in SECTOR_TERMS.items() if re.search(pattern, scope)}
    template = dictionary()
    checklist = []
    for item in template['items']:
        in_scope = not item['sector'] or item['sector'] in active
        matching = []
        if item['id'] == 'OPS-22':
            matching = [e['id'] for e in entries if e['kind'] == 'labour_procedure']
        if item['id'] == 'CON-07' and in_scope:
            matching = [e['id'] for e in entries if e['kind'] == 'recall']
        state = 'requires_event_evidence' if in_scope else 'outside_declared_sector_scope'
        if matching:
            state = 'linked_event_requires_specific_judgment'
        checklist.append({**item, 'state': state, 'entry_ids': matching,
                          'required_evidence': checklist_requirements(item),
                          'boundary': '未激活的行业词条不代表集团不存在该业务；已证实的关联主体事件仍单列。' if not in_scope else '尚不足以肯定或排除该模板描述；不默认计分。'})
    unique = {}
    for r in facts:
        key = (r.get('source_url'), r.get('kind'), r.get('page'), r.get('fact'))
        unique.setdefault(key, r)
    facts = list(unique.values())
    entries = list({e['id']: e for e in entries}.values())
    attach_case_display_references(entries, displayed_judicial)
    gaps = [
        '召回检索和来源解析并非全量覆盖；403、跳转首页、空结果不能证明没有记录。',
        '已披露的具体风险事项不等于集团重大性已量化；须核对实际敞口、整改、发生概率及当前状态。',
        '管理、渠道及技术等模板问题需相应事件和可比证据；不由创始人主导、资料缺失、销售目标或宣传内容直接定级。',
    ]
    dimensions = []
    for category in CATEGORIES:
        group = [e for e in entries if e['category'] == category]
        dimensions.append({'name': category, 'score': None, 'level': 'unknown',
                           'reason': '；'.join(dict.fromkeys(e['label'] + '：' + e['assessment'] for e in group)) if group else '对应词条尚缺足以作肯定/排除判断的具体事件证据；需要按核查目录继续验证。',
                           'observed_entry_ids': [e['id'] for e in group],
                           'evidence_ids': sorted({x for e in group for x in e['evidence_ids']})})
    return {'version': VERSION, 'target_name': target, 'as_of_date': as_of,
            'overall_score': None, 'risk_level': 'unknown',
            'scoring_basis': '不对资料缺口、来源数量或模型分取平均；已核事项及其影响单列。集团风险数值须有重大性和概率依据。',
            'dimensions': dimensions, 'key_risks': list(dict.fromkeys(e['label'] + '：' + e['assessment'] for e in entries)),
            'unknowns': gaps, 'recommended_followups': list(dict.fromkeys(e['followup'] for e in entries)),
            'entries': entries, 'facts': facts, 'checklist': checklist, 'coverage': coverage,
            'query_attempts': query_attempts or [], 'active_template_sectors': sorted(active),
            'template_reference': template['template_reference'], 'template_sha256': template['template_sha256'],
            'information_gaps': gaps,
            'diagnostic': {'template_items': len(checklist), 'category_counts': dict(Counter(i['category'] for i in checklist)),
                           'checklist_states': dict(Counter(i['state'] for i in checklist)),
                           'entries': len(entries), 'by_kind': dict(Counter(e['kind'] for e in entries)),
                           'dated_subsidiary_relations': len(relations), 'filters': dict(counts)}}


def _recall_lines(group,display_context=None):
    r = group[0]['fact_record']
    lines = [r['publication_date'] + '公告；实施日：' + (r['effective_date'] or '待核对') + '。' + refs(r), '']
    rows = []
    for e in group:
        record = e['fact_record']
        for s in record['scope_parts']:
            rows.append([record['entity'], record['recall_number'] or '本原公告未列编号',
                         s['production_from'] + '至' + s['production_to'], s['product_scope'],
                         str(s['reported_quantity']) + s['unit']])
    lines += _table(['生产商', '召回编号', '生产起止期', '车型范围', '公告数量'], rows)
    lines += ['', '潜在缺陷及后果（原文）：' + r['defect_quote'], '', '整改安排（原文）：' + r['remedy_quote'], '']
    seen = set()
    for e in group:
        record = e['fact_record']
        link = record.get('relationship')
        if link and (link['entity'], link['as_of']) not in seen:
            seen.add((link['entity'], link['as_of']))
            signature=json.dumps([link,record['relationship_timing']],ensure_ascii=False,sort_keys=True)
            shown=(display_context or {}).get('relationships',set())
            if signature in shown:
                lines+=['归属核对：'+link['entity']+'；'+link['as_of']+'，物理页'+str(link['page'])
                        +'；持股及责任边界同本节前项相同原件。'+refs(link),'']
                continue
            if display_context is not None:display_context.setdefault('relationships',set()).add(signature)
            lines += ['归属依据：' + link['entity'] + '在' + link['as_of'] + '子公司表的直接/间接持股列分别为'
                      + link['direct_pct'] + '/' + link['indirect_pct'] + '；物理页' + str(link['page'])
                      + '。' + refs(link) + record['relationship_timing'] + '；该截至日关系不证明公告日股权未变化，也不直接确认母公司法律责任。', '']
    if display_context is None or r['boundary'] not in display_context.setdefault('boundaries',set()):
        lines += [r['boundary'],'']
        if display_context is not None:display_context['boundaries'].add(r['boundary'])
    return lines


def render_risk_register(p):
    lines = ['## 11. ' + TITLE, '',
             '风险识别按模板的组织与管理、业务与运营、行业特殊风险三类组织。模板词条用于逐项核查，不能直接套作企业事实；产品召回、具体诉讼和并购资金核查作为扩展事项明确列示。', '',
             '已取得的原件支持以下具体事项及有边界的影响判断。其核查优先级与公司整体风险等级分开：尚未量化的集团重大性保留待核验，不将未取得资料当作低风险，也不按模型评分求平均。', '']
    for category in CATEGORIES:
        lines += ['### ' + category, '']
        group = [e for e in p['entries'] if e['category'] == category]
        if not group:
            lines += ['该类尚未形成足以支持模板负面描述的具体事件判断。应依据对应核查目录补证，当前不能据此排除风险。', '']
            continue
        rendered_recalls = set()
        display_context={};followup_origins={}
        for e in group:
            r = e['fact_record']
            if e['kind'] == 'recall':
                key = (r['source_url'], r['defect_quote'], r['remedy_quote'])
                if key in rendered_recalls:
                    continue
                rendered_recalls.add(key)
            lines += ['#### ' + e['label'] + '（扩展核查事项）', '']
            if e['kind'] == 'recall':
                peers = [x for x in group if x['kind'] == 'recall' and
                         (x['fact_record']['source_url'], x['fact_record']['defect_quote'], x['fact_record']['remedy_quote']) == key]
                lines += _recall_lines(peers,display_context)
            else:
                records = e.get('supporting_records') or [r]
                if e.get('supporting_records'):
                    records = _context_sample(records)
                    lines += ['下表选列不同来源、时期的关键原文；完整记录见风险登记附件，资金及购买会计明细接续第十章，不跨笔、跨币种累计。', '']
                lines.extend(_table(['主体/事项', '原件时期与定位', '已核披露'],
                    [[str(x.get('entity') or x.get('case_description') or x.get('case_number') or p['target_name']),
                      str(x.get('period') or x.get('date') or '按原件') + ('；物理页' + str(x['page']) if x.get('page') else '') + refs(x),
                      _display_fact(x)] for x in records]))
                lines += ['']
            followup=e['followup']
            if e['kind']=='recall':
                signature=(followup,e['priority'],e['company_severity'])
                if signature in followup_origins:
                    followup='核验要求同本节'+followup_origins[signature]+'公告召回项；按本批次编号/车型及VIN分别核对整改与实际成本。'
                else:followup_origins[signature]=r['publication_date']
            lines += ['判断：' + e['assessment'], '', '跟进：' + followup + ' 核查顺序：' + e['priority'] + '；' + e['company_severity'] + '。', '']
    turnover = [r for r in p['facts'] if r['kind'] == 'turnover']
    if turnover:
        lines += ['### 人员指标的解释边界', '',
                  '已取得员工流失率披露，但不同期间、主动/被动及公式分母须按第八章核对。净人数变化不等于流失或裁员，未有可比基准不能认定高流失。' + combined_refs(turnover[:2]), '']
    counts = p['diagnostic']['checklist_states']
    state_labels = {'requires_event_evidence': '需要具体事件证据',
                    'outside_declared_sector_scope': '不在当前声明行业核查范围',
                    'linked_event_requires_specific_judgment': '已有相关事项，须按该词条进一步核对'}
    lines += ['### 模板核查覆盖与判断缺口', '',
              '75个原始词条已逐项建立核查状态和所需材料；当前行业词条范围：' + ('、'.join(p['active_template_sectors']) or '尚待明确') + '。', '',
              '核查目录：' + '；'.join(state_labels.get(k, k) + ' ' + str(v) + '项' for k, v in counts.items()) + '。此处统计是核查覆盖状态，不是风险发生数或企业质量评分。', '',
              '尚不能仅凭创始人主导、年龄亲属、业务多元、销量目标、研报预测或技术宣传推定治理失效、压货、造假及商誉减值。监管交流案例也不能替代审查结论。具体判断需补足对应原件和同口径对照。', '',
              '当前召回/司法材料的获取范围和平台权限仍有限；未接纳或未检索到的记录不能当作全时段无风险证明。完整75项核查目录及逐项取证要求保留在结构化风险登记附件。']
    return '\n'.join(lines).strip()


def attach_case_display_references(entries, displayed_judicial):
    shown={displayed_case_key(r) for r in (displayed_judicial or {}).get('facts',[])
           if r.get('kind')=='disclosed_case'}
    for entry in entries:
        r=entry['fact_record']
        if r.get('kind')=='disclosed_case' and displayed_case_key(r) in shown:
            entry['fact_record']={**r,'display_reference':{'chapter':9,'section':'发行人及专项法律文件列示事项'}}


def _display_fact(record):
    if record.get('kind')=='disclosed_case' and (record.get('display_reference') or {}).get('chapter')==9:
        return ('原件案件阶段：'+record.get('stage','待核')+'；执行披露：'+record.get('execution','待核')
                +'；涉案金额字段：'+record.get('amount','待核')+'；判决主文及诉讼费用详见第九章同事项。')
    if record.get('kind') == 'labour':
        return (record.get('case_number', '') + '；目标主体角色：' + record.get('role', '待核')
                + '；' + record.get('stage', '') + '；' + record.get('amount', '金额待核'))
    fact = str(record.get('fact') or '').replace('|', '／').replace('\n', ' ')
    carrying = re.search(r'As at\s+\d{1,2}\s+\w+\s+20\d{2},?\s+the net carrying amount of goodwill[^.]+\.', fact, re.I)
    if carrying:
        return carrying[0] + '（期末账面金额，不能当作当年减值金额。）'
    return fact


def _context_sample(records, limit=3):
    selected, seen = [], set()
    for r in sorted(records, key=lambda r: (record_rank(r), '年度报告' in str(r.get('period'))), reverse=True):
        key = (r['source_url'], r.get('period'))
        if key in seen:
            continue
        seen.add(key)
        selected.append(r)
        if len(selected) >= limit:
            break
    return selected


def risk_register_errors(text, p):
    errors = []
    if len(p.get('checklist', [])) != 75 or len({i['id'] for i in p.get('checklist', [])}) != 75:
        errors.append('风险字典75项覆盖不完整')
    if not p.get('entries'):
        errors.append('尚未形成具体可追溯风险事项，需要补充原件核查')
    allowed = {e for r in p.get('facts', []) for e in r.get('evidence_ids', [])}
    if set(cited_evidence_ids(text)) - allowed:
        errors.append('出现未进入风险原件包的证据编号')
    for e in p.get('entries', []):
        if not e['evidence_ids'] or not e.get('assessment') or not e.get('followup'):
            errors.append('风险事项缺少原件引用/判断/后续核查')
    return list(dict.fromkeys(errors))
