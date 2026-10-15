"""Chapter 3: dated corporate events and growth supported by comparable data.

No company-specific milestones or template conclusions are embedded here.
Original-currency amounts, proposals/completions and reporting periods remain
separate. Registration details and control claims belong in chapter 2.
"""
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal
from difflib import SequenceMatcher
from urllib.parse import urlparse

from .company_governance import (
    EID, _cell, _filing_period, _period_rank, _primary_filing,
    _table, compact, get, read_fields, refs,
)
from .report_prompts import _company_fact_has_trusted_target_anchor

TITLE = '历史沿革与成长质量'
HEADINGS = ('关键沿革与业务发展时间线', '成长质量核对', '历史遗留事项', '核验重点')
VERSION = 'company-history-v1'
DATE = re.compile(r'(20\d{2}|19\d{2})年(?:(\d{1,2})月)?(?:(\d{1,2})日)?')
METRICS = ('营业收入','归属于上市公司股东的净利润','经营活动产生的现金流量净额')
EVENT_WORDS = re.compile(r'整体改制|改制设立|更名|收购|并购|增资|减资|回购|注销|增发|发行|配售|转增|送红股|上市(?!公司|规则|管理)|投产|量产|停产|停止生产|成立|设立|签署|发布|推出|上线')
RULE = re.compile(r'应当|不得|可以|有权|如发生|若发生|候选|假设|承诺函|竞业承诺|《不竞争承诺》|详情请见|公告编号')
NON_EVENT = re.compile(r'上市规则|上市管理|公司法|制订本章程|制定本章程|本所接受|特聘法律顾问|注册简称|本次注册|法律意见|榜单|排行榜|排名第|位列|荣获|论文|发表|研究论文|发布于|披露于|财务报表主要项目|合同负债|预收购房款')
PENDING = re.compile(r'拟|计划|预计|将于|尚未|尚待|待完成|不超过|意向|签署|签订|达成协议')
AMOUNT = r'[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}'


def _date(text, event=True):
    text=_normalize_year(text)
    dates=[m for m in DATE.finditer(text) if m.start()==0 or text[m.start()-1] not in '-—至']
    dates=[m for m in dates if not re.match(r'[\s）)]*(?:的?总股本|的?股本|为基数)',text[m.end():])]
    dates=[m for m in dates if not re.search(r'目标|愿景|规划',text[m.end():m.end()+14])]
    if not dates:
        return ''
    # Approval, signing, announcement and closing may all occur on different
    # dates. Prefer a date attached to the stated action, never publication.
    chosen=[]
    for i,m in enumerate(dates):
        clause=text[m.end():dates[i+1].start() if i+1<len(dates) else len(text)]
        if (EVENT_WORDS.search(clause) or re.search(r'实施完成|实施完毕|完成',clause)) and not re.match(r'[^，。；]{0,45}(?:核准|批准|披露|公告)',clause):
            chosen.append(m)
    if not chosen and re.search(r'(?:并于|于)\d{1,2}月\d{1,2}日[^。]{0,20}上市',text):
        return ''  # Execution year omitted; do not substitute approval date.
    m=max(chosen or dates,key=lambda x:(bool(x[3]),bool(x[2]),x.start())) if event else dates[0]
    y,month,day=m.groups()
    return y+('-'+month.zfill(2) if month else '')+('-'+day.zfill(2) if day else '')


def _normalize_year(text):
    digits=dict(zip('〇零一二三四五六七八九','00123456789'))
    return re.sub(r'[一二三四五六七八九〇零]{4}年',lambda m:''.join(digits[c] for c in m[0][:-1])+'年',text)


def _event_kind(text):
    if re.search(r'整体改制|改制设立|变更设立',text):
        return '工商沿革'
    if re.search(r'更名|成立|设立',text) and not re.search(r'发行|配售|上市|收购|发布|推出|量产|投产',text):
        return '工商沿革'
    return '资本事项' if re.search(r'增资|减资|回购|注销|增发|发行|配售|转增|送红股|证券交易所|联交所|[AH]\s*股|募资|募集',text) else '业务动作'


def _event_status(text):
    # Signature is a completed signing action, not completed acquisition or
    # funding. Do not let the word "完成" elsewhere erase that distinction.
    if re.search(r'尚未|尚待|未完成',text):
        return '尚未完成'
    if re.search(r'拟|计划|预计|将于|将凭借|将逐步|并将|意向|不超过',text):
        return '计划／拟议'
    if re.search(r'签署|签订|达成协议',text) and not re.search(r'交割完成|完成交割|收购完成|完成收购|资金到账|配售完成',text):
        return '已签约／完成待核验'
    if re.search(r'审议通过|决议通过',text) and not re.search(r'实施完[毕成]|已实施|已完成|完成交割|资金到账',text):
        return '已决议／执行待核验'
    if re.search(r'核准|批准|同意',text) and not re.search(r'完成|注册登记|营业执照|在[^。]{1,35}(?:交易所|联交所)上市|于[^。]{1,30}上市',text):
        return '已核准／落地待核验'
    return '原文记载已发生'


def financial_rows(raw, period):
    """Read explicit current/prior headers, including flattened filing tables."""
    records=[]
    columns=None
    for line in raw.splitlines():
        if not line.strip().startswith('|'):
            if line.strip():
                columns=None
            continue
        cells=[c.strip() for c in line.strip().strip('|').split('|')]
        labels=[re.sub(r'\s+','',c) for c in cells]
        years=[(i,c) for i,c in enumerate(labels) if re.fullmatch(r'20\d{2}年',c)]
        current=next((i for i,c in enumerate(labels) if c in {'本报告期','本期','本年度'}),None)
        prior=next((i for i,c in enumerate(labels) if c in {'上年同期','上期','上年度'}),None)
        if len(years)>=2:
            ordered=sorted(years,key=lambda x:x[1],reverse=True)
            current,prior=ordered[0][0],ordered[1][0]
        if current is not None and prior is not None:
            change=next((i for i,c in enumerate(labels) if '增减' in c or '同比' in c),None)
            columns=(current,prior,change)
            continue
        label=re.fullmatch(r'('+ '|'.join(map(re.escape,METRICS))+r')[（(]([^）)]+)[）)]',cells[0]) if cells else None
        if not columns or not label or max(i for i in columns if i is not None)>=len(cells):
            continue
        current,prior,change=columns
        if not all(re.fullmatch(r'[-+]?\d[\d,]*(?:\.\d+)?',cells[i]) for i in (current,prior)):
            continue
        yoy=cells[change] if change is not None and re.fullmatch(r'[-+]?\d+(?:\.\d+)?%',cells[change]) else ''
        records.append(dict(metric=label[1],value=cells[current],previous_value=cells[prior],unit=label[2],yoy=yoy,period=period))
    if records:
        return records
    # Flattened PDFs have no cell boundaries. Require the exact two-year
    # header and two-decimal amounts; otherwise leave a gap rather than guess.
    text=re.sub(r'\s+','',raw)
    header=re.search(r'(20\d{2})年(20\d{2})年本年比上年增减(?:20\d{2}年)?',text)
    if not header or int(header[1])<=int(header[2]):
        return []
    table=text[header.end():header.end()+2600]
    for metric in METRICS:
        match=re.search(re.escape(metric)+r'[（(]([^）)]+)[）)]('+AMOUNT+r')('+AMOUNT+r')([-+]?\d+(?:\.\d+)?%)',table)
        if match:
            records.append(dict(metric=metric,unit=match[1],value=match[2],previous_value=match[3],yoy=match[4],period=period))
    return records


def _issuer_hosts(sources, target):
    hosts=set()
    for source in sources or []:
        if not _primary_filing(source,target):continue
        head=str(get(source,'content'))[:2600]
        for match in re.finditer(r'(?:網站|网站|网址|網址|Website)\s*[:：]\s*(https?://[^\s|<>）)]+)',head,re.I):
            host=urlparse(match[1]).hostname
            if host:hosts.add(host.lower().removeprefix('www.'))
    return hosts


def _heading_events(raw):
    """Bind a bullet only to the adjacent year heading, never the year nav."""
    year='';headings=set();emitted=False
    for line in raw.splitlines():
        line=line.strip()
        if line.startswith('#') and not re.fullmatch(r'#{1,6}\s*(?:19|20)\d{2}年?',line):
            # Responsive sites often repeat a mobile timeline with missing
            # headings. Do not bind those bullets to a previous desktop year.
            heading=re.sub(r'^#+\s*','',line)
            if emitted and heading in headings:break
            headings.add(heading);year='';continue
        match=re.fullmatch(r'(?:#{1,6}\s*)?((?:19|20)\d{2})(?:年)?',line)
        if match:
            year=match[1];continue
        if not year or not re.match(r'^[•●·*-]\s*\D',line):continue
        # PDF/HTML extractors can collapse several bullets into one line.
        # Split actual bullet glyphs, never a hyphen inside a product version.
        for value in re.split(r'[•●·]',re.sub(r'^[•●·*-]\s*','',line)):
            value=value.strip()
            if not 5<=len(value)<=200 or re.search(r'目标|愿景|承诺|荣获|榜单|\bmax\b',value,re.I):continue
            if re.search(r'有限公司.{0,20}上市',value):continue
            if re.search(r'进入|下线|成立|创立|投产|量产|发布|推出|停止|上市|交付|建成|落成|合作|收购|首次发售',value):
                emitted=True
                yield year,value


def _release_topics(text):
    """Keep generations/versions distinct when comparing release dates."""
    pattern=r'(?:第[一二三四五六七八九十\d]+代)?[A-Z]{2,10}(?:-[A-Za-z0-9]+)?(?:\s*\d+(?:\.\d+)*)?'
    return {re.sub(r'\s+','',m[0]) for m in re.finditer(pattern,text)
            if (m.start()==0 or not text[m.start()-1].isascii() or not text[m.start()-1].isalnum())}


def _event_family(record):
    """Selection diversity only: do not merge facts or their evidence."""
    text=record['fact']
    if re.search(r'转增|送红股|送股',text):return '资本分配'
    if re.search(r'发行.{0,30}债券|债券.{0,30}发行',text):return '债券发行'
    if re.search(r'首次.{0,20}(?:发行|发售)|交易所.{0,15}上市|联交所.{0,5}上市',text) and not re.search(r'增发|非公开发行',text):
        return '上市发行-H' if re.search(r'H\s*股|香港|联交所',text) else '上市发行-A' if re.search(r'A\s*股|深圳|深交所',text) else '上市发行'
    if re.search(r'配售|增发|募资|募集|非公开发行',text):return '外部融资'
    if re.search(r'减资|回购|注销',text):return '回购减资'
    if re.search(r'停止|停产|退出',text):return '业务退出'
    if re.search(r'收购|并购',text):return '业务并购'
    if re.search(r'合资|合作',text):return '业务合作'
    if re.search(r'投产|量产|下线|交付',text):return '生产交付'
    if re.search(r'发布|推出',text):return '产品技术'
    return record['event_type']


def _select_events(rows,quota):
    # Prefer exact execution dates over coarse issuer website years. Keep a
    # first milestone and diverse recent actions before filling spare slots.
    if not rows:return []
    primary=[r for r in rows if r['source_rank']==max(x['source_rank'] for x in rows)]
    first_year=min(r['period'][:4] for r in primary)
    first=max((r for r in primary if r['period'].startswith(first_year)),
              key=lambda r:(len(r['period']),r['status']=='原文记载已发生'))
    selected=[first];families={_event_family(first)}
    recent=sorted(primary,key=lambda r:(r['period'],len(r['period']),bool(re.search(r'所得.*净额|募集.*净额|发行价|发行价格',r['fact']))),reverse=True)
    # Execution and decision are different facts; favor executed actions for
    # the limited summary, retaining incomplete status for any selected plan.
    recent.sort(key=lambda r:bool(re.search(r'待核验|拟议|尚未',r['status'])))
    for row in recent:
        if len(selected)>=quota:break
        if _event_family(row) not in families:
            selected.append(row);families.add(_event_family(row))
    for row in recent:
        if len(selected)>=quota:break
        # A year-only website entry adds no date detail to the same action.
        if any(row['period'][:4]==old['period'][:4] and _event_family(row)==_event_family(old) for old in selected):continue
        selected.append(row)
    return selected


def build_history_package(cleaned, target, sources=None, *, governance=None, limit=38000):
    by_url={str(get(s,'url')):s for s in sources or []}
    by_source=defaultdict(list)
    for f in cleaned.get('facts') or []:
        if isinstance(f,dict) and EID.fullmatch(str(f.get('evidence_id') or '')):
            by_source[str(f.get('source_url') or '')].append(f)
    records=[];counts=Counter();seen={}
    issuer_hosts=_issuer_hosts(sources,target)

    def add(card,kind,text,*,period='',source_rank=1,**fields):
        text=re.sub(r'\s+',' ',text).strip()
        if kind=='event':
            text=re.split(r'[，,](?=充分体现|创下|率先实现|构建了|通过更有温度|推动长期|赢得市场|彰显)',text)[0]
        if not 4<=len(text)<=650:
            counts['oversize_or_empty_claim']+=1
            return
        record=dict(kind=kind,fact=text,evidence_quote=text,evidence_scope='target_direct',
                    evidence_id=card['evidence_id'],evidence_ids=[card['evidence_id']],source_url=card.get('source_url',''),
                    source_title=card.get('source_title',''),period=period,source_rank=source_rank,**fields)
        key=json.dumps({k:v for k,v in record.items() if k not in {'evidence_id','evidence_ids','source_url','source_title','source_rank'}},ensure_ascii=False,sort_keys=True)
        if key in seen:
            if card['evidence_id'] not in seen[key]['evidence_ids']:
                seen[key]['evidence_ids'].append(card['evidence_id'])
            counts['duplicate_claim']+=1
            return
        seen[key]=record;records.append(record)

    # The admitted registry founding date is a historical start point. Do not
    # reproduce the whole chapter-2 table or infer capital contribution status.
    for r in (governance or {}).get('facts',[]):
        if r['kind']=='registry' and r['field']=='成立日期':
            add(r,'event',target+'登记成立日期为'+r['value']+'。',period=r['value'],source_rank=3,
                event_type='工商沿革',status='登记记录')

    def source_priority(item):
        src=by_url.get(item[0]);meta=get(src,'source_metadata',{}) or {}
        return 0 if _primary_filing(src,target) or get(src,'source_type') in {'official','filing'} or (meta.get('quality') or {}).get('source_type') in {'official','filing'} else 1

    for url,cards in sorted(by_source.items(),key=source_priority):
        src=by_url.get(url);raw=str(get(src,'content') or '')
        if not raw:
            continue
        meta=get(src,'source_metadata',{}) or {}
        if meta.get('entity_validation') in {'rejected','related_entity_context','ambiguous'}:
            counts['rejected_source']+=1;continue
        primary=_primary_filing(src,target)
        host=(urlparse(url).hostname or '').lower().removeprefix('www.')
        issuer_site=host in issuer_hosts
        eligible=[f for f in cards if f.get('eligible_for_report') is not False
                  and f.get('entity_match') not in {'mismatch','ambiguous','out_of_scope'}
                  and f.get('source_entity_validation')!='rejected'
                  and ((f.get('evidence_scope','target_direct') in {'','target_direct'} and _company_fact_has_trusted_target_anchor(f,target))
                       or ((primary or issuer_site) and f.get('claim_type')=='source_excerpt' and f.get('evidence_scope') in {'target_direct','industry_context','related_entity_context'}))]
        if not eligible:
            counts['no_admissible_card']+=1;continue
        f=eligible[0]
        authority=primary or issuer_site or get(src,'source_type') in {'official','filing'} or (meta.get('quality') or {}).get('source_type') in {'official','filing'}
        rank=3 if authority else 1
        period=_filing_period(src)
        if issuer_site:
            for year,value in _heading_events(raw):
                add(f,'event',value,period=year,source_rank=rank,
                    event_type='资本事项' if '交易所上市' in value else '创业起点（公司自述）' if re.search(r'创立|创业|成立.*起步',value) else '业务动作',
                    status='官网沿革记载（公司自述）',date_basis='year_heading')
        if period:
            for metric in financial_rows(raw,period):
                quote=f"{metric['metric']}（{metric['unit']}）：本期{metric['value']}，上年同期{metric['previous_value']}"+(f"，同比{metric['yoy']}。" if metric['yoy'] else '。')
                add(f,'performance',quote,source_rank=rank,**metric)
        # Only bounded, explicit issuer actions become milestones. Personal
        # resumes, legal permissions and subsidiary histories remain excluded.
        text=re.sub(r'--- PDF page \d+ ---',' ',raw)
        text=re.sub(r'(?:網站|网站|网址|網址|Website)\s*[:：]\s*https?://[^\s|<>）)]+','',text,flags=re.I)
        prose=re.split(r'(?<=[。！？])\s*',text)
        for pos,sentence in enumerate(prose):
            # An IPO subsection can put quantity/price in one sentence and
            # listing date in the next. Keep the adjacent issuer statements
            # together instead of claiming the issue price is unavailable.
            if pos and re.search(r'公司.{0,40}发行.{0,70}上市',re.sub(r'\s+','',sentence)):
                previous=prose[pos-1]
                if len(previous)<300 and re.search(r'公司首次.{0,40}发行',previous) and re.search(r'发行价格',previous):
                    sentence=previous+sentence
            # A website's undelimited navigation/field list can precede its
            # first prose sentence. Strip that prelude only when the remaining
            # paragraph is a complete dated issuer action. PDF paragraph wraps
            # inside a sentence must never create incomplete milestones.
            if len(sentence)>550:
                paragraphs=re.split(r'\n\s*\n',sentence)
                starts=[i for i,p in enumerate(paragraphs) if DATE.search(_normalize_year(p)) and EVENT_WORDS.search(p)
                        and re.search(r'本公司|本集团|公司',p) and len(p)<500]
                if starts:sentence='\n\n'.join(paragraphs[starts[-1]:]).strip()
            sentence=re.sub(r'\s+',' ',sentence).strip()
            sentence=re.sub(r'(?<=[\u4e00-\u9fff\d])\s+(?=[\u4e00-\u9fff\d])','',sentence)
            sentence=re.sub(re.escape(target)+r'\s*20\d{2}年(?:半年度|年度|第[一三]季度)报告(?:全文|摘要)?\d{0,3}','',sentence)
            sentence=re.sub(r'^\d{1,3}(?=前述|本公司|本集团|公司)','',sentence)
            sentence=re.sub(r'\[\d+(?:-\d+)?\]','',sentence)
            sentence=re.split(r'[，,](?=(?:19|20)\d{2}年(?:位居|荣获|获评|排名))',sentence)[0]
            if '每股收益' in sentence and '注：' in sentence:
                sentence=sentence.rsplit('注：',1)[-1]
            if not 10<=len(sentence)<=550 or not DATE.search(_normalize_year(sentence)) or not EVENT_WORDS.search(sentence):
                continue
            if RULE.search(sentence) or NON_EVENT.search(sentence) or re.search(r'用户查询|若你需要|先生|女士|工作经历|任职经历|前10名股东|上述股东|□||☑',sentence):
                continue
            if sentence.count('《')>3 or sentence.count('》')>3:
                counts['layout_noise']+=1;continue
            if re.search(re.escape(target)+r'公开发行20\d{2}年公司债券.{0,15}募集说明书',sentence):
                counts['layout_noise']+=1;continue
            if '|' in sentence or 'http' in sentence or re.search(r'第[一二三四五六七八九十]+节',sentence):
                continue
            anchor=re.search(r'本公司(?!子公司)|本集团(?!子公司)|(?<![子孙该])公司(?:于|在|首次|成立|增发|向|[，,])',sentence)
            if compact(target) not in compact(sentence) and not (authority and anchor):
                continue
            action=re.search(r'(?:'+re.escape(target)+r'|本集团|本公司|(?<![子孙该])公司).{0,180}(?:整体改制|变更设立|收购|并购|增资|减资|回购|注销|增发|发行(?!在外)|发售|配售|转增|送红股|上市(?!公司|规则|管理)|投产|量产|停止生产|成立|设立|签署|发布|推出|上线)',sentence)
            if not action:
                continue
            if re.search(r'子公司|附属公司|参股公司|联营公司',sentence):
                continue
            date=_date(sentence)
            if date:
                add(f,'event',sentence,period=date,source_rank=rank,event_type=_event_kind(sentence),status=_event_status(sentence))
        # Atomic excerpts can retain source line breaks that prose splitting
        # misses. Verify the quote and all figures before admitting the claim.
        for atom in eligible:
            if atom.get('claim_type') in {'source_excerpt','structured_field'}:
                continue
            claim=str(atom.get('fact') or '');quote=str(atom.get('evidence_quote') or '')
            if not quote or compact(quote) not in compact(raw) or RULE.search(claim):
                continue
            if not set(re.findall(r'\d+(?:\.\d+)?',claim))<=set(re.findall(r'\d+(?:\.\d+)?',quote)):
                continue
            date=_date(claim)
            if date and EVENT_WORDS.search(claim) and re.search(re.escape(target)+r'|本公司|本集团',claim):
                if not re.search(r'子公司|行业|先生|女士',claim) and not NON_EVENT.search(claim):
                    add(atom,'event',claim,period=date,source_rank=rank,event_type=_event_kind(claim),status=_event_status(claim))
            if re.search(r'历史遗留|未决诉讼|权属纠纷|历史债务|违规担保',claim) and re.search(r'判决|立案|收到|发生|承担',claim):
                add(atom,'legacy',claim,period=date or str(atom.get('date') or ''),source_rank=rank)
    events=sorted([r for r in records if r['kind']=='event'],key=lambda r:(-r['source_rank'],r['period']))
    dedup=[]
    for r in events:
        if any(r['period']==old['period'] and r['event_type']==old['event_type'] and r['status']==old['status']
               and set(re.findall(r'\d+(?:\.\d+)?',r['fact']))==set(re.findall(r'\d+(?:\.\d+)?',old['fact']))
               and SequenceMatcher(None,compact(r['fact']),compact(old['fact'])).ratio()>.78 for old in dedup):
            counts['near_duplicate_event']+=1;continue
        dedup.append(r)
    topic_events=defaultdict(list)
    for r in dedup:
        if '发布' in r['fact']:
            for token in _release_topics(r['fact']):
                topic_events[token].append(r)
    time_conflicts=[];conflict_events=[]
    for token,rows in topic_events.items():
        years={r['period'][:4] for r in rows}
        if len(years)>1 and len(years)<=3 and any(r.get('date_basis')=='year_heading' for r in rows):
            chosen_rows=[]
            for year in sorted(years):
                row=next(r for r in rows if r['period'].startswith(year))
                row['status']='来源时点差异待核验'
                chosen_rows.append(row)
            conflict_events+=chosen_rows
            time_conflicts.append({'topic':token,'periods':sorted(years),
                                   'evidence_ids':list(dict.fromkeys(e for r in chosen_rows for e in r['evidence_ids']))})
    # Balance start points, business milestones and recent capital actions.
    chosen=[]
    for event_type,quota in [('工商沿革',2),('创业起点（公司自述）',1),('业务动作',8),('资本事项',7)]:
        rows=[r for r in dedup if r['event_type']==event_type]
        if event_type=='工商沿革':
            rows.sort(key=lambda r:(bool(re.search(r'核准|拟议|签约',r['status'])),-r['source_rank'],
                                    0 if r['status']=='登记记录' or '营业执照' in r['fact'] else 1,r['period']))
            chosen+=rows[:quota]
        else:
            chosen+=_select_events(rows,quota)
    chosen.sort(key=lambda r:r['period'])
    chosen+=[r for r in conflict_events if r not in chosen]
    chosen.sort(key=lambda r:r['period'])
    metrics={}
    for r in sorted((r for r in records if r['kind']=='performance'),key=lambda r:-r['source_rank']):
        key=(r['period'],r['metric'])
        if key in metrics and (r['value'],r['previous_value'],r['unit'],r['yoy'])!=(metrics[key]['value'],metrics[key]['previous_value'],metrics[key]['unit'],metrics[key]['yoy']):
            counts['financial_conflict']+=1
            metrics[key]['conflict']=True
            metrics[key].setdefault('alternative_records',[]).append(r)
            metrics[key]['evidence_ids']=list(dict.fromkeys(metrics[key]['evidence_ids']+r['evidence_ids']))
        else:
            metrics.setdefault(key,r)
    periods=sorted({r['period'] for r in metrics.values()},key=_period_rank,reverse=True)[:3]
    chosen+=[r for r in metrics.values() if r['period'] in periods]
    chosen+=[r for r in records if r['kind']=='legacy'][:3]
    selected=[]
    for r in chosen:
        if len(json.dumps(selected+[r],ensure_ascii=False))<=max(0,limit-2500):
            selected.append(r)
        else:counts['budget_excluded']+=1
    gaps=[]
    if not any(r['kind']=='event' and r['event_type']=='业务动作' for r in selected):
        gaps.append('业务演进阶段尚缺可核对原始节点，需补充官网沿革、产品/产线投产或并购交割材料。')
    if not any(r['kind']=='performance' for r in selected):
        gaps.append('成长质量尚缺同口径经营数据，不能由融资、上市或产品发布推出收入利润持续增长。')
    gaps.append('历史遗留事项的完整覆盖需结合工商变更、并购交割、权属及债务/担保材料核对；本章未覆盖不等于不存在。')
    if counts['layout_noise']:
        gaps.append('部分沿革图的文字提取存在版面错乱，未据此建立日期与事件对应；需对原页进行OCR/版面核对。')
    if counts['financial_conflict']:
        gaps.append('相同报告期的经营数据存在来源差异，冲突指标仅并存待核验，不用于成长趋势判断。')
    if time_conflicts:
        gaps.append('部分发布节点在官网沿革与其他披露中的年份不同；需核对原版文件、发布地区及技术版本，不任选一个日期覆盖。')
    return {'version':VERSION,'target_name':target,'facts':selected,'information_gaps':gaps,'time_conflicts':time_conflicts,
            'diagnostic':{'candidate_claims':len(records),'delivered_claims':len(selected),
                          'by_kind':dict(Counter(r['kind'] for r in selected)),'filters':dict(counts)}}


def _trend(record):
    if record.get('conflict'):
        return None
    a=Decimal(record['value'].replace(',',''));b=Decimal(record['previous_value'].replace(',',''))
    return 1 if a>b else -1 if a<b else 0


def render_history(package):
    events=[r for r in package['facts'] if r['kind']=='event']
    performance=[r for r in package['facts'] if r['kind']=='performance']
    legacy=[r for r in package['facts'] if r['kind']=='legacy']
    lines=[f'## 3. {TITLE}','','### '+HEADINGS[0],'']
    lines+=_table(['事件日期','类型','原文事件','状态边界','来源'],[
        [r['period'],r['event_type'],r['fact'],r['status']+('；第三方资料记载' if r['source_rank']<3 else ''),refs(r)] for r in events])
    if events:
        lines+=['','登记成立、改制、签约、核准、发行和挂牌日期各按原文动作保留；“拟议/签约”不代表交割或资金到账。资本公积转增、送股不当作外部现金融资，原币金额、股份数量与每股价格不相互替代。']
        lines+=['官网沿革中的创业及产品表述属于公司自述，创业起点不替代登记成立日期；发布、投产、下线等动作本身不能证明市场认可或商业成功。所列为已取得材料中的代表节点，不能视为完整融资及变更记录。']
    for conflict in package.get('time_conflicts',[]):
        lines+=['- '+conflict['topic']+'发布节点的来源年份为'+'／'.join(conflict['periods'])+'，已并列标记待核验；需确认事件范围、地区及版本后再确定节点。'+refs(conflict)]
    lines+=['','### '+HEADINGS[1],'']
    by_period=defaultdict(dict)
    for r in performance:by_period[r['period']][r['metric']]=r
    rows=[]
    for period,items in sorted(by_period.items(),key=lambda x:_period_rank(x[0])):
        values=[];ids=[]
        for metric in METRICS:
            r=items.get(metric)
            if not r:values.append('本章未形成可核对数据');continue
            value=r['value']+r['unit']+'；上年同期'+r['previous_value']+r['unit']+(('；同比'+r['yoy']) if r['yoy'] else '')
            if r.get('conflict'):
                value+='；另有来源值：'+'／'.join(a['value']+a['unit']+'（上年同期'+a['previous_value']+a['unit']+'）' for a in r['alternative_records'])+'，差异待核验'
            values.append(value)
            ids+=r['evidence_ids']
        rows.append([period,*values,refs({'evidence_ids':list(dict.fromkeys(ids))})])
    lines+=_table(['数据期','营业收入','归母净利润','经营现金流净额','来源'],rows)
    if performance:
        lines+=['','年度与半年度分开，变化方向只比较源表同口径的本期和上年同期；不拿半年数与全年数相除，不自行换汇。']
        for period,items in sorted(by_period.items(),key=lambda x:_period_rank(x[0])):
            revenue=items.get(METRICS[0]);profit=items.get(METRICS[1]);cash=items.get(METRICS[2])
            if not revenue or not profit or _trend(revenue) is None or _trend(profit) is None:continue
            dr,dp=_trend(revenue),_trend(profit)
            if dr>0 and dp<0:judgment='收入同比增加、归母净利润同比减少，规模与利润表现分化，不能写成同步高增长。'
            elif dr<0 and dp<0:judgment='收入与归母净利润同比减少，不支持沿用持续快速增长的概括。'
            elif dr>0 and dp>0:judgment='收入与归母净利润同比增加；这只能说明对应时期的变化，不能自动证明未来增长持续性。'
            else:judgment='收入与归母净利润的变化分别按源表保留，不用单一增长标签替代。'
            cited=revenue['evidence_ids']+profit['evidence_ids']
            if cash and _trend(cash) is not None:
                if dr>0 and _trend(cash)<0:judgment+='经营现金流净额同比减少，仍需核对利润与现金的差异。'
                cited+=cash['evidence_ids']
            lines+=['- '+period+'：'+judgment+refs({'evidence_ids':list(dict.fromkeys(cited))})]
        lines+=['','融资、上市、投产与发布只证明对应动作；资本市场背书、品牌认可、技术壁垒、回款质量或上市合规性需各自的直接材料。']
    else:
        lines+=['','本章尚无可用于同口径比较的经营数据，成长质量待核验，不按公司规模或融资阶段补写增长结论。']
    lines+=['','### '+HEADINGS[2],'']
    if legacy:
        lines+=_table(['事件期','明确记载事项','来源'],[[r['period'] or '事件日期未载',r['fact'],refs(r)] for r in legacy])
    else:
        lines+=['本章尚未形成可核对的具体历史遗留事件明细；不能据此认定没有遗留问题、出资瑕疵或上市规范性问题。']
    lines+=['','### '+HEADINGS[3],'']
    lines+=['- '+gap for gap in package['information_gaps']]
    if any(r['status']!='原文记载已发生' and r['status']!='登记记录' for r in events):
        lines+=['- 对计划或签约事项核对后续交割、资金到账及登记完成材料，不以较早的拟议日期代替落地时间。']
    return '\n'.join(lines)


def history_errors(text,package):
    errors=[]
    if text.strip()!=render_history(package).strip():errors.append('第三章出现未受原文事件或比较数据支持的改写')
    allowed={eid for r in package['facts'] for eid in r['evidence_ids']}
    if set(EID.findall(text))-allowed:errors.append('第三章存在未知证据编号')
    if not package['facts']:errors.append('第三章没有可核对事件或成长数据')
    return errors
