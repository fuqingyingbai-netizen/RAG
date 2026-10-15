"""Chapter 8: workforce definitions, training and turnover are separate claims."""
import json
import re
from collections import Counter,defaultdict
from urllib.parse import urlparse

from .company_evidence import source_body,document_pages
from .company_governance import EID,_table,compact,get,refs
from .company_history import _issuer_hosts
from .company_management import issuer as management_issuer
from .company_business import _cell,_prose

TITLE='企业文化及人员流失情况'
HEADINGS=('内部文化价值观与文化践行引导','团队激励与人才结构现状','人才储备、培养与梯队建设','销售/研发/技术等核心岗位人员流失情况','核验判断与具体缺口')
VERSION='company-people-v1'
METRICS={
 '员工总人数':('workforce','人'),'员工总数':('workforce','人'),
 '生产人员人数':('workforce','人'),'销售人员人数':('workforce','人'),'技术人员人数':('workforce','人'),
 '行政人员人数':('workforce','人'),'外包人员':('workforce','人'),'实习生':('workforce','人'),
 '长期员工人数':('workforce','人'),'临时员工人数':('workforce','人'),
 '员工流失率':('turnover','%'),'中国内地员工流失率':('turnover','%'),'港澳台及海外员工流失率':('turnover','%'),
 '高级管理层流失率':('turnover','%'),'中层管理人员流失率':('turnover','%'),'普通员工流失率':('turnover','%'),
 '销售人员流失率':('turnover','%'),'研发人员流失率':('turnover','%'),'技术人员流失率':('turnover','%'),
 '员工培训次数':('training','次'),'受训员工总人数':('training','人'),'受训员工占比':('training','%'),
 '员工培训总支出':('training','金额'),'年度培训支出金额':('training','金额'),'年度培训人均成本':('training','金额'),
 '员工受训总时数':('training','小时'),'员工受训人均时数':('training','小时'),
 '员工培训覆盖率':('training','%'),'员工人均接受培训小时数':('training','小时'),
 '员工ESG相关培训开展场数':('training','场'),'员工ESG相关培训覆盖人次':('training','人次'),
 '绩效管理制度的员工覆盖率':('incentive','%'),
}
VALUE=r'(?:[-+]?\d[\d,]*(?:\.\d+)?|[/—-])'
MONEY=r'(?:万元人民币|人民币万元|人民币元|万元|千元|元|USD|HKD)'


def table_metrics(page):
    """Read explicit annual columns; no guessing flat integer cell borders."""
    raw=str(page.get('text') or '').replace('|',' ')
    headers=list(re.finditer(r'指标\s+单位\s+((?:20\d{2}年\s*){2,4})',raw))
    rows=[]
    for i,header in enumerate(headers):
        end=headers[i+1].start() if i+1<len(headers) else len(raw)
        rows+=_metric_block(raw[header.end():end],re.findall(r'20\d{2}',header[1]),page['page'])
    return rows


def _metric_block(raw,years,page):
    order=sorted(range(len(years)),key=lambda i:years[i]);old,new=order[-2:]
    rows=[]
    for metric,(kind,unit) in METRICS.items():
        label=r'\s*(?:\n\s*\d{1,3}\s*\n)?\s*'.join(map(re.escape,metric))
        units=MONEY if unit=='金额' else re.escape(unit)
        # A wrapped superscript is a note ID, not the first data cell.
        pattern=r'(?m)^\s*'+label+r'\s*(?:\n\s*\d{1,3}\s*)?(?P<unit>'+units+r')\s+'+r'\s+'.join('('+VALUE+')' for _ in years)+r'\s*$'
        for m in re.finditer(pattern,raw):
            values=list(m.groups()[1:])
            if values[new] in {'/','—','-'}:continue
            rows.append({'kind':kind,'metric':metric,'value':values[new],'previous_value':values[old],
                         'period':years[new]+'年','previous_period':years[old]+'年','unit':m['unit'],
                         'page':page,'fact':metric+'：'+years[new]+'年'+values[new]+m['unit']+'；'+years[old]+'年'+values[old]+m['unit'],
                         'evidence_quote':m[0].strip(),'mode':'公司披露原表，未作为独立员工调查'})
    return rows


def formula_notes(page):
    raw=str(page.get('text') or '')
    lines=[]
    for line in raw.splitlines():
        if re.search(r'流失率\s*[=＝]|流失率.*计算公式|计算公式.*流失率|各类别.*(?:受训|培训).*占比.*[=＝]|类别.*培训覆盖率\s*[=＝]|受训员工占比\s*[=＝]',line):
            lines.append(_prose(line).strip())
    return lines


def source_notes(pages):
    notes=[]
    for p in pages:
        for line in str(p['text']).splitlines():
            if re.search(r'涵盖员工[（(]|不适用.*公司法|申诉系统新增|培训总支出下降的原因',_cell(line)):
                notes.append({'page':p['page'],'text':_prose(line)})
    return notes


def practice_topic(text):
    for topic,pattern in [('postdoctoral',r'博士后'),('new_employee',r'新员工|应届生|入职培训'),
                          ('leadership',r'管理人才|领导力|班组长|干部培养'),('skills',r'技能人才|师带徒|技能认证'),
                          ('communication',r'员工沟通|HR面对面|申诉渠道|反馈机制'),('inclusion',r'反歧视|反骚扰'),
                          ('career_path',r'晋升机制|人才发展通道|晋升通道')]:
        if re.search(pattern,text):return topic
    return 'general'


def policy_rows(pages,period,target=''):
    rows=[]
    short=re.sub(r'(?:股份有限公司|有限责任公司|有限公司)$','',target)
    for page in pages:
        text=re.sub(r'(?m)^\d*\s*20\d{2}[^\n]{0,100}(?:报告|Report)\s*$','',page['text'])
        text=re.sub(r'(?m)^开篇[^\n]*鉴证声明\s*$','',text)
        for raw in re.split(r'(?<=[。；])',text):
            quote=_prose(raw)
            if not 25<=len(quote)<=650:continue
            if quote.count('•')>3 or quote.count('%')>4 or re.search(r'B[1-9]\.\d|主要绩效指标摘要',quote):continue
            if re.search(r'以下措施|如下|下表|流程图',quote):continue
            subjects=['我们','本公司','本集团','公司']+([target,short] if target else [])
            anchored=list(re.finditer('|'.join(re.escape(x) for x in sorted(set(subjects),key=len,reverse=True)),quote))
            if not anchored:continue
            start=None
            for m in anchored:
                tail=quote[m.end():m.end()+70]
                if m[0]=='公司' and not re.match(r'已|将|正|在|于|通过|建立|高度重视|积极|坚持|制定|开展|为员工|致力|设立|构建|组织|推出|搭建|决定|同步|面向|累计',tail):continue
                if re.search(r'制定|建立|开展|组织|举办|完善|搭建|推出|培养|优化|设立|增加',tail):start=m.start();break
            if start is None:continue
            quote=quote[start:]
            if not re.search(r'员工|人才|岗位|人事|培训|价值观|晋升|职业|师带徒|薪酬|博士后',quote):continue
            if re.search(r'供应商|客户|经销商',quote) and not re.search(r'员工|人才|人事|职业|研发人才',quote):continue
            if not re.search(r'制定|建立|开展|组织|举办|完善|搭建|推出|培养|优化|设立|培训|晋升|增加',quote):continue
            if re.search(r'员工沟通|员工申诉|投诉渠道|反馈机制|文化交流|价值观|反歧视|反骚扰|人权保障|员工手册|文化宣贯',quote):aspect=HEADINGS[0]
            elif re.search(r'员工持股|股权激励|薪酬|绩效考核|绩效评估|绩效管理|员工绩效|晋升机制|发展通道',quote):aspect=HEADINGS[1]
            elif re.search(r'人才培养|专项培训|培训体系|新员工.*培训|训练营|导师带教|博士后|人才梯队|继任|人才储备',quote):aspect=HEADINGS[2]
            else:continue
            focused=bool(re.search(r'人才培养体系|新员工|应届生|师带徒|博士后|领导力|晋升机制|人才发展通道|员工沟通|HR面对面|反歧视和反骚扰',quote))
            topic=practice_topic(quote)
            planned=bool(re.search(r'目标|致力于|旨在|将于|未来|到20\d{2}年|决定实施',quote))
            rows.append({'kind':'practice','aspect':aspect,'period':period,'page':page['page'],'fact':quote,'evidence_quote':quote,'topic':topic,'selection_priority':int(focused)+int(topic!='general'),
                         'mode':'公司计划/制度目标，非完成或效果证明' if planned else '公司制度/实践自述，执行效果与员工体验仍需独立核验'})
    return rows


def build_people_package(cleaned,target,sources=None,*,limit=60000):
    cards=defaultdict(list)
    for c in cleaned.get('facts') or []:
        if isinstance(c,dict) and EID.fullmatch(str(c.get('evidence_id') or '')):cards[str(c.get('source_url') or '')].append(c)
    hosts=_issuer_hosts(sources,target);records=[];notes=[];counts=Counter()
    for s in sources or []:
        raw,origin=source_body(s);url=str(get(s,'url'));meta=get(s,'source_metadata',{}) or {}
        if origin=='discovery_summary' or meta.get('entity_validation') in {'rejected','ambiguous','related_entity_context'}:continue
        host=(urlparse(url).hostname or '').lower().removeprefix('www.')
        statement=bool(re.search(r'本报告(?:为|由|是).{0,30}'+re.escape(compact(target)),compact(raw[:6000])))
        scoped_report=host in hosts and statement
        # A retrieved PDF may itself establish who issued the report even
        # when no earlier stock-exchange filing supplied the website field.
        # Require both the standalone full issuer heading and the explicit
        # report ownership statement; a search title or parent mention fails.
        extracted_pdf=(meta.get('document_extraction') or {}).get('method')=='embedded_pdf_text'
        named_pdf=extracted_pdf and statement and management_issuer(s,target,hosts|{host})
        if not (management_issuer(s,target,hosts) or scoped_report or named_pdf):continue
        usable=[c for c in cards[url] if c.get('eligible_for_report') is not False and c.get('entity_match') not in {'mismatch','ambiguous','out_of_scope'} and c.get('source_entity_validation')!='rejected']
        if not usable:continue
        c=usable[0];pages=document_pages(s)
        year=re.search(r'(20\d{2})\s*年',raw[:6000]);period=year[1]+'年' if year else '报告年度未绑定'
        local_notes=source_notes(pages)
        for note in local_notes:notes.append({**note,'kind':'source_note','fact':note['text'],
                                                     'evidence_id':c['evidence_id'],'evidence_ids':[c['evidence_id']],
                                                     'source_url':url,'source_title':c.get('source_title',''),'evidence_scope':'target_direct'})
        formulas=[{'page':p['page'],'text':t} for p in pages for t in formula_notes(p)]
        for page in pages:
            for r in table_metrics(page):
                word='流失率' if r['kind']=='turnover' else '培训|受训' if r['kind']=='training' else r'(?!)'
                r['definitions']=[n for n in formulas if n['page'] in {page['page'],page['page']+1} and re.search(word,n['text'])]
                if '高级管理层' in r['metric'] and any(re.search(r'不适用.*公司法',n['text']) for n in local_notes):
                    r['population_note']='公司管理架构口径，不等同第七章法定高管名单'
                records.append((c,r))
        records.extend((c,r) for r in policy_rows(pages,period,target))
        ext=meta.get('document_extraction') or {};counts['omitted_pages']+=int(ext.get('omitted_pages') or 0);counts['needs_ocr_pages']+=len(ext.get('needs_ocr_pages') or [])
    unique=[];seen={}
    for c,r in records:
        key=(r['kind'],r.get('aspect'),r.get('metric'),r['period'],r.get('unit'),compact(r['fact']),
             tuple(compact(n['text']) for n in r.get('definitions') or []))
        if key in seen:seen[key]['evidence_ids']=list(dict.fromkeys(seen[key]['evidence_ids']+[c['evidence_id']]));counts['duplicate_claim']+=1;continue
        r.update(evidence_id=c['evidence_id'],evidence_ids=[c['evidence_id']],source_url=c['source_url'],source_title=c.get('source_title',''),evidence_scope='target_direct')
        seen[key]=r;unique.append(r)
    metrics=[r for r in unique if r['kind']!='practice'];practices=[]
    latest={}
    for r in metrics:latest[(r['metric'],r['unit'])]=max(latest.get((r['metric'],r['unit']),''),r['period'])
    metrics=[r for r in metrics if r['period']==latest[(r['metric'],r['unit'])]]
    groups=defaultdict(list)
    for r in metrics:groups[(r['metric'],r['unit'],r['period'])].append(r)
    for group in groups.values():
        if len(group)>1:
            counts['same_name_differences']+=1
            for r in group:r['difference']=True
    for aspect in HEADINGS[:3]:
        rows=sorted([r for r in unique if r.get('aspect')==aspect],key=lambda r:(r['period'],r['selection_priority']),reverse=True)
        chosen=[];topics=set();diverse=[]
        for r in rows:
            if r['topic'] not in topics:diverse.append(r);topics.add(r['topic'])
        for r in diverse+rows:
            if any(compact(r['fact']) in compact(old['fact']) or compact(old['fact']) in compact(r['fact']) for old in chosen):continue
            titles=set(re.findall(r'《([^》]+)》',compact(r['fact'])))
            numbers=set(re.findall(r'\d+(?:\.\d+)?',r['fact']))
            if titles and any(r['period']==old['period'] and r['mode']==old['mode'] and r['topic']==old['topic']
                              and titles & set(re.findall(r'《([^》]+)》',compact(old['fact'])))
                              and numbers==set(re.findall(r'\d+(?:\.\d+)?',old['fact'])) for old in chosen):continue
            chosen.append(r)
            if len(chosen)==4:break
        practices+=chosen
    delivered=[]
    for r in metrics+practices:
        if len(json.dumps(delivered+[r],ensure_ascii=False))<=max(0,limit-5000):delivered.append(r)
        else:counts['budget_excluded']+=1
    gaps=['集团员工、法人参保、劳务派遣/外包、实习与统计时点分别核对，不能将不同人群的数量当冲突或社保缺口。',
          '流失率保留原名、公式、统计期、主动/被动离职范围与分母；不从净减员反推离职、裁员或稳定性，不机械换算为年度离职率。',
          '已得整体或管理层流失率不能代替销售、研发、技术关键岗位流失；岗位离任、招聘人数、晋升人数与离开企业人数分别核对。',
          '培训人数、次数、人次、时数、支出与覆盖定义分别保留；培养计划及完成培训不证明晋升公平、留任或人才能力已改善。',
          '文化制度、具体实践、员工感受与独立执行核验分开；信息缺口不直接判为文化脱节、管理失效或高流失风险。']
    if counts['omitted_pages']:gaps.append('原件尚未提取全文，未选到指标不等于未披露。')
    if counts['needs_ocr_pages']:gaps.append('存在低文字页尚未执行OCR；已得可读文字与扫描页识别分开。')
    if counts['same_name_differences']:gaps.append('同名同期间指标存在不同值或公式，均保留出处；范围、定义及重述版本需核对，未择一或跨表拼接。')
    if counts['budget_excluded']:gaps.append('部分已识别记录超出本章展示预算，不代表该信息不存在或未披露。')
    missing=[m for m in ('销售人员流失率','研发人员流失率','技术人员流失率') if not any(r.get('metric')==m for r in delivered)]
    if missing:gaps.append('本章尚未形成可绑定原表的'+ '、'.join(missing)+'；不能改写成企业全文未披露。')
    return {'version':VERSION,'target_name':target,'facts':delivered,'source_notes':notes,'information_gaps':gaps,
            'diagnostic':{'candidate_claims':len(records),'delivered_claims':len(delivered),'by_kind':dict(Counter(r['kind'] for r in delivered)),'filters':dict(counts)}}


def render_people(p):
    facts=p['facts'];lines=['## 8. '+TITLE,'']
    for i,heading in enumerate(HEADINGS[:3]):
        lines+=['### '+heading,'']
        if i==1:group=[r for r in facts if r['kind'] in {'workforce','incentive'}]
        elif i==2:group=[r for r in facts if r['kind']=='training']
        else:group=[]
        if group:lines+=metric_table(group)
        for r in facts:
            if r.get('aspect')==heading:lines+=['- '+r['period']+'公司披露：'+r['fact']+'（'+r['mode']+'） '+refs(r)+f"（物理页{r['page']}）"]
        if not group and not any(r.get('aspect')==heading for r in facts):lines+=['尚未形成可绑定原文的对应记录，不能据此认定企业没有相关制度或实践。']
        lines+=['']
    lines+=['### '+HEADINGS[3],''];turnover=[r for r in facts if r['kind']=='turnover']
    if turnover:lines+=metric_table(turnover)
    else:lines+=['尚未形成可绑定公式和时期的流失率记录，不据此判为高风险或无人员流失。']
    formulas=[]
    for r in facts:
        for n in r.get('definitions') or []:
            key=(n['text'],n['page'],r['evidence_id'])
            if key not in formulas:formulas.append(key)
    if formulas:
        lines+=['','原表定义（不自动统一为年度口径）：']
        for text,page,eid in formulas:lines+=['- '+text+f' [{eid}]（物理页{page}）']
    lines+=['','总体与分类公式可能采用不同分子/分母，培训分类占比也未必是该类别全员受训覆盖率。未确认定义一致前，不做同业流失率或培训覆盖率排名。',
            '','### '+HEADINGS[4],'']
    for n in p['source_notes']:lines+=['- 原页范围/说明：'+n['text']+f" [{n['evidence_id']}]（物理页{n['page']}）"]
    lines+=['- 公开文化、培养及员工调查属于公司披露；员工满意度的量表与方法见第五章，激励执行阶段见第四章，具体管理人员任职变动见第七章，避免把相同数据重复打分。']
    lines+=['- '+g for g in p['information_gaps']]
    return '\n'.join(lines)


def metric_table(rows):
    return _table(['指标原名','统计期','本期值／原单位','比较期值','口径及来源'],[
        [r['metric'],r['period'],r['value']+r['unit'],r['previous_period']+' '+(r['previous_value']+r['unit'] if r['previous_value'] not in {'/','—','-'} else '未载'),
         ('同名值/公式差异待核；' if r.get('difference') else '')+r.get('population_note','公司自报；按原定义核对')+'；'+refs(r)+f"（物理页{r['page']}）"] for r in rows])


def people_errors(text,p):
    errors=[]
    if text.strip()!=render_people(p).strip():errors.append('第八章出现未受文化与人员原始证据支持的改写')
    if not p['facts']:errors.append('第八章尚无可核对的文化与人员记录')
    allowed={e for r in p['facts'] for e in r['evidence_ids']}|{n['evidence_id'] for n in p['source_notes']}
    if set(EID.findall(text))-allowed:errors.append('第八章存在未知证据编号')
    return errors
