"""Chapter 7: dated roles and actual personnel events, never faction inference."""
import json
import re
from collections import Counter,defaultdict
from datetime import date
from urllib.parse import urlparse

from .company_evidence import source_body,document_pages,pending_ocr_notice
from .company_governance import EID,_filing_period,_table,compact,get,refs
from .company_business import _cell,_prose,_clean
from .company_history import _issuer_hosts

TITLE='核心管理团队风险研判'
HEADINGS=('管理层履历与岗位配置','任职变动与时间线','产业资源及明确关联关系','管理能力与团队掌控力评估','派系斗争、人事动荡与商业腐败信号','本章待核验事项')
VERSION='company-management-v1'
DATE=r'(?:20\d{2}年\d{1,2}月\d{1,2}日|20\d{2}[/.-]\d{1,2}[/.-]\d{1,2})'
PERSON=r'[\u4e00-\u9fff·]{2,8}'
ROLE=r'(?:董事长|副董事长|非独立董事|独立非执行董事|独立董事|执行董事|非执行董事|职工董事|董事|总裁|总经理|副总裁|财务总监|董事会秘书|公司秘书|内部审计负责人|证券事务代表|首席(?:财务|技术|运营|人才|执行|信息|风险|合规|科学)官|CEO|CFO|CTO|COO)'


def iso(value):
    m=re.fullmatch(r'(20\d{2})[年/.-](\d{1,2})[月/.-](\d{1,2})日?',_cell(value))
    if not m:return ''
    try:return date(*map(int,m.groups())).isoformat()
    except ValueError:return ''


def period_date(period):
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
    name=r'\s*'.join(map(re.escape,str(target).strip()))
    return bool(re.search(r'(?m)^\s*'+name+r'\s*(?:\n|20\d{2}\s*年)',raw))


def roster_rows(pages,period):
    rows=[];active=False;person='';status='';last_page=0
    for page in pages:
        if page['page']>last_page+1:active=False;person='';status=''
        for table in page.get('tables') or []:
            head=''.join(_cell(c) for row in table[:4] for c in row if c)
            if all(x in head for x in ('姓名','职务','任职状态','任期起始')):active=True;person='';status=''
            if not active:continue
            for raw_row in table:
                cells=[_cell(c) for c in raw_row if c and _cell(c)]
                if len(cells)>=7 and cells[1] in {'男','女'} and cells[2].isdigit():
                    name,_,_,role,state,start,end=cells[:7]
                    if not iso(start):continue
                    person=name;status=state
                elif person and len(cells)>=3 and re.search(ROLE,cells[0]):
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
    for page in pages:
        body=_prose(_clean(page['text'],target));spans.append((len(text),page['page']));text+=body+'\n'
    alternatives='|'.join(re.escape(n) for n in sorted(names,key=len,reverse=True))
    if not alternatives:return []
    pattern=r'(?P<name>'+alternatives+r')(?:先生|女士)?[，,](?=[男女一二三四五六七八九十〇零0-9]|中国|硕士|博士)'
    matches=list(re.finditer(pattern,text));rows=[]
    for i,m in enumerate(matches):
        block=text[m.end():matches[i+1].start() if i+1<len(matches) else len(text)]
        # Qualifying declarations are separate from professional experience.
        block=re.split(r'截至目前|且不存在以下|与持有公司|董事、高级管理人员报告期内',block)[0]
        sentences=re.split(r'(?<=[。；])',block)
        selected=[]
        for sentence in sentences:
            if not re.search(r'毕业|学位|学历|曾任|历任|加入|现任|负责|担任',sentence):continue
            if re.search(r'入选|榜单|最具影响力|法》|任职资格',sentence):continue
            if sum(map(len,selected))+len(sentence)>680:break
            selected.append(sentence)
        fact=_prose(''.join(selected)).strip()
        if not fact:continue
        page=next(n for start,n in reversed(spans) if start<=m.start())
        end=m.end()+sum(map(len,selected));used=[n for start,n in spans if m.start()<=start<=end]
        rows.append({'kind':'biography','entity':m['name'],'period':period,'as_of':period_date(period) or period,
                     'page':page,'pages':list(dict.fromkeys([page]+used)),'fact':fact,'evidence_quote':fact,
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
            rows.append({'kind':'relationship','entity':'、'.join(mentioned),'period':period,'as_of':period_date(period) or period,
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


def build_management_package(cleaned,target,sources=None,*,limit=100000):
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
        pages=document_pages(source);base=roster_rows(pages,period)+change_rows(pages,period)+outside_roles(pages,period)
        if not _filing_period({'content':raw,'title':''}):base+=appointments(pages,raw)
        documents.append((c,pages,period));records.extend((c,r) for r in base)
        ext=(get(source,'source_metadata',{}) or {}).get('document_extraction') or {}
        counts['omitted_pages']+=int(ext.get('omitted_pages') or 0);counts['needs_ocr_pages']+=len(ext.get('needs_ocr_pages') or [])
        counts['table_pages_pending']+=len((ext.get('management_tables') or {}).get('pending_pages') or [])
    names={r['entity'] for c,r in records if r['kind'] in {'role','change','appointment'}}
    for c,pages,period in documents:
        records.extend((c,r) for r in biography_rows(pages,names,period,target)+relationship_rows(pages,names,period,target))
    unique=[];seen={}
    for c,r in records:
        key=json.dumps({k:v for k,v in r.items() if k not in {'page','pages','evidence_quote'}},ensure_ascii=False,sort_keys=True)
        if key in seen:
            seen[key]['evidence_ids']=list(dict.fromkeys(seen[key]['evidence_ids']+[c['evidence_id']]));counts['duplicate_claim']+=1;continue
        r.update(evidence_id=c['evidence_id'],evidence_ids=[c['evidence_id']],source_url=c['source_url'],source_title=c.get('source_title',''),evidence_scope='target_direct')
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
    for r in sorted([r for r in unique if r['kind']=='biography'],key=lambda x:x['as_of'],reverse=True):bios.setdefault(r['entity'],r)
    selected.extend(bios.values())
    selected.extend([r for r in unique if r['kind']=='outside_role'][:24])
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
    return {'version':VERSION,'target_name':target,'facts':delivered,'information_gaps':gaps,
            'diagnostic':{'candidate_claims':len(records),'delivered_claims':len(delivered),'by_kind':dict(Counter(r['kind'] for r in delivered)),'filters':dict(counts)}}


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
    for r in sorted(candidates,key=lambda r:(r['as_of'],r['kind']=='appointment'),reverse=True):
        for role in re.split(r'、|兼|及',r['role']):
            family='secretary' if '秘书' in role else 'board' if '董事' in role else 'vice_president' if '副总裁' in role else role
            people[r['entity']].append({**r,'role':role,'family':family})
    result=[]
    for person,rows in people.items():
        newest={family:max(r['as_of'] for r in rows if r['family']==family) for family in {r['family'] for r in rows}}
        chosen=[r for r in rows if r['as_of']==newest[r['family']] and r.get('status') not in {'离任','任期满离任'}]
        if reset:chosen=[r for r in chosen if r['as_of']>=reset or r['family']!='board']
        if chosen:result.append((person,chosen))
    return result


def render_management(p):
    facts=p['facts'];lines=['## 7. '+TITLE,'','### '+HEADINGS[0],'']
    roster=latest_roles(facts);bios={r['entity']:r for r in facts if r['kind']=='biography'}
    if roster:
        lines+=['已得任职披露涉及'+str(len(roster))+'名人员，含董事、高管及其他岗位；不将此数直接当作完整法定高管人数。','']
        lines+=_table(['姓名','已得最新任职披露／基准日','原披露任期','履历与岗位依据','来源'],[
            [name,'；'.join(dict.fromkeys(r['role']+'（'+(r['period'] if r['kind']=='role' else r['as_of'])+'）' for r in rows)),
             '；'.join(dict.fromkeys(r['start']+'至'+r['end'] for r in rows)),
             biography_excerpt(bios[name],rows) if name in bios else '未选到可绑定个人的履历，不能据此认定公司未披露。',
             ' '.join(dict.fromkeys(refs(r)+f"（物理页{r['page']}）" for r in rows))+('；履历'+refs(bios[name])+f"（物理页{bios[name]['page']}）" if name in bios else '')] for name,rows in roster])
        lines+=['','任职表中的现任、历史职务、同人多职与后续正式任命分别记录；上述为已得最新披露，不保证今天状态。年报标签指该文件任职披露，未另认定为精确年末时点；表内起始日期是对应职位的源字段，不直接当本届董事会统一起始日。财务签署人名单不代表完整高管名单。']
    else:lines+=['尚未形成可绑定任职时点的人员表；不以搜索简介或财务签字名单补造完整团队。']
    lines+=['','### '+HEADINGS[1],'']
    changes=[r for r in facts if r['kind'] in {'change','appointment'}]
    if changes:
        grouped={}
        for r in sorted(changes,key=lambda x:x['start'],reverse=True):
            key=(r['start'],r['role'],r['action'],r.get('reason') or r['mode'])
            if key not in grouped:grouped[key]=[r]
            elif r['entity'] not in {x['entity'] for x in grouped[key]}:grouped[key].append(r)
        lines+=_table(['人员','职务','日期／动作','原因与边界','出处'],[
            ['、'.join(r['entity'] for r in rows),key[1],key[0]+'；'+key[2],key[3],
             ' '.join(dict.fromkeys(refs(r)+f"（物理页{r['page']}）" for r in rows))] for key,rows in grouped.items()])
        lines+=['','聘任、升迁、岗位调整、换届、治理架构调整与离任分开；候选提名不当正式任职，正常离任不直接判为内斗或动荡。历史人员表不覆盖更新后的董事独立性类别。']
    else:lines+=['未选到可绑定具体人员与日期的变动记录，不等于无变动。']
    lines+=['','### '+HEADINGS[2],'']
    relationships=[r for r in facts if r['kind']=='relationship']
    for r in relationships:lines+=['- '+r['period']+'公司披露：'+r['fact']+' '+refs(r)+f"（物理页{r['page']}）"]
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
    if bio['as_of']<max(r['as_of'] for r in roles):
        text=re.sub(r'(?:现任|目前担任)[^。；]*(?:[。；]|$)','',text)
    pieces=[]
    for part in re.split(r'(?<=[。，；])',text):
        if sum(map(len,pieces))+len(part)>250:break
        pieces.append(part)
    excerpt=''.join(pieces).strip()
    return '履历文件期'+bio['period']+'：'+(excerpt or '详见原履历')+('（节选；完整履历保留于证据包）' if excerpt!=bio['fact'] else '')


def management_errors(text,p):
    errors=[]
    if text.strip()!=render_management(p).strip():errors.append('第七章出现未受任职与履历证据支持的改写')
    if not any(r['kind'] in {'role','appointment','change'} for r in p['facts']):errors.append('第七章尚无可核对的管理团队记录')
    allowed={e for r in p['facts'] for e in r['evidence_ids']}
    if set(EID.findall(text))-allowed:errors.append('第七章存在未知证据编号')
    return errors
