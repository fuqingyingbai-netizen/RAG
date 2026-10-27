"""Chapter 2: field-level evidence, dated ownership and explicit relationships.

Facts are rendered deterministically. The workbook's C3 is a style example,
not evidence that shareholders agree or that governance is stable.
"""
import json
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlparse

from .report_prompts import _company_fact_has_trusted_target_anchor
from .company_text import match_compact, issuer_anchor
from .company_financial_statements import fiscal_report_period,quarter_report_period

TITLE = "主体工商基本信息核查股东关系与治理底盘"
HEADINGS = ("主体工商信息表", "股权与治理信息表", "股东/实控人/关联方关系网图", "治理底盘判断")
VERSION = "company-governance-v6-complete-multiline-registry-records"
EID = re.compile(r"E-[A-Z0-9-]{6,}", re.I)


def cited_evidence_ids(text):
    """Citation syntax, not words such as E-learning in a literal quote."""
    return re.findall(r'[\[［]('+EID.pattern+r')[\]］]',str(text or ''),re.I)


MISSING = {"", "-", "--", "待查", "待核验", "暂无", "暂无数据", "未披露", "null", "none", "n/a"}
ALIASES = {
    "企业名称": ("企业名称", "公司名称", "主体名称", "companyName", "company_name", "Name", "name"),
    "统一社会信用代码": ("统一社会信用代码", "信用代码", "creditCode", "CreditCode", "credit_code"),
    "成立日期": ("成立日期", "成立时间", "establishDate", "estiblishTime", "StartDate"),
    "注册资本": ("注册资本", "注册资金", "regCapital", "RegistCapi"),
    "实缴资本": ("实缴资本", "实收资本", "actualCapital", "RecCap"),
    "法定代表人": ("法定代表人", "法人代表", "legalPersonName", "OperName"),
    "登记状态": ("登记状态", "经营状态", "regStatus", "Status"),
    "企业类型": ("企业类型", "公司类型", "companyOrgType", "EconKind"),
    "注册地址": ("注册地址", "住所", "regLocation", "Address"),
    "营业期限": ("营业期限", "经营期限", "operatingPeriod"),
    "经营范围": ("经营范围", "businessScope", "Scope"),
    "人员规模": ("人员规模", "员工人数", "staffNumRange"),
    "参保人数": ("参保人数", "socialStaffNum"),
    "实际控制人": ("实际控制人", "actualController"),
    "数据日期": ("数据日期", "数据基准日", "截至日期", "截止日期", "as_of_date", "data_date"),
}
SHARE_NAMES = ("股东名称", "股东", "投资人名称", "shareholderName", "StockName")
RATIOS = ("持股比例", "出资比例", "持股比例（%）", "持股比例(%)", "stockPercent", "StockPercent", "ratio")
PEOPLE = ("姓名", "人员姓名", "personName", "Name")
ROLES = ("职务", "职位", "position", "Job")


def get(obj, key, default=""):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def compact(value):
    return re.sub(r"\s+", "", str(value or "")).casefold()


def present(value):
    return value is not None and str(value).strip().casefold() not in MISSING


def pick(row, keys):
    return next((str(row[k]).strip() for k in keys if k in row and present(row[k]) and not isinstance(row[k], (dict, list))), "")


def _registry_subject_text(content, target=''):
    """Keep explicit legal-subject records separate, including PDF subsidiaries.

    A repeated issuer page header cannot reset a subsidiary's field block.
    Shareholder/person/product names are not the record's legal subject.
    """
    label = re.compile(r'(?<![A-Za-z\u4e00-\u9fff])'
        r'(?:(?:全资|控股)?子公司名称|企业名称|公司名称|主体名称|中文名称|发行人名称|名称|companyName|company_name|Name)'
        r'[ \t]*(?:[：:]|\|)[ \t]*(?P<value>[^\n|]+)',re.I)
    legal = re.compile(r'^[ \t]*(?P<name>[^：:，,；;\n|]{2,120}(?:股份有限公司|有限责任公司|有限公司|股份公司|分公司|'
        r'合伙企业(?:[（(]有限合伙[）)])?|\bLimited\b|\bLtd\.?|\bInc\.?|\bLLC\b|\bplc\b|\bCorporation\b))',re.I)
    field_label = re.compile('|'.join(re.escape(a)+r'[ \t]*[：:]' for aliases in ALIASES.values() for a in aliases))
    anchors=[]
    for match in label.finditer(content):
        value=field_label.split(match['value'],maxsplit=1)[0].strip(' \t，,。；;')
        if target and compact(value)==compact(target):
            name=target
        else:
            owner=legal.match(value)
            if not owner:continue
            name=owner['name'].strip()
        start=match.start()
        # A compact field record may put its data date before its legal name.
        # Extend only over schema rows, never over a prospectus narrative.
        separator=content.rfind('\n\n',0,start)
        block_start=separator+2 if separator>=0 else 0
        prefix=content[block_start:start]
        if not any(block_start<=old[0]<start for old in anchors) and all(
                not line.strip() or line.strip().startswith(('|','#')) or field_label.match(line.strip())
                for line in prefix.splitlines()):
            start=block_start
        anchors.append((start,name))
    # A profile can put its named heading above 工商信息 and repeat the
    # explicit 主体名称 only in a later module. Bind that actual field block,
    # without borrowing the leading search/SEO summary or a PDF page header.
    if target:
        named_heading=re.compile(r'(?m)^[ \t]*'+re.escape(target)+r'[ \t]*$')
        for header in re.finditer(r'(?m)^[ \t]*(?:工商信息|企业基本信息|公司基本信息|基本登记信息)'
                                  r'(?:[ \t]+以上数据来源于互联网)?[ \t]*$',content):
            if named_heading.search(content[:header.start()]) and not any(
                    start<header.start() and compact(name)!=compact(target) for start,name in anchors):
                anchors.append((header.start(),target))
        anchors.sort(key=lambda item:item[0])
    if not anchors:
        return content,''
    target=target or anchors[0][1]
    retained=[]
    for i,(start,name) in enumerate(anchors):
        if compact(name)==compact(target):
            end=anchors[i+1][0] if i+1<len(anchors) else len(content)
            retained.append(content[start:end])
    return '\n'.join(retained),target if retained else ''


def read_fields(content: str, target: str=''):
    """Keep header meanings, names, units and row boundaries across providers."""
    fields, tables = {}, []
    try:
        obj = json.loads(content.strip().removeprefix("```json").removesuffix("```").strip())
    except (ValueError, TypeError):
        obj = None
    if isinstance(obj, dict):
        for _ in range(5):
            child = next((obj[k] for k in ("data", "result", "Result", "Data", "body") if isinstance(obj.get(k), dict)), None)
            if child is None:
                break
            obj = child
        # Only the envelope's own legal name identifies the target. A name in
        # a nested shareholder/subsidiary array cannot authenticate the source.
        fields = {key: pick(obj, aliases) for key, aliases in ALIASES.items()}
        def walk(value, section=''):
            if isinstance(value, list):
                tables.extend({**x,'_section':section} for x in value if isinstance(x, dict))
                for x in value:
                    walk(x,section)
            elif isinstance(value, dict):
                for key,x in value.items():
                    if isinstance(x, (dict, list)):
                        walk(x,str(key))
        walk(obj)
        return fields, tables
    content,subject=_registry_subject_text(content,target)
    # The name comes from an explicit original field, never a query echo.
    if subject:fields['企业名称']=subject
    blocks = re.split(r"(?m)(^#{1,6} .*$)|\n\s*\n", content)
    section=''
    for block in blocks:
        if not block:
            continue
        if re.match(r'^#{1,6} ',block):
            section=block
            continue
        rows = [[c.strip() for c in line.strip().strip("|").split("|")]
                for line in block.splitlines() if line.strip().startswith("|")]
        if not rows:
            continue
        separator = lambda row: all(re.fullmatch(r"[-: ]+", c or " ") for c in row)
        header = rows[0] if len(rows)>1 and separator(rows[1]) else []
        data = rows[2:] if header else rows
        for row in data:
            if separator(row):
                continue
            if len(row)==2:
                for name, aliases in ALIASES.items():
                    if row[0] in aliases and present(row[1]):
                        fields.setdefault(name, row[1])
            if header and len(row)==len(header) and any(x in header for x in (*SHARE_NAMES, *PEOPLE, "变更日期", "变更时间")):
                tables.append({**dict(zip(header, row)),'_section':section})
    # Plain key:value records are common in official pages and MCP responses.
    known = {a:name for name,aliases in ALIASES.items() for a in aliases}
    pattern = '|'.join(re.escape(k) for k in sorted(known,key=len,reverse=True))
    lines=content.splitlines(keepends=True)
    for line_number,original_line in enumerate(lines):
        line=original_line.rstrip('\r\n')
        matches=list(re.finditer(r'('+pattern+r')\s*[：:]\s*',line)) if '|' not in line else []
        for i,match in enumerate(matches):
            value=line[match.end():matches[i+1].start() if i+1<len(matches) else len(line)]
            if i+1==len(matches) and known[match[1]] in {'经营范围','成立日期'}:
                # Native prospectus fields wrap over physical lines. Keep
                # the original continuation, but never cross a new field,
                # section, table, blank separator or page-number artifact.
                continuation=[]
                for following in lines[line_number+1:]:
                    candidate=following.strip()
                    if known[match[1]]=='成立日期' and (re.fullmatch(r'\d{4}[-./年]\d{1,2}[-./月]\d{1,2}日?',value.strip()) or
                            not re.match(r'(?:(?:19|20)\d{2}|\d{1,2}[月日]|整体|改制|设立|变更|股份公司|股份有限公司|有限责任公司|有限公司)',candidate)):
                        break
                    if (not candidate or candidate.startswith(('|','#')) or
                            re.match(r'(?:[一二三四五六七八九十]+[、．.]|[（(][一二三四五六七八九十]+[）)])',candidate) or
                            re.fullmatch(r'\d+(?:[-/]\d+)*',candidate) or
                            re.match(r'[\u4e00-\u9fffA-Za-z_（）() ]{1,20}\s*[：:]',candidate)):
                        break
                    continuation.append(following)
                if continuation:value+=original_line[len(line):]+''.join(continuation)
            value=value.strip()
            if present(value):
                fields.setdefault(known[match[1]],value)
    return fields, tables


def _ratio(row):
    value = pick(row, RATIOS)
    if not value:
        return ""
    if re.fullmatch(r"\d+(?:\.\d+)?%", value):
        return value
    if re.fullmatch(r"\d+(?:\.\d+)?", value) and any(k in row for k in ("持股比例（%）", "持股比例(%)")):
        return value + "%"
    # A raw decimal without a stated scale must not be converted to a percent.
    return value + "（源字段未载百分比单位）"


def _historical(text):
    return bool(re.search(r"设立时|发起人|历史股东|变更前|原股东|historical|history|founder", text,re.I))


def _primary_filing(source, target):
    host=(urlparse(str(get(source,'url'))).hostname or '').lower()
    official=any(host==d or host.endswith('.'+d) for d in ('szse.cn','sse.com.cn','cninfo.com.cn','hkexnews.hk'))
    if not official:return False
    head=match_compact(str(get(source,'content'))[:2400])
    # A parent's mention inside a subsidiary filing is insufficient. Require
    # the issuer's full name immediately followed by its reporting period.
    normal=bool(re.search(re.escape(match_compact(target))+r'20\d{2}年(?:年度|半年度|第[一三]季度)报告',head))
    fiscal=fiscal_report_period(str(get(source,'content'))[:6500])
    return official and (normal or bool(fiscal and issuer_anchor(str(get(source,'content'))[:6500],target)['matched']) or bool(quarter_report_period(str(get(source,'content')),target)))


def _filing_period(source):
    text=match_compact(str(get(source,'title'))+' '+str(get(source,'content'))[:2400])
    m=re.search(r'20\d{2}年(?:半年度|年度|第一季度|第三季度)报告',text)
    if m:return m[0]
    fiscal=fiscal_report_period(str(get(source,'title'))+' '+str(get(source,'content'))[:6500])
    quarter=quarter_report_period(str(get(source,'content')))
    return fiscal['period'] if fiscal else quarter['period'] if quarter else ''


def _period_rank(value):
    year=re.search(r'20\d{2}',value)
    return (int(year[0]) if year else 0,
            6 if '半年度' in value else 1 if '第一季度' in value else 9 if '第三季度' in value else 12)


def _filing_claims(source):
    """Recover literal declarations and completed events, not charter rules."""
    raw=re.sub(r'--- PDF page \d+ ---',' ',str(get(source,'content')))
    text=re.sub(r'\s+','',raw)
    declarations=[]
    pattern=r'(?:^|[。；:：|]|主要职业及职务)(?P<claim>(?:本公司|本集团|公司)(?:的)?(?:控股股东(?:和|及))?实际控制人为[^。；]{2,110}[。；])'
    for m in re.finditer(pattern,text):
        quote=m['claim']
        if not re.search(r'可能|应当|候选|拟|担任本公司|与本公司无关',quote):
            declarations.append(quote)
    for m in re.finditer(r'(?:^|[。；:：|]|主要职业及职务)(?P<claim>(?:本公司|本集团|公司)(?:无(?:控股股东(?:和|及))?实际控制人|无控股股东[，,]无实际控制人)[。；])',text):
        declarations.append(m['claim'])
    events=[]
    for sentence in re.split(r'(?<=[。！？])',text):
        if not 25<=len(sentence)<=450:
            continue
        if not re.search(r'注销|减少注册资本|注册资本由|注册资本从|完成.{0,12}减资',sentence):
            continue
        if not re.search(r'20\d{2}',sentence) or re.search(r'应当|可以|不得|有权|若|假设|拟|计划|未完成|尚未|尚待|预计|将于|发生以下|详情请见|公告编号',sentence):
            continue
        if not re.search(r'完成|已|由[^。]{2,80}(?:增至|减至|变更为)',sentence):
            continue
        dates=re.findall(r'(20\d{2})年(\d{1,2})月(\d{1,2})日',sentence)
        date=''
        if dates:
            y,m,d=dates[-1]
            date=f'{y}-{m.zfill(2)}-{d.zfill(2)}'
        events.append((sentence,date))
    return list(dict.fromkeys(declarations)),events


def _controller_entity(value):
    value=re.sub(r'^(?:.*?实际控制人为)','',value).split('，')[0].rstrip('。；')
    value=re.sub(r'(?:先生|女士)$','',value)
    return value if re.fullmatch(r'[\u4e00-\u9fff·]{2,10}',value) and not re.search(r'不适用|未披露|待核验|无实际|无控股|不存在|未知',value) else ''


def build_governance_package(cleaned: dict, target: str, sources=None, *, limit=50000, as_of_date="") -> dict:
    # Explicit acquisition-date provenance adds bookkeeping to every row.
    # Allow for it without displacing previously retained substantive records.
    by_url = {str(get(s, "url")):s for s in sources or []}
    source_cards = defaultdict(list)
    counters = Counter()
    for f in cleaned.get("facts") or []:
        if isinstance(f, dict) and EID.fullmatch(str(f.get("evidence_id") or "")):
            source_cards[str(f.get("source_url") or "")].append(f)
    records, seen = [], {}
    beneficial_contexts={}

    def add(f, kind, *, value="", field="", entity="", period="", **values):
        source = by_url.get(str(f.get("source_url") or ""))
        meta = get(source, "source_metadata", {}) or {}
        acquired=str(meta.get('retrieved_at') or '')
        acquired=acquired if re.match(r'^20\d{2}-\d{2}-\d{2}',acquired) else ''
        r = dict(kind=kind, field=field, value=str(value), entity=entity,
                 period=period or "数据基准日未载", observed_at=(acquired or str(get(source,"created_at") or ""))[:10],
                 observed_at_basis='retrieved_at' if acquired else 'source_created_at',
                 evidence_id=f['evidence_id'], source_url=f.get('source_url',''),
                 source_title=f.get('source_title',''), evidence_scope='target_direct', **values)
        # Do not collapse conflicting values, distinct entities or different dates.
        identity={k:v for k,v in r.items() if k not in {'evidence_id','source_url','source_title','observed_at','observed_at_basis'}}
        if kind in {'beneficial_ownership','beneficial_ownership_total'}:
            identity.pop('value',None)
            identity['entity']=r['holder_key']
        key = json.dumps(identity,ensure_ascii=False,sort_keys=True)
        if key in seen:
            prev=seen[key]
            if f['evidence_id'] not in prev['evidence_ids']:
                prev['evidence_ids'].append(f['evidence_id'])
            counters['duplicate_records']+=1
            return
        r['evidence_ids']=[f['evidence_id']]
        r['fact']=str(value or (entity+' '+str(values)))
        r['evidence_quote']=r['fact']
        seen[key]=r
        records.append(r)

    # Prefer the dedicated registration record for duplicate identity fields;
    # keep corroborating records in the package without repeating eight cites.
    def source_order(item):
        src=by_url.get(item[0]);tool=str((get(src,'source_metadata',{}) or {}).get('tool') or '')
        return 0 if tool=='get_company_registration_info' else 1
    for url, cards in sorted(source_cards.items(),key=source_order):
        src=by_url.get(url)
        meta=get(src,'source_metadata',{}) or {}
        if meta.get('entity_validation') in {'rejected','related_entity_context','ambiguous'}:
            counters['rejected_subject_sources']+=1
            continue
        primary=_primary_filing(src,target) if src is not None else False
        eligible=[f for f in cards if f.get('eligible_for_report') is not False
                  and (f.get('evidence_scope','target_direct') in {'','target_direct'}
                       or (primary and f.get('claim_type')=='source_excerpt' and f.get('evidence_scope') in {'industry_context','related_entity_context'}))
                  and f.get('entity_match') not in {'mismatch','ambiguous','out_of_scope'}
                  and f.get('source_entity_validation')!='rejected'
                  and (_company_fact_has_trusted_target_anchor(f,target) or primary)]
        if not eligible:
            counters['no_eligible_source_card']+=1
            continue
        raw=str(get(src,'content') or '')
        if primary:
            report_period=_filing_period(src)
            from .company_overseas_identity import overseas_filing_identity
            overseas=overseas_filing_identity([src],target)
            if overseas:
                for field,value in [('企业名称',target),('注册司法辖区',overseas['jurisdiction'])]:
                    add(eligible[0],'registry',field=field,value=value,
                        period=report_period+'（发行人文件披露，非独立工商核验）',basis='official_overseas_filing')
            declarations,events=_filing_claims(src)
            for quote in declarations:
                add(eligible[0],'control',field='报告原文明确披露',value=quote,period=report_period,
                    entity=_controller_entity(quote), basis='primary_filing')
            for quote,date in events:
                add(eligible[0],'history',value=quote,period=date or '报告期披露：'+report_period,
                    basis='primary_filing')
            from .company_evidence import source_body,document_pages
            from .company_text import issuer_anchor
            if source_body(src)[1]!='discovery_summary' and issuer_anchor(raw,target)['matched']:
                from .company_beneficial_ownership import beneficial_ownership_disclosures
                holdings,contexts=beneficial_ownership_disclosures(document_pages(src),as_of_date=as_of_date)
                for context in contexts:
                    key=context['key']
                    if key not in beneficial_contexts:
                        beneficial_contexts[key]={**context,'evidence_ids':[eligible[0]['evidence_id']]}
                    elif eligible[0]['evidence_id'] not in beneficial_contexts[key]['evidence_ids']:
                        beneficial_contexts[key]['evidence_ids'].append(eligible[0]['evidence_id'])
                for holding in holdings:
                    values={k:v for k,v in holding.items() if k not in {'kind','entity','period','fact','evidence_quote'}}
                    add(eligible[0],holding['kind'],entity=holding['entity'],period=holding['period'],
                        value=holding['evidence_quote'],**values)
        fields, rows=read_fields(raw,target)
        if fields.get('企业名称') and compact(fields['企业名称'])==compact(target):
            f=eligible[0]
            period=fields.get('数据日期') or meta.get('as_of_date') or meta.get('data_date') or ''
            structured=url.startswith('structured://') or meta.get('content_kind','').startswith('structured_data')
            history=_historical(str(get(src,'title'))+' '+str(meta.get('tool') or ''))
            for field,value in fields.items():
                if field=='数据日期' or not present(value):
                    continue
                if field in {'注册资本','实缴资本'} and len(re.findall(r'人民币|美元|港元',str(value)))>1:
                    counters['duplicated_currency_unit_rejected']+=1
                    continue
                if field!='经营范围' and re.search(r'(?:注册资本|成立日期|法定代表人|登记状态)\s*[：:]',value):
                    counters['concatenated_fields_rejected']+=1
                    continue
                if field=='实际控制人':
                    add(f,'control',field=field,value=value,period=period,entity=_controller_entity(value))
                elif field in ALIASES:
                    add(f,'registry',field=field,value=value,period=period)
            for row in rows:
                date=pick(row,('数据日期','截至日期','截止日期','as_of_date')) or period
                name=pick(row,SHARE_NAMES)
                if name:
                    contribution=next((f'{k}：{v}' for k,v in row.items() if re.search(r'认缴|出资额|ShouldCapi',k) and present(v)), '')
                    count=next((f'{k}：{v}' for k,v in row.items() if re.search(r'持股数|股份数量',k) and present(v)), '')
                    row_history=history or _historical(pick(row,('_section',))+' '+pick(row,('角色','股东类型','备注')))
                    add(f,'historical_shareholder' if row_history else 'shareholder',entity=name,
                        ratio=_ratio(row),count=count,contribution=contribution,period=date)
                person=pick(row,PEOPLE)
                role=pick(row,ROLES)
                if person and role:
                    add(f,'personnel',entity=person,role=role,term=pick(row,('本届任期','任期','任职日期','Term')),
                        period=date)
                change_date=pick(row,('变更日期','变更时间','changeDate'))
                before=pick(row,('变更前','变更前内容','beforeContent'))
                after=pick(row,('变更后','变更后内容','afterContent'))
                if change_date and before and after:
                    item=pick(row,('变更事项','变更项目','changeItem'))
                    add(f,'history',value=f'{item}：{before} → {after}',period=change_date)
        elif url.startswith('structured://'):
            counters['raw_subject_unconfirmed']+=1
            continue
        # Historical events are retained separately; a recent charter date is
        # not the date of its historical founder holdings or restructuring.
        for f in eligible:
            if f.get('claim_type') in {'source_excerpt','structured_field'}:
                continue
            text=str(f.get('fact') or '')
            quote=str(f.get('evidence_quote') or '')
            if not raw or not quote or compact(quote) not in compact(raw):
                counters['unverified_atomic_claim']+=1
                continue
            if not 10<=len(text)<=550 or re.search(r'通常|推断|候选|可能|被视为|应当|不得|可以|有权|若需',text):
                continue
            if not set(re.findall(r'\d+(?:\.\d+)?',text))<=set(re.findall(r'\d+(?:\.\d+)?',quote)):
                continue
            if re.search(r'整体改制|改制设立|发起人|设立时|股东变更|股权变更|注册资本由|注册资本从|完成.{0,12}减资',text):
                add(f,'history',value=text,period=str(f.get('date') or '历史事项，事件日期未载'))
            elif re.search(r'(?:实际控制人|控股股东)(?:为|是|：)',text) and not re.search(r'未|待核验|需以|之一',text):
                if compact(text.rstrip('。')) in compact(quote):
                    add(f,'control',field='控制关系披露',value=text,period=str(f.get('date') or ''))
    # Deterministic factual tables receive whole records, not a clipped prompt.
    # Keep the latest dated control disclosure, alongside undated platform
    # fields. Historical repeats do not masquerade as additional verification.
    ownership_kinds={'beneficial_ownership','beneficial_ownership_total'}
    latest_beneficial=max((r['cutoff'] for r in records if r['kind'] in ownership_kinds),default='')
    older_beneficial=[r for r in records if r['kind'] in ownership_kinds and r['cutoff']!=latest_beneficial]
    counters['older_beneficial_rows_not_displayed']+=len(older_beneficial)
    records=[r for r in records if r not in older_beneficial]
    controls=[r for r in records if r['kind']=='control' and r.get('basis')=='primary_filing']
    latest_control=max((r['period'] for r in controls),key=_period_rank,default='')
    records=[r for r in records if r not in controls or r['period']==latest_control]
    histories=sorted([r for r in records if r['kind']=='history'],key=lambda r:(_period_rank(r['period']),r['period']),reverse=True)
    admitted_history=[]
    for r in histories:
        if any(set(re.findall(r'\d+(?:\.\d+)?',r['value']))==set(re.findall(r'\d+(?:\.\d+)?',old['value']))
               and SequenceMatcher(None,compact(r['value']),compact(old['value'])).ratio()>.9 for old in admitted_history):
            counters['duplicate_history']+=1
            continue
        admitted_history.append(r)
    # Include the latest completed changes and a separately admitted founding
    # event, instead of reproducing decades of capital history in this chapter.
    founding=[r for r in admitted_history if re.search(r'整体改制|改制设立',r['value'])][:1]
    history_keep=admitted_history[:3]+[r for r in founding if r not in admitted_history[:3]]
    records=[r for r in records if r['kind']!='history' or r in history_keep]
    priority={'registry':0,'shareholder':1,'beneficial_ownership':2,'beneficial_ownership_total':2,'control':2,'history':3,'personnel':4,'historical_shareholder':5}
    records.sort(key=lambda r:priority[r['kind']])
    selected=[]
    for r in records:
        if len(json.dumps(selected+[r],ensure_ascii=False))<=max(0,limit-3500):
            selected.append(r)
        else:
            counters['budget_excluded']+=1
    conflict_groups=defaultdict(list)
    for r in selected:
        if r['kind']=='registry':
            conflict_groups[(r['field'],r['period'])].append(r)
        elif r['kind']=='shareholder':
            conflict_groups[('股东持股比例:'+r['entity'],r['period'])].append(r)
        elif r['kind'] in ownership_kinds:
            conflict_groups[('原件受益所有权:'+r['holder_key'],r['period'])].append(r)
    conflicts=[]
    for (field,date),rs in conflict_groups.items():
        vals={(f"普通股 {r['ordinary_shares']}；美国存托股 {r['ads']}；原表比例 {r['ratio']}"
               if r['kind'] in ownership_kinds else r.get('ratio') or r['value']) for r in rs}
        if len(vals)>1:
            conflicts.append({'field':field,'period':date,'values':sorted(vals),
                              'evidence_ids':list(dict.fromkeys(eid for r in rs for eid in r['evidence_ids']))})
    kinds={r['kind'] for r in selected}
    gaps=[]
    if any(r.get('basis')=='official_overseas_filing' for r in selected):
        gaps.append('境外发行人名称和注册司法辖区来自官方发行人文件，未替代专业平台实际查询或独立工商档案核验；不能套用中国内地统一社会信用代码、法定代表人或注册资本字段。')
    if any(r['kind'] in ownership_kinds for r in selected):
        gaps.append('已接纳发行人20-F受益所有权子表，不是完整登记股东名册；可能含未来60日内权利及受托表决/处置权，不直接等同本人金钱权益或实际控制。')
        if len({r['context_key'] for r in selected if r['kind'] in ownership_kinds})>1:
            gaps.append('同一截至日有多份定义或附注不同的受益所有权披露，已按原件分别列示，不把重复行当新增独立持有人。')
    for kind,label in (('registry','工商登记原始字段'),('shareholder','当前股东明细'),('personnel','主要人员明细'),
                       ('history','股权变动与减资事件记录'),('control','明确的控制关系或表决权安排披露')):
        if kind not in kinds:
            gaps.append(f'{label}未在本章形成可核对记录，需补充对应原始材料。')
    # A restructuring event does not mean ownership/capital changes were covered.
    if not any(r['kind']=='history' and re.search(r'变更|减资|注册资本由|注册资本从',r['value']) for r in selected):
        gap='股权变动、减资尚缺完整的逐项事件日期和前后值对照，需补充工商变更档案和相关公告。'
        gaps=[x for x in gaps if not x.startswith('股权变动与减资')]+[gap]
    context_keys={r['context_key'] for r in selected if r['kind'] in ownership_kinds}
    from .company_selection_audit import selection_audit
    return {'version':VERSION,'target_name':target,'facts':selected,'conflicts':conflicts,
            'selection_audit':selection_audit(records,selected),
            'beneficial_ownership_contexts':[value for key,value in beneficial_contexts.items() if key in context_keys],
            'information_gaps':gaps,'diagnostic':{'candidate_records':len(records),'delivered_records':len(selected),
            'by_kind':dict(Counter(r['kind'] for r in selected)),'filters':dict(counters)}}


def _cell(value):
    # Evidence is data, never Markdown instructions or executable HTML.
    return re.sub(r'\s+',' ',str(value or '')).replace('|','／').replace('<','&lt;').replace('>','&gt;').replace('[','［').replace(']','］').strip() or '待核验'


def refs(record):
    return ''.join(f'[{eid}]' for eid in dict.fromkeys(record['evidence_ids']))


def combined_refs(records):
    return refs({'evidence_ids':[eid for record in records for eid in record['evidence_ids']]})


def provenance(record):
    period=record['period']
    observed=record.get('observed_at')
    if not observed:return period
    if record.get('observed_at_basis')=='retrieved_at':return period+f'；原件采集记录日期{observed}'
    if record.get('observed_at_basis')=='source_created_at':return period+f'；本次入库日期{observed}（原始采集时间未单列）'
    return period+f'；记录日期{observed}（时间性质未单列）'


def _table(headers, rows):
    if not rows:
        return ['本章尚未形成该项可直接核对的事实，待核验。']
    return ['| '+' | '.join(headers)+' |','| '+' | '.join('---' for _ in headers)+' |']+[
        '| '+' | '.join(_cell(v) for v in row[:-1])+' | '+row[-1]+' |' for row in rows]


def _timed_table(headers, rows):
    # A shared snapshot is stated once, rather than repeated in every cell.
    periods={row[-2] for row in rows}
    if rows and len(periods)==1:
        return ['资料口径：'+_cell(next(iter(periods)))+'。','']+_table(
            headers[:-2]+headers[-1:], [row[:-2]+row[-1:] for row in rows])
    return _table(headers,rows)


def _role_priority(role):
    roles=re.split(r'[,，、/]',role)
    if any(r in {'董事长','执行董事','总经理','总裁'} for r in roles):
        return 0
    if re.search(r'董事|监事',role):
        return 1
    return 2 if re.search(r'财务|秘书',role) else 3


def render_beneficial_ownership(package: dict) -> str:
    """Deterministic original-value table shared by full and compact writers."""
    groups=defaultdict(list)
    for record in package.get('facts', []):
        groups[record['kind']].append(record)
    lines=[]
    beneficial=groups['beneficial_ownership']+groups['beneficial_ownership_total']
    if not beneficial:
        return ''
    lines+=['#### 发行人受益所有权披露（非完整登记股东名册）','',
        '普通股、美国存托股和原表比例分别保留。可能包含截至日后60日内可取得股份及受托表决或处置权，不直接等同本人金钱权益、已到手股份或实际控制。逐人分母按原件定义，比例不简单相加；0.0%为原表显示值，不能据此认定0股。本轮不自行换算ADS或重算合计。','']
    for context in package.get('beneficial_ownership_contexts',[]):
        group=[r for r in beneficial if r['context_key']==context['key']]
        if not group:
            continue
        lines+=['原表截至日：'+context['cutoff']+'；物理页'+str(context['page'])+'。仅列本次成功对齐的'+str(len(group))+'条原文记录，合计行不是独立持有人。'+refs(context),'']
        lines+=_table(['原表主体','普通股（原表）','美国存托股（原表）','原表比例','记录性质／出处'],[
            [r['entity']+('（原注'+r['footnote_marker']+'）' if r['footnote_marker'] else ''),r['ordinary_shares'],r['ads'],r['ratio'],
             ('原表合计，非独立主体' if r['kind']=='beneficial_ownership_total' else '20-F定义下的受益所有权')+'；'+refs(r)] for r in group])
        for note in context.get('holder_caveats',[]):
            lines+=['','原注'+note['marker']+'的权益边界：'+_cell(note['quote'])+' '+refs(context)+'（物理页'+str(note['page'])+'）']
    return '\n'.join(lines)


def shareholder_aggregate(record):
    return bool(re.fullmatch(r'(?:A股股东|H股股东|境外上市外资股|境内上市内资股|合计|合計|总计|總計)', str(record.get('entity') or '').strip(), re.I))


def render_registered_shareholders(package: dict) -> str:
    """The graph and compact narrative must not replace original row values."""
    rows = [r for r in package.get('facts', []) if r['kind'] == 'shareholder']
    if not rows: return ''
    lines = ['#### 股东登记原值及资料口径', '']
    lines += _timed_table(['登记股东名称','源表持股比例','持股数／出资额（原字段）','数据时点／口径','来源'], [
        [r['entity'] + ('（原表股份类别汇总，非独立股东）' if shareholder_aggregate(r) else ''), r.get('ratio') or '源表未载', r.get('count') or r.get('contribution') or '源表未载', provenance(r), refs(r)] for r in rows])
    lines += ['', '原表比例、持股数和认缴金额分别保留，原字段未载单位不补单位；数据基准日未载不以采集日替代。同一主体的不同来源比例并列，不任选一值；图中对应差异亦保留，不能据此计算表决权合计或认定完整股东名册。']
    return '\n'.join(lines)


def render_governance_personnel(package: dict) -> str:
    """Keep source role/term fields behind the displayed relationship nodes."""
    rows=sorted([r for r in package.get('facts',[]) if r['kind']=='personnel'],key=lambda r:_role_priority(r['role']))
    if not rows:return ''
    shown=rows[:12]
    lines=['#### 主要人员原值及资料口径','']
    lines+=_timed_table(['姓名','源表职务','源表任期','数据时点／口径','来源'],[
        [r['entity'],r['role'],r.get('term') or '源表未载',provenance(r),refs(r)] for r in shown])
    lines+=['','任职、创始人及技术人员字段各按源表含义保留，不等同全部工商治理职务或实际控制；未载任期与数据基准日不补齐。']
    if len(rows)>len(shown):lines+=['本表选列'+str(len(shown))+'条主要人员记录，其余'+str(len(rows)-len(shown))+'条及完整原文保留于本章证据包和来源台账，不据展示上限推断其余职位不存在。']
    return '\n'.join(lines)


def render_governance(package: dict) -> str:
    groups=defaultdict(list)
    for r in package['facts']:
        groups[r['kind']].append(r)
    lines=[f'## 2. {TITLE}','','### '+HEADINGS[0],'']
    rows=[]
    for r in groups['registry']:
        field=r['field']
        if field in {'人员规模','参保人数'}:
            field+='（登记主体口径）'
        value=r['value']
        if field=='经营范围' and len(value)>300:
            value=value[:300].rsplit('；',1)[0]+'…（登记经营范围节选；完整文本见原始记录）'
        rows.append([field,value,provenance(r),'['+r['evidence_ids'][0]+']'])
    lines+=_timed_table(['字段','登记记录','数据时点／口径','来源'],rows)
    if any(r['field']=='经营范围' for r in groups['registry']):
        lines+=['','经营范围是登记允许范围，不能据此确认每项业务已经实际开展。']
    if groups['history'] or groups['historical_shareholder']:
        lines+=['','#### 设立与变更事项（历史口径）','']
        rows=[[r['period'],r['value'] or r['entity'],refs(r)] for r in groups['history']]
        rows += [[r['period'],'历史股东 '+r['entity']+'；'+r.get('ratio',''),refs(r)] for r in groups['historical_shareholder']]
        lines+=_table(['事件日期','已核对事项','来源'],rows)
        lines+=['','登记成立日期、改制日期、文件发布日期分别保留；历史发起人比例不作为当前持股比例。']
    lines+=['','### '+HEADINGS[1],'',render_registered_shareholders(package),'']
    shareholders=groups['shareholder']
    if shareholders:
        lines+=['','以上保留源表名称及登记持股口径；未载数据基准日的记录不借用采集日期或其他报告期补齐。持股数、认缴金额和注册资本分别列示，不相互换算；未确认完整股东名册前不计算未列股东比例或表决权合计。']
    beneficial_text=render_beneficial_ownership(package)
    if beneficial_text:
        lines+=['',beneficial_text]
    lines+=['','#### 主要人员记录','']
    personnel=groups['personnel']
    # Board, executive, finance and secretary roles first; do not lose current
    # independent/employee directors to a stale charter's executive roster.
    personnel=sorted(personnel,key=lambda r:_role_priority(r['role']))
    shown=personnel[:12]
    lines+=_timed_table(['姓名','源表职务','源表任期','数据时点／口径','来源'],[
        [r['entity'],r['role'],r['term'] or '源表未载',provenance(r),refs(r)] for r in shown])
    if len(personnel)>len(shown):
        lines+=['',f'本表展示{len(shown)}条主要人员记录；其余{len(personnel)-len(shown)}条保留在本章证据包，不能据本表推断职位不存在。']
    if personnel:
        lines+=['','任职记录只证明源表所列职务，不自动证明实际控制、一致行动或关联交易；同一人的任期不扩展为法定代表人任职起始日。']
    if groups['control']:
        lines+=['','#### 控制关系的明确披露','']
        lines+=_timed_table(['原字段','披露内容','数据时点／口径','来源'],[
            [r['field'],r['value'],provenance(r),refs(r)] for r in groups['control']])
    lines+=['','### '+HEADINGS[2],'',
            '关系图仅连接已有证据明确列示的股东及任职关系；表决权委托、一致行动、代持、亲属或股东之间的控制边不作补绘。图形本身不增加事实。']
    lines+=['','### '+HEADINGS[3],'']
    overlap=next(((s,p) for s in shareholders for p in personnel if compact(s['entity'])==compact(p['entity']) and re.search(r'董事长|总经理|总裁|执行董事',p['role'])),None)
    if overlap:
        s,p=overlap
        lines+=[f"- {_cell(s['entity'])}同时出现在股东记录与主要人员记录中，职务为{_cell(p['role'])}；可确认持股与任职的交集，不能仅据此认定其掌握全部决策权。"+refs({'evidence_ids':list(dict.fromkeys(s['evidence_ids']+p['evidence_ids']))})]
    if groups['control']:
        lines+=['- 控制关系以本章明确披露的内容和时点为限；登记持股比例不替代表决权安排或最终受益关系核验。']
    else:
        lines+=['- 本章尚未取得足以确认实际控制或一致行动安排的明确记录；不据持股排序、共同任职或示例文本补出控制结论。']
    if package['conflicts']:
        for c in package['conflicts']:
            lines+=[f"- {_cell(c['field'])}在{_cell(c['period'])}存在不同来源值：{'／'.join(_cell(v) for v in c['values'])}，待核验；不任选一个覆盖其他值。"+refs(c)]
    lines+=['- 股东关系是否存在争议、外部投资人是否参与重大决策，以及治理机制实际执行效果，需对应协议、决议或事件材料支持，不能由登记表直接得出稳定或无冲突结论。']
    if package['information_gaps']:
        lines+=['','待核验重点：'+'；'.join(x.rstrip('。') for x in package['information_gaps'])+'。']
    return '\n'.join(lines)


def governance_errors(text, package):
    """Deterministic re-render is also the contract after optional editors."""
    errors=[]
    if text.strip()!=render_governance(package).strip():
        errors.append('第二章出现未由字段证据渲染的改写或丢失')
    ids=set(cited_evidence_ids(text))
    allowed={eid for r in package['facts'] for eid in r['evidence_ids']}
    if ids-allowed:
        errors.append('第二章存在未知证据编号')
    if not any(r['kind']!='registry' or r['field']!='企业名称' for r in package['facts']):
        errors.append('第二章没有主体匹配的字段或历史事件证据')
    return errors


def governance_graph_nodes(package, graph_kind):
    """Use exactly the chapter's admitted records, never unrelated raw rows."""
    nodes=[]
    seen=set()
    records=sorted(package['facts'],key=lambda r:0 if r['kind']=='control' else 1)
    for r in records:
        node=None
        if graph_kind in {'control','relationship'} and r['kind']=='control' and r['entity']:
            node=(r['entity'],'披露实际控制人',r['period'])
        elif graph_kind=='equity' and r['kind']=='shareholder' and not shareholder_aggregate(r):
            node=(r['entity'],'登记股东；'+r['period'],r['ratio'] or '比例未载')
        elif graph_kind=='beneficial' and r['kind']=='beneficial_ownership' and r['entity']:
            # A disclosed beneficial interest is neither a registry holding nor
            # proof of control. Aggregates must never become person nodes.
            node=(r['entity'],'披露实益持股 '+(r.get('ratio') or '比例未载'),
                  r.get('cutoff') or r['period'])
        elif graph_kind in {'control','relationship'} and r['kind']=='personnel':
            node=(r['entity'],r['role'],'任职记录，非控制结论')
        elif graph_kind in {'control','relationship'} and r['kind']=='registry' and r['field']=='法定代表人':
            node=(r['value'],'法定代表人','登记角色，非控制结论')
        identity = node if graph_kind in {'beneficial','equity'} else node[0] if node else None
        if node and identity not in seen and compact(node[0])!=compact(package['target_name']):
            nodes.append(node)
            seen.add(identity)
    return nodes
