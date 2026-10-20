"""Chapter 7: dated roles and actual personnel events, never faction inference."""
import json
import re
from collections import Counter,defaultdict
from datetime import date
from urllib.parse import urlparse

from .company_evidence import source_body,document_pages,pending_ocr_notice,without_sequence_footers
from .company_governance import cited_evidence_ids
from .company_governance import EID,_filing_period,_table,compact,get,refs,read_fields,present
from .company_business import _cell,_prose,_clean
from .company_history import _issuer_hosts
from .company_text import issuer_anchor, OriginalTextView, match_text

TITLE='核心管理团队风险研判'
HEADINGS=('管理层履历与岗位配置','任职变动与时间线','产业资源及明确关联关系','管理能力与团队掌控力评估','派系斗争、人事动荡与商业腐败信号','本章待核验事项')
VERSION='company-management-v3-roster-table-boundaries'
DATE=r'(?:20\d{2}年\d{1,2}月\d{1,2}日|20\d{2}[/.-]\d{1,2}[/.-]\d{1,2})'
PERSON=r'[\u4e00-\u9fff·]{2,8}'
ROLE=r'(?:董事长|副董事长|主席|副主席|非独立董事|独立非执行董事|独立董事|执行董事|非执行董事|职工董事|董事|总裁|总经理|副总裁|财务总监|董事会秘书|公司秘书|内部审计负责人|证券事务代表|首席(?:财务|法务|技术|运营|人才|执行|信息|风险|合规|科学)官|CEO|CFO|CTO|COO)'


def iso(value):
    m=re.fullmatch(r'(20\d{2})[年/.-](\d{1,2})[月/.-](\d{1,2})日?',_cell(value))
    if not m:return ''
    try:return date(*map(int,m.groups())).isoformat()
    except ValueError:return ''


def period_date(period):
    exact=iso(period)
    if exact:return exact
    explicit=re.search(r'截至(20\d{2}-\d{2}-\d{2})',period)
    if explicit:return iso(explicit[1])
    if '财年' in period:return ''
    y=re.search(r'20\d{2}',period)
    if not y:return ''
    return y[0]+('-06-30' if '半年度' in period else '-03-31' if '第一季度' in period else '-09-30' if '第三季度' in period else '-12-31')


def announcement_date(raw):
    t=_cell(raw)
    m=re.search(r'(?:董事会|特此公告[。！]?)('+DATE+')',t)
    if not m:m=re.search(r'(?:会议|职工代表大会)(?:于|时间[:：])('+DATE+')',t)
    return iso(m[1]) if m else ''


def issuer(source,target,hosts):
    meta=get(source,'source_metadata',{}) or {}
    if meta.get('entity_validation') in {'rejected','ambiguous','related_entity_context'}:return False
    host=(urlparse(str(get(source,'url'))).hostname or '').lower().removeprefix('www.')
    if not (host in hosts or any(host==d or host.endswith('.'+d) for d in ('cninfo.com.cn','szse.cn','sse.com.cn','hkexnews.hk'))):return False
    raw=str(get(source,'content') or '')[:3000]
    # A standalone issuer heading authenticates the document, not a search
    # title or a parent's name mentioned in a subsidiary biography.
    return issuer_anchor(raw,target)['matched']


def roster_rows(pages,period):
    rows=[];active=False;person='';status='';last_page=0
    for page in pages:
        if page['page']>last_page+1:active=False;person='';status=''
        for table in page.get('tables') or []:
            head=''.join(_cell(c) for row in table[:4] for c in row if c)
            if all(x in head for x in ('姓名','职务','任职状态','任期起始')):active=True;person='';status=''
            elif re.search(r'会议届次|会议名称|召开日期|披露日期|会议决议|董事出席会议|出席董事会',head):
                active=False;person='';status=''
            if not active:continue
            for raw_row in table:
                cells=[_cell(c) for c in raw_row if c and _cell(c)]
                if len(cells)>=7 and cells[1] in {'男','女'} and cells[2].isdigit():
                    name,_,_,role,state,start,end=cells[:7]
                    if not iso(start) or not position_role(role):continue
                    person=name;status=state
                elif person and len(cells)>=3 and position_role(cells[0]):
                    role=cells[0]
                    if cells[1] in {'现任','离任','任期满离任'}:state,start,end=cells[1:4] if len(cells)>=4 else ('','','')
                    else:state= status;start,end=cells[1:3]
                    if not iso(start):continue
                    status=state;name=person
                else:continue
                rows.append({'kind':'role','entity':name,'role':role,'status':state,'start':iso(start),'end':iso(end) or end,
                             'period':period,'as_of':period_date(period),'page':page['page'],
                             'fact':name+'：'+role+'；源表状态'+state+'；任期'+start+'至'+end,
                             'evidence_quote':' | '.join(cells),'mode':'法定报告任职表，现任仅指文件基准期'})
        last_page=page['page']
    return rows


def position_role(value):
    """A position may contain 董事; a 董事会会议 is still an event."""
    return bool(value and len(value)<=80 and re.search(ROLE+r'|监事|执行总裁|副总经理',value)
                and not re.search(r'会议|议案|决议|公告|召开|披露日期',value))


def simple_annual_roster_rows(pages,period):
    """Read an explicit name/age/title roster, never an award or meeting list.

    A report period orders disclosures; it does not supply a missing roster
    effective date or tenure. Native names/quotes and source titles are kept.
    """
    rows=[]
    for page in pages:
        text=match_text(page['text'])
        head=re.search(r'姓名\s*(?:[（(]\d+[）)]\s*)?年龄\s+(?:职位|职务)(?:\s*[╱/／]\s*职衔)?',text)
        if not head:continue
        context=text[max(0,head.start()-450):head.start()]
        if not re.search(r'董事[、，,及和\s]+高级管理人员',context) or re.search(r'候选|候任|拟聘',context):continue
        stop=re.search(r'(?m)^\s*†\s*[\u4e00-\u9fff]|履历资料|简历资料|注[:：]',text[head.end():])
        end=head.end()+stop.start() if stop else min(len(text),head.end()+2200)
        view=OriginalTextView(page['text'])
        pattern=(r'(?m)^[ \t]*(?P<name>[\u4e00-\u9fff·]{2,12}|[A-Za-z][A-Za-z. \'-]{2,70})[ \t]*'
                 r'(?:\n[ \t]*)?(?:[†*‡]\s*)?(?:\([a-z0-9]+\)\s*)*'
                 r'(?P<age>\d{1,3})[ \t]+(?P<role>[^\n]+)')
        for m in re.finditer(pattern,text[head.end():end]):
            role=m['role'].strip()
            if not position_role(role):continue
            offset=head.end();name=view.quote(offset+m.start('name'),offset+m.end('name')).strip()
            quote=view.quote(offset+m.start(),offset+m.end()).strip()
            rows.append({'kind':'role','entity':name,'role':role,'source_role':view.quote(offset+m.start('role'),offset+m.end('role')).strip(),
                         'source_age':m['age'],'status':'文件列示，名册时点未另载','start':'未绑定任期起始','end':'届期及生效条款按原表脚注核对',
                         'period':period,'as_of':'','document_period_end':period_date(period),'page':page['page'],
                         'roster_format':'simple_annual','temporal_basis':'roster_effective_date_not_stated',
                         'fact':name+'：'+role+'；本轮仅绑定文件列示，完整任期及精确时点待核',
                         'evidence_quote':quote,'mode':'原件姓名/年龄/职衔表；不以财年末代替任职生效日，不认定截至今天仍在任'})
    return rows


def narrative_annual_biographies(pages,names,period):
    if not names:return []
    name_key=lambda name:re.sub(r'\s+',' ',match_text(name)).casefold()
    normalized={name_key(name):name for name in names}
    alternatives='|'.join(re.escape(n).replace(r'\ ',r'\s+') for n in sorted(normalized,key=len,reverse=True))
    raw='';spans=[];active=False
    for page in pages:
        text=page['text'];matching=match_text(text)
        if not active:
            marker=re.search(r'履历资料|简历资料',matching)
            if not marker:continue
            text=OriginalTextView(text).quote(marker.end(),len(matching));active=True
        boundary=re.search(r'(?m)^\s*[B-D][.．]\s*(?:薪酬|报酬|董事会|员工|雇员)',match_text(text))
        if boundary:text=OriginalTextView(text).quote(0,boundary.start())
        spans.append((len(raw),page['page']));raw+=text+'\n'
        if boundary:break
    view=OriginalTextView(raw)
    matches=list(re.finditer(r'(?m)^\s*(?P<name>'+alternatives+r')(?=\s*(?:于|自|为|目前|曾|是|现任|has\b|is\b))',view.text,re.I))
    rows=[]
    for i,m in enumerate(matches):
        end=matches[i+1].start() if i+1<len(matches) else len(view.text)
        block=view.text[m.end():end]
        section=re.search(r'(?m)^\s*[^\n。；]{2,35}(?:合伙|制度|治理|薪酬|提名|委员会|股权激励|董事会)\s*$',block)
        if section:block=block[:section.start()]
        sentences=list(re.finditer(r'[^。]+[。]?',block));chosen=[];used=0
        for sentence in sentences:
            if used+len(sentence[0])>900 or m.end()+sentence.end()-m.start()>1200:break
            if re.search(r'加入|担任|毕业|学位|学历|曾任|历任|供职|任职|负责|大学|学院',sentence[0]):chosen.append(sentence);used+=len(sentence[0])
        if not chosen:continue
        finish=m.end()+chosen[-1].end();start=m.start();quote=view.quote(start,finish).strip()
        page=next(n for offset,n in reversed(spans) if offset<=len(view.quote(0,start)))
        used_pages=[n for offset,n in spans if len(view.quote(0,start))<=offset<len(view.quote(0,finish))]
        rows.append({'kind':'biography','entity':normalized[name_key(m['name'])],'period':period,'as_of':'',
                     'document_period_end':period_date(period),'page':page,'pages':list(dict.fromkeys([page]+used_pages)),
                     'fact':quote,'evidence_quote':quote,'biography_format':'narrative_annual',
                     'mode':'公司年报公开履历原文；既往经历不认定为当前任职或个人绩效'})
    return rows


def registered_roster_rows(governance,sources,target):
    """Reuse verified registration fields without promoting them to current jobs."""
    by_url={str(get(s,'url') or ''):s for s in sources or []};rows=[]
    for row in (governance or {}).get('facts',[]):
        if row.get('kind')!='personnel' or row.get('evidence_scope')!='target_direct' or row.get('eligible_for_report') is False:continue
        source=by_url.get(str(row.get('source_url') or ''));meta=get(source,'source_metadata',{}) or {}
        if meta.get('tool')!='get_key_personnel' or meta.get('entity_validation')!='verified':continue
        url=str(get(source,'url') or '')
        if not (url.startswith('structured://') or str(meta.get('content_kind') or '').startswith('structured_data')):continue
        fields,_=read_fields(source_body(source)[0])
        if compact(fields.get('企业名称',''))!=compact(target):continue
        name,role=str(row.get('entity') or ''),str(row.get('role') or '')
        if not present(name) or not present(role) or len(role)>160 or re.search(r'会议|议案|决议|公告|召开|披露日期',role):continue
        period=str(row.get('period') or '')
        if period in {'数据基准日未载','未载','未披露'}:period=''
        rows.append({**row,'kind':'registered_role','as_of':'','period':period,
                     'temporal_basis':'platform_registered_snapshot' if period else 'undated_platform_snapshot',
                     'fact':name+'：平台本次返回的主要人员原职务字段为'+role+'；数据基准日'+(period or '未载')+'。',
                     'mode':'已核对目标企业名称的平台注册主要人员表；不等于独立工商档案核查、正式任命或完整现任团队'})
    return rows


def platform_team_profiles(cleaned,sources,target):
    """Keep explicitly returned team descriptions separate from formal jobs."""
    cards=defaultdict(list)
    for c in cleaned.get('facts') or []:
        if (isinstance(c,dict) and EID.fullmatch(str(c.get('evidence_id') or ''))
                and c.get('eligible_for_report') is not False
                and c.get('evidence_scope')=='target_direct'
                and c.get('entity_match') not in {'mismatch','ambiguous','out_of_scope'}
                and c.get('source_entity_validation')!='rejected'):
            cards[str(c.get('source_url') or '')].append(c)
    result=[];seen=set()
    for source in sources or []:
        url=str(get(source,'url') or '');meta=get(source,'source_metadata',{}) or {}
        if (meta.get('provider')!='xiniu' or meta.get('tool')!='get_company_info'
                or meta.get('entity_validation')!='verified' or not url.startswith('structured://') or not cards[url]):continue
        raw=source_body(source)[0];fields,rows=read_fields(raw)
        if compact(fields.get('企业名称',''))!=compact(target):continue
        c=cards[url][0]
        for row in rows:
            if not all(k in row for k in ('职位','姓名','教育经历','介绍')):continue
            name,role=str(row['姓名']),str(row['职位'])
            if not present(name) or not present(role) or len(name)>80 or len(role)>160:continue
            quote=next((line.strip() for line in raw.splitlines() if line.strip().startswith('|') and name in line and role in line),'')
            key=(name,role,row['教育经历'],row['介绍'])
            if not quote or key in seen:continue
            seen.add(key)
            result.append({'kind':'platform_team_profile','entity':name,'role':role,'education':row['教育经历'],
                           'profile':row['介绍'],'period':fields.get('数据日期') or '', 'as_of':'',
                           'fact':name+'；平台职位原字段：'+role+'；平台教育原字段：'+row['教育经历']+'；平台介绍：'+row['介绍'],
                           'evidence_quote':quote,'source_url':url,'source_title':c.get('source_title',''),
                           'evidence_id':c['evidence_id'],'evidence_ids':[c['evidence_id']],'evidence_scope':'target_direct',
                           'mode':'平台二次整理的团队人物描述；非独立履历核验、正式任命或截至查询日的完整现任团队'})
    return result


def change_rows(pages,period):
    rows=[];person=''
    for page in pages:
        for table in page.get('tables') or []:
            head=''.join(_cell(c) for row in table[:2] for c in row if c)
            if not all(x in head for x in ('姓名','担任的职务','类型','日期','原因')):continue
            for raw_row in table:
                c=[_cell(x) for x in raw_row if x is not None]
                nonempty=[x for x in c if x]
                if len(nonempty)==5 and iso(nonempty[3]):person,role,action,when,reason=nonempty
                elif person and len(nonempty)==4 and iso(nonempty[2]):role,action,when,reason=nonempty
                else:continue
                rows.append({'kind':'change','entity':person,'role':role,'action':action,'start':iso(when),'as_of':iso(when),
                             'period':period,'reason':reason,'page':page['page'],'mode':'法定报告人员变动表',
                             'fact':person+'：'+role+'；'+action+'；'+when+'；原因原文：'+reason,'evidence_quote':' | '.join(nonempty)})
    return rows


def appointments(pages,raw):
    when=announcement_date(raw)
    if not when:return []
    rows=[]
    # Signature dates identify the announcement, while each action must be
    # an adopted resolution or an explicitly elected candidate.
    for page in pages:
        t=_cell(page['text'])
        for m in re.finditer(r'(?:董事会同意|同意)(?:选举|聘任)(?P<names>(?:'+PERSON+r'(?:先生|女士)[、，,]?)+)为(?P<role>[^，。；（(]{2,45})',t):
            role=re.sub(r'^本?公司','',m['role'])
            # Board ordinal is context, not part of a position name.
            role=re.sub(r'^第[一二三四五六七八九十0-9]+届董事会','',role)
            if not re.fullmatch(ROLE+r'(?:(?:兼|及|、|和)'+ROLE+r')*',role):continue
            names=re.findall(r'('+PERSON+r')(?:先生|女士)',m['names'])
            term=re.search(r'任期[一二三四五六七八九十两0-9]+年[^。]{0,160}(?:。|$)',t[m.end():])
            for name in names:
                rows.append({'kind':'appointment','entity':name,'role':role,'action':'正式选举/聘任决议','start':when,'end':term[0].rstrip('。') if term else '按原公告任期条款核对',
                             'status':'任命/当选披露','as_of':when,'period':when,'page':page['page'],'fact':m[0],
                             'evidence_quote':m[0],'mode':'公司已通过决议，非候选提名'})
    # Election results can span physical pages; retain the per-row page and
    # role category from the actual adopted proposal, not the word candidate.
    category=''
    for page in pages:
        text=page['text'];flat=_cell(text)
        if '关于公司董事会换届选举非独立董事的议案' in flat and '表决结果：通过' in flat:category='非独立董事'
        for segment in re.split(r'(关于公司董事会换届选举独立董事的议案|关于公司董事会换届选举非独立董事的议案)',text):
            if '换届选举' in _cell(segment) and len(_cell(segment))<40:
                category='非独立董事' if '非独立' in _cell(segment) else '独立董事';continue
            for m in re.finditer(r'('+PERSON+r')(?:先生|女士)[\d,.%\s]+当选',segment):
                if not category:continue
                rows.append({'kind':'appointment','entity':m[1],'role':category,'action':'股东会表决当选','start':when,'end':'按换届公告任期条款核对',
                             'status':'任命/当选披露','as_of':when,'period':when,'page':page['page'],'fact':m[0],
                             'evidence_quote':m[0],'mode':'股东会实际表决结果'})
    return rows


def biography_rows(pages,names,period,target):
    text='';spans=[]
    prose_pages=without_sequence_footers(pages)
    for page in prose_pages:
        body=_prose(_clean(page['text'],target));spans.append((len(text),page['page']));text+=body+'\n'
    alternatives='|'.join(re.escape(n) for n in sorted(names,key=len,reverse=True))
    if not alternatives:return []
    pattern=r'(?P<name>'+alternatives+r')(?:先生|女士)?[，,](?=[男女一二三四五六七八九十〇零0-9]|中国|硕士|博士)'
    matches=list(re.finditer(pattern,text));rows=[]
    for i,m in enumerate(matches):
        block=text[m.end():matches[i+1].start() if i+1<len(matches) else len(text)]
        # Qualifying declarations are separate from professional experience.
        block=re.split(r'截至目前|且不存在以下|与持有公司|董事、高级管理人员报告期内',block)[0]
        selected=[];last_offset=0
        for match in re.finditer(r'[^。；]+[。；]?',block):
            sentence=match[0]
            if not re.search(r'毕业|学位|学历|曾任|历任|加入|创办|创立|任职|供职|现任|负责|担任',sentence):continue
            if re.search(r'入选|榜单|最具影响力|法》|任职资格',sentence):continue
            if sum(map(len,selected))+len(sentence)>680:break
            selected.append(sentence);last_offset=match.end()
        fact=_prose(''.join(selected)).strip()
        if not fact:continue
        page=next(n for start,n in reversed(spans) if start<=m.start())
        end=m.end()+last_offset;used=[n for start,n in spans if m.start()<=start<=end]
        rows.append({'kind':'biography','entity':m['name'],'period':period,'as_of':period_date(period) or period,
                     'page':page,'pages':list(dict.fromkeys([page]+used)),'fact':fact,'evidence_quote':fact,
                     'source_text_transformations':[change for p in prose_pages if p['page'] in [page]+used
                                                    for change in p.get('source_text_transformations',[])],
                     'mode':'公司公开履历自述，历史经历不等于现职或个人业绩核验'})
    return rows


def relationship_rows(pages,names,period,target):
    rows=[];context='';context_age=0
    for page in pages:
        text=_cell(_clean(page['text'],target))
        for sentence in re.split(r'(?<=[。；])',text):
            context_age+=len(sentence)
            if context_age>2000:context=''
            for n in names:
                if re.search(re.escape(n)+r'(?:先生|女士)，[一二三四五六七八九十〇零0-9]',sentence):context=n;context_age=0
            sentence=re.split(r'且不存在以下情形',sentence)[0]
            sentence=re.sub(r'^.*?关联关系或一致行动的说明\d*[、.]?','',sentence)
            mentioned=sorted((n for n in names if n in sentence),key=sentence.find)
            abbreviated=re.match(r'^([\u4e00-\u9fff])(?:先生|女士)',sentence)
            if abbreviated:
                if not context or not context.startswith(abbreviated[1]):continue
                if context not in mentioned:mentioned=[context]+mentioned
            if len(mentioned)<2 or not re.search(r'兄弟|兄长|姐妹|夫妻|父子|父女|母子|母女|表兄|表姐|表弟|表妹|表亲|亲属|一致行动',sentence):continue
            if not 10<=len(sentence)<=550:continue
            rows.append({'kind':'relationship','entity':'、'.join(mentioned),'subject':context if abbreviated else mentioned[0],
                         'period':period,'as_of':period_date(period) or period,
                         'page':page['page'],'fact':sentence,'evidence_quote':sentence,'mode':'公司明确关系披露，非派系或利益输送认定'})
    return rows


def outside_roles(pages,period):
    rows=[];active=False;category='';last=0
    for page in pages:
        if page['page']>last+1:active=False
        for table in page.get('tables') or []:
            header=''.join(_cell(c) for row in table[:3] for c in row if c)
            if '任职人员姓名' in header and ('股东单位名称' in header or '其他单位名称' in header):
                active=True;category='股东单位' if '股东单位名称' in header else '其他单位'
            elif any(w in header for w in ('税前报酬','董事出席','任职状态')):active=False
            if not active:continue
            for raw_row in table:
                c=[_cell(x) for x in raw_row if x and _cell(x)]
                if len(c)!=6 or not re.search(ROLE+r'|主席|总经理|合伙人',c[2]) or c[-1] not in {'是','否'}:continue
                if not re.fullmatch(PERSON,c[0]) or not re.search(r'20\d{2}',c[3]):continue
                rows.append({'kind':'outside_role','entity':c[0],'organisation':c[1],'role':c[2],'start':iso(c[3]) or c[3],
                             'end':iso(c[4]) or c[4],'remunerated':c[5],'period':period,'as_of':period_date(period),
                             'page':page['page'],'fact':' | '.join(c),'evidence_quote':' | '.join(c),
                             'mode':category+'任职字段，不推导控制权或商业合作'})
        last=page['page']
    return rows


def build_management_package(cleaned,target,sources=None,*,limit=160000,governance=None):
    by_url=defaultdict(list)
    for c in cleaned.get('facts') or []:
        if isinstance(c,dict) and EID.fullmatch(str(c.get('evidence_id') or '')):by_url[str(c.get('source_url') or '')].append(c)
    hosts=_issuer_hosts(sources,target);records=[];documents=[];counts=Counter()
    for source in sources or []:
        raw,origin=source_body(source);url=str(get(source,'url'))
        if origin=='discovery_summary' or not issuer(source,target,hosts):continue
        cards=[c for c in by_url[url] if c.get('eligible_for_report') is not False and c.get('entity_match') not in {'mismatch','ambiguous','out_of_scope'} and c.get('source_entity_validation')!='rejected']
        if not cards:continue
        c=cards[0];period=_filing_period({'content':raw,'title':''}) or announcement_date(raw)
        if not period:continue
        pages=document_pages(source);roster=roster_rows(pages,period)
        simple=simple_annual_roster_rows(pages,period) if not roster and '财年' in period else []
        base=roster+simple+change_rows(pages,period)+outside_roles(pages,period)
        if not _filing_period({'content':raw,'title':''}):base+=appointments(pages,raw)
        documents.append((c,pages,period,{r['entity'] for r in simple}));records.extend((c,r) for r in base)
        ext=(get(source,'source_metadata',{}) or {}).get('document_extraction') or {}
        counts['omitted_pages']+=int(ext.get('omitted_pages') or 0);counts['needs_ocr_pages']+=len(ext.get('needs_ocr_pages') or [])
        counts['table_pages_pending']+=len((ext.get('management_tables') or {}).get('pending_pages') or [])
    names={r['entity'] for c,r in records if r['kind'] in {'role','change','appointment'}}
    for c,pages,period,simple_names in documents:
        bios=biography_rows(pages,names,period,target)
        bios+=narrative_annual_biographies(pages,simple_names-{r['entity'] for r in bios},period)
        records.extend((c,r) for r in bios+relationship_rows(pages,names,period,target))
    unique=[];seen={}
    for c,r in records:
        key=json.dumps({k:v for k,v in r.items() if k not in {'page','pages','evidence_quote'}},ensure_ascii=False,sort_keys=True)
        location={'evidence_id':c['evidence_id'],'source_url':c['source_url'],'page':r['page'],'pages':r.get('pages') or [r['page']]}
        if key in seen:
            seen[key]['evidence_ids']=list(dict.fromkeys(seen[key]['evidence_ids']+[c['evidence_id']]))
            if location not in seen[key]['evidence_locations']:seen[key]['evidence_locations'].append(location)
            counts['duplicate_claim']+=1;continue
        r.update(evidence_id=c['evidence_id'],evidence_ids=[c['evidence_id']],source_url=c['source_url'],source_title=c.get('source_title',''),evidence_scope='target_direct')
        r['evidence_locations']=[location]
        seen[key]=r;unique.append(r)
    selected=[]
    for kind in ('role','appointment','change'):
        selected.extend(r for r in unique if r['kind']==kind)
    relations={}
    for r in sorted([r for r in unique if r['kind']=='relationship'],key=lambda x:x['as_of'],reverse=True):
        key=tuple(sorted(r['entity'].split('、')))
        previous=relations.get(key)
        if previous is None:relations[key]=[r]
        elif r['as_of']==previous[0]['as_of'] and r['fact'] not in {x['fact'] for x in previous}:previous.append(r)
        else:counts['older_or_duplicate_relationship']+=1
    for rows in relations.values():selected.extend(rows)
    # Keep each named person's latest biography. Do not reduce the roster to
    # financial signatories, or carry a prior director class into a new term.
    bios={}
    for r in sorted([r for r in unique if r['kind']=='biography'],key=_observation_date,reverse=True):bios.setdefault(r['entity'],r)
    selected.extend(bios.values())
    selected.extend([r for r in unique if r['kind']=='outside_role'][:24])
    registered=[];platform_profiles=[]
    if not any(r['kind'] in {'role','appointment'} for r in selected):
        registered=registered_roster_rows(governance,sources,target)
        selected.extend(registered)
        platform_profiles=platform_team_profiles(cleaned,sources,target)
        selected.extend(platform_profiles)
    delivered=[]
    for r in selected:
        if len(json.dumps(delivered+[r],ensure_ascii=False))<=max(0,limit-4000):delivered.append(r)
        else:counts['budget_excluded']+=1
    gaps=['补核报告基准日之后的任命、续聘、辞任及生效条件；文件中的“现任”不保证截至今天仍在任。',
          '核对关键岗位实际授权、继任梯队、交接及履职结果；团队履历和集团业绩不能直接证明个人贡献或团队掌控力。',
          '对具体管理人员核对事件主体、日期、程序阶段、责任与处置结果；关联企业数量、同姓、共同任职或亲属关系本身不等于派系、腐败或利益输送。',
          '工商人员、董事会、法定高管及财务签署人范围分别核对，不把单一接口名单视为完整团队。']
    if counts['table_pages_pending']:gaps.append('部分人员表格页尚未完成单元格提取；未选到任职字段不能写为企业未披露。')
    if counts['omitted_pages']:gaps.append('原件提取尚未覆盖全文；仅以已取得原页作核对。')
    if counts['needs_ocr_pages']:gaps.append(pending_ocr_notice(sources,'低文字页尚未执行OCR，不能据此认定缺少履历或人员信息。'))
    if counts['budget_excluded']:gaps.append('本章预算未容纳全部已识别记录，不能根据展示名单推断其余岗位不存在。')
    if any(r.get('roster_format')=='simple_annual' for r in delivered):gaps.append('简式年报名册的完整任期与精确时点尚未逐人绑定；届期及生效条款需结合原表脚注复核，不把财年截止日当任职生效日。')
    if registered:gaps.append('本次已得平台注册主要人员记录，但正式任命、完整任期和个人履历仍待核对；登记职务不直接等于创始人、业务负责人、实际控制人或完整现任团队。')
    if platform_profiles:gaps.append('平台团队描述与登记人员范围不同，未逐人核验学历、经历及离职/在任时间；不将创始人描述替代登记职务或实际控制证明。')
    return {'version':VERSION,'target_name':target,'facts':delivered,'information_gaps':gaps,
            'diagnostic':{'candidate_claims':len(records)+len(registered)+len(platform_profiles),'delivered_claims':len(delivered),'by_kind':dict(Counter(r['kind'] for r in delivered)),'filters':dict(counts)}}


def _observation_date(row):
    return row.get('as_of') or row.get('document_period_end') or ''


def latest_roles(records):
    announcements=[r for r in records if r['kind']=='appointment']
    board_elections=[r for r in announcements if r['action']=='股东会表决当选']
    dates={r['as_of'] for r in board_elections}
    reset=max((d for d in dates if {'独立董事','非独立董事'}<={r['role'] for r in board_elections if r['as_of']==d}),default='')
    people=defaultdict(list)
    candidates=[r for r in records if r['kind'] in {'role','appointment'}]
    for r in records:
        if r['kind']=='change' and re.search(r'离任|辞任|辞职|解聘|免职|聘任|被选举',r['action']):
            leaving=bool(re.search(r'离任|辞任|辞职|解聘|免职',r['action']))
            candidates.append({**r,'status':'离任' if leaving else '变动表任职披露','end':r['start'] if leaving else '源表未载终止日'})
    for r in sorted(candidates,key=lambda r:(_observation_date(r),r['kind']=='appointment'),reverse=True):
        if not position_role(r['role']):continue
        for role in re.split(r'、|兼|及',r['role']):
            # A chair appointment does not itself reclassify independent vs
            # non-independent directorship, and a company secretary is not
            # automatically replaced by a board-secretary appointment.
            family=('board_secretary' if role=='董事会秘书' else
                    'company_secretary' if role=='公司秘书' else
                    'board_leadership' if '董事长' in role else
                    'board_class' if '董事' in role else
                    'vice_president' if '副总裁' in role else role)
            people[r['entity']].append({**r,'role':role,'family':family})
    result=[]
    for person,rows in people.items():
        newest={family:max(_observation_date(r) for r in rows if r['family']==family) for family in {r['family'] for r in rows}}
        chosen=[r for r in rows if _observation_date(r)==newest[r['family']] and r.get('status') not in {'离任','任期满离任'}]
        if reset:chosen=[r for r in chosen if _observation_date(r)>=reset or r['family'] not in {'board_class','board_leadership'}]
        if chosen:result.append((person,chosen))
    return result


def _locations(rows):
    """Cite a source once with all supporting physical pages."""
    locations={}
    for r in rows:
        # The physical page here belongs to the primary original. Alternate
        # sources may paginate differently; keep their individual locations
        # in the package instead of attaching this page to every citation.
        for eid in r['evidence_ids'][:1]:
            locations.setdefault(eid,[])
            for page in r.get('pages') or [r['page']]:
                if page not in locations[eid]:locations[eid].append(page)
    return '；'.join('['+eid+']（物理页'+ '、'.join(map(str,sorted(pages)))+'）' for eid,pages in locations.items())


def _term_text(row):
    # Attachment pointers are not tenure terms. The complete untouched field
    # remains in the evidence package alongside the original page and quote.
    text=re.sub(r'（[^（）]*简历详见附件[^（）]*）','',row.get('end') or '').strip()
    if not text or text.startswith('按'):
        return '终止条款待按原公告核对'
    return text


def _role_parts(row):
    return [x for x in re.split(r'、|兼|及',row['role']) if x]


def render_management(p):
    facts=p['facts'];lines=['## 7. '+TITLE,'','### '+HEADINGS[0],'']
    roster=latest_roles(facts);bios={r['entity']:r for r in facts if r['kind']=='biography'}
    if roster:
        lines+=['已得任职披露涉及'+str(len(roster))+'名人员，含董事、高管及其他岗位；不将此数直接当作完整法定高管人数。','']
        if any(r.get('roster_format')=='simple_annual' for _,rows in roster for r in rows):
            lines+=['简式年报名册仅表示原件列示；其完整任期和精确时点未逐人绑定。财年截止日只用于排列文件期，不当任职生效日；个别届期及生效信息仍需结合原表脚注核对。','']
        shared={r['period'] if r['kind']=='role' else r['as_of'] for _,rows in roster for r in rows}
        common_date=next(iter(shared)) if len(shared)==1 else ''
        if common_date:lines+=['下表各岗位已得最新任职披露的公告日／文件期均为'+common_date+'；任期条款集中列于表后，履历仅摘录教育及既往经历。','']
        lines+=_table(['姓名','职务／披露时点','履历要点（公司自述）','出处'],[
            [name,'；'.join(dict.fromkeys(r['role']+('' if common_date else '（'+(r['period'] if r['kind']=='role' else r['as_of'])+'）') for r in rows)),
             biography_excerpt(bios[name],rows) if name in bios else '未选到可绑定个人的履历，不能据此认定公司未披露。',
             _locations(rows+([bios[name]] if name in bios else []))] for name,rows in roster])
        terms={}
        for name,rows in roster:
            for r in rows:
                key=(r['start'],_term_text(r))
                terms.setdefault(key,[]).append(r)
        lines+=['','任期对应（共同条款只列一次；不推算日历终止日）：','']
        lines+=_table(['起始字段','对应人员及职务','终止字段／条款','出处'],[
            [key[0],'；'.join(name+'（'+'、'.join(dict.fromkeys(r['role'] for r in rows if r['entity']==name))+'）' for name in dict.fromkeys(r['entity'] for r in rows)),key[1],_locations(rows)]
            for key,rows in terms.items()])
        lines+=['','任职表保留各职位的最新已得披露，文件时点不同不保证同时有效，亦不保证今天状态。董事类别、董事长/副董事长、董秘/公司秘书分别更新，不由一个岗位的续聘推断其他岗位续任或董事类别变更。年报标签指该文件任职披露，未另认定为精确年末时点；任期起始字段不直接当本届董事会统一起始日。财务签署人名单不代表完整高管名单。']
    else:lines+=['尚未形成可绑定任职时点的正式人员表；不以搜索简介或财务签字名单补造完整团队。']
    registered=[r for r in facts if r['kind']=='registered_role']
    if registered:
        lines+=['','本次平台返回的主要人员登记快照（独立列示，不当作正式任命或完整现任团队）：','']
        lines+=_table(['姓名','平台原职务字段','数据基准日及边界','出处'],[
            [r['entity'],r['role'],(r['period'] or '未载')+'；仅为本次平台返回登记记录',refs(r)] for r in registered])
        lines+=['','数据基准日未载时不能按查询日认定仍在任。登记职务、业务负责人、创始人及实际控制人分别核对，不将“财务负责人”直接改写为CFO，也不由登记名册推断个人贡献或团队稳定性。']
    profiles=[r for r in facts if r['kind']=='platform_team_profile']
    if profiles:
        lines+=['','平台另载团队人物描述（与上面的登记人员范围不同，未经独立履历核验）：','']
        lines+=_table(['姓名','平台职位／教育原字段','平台介绍原文','日期及边界／来源'],[
            [r['entity'],r['role']+'；'+r['education'],r['profile'],(r['period'] or '数据基准日未载')+'；平台二次整理，任职/离职时间待核；'+refs(r)] for r in profiles])
        lines+=['','原职务中的“已离职”等限定按平台返回保留，不推定具体离职日期或团队流失率；创始人、技术负责人、登记人员及实际控制人分别核对。此表不证明其学历经历、个人绩效或截至查询日仍在任。']
    lines+=['','### '+HEADINGS[1],'']
    changes=[r for r in facts if r['kind'] in {'change','appointment'}]
    if changes:
        latest={(name,r['as_of'],r['role']) for name,rows in roster for r in rows}
        represented=[r for r in changes if r['kind']=='appointment' and all((r['entity'],r['as_of'],role) in latest for role in _role_parts(r))]
        summaries={}
        for r in represented:summaries.setdefault((r['start'],r['action']),[]).append(r)
        for key,rows in summaries.items():
            lines+=['- '+key[0]+'：'+key[1]+'，涉及'+str(len({r['entity'] for r in rows}))+'名人员；具体人员、岗位及任期见上表。'+_locations(rows)]
        changes=[r for r in changes if r not in represented]
        grouped={}
        for r in sorted(changes,key=lambda x:x['start'],reverse=True):
            key=(r['start'],r['role'],r['action'],r.get('reason') or r['mode'])
            if key not in grouped:grouped[key]=[r]
            elif r['entity'] not in {x['entity'] for x in grouped[key]}:grouped[key].append(r)
        if grouped:lines+=_table(['人员','职务','日期／动作','原因与边界','出处'],[
            ['、'.join(r['entity'] for r in rows),key[1],key[0]+'；'+key[2],key[3],
             ' '.join(dict.fromkeys(refs(r)+f"（物理页{r['page']}）" for r in rows))] for key,rows in grouped.items()])
        lines+=['','聘任、升迁、岗位调整、换届、治理架构调整与离任分开；候选提名不当正式任职，正常离任不直接判为内斗或动荡。历史人员表不覆盖更新后的董事独立性类别。']
    else:lines+=['未选到可绑定具体人员与日期的变动记录，不等于无变动。']
    lines+=['','### '+HEADINGS[2],'']
    relationships=[r for r in facts if r['kind']=='relationship']
    for r in relationships:
        subject='（'+r['subject']+'相关原文）' if r.get('subject') else ''
        lines+=['- '+r['period']+'公司披露'+subject+'：'+r['fact']+' '+refs(r)+f"（物理页{r['page']}）"]
    outside=[r for r in facts if r['kind']=='outside_role']
    if outside:
        lines+=_table(['人员','披露兼职单位及职务','统计期／任期字段','是否领取报酬津贴','出处'],[
            [r['entity'],r['organisation']+'：'+r['role'],r['period']+'；'+r['start']+'至'+r['end'],r['remunerated'],refs(r)+f"（物理页{r['page']}）"] for r in outside])
    if not relationships and not outside:lines+=['尚未形成可逐项绑定的公开关系/兼职记录；不从关联企业总数补造控制、合作或亲属关系。']
    lines+=['','兼职、教育经历及前雇主可作为后续能力访谈线索，不能据此证明客户资源、商业合作、控制权或个人商业化贡献。股权比例、名义持有人及控制关系以第二章已核对字段为准，不由持股比例阈值或共同创始经历自行认定。',
            '','### '+HEADINGS[3],'','已得履历只支持对应教育、工作经历和岗位职责。公司营收、研发投入、员工规模、估值和展会活动不足以归因到某位高管的战略能力、执行力或利益联盟；仍需具体决策、授权、业务结果及独立反馈核对。',
            '','### '+HEADINGS[4],'','本章尚未形成同时绑定具体人员、事件日期、程序状态和处置结果的独立风险记录，不能据此判断不存在风险。任职资格附件中的“未受处罚/不存在所列情形”属于公司声明，不能改写为本项目完成司法、制裁或廉洁核验，也不能把条款列举当作已发生处罚。公司层面的案件、诉讼数量或数据库自身风险条数不直接归为管理人员个人责任；具体事件见第九章核对与后续穿透。',
            '','供应商、采购与经销商的稳定/无腐败结论不由本章模板示例推导；只有涉及明确管理人员的关系及具体行为证据才能支持相应判断。',
            '','### '+HEADINGS[5],'']+['- '+g for g in p['information_gaps']]
    return '\n'.join(lines)


def biography_excerpt(bio,roles):
    text=bio['fact']
    if bio.get('biography_format')=='narrative_annual':
        sentences=[x.strip() for x in re.findall(r'[^。]+[。]?',text) if x.strip()]
        education=[x for x in sentences if re.search(r'毕业|学位|学历',match_text(x))]
        career=[x for x in sentences if re.search(r'曾任|曾担任|历任|加入|创办|创立|任职|供职',match_text(x))]
        chosen=[]
        for sentence in education[:1]+career[:2]:
            if sentence not in chosen and sum(map(len,chosen))+len(sentence)<=260:chosen.append(sentence)
        prefix='' if {r['as_of'] for r in roles}=={bio['as_of']} else bio['period']+'履历：'
        return prefix+('；'.join(x.rstrip('。') for x in chosen) or '教育及既往经历详见原履历')+'（节选；完整履历见证据包）'
    # Current posts are already in the dated roster and outside-role table.
    # Repeating them here obscures education/prior experience and may revive
    # an older title. Preserve the full biography in the package, not the body.
    text=re.sub(r'(?:现任|目前担任)[^。；]*(?:[。；]|$)','',text)
    text=re.sub(r'(?:自)?[一二三四五六七八九〇零\d]{4}年[^。；]{0,35}至今(?:任|担任)[^。；]*(?:[。；]|$)','',text)
    clauses=[x.strip('，,。；; ') for x in re.split(r'[，,。；;]',text) if x.strip('，,。；; ')]
    matching=match_text if bio.get('biography_format')=='narrative_annual' else lambda x:x
    schools=[x for x in clauses if '毕业' in matching(x)]
    qualifications=[x for x in clauses if re.search(r'学位|学历',matching(x)) and '毕业' not in matching(x)]
    education=schools[:1]+qualifications[:1]
    # Prefer the actual school/degree over birth, nationality, honours or
    # society titles. Prior employment is a separate dated career excerpt.
    career=[x for x in clauses if re.search(r'曾任|历任|加入|创办|创立|任职|供职',matching(x))]
    pieces=[]
    for group in (education[:2],career[:2]):
        for part in group:
            if part not in pieces and sum(map(len,pieces))+len(part)<=140:pieces.append(part)
    excerpt='；'.join(pieces)
    period='' if {r['as_of'] for r in roles}=={bio['as_of']} else bio['period']+'履历：'
    return period+(excerpt or '教育及既往经历详见原履历')+'（节选；完整履历见证据包）'


def management_errors(text,p):
    errors=[]
    if text.strip()!=render_management(p).strip():errors.append('第七章出现未受任职与履历证据支持的改写')
    if not any(r['kind'] in {'role','appointment','change','registered_role','platform_team_profile'} for r in p['facts']):errors.append('第七章尚无可核对的管理团队记录')
    if any(r['kind'] in {'role','appointment','change'} and not position_role(r['role']) for r in p['facts']):errors.append('第七章任职字段含会议或其他非职务内容')
    allowed={e for r in p['facts'] for e in r['evidence_ids']}
    if set(cited_evidence_ids(text))-allowed:errors.append('第七章存在未知证据编号')
    return errors
