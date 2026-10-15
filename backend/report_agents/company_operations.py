"""Evidence-bound chapter 4: distinguish governance design from execution.

Public filings can establish disclosed rules and instances. They do not, on
their own, prove decision quality, internal efficiency or employee satisfaction.
"""
import json
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from urllib.parse import urlparse

from .company_governance import EID, _filing_period, _period_rank, _primary_filing, _table, compact, get, refs
from .company_history import _issuer_hosts
from .report_prompts import _company_fact_has_trusted_target_anchor

TITLE='组织治理与运营管理评估'
HEADINGS=('组织架构合理性','决策机制','权责划分','执行流程','内部激励','企业应变能力','组织创新能力')
VERSION='company-operations-v1'
PATTERNS={
 HEADINGS[0]:r'组织架构|管理层级设置|汇报关系|设立.{0,12}(?:事业部|研究院)|划分.{0,12}事业部|出于管理目的.{0,20}划分业务单元|报告分部',
 HEADINGS[1]:r'董事会.{0,24}(?:召开|会议|表决)|董事.{0,14}出席|(?:审核|审计|提名|薪酬|战略)委员会.{0,30}(?:召开|审议|组成|成员)',
 HEADINGS[2]:r'(?:总经理|总裁).{0,12}对董事会负责|董事会.{0,12}授权.{0,20}(?:管理层|总经理|总裁)|(?:审核|审计)委员会负责|(?:总裁|总经理)行使下列职权',
 HEADINGS[3]:r'内部控制体系建设委员会|内部控制.{0,14}(?:重大缺陷|重要缺陷|有效性)|(?:采购|供应商|生产).{0,12}(?:准入制度|审批流程|质量管理制度)|(?:整改|审计).{0,16}(?:完成|落实)',
 HEADINGS[4]:r'员工持股计划.{0,50}(?:涉及|不超过|资金总额|买入|解锁|考核|完成)|(?:股票期权|限制性股票).{0,25}(?:授予|归属|行权)|绩效考核.{0,15}(?:办法|制度|指标)',
 HEADINGS[5]:r'(?:公司|本集团|本公司).{0,55}(?:应急预案|应急演练|危机响应|产线切换|业务连续性|供应链中断|供应链风险).{0,50}(?:建立|制定|开展|执行|调整|采取|应对)|(?:建立|制定|开展).{0,20}(?:应急预案|应急演练|业务连续性)',
 HEADINGS[6]:r'(?:公司|本集团|本公司).{0,30}(?:设立|建立|成立).{0,25}(?:研究院|研发中心|创新平台)|(?:研发立项|成果归属|专利转化|技术共享).{0,20}(?:机制|制度|流程|协议)',
}
BOUNDARIES={
 HEADINGS[0]:'法人、集团、子公司和参保人数分别保留统计范围与时点。规模及地址差异不足以证明组织分散、外包或架构不合理；架构适配性还需汇报线、职能及业务规模对应材料。',
 HEADINGS[1]:'人员名单证明已披露任职，章程证明制度安排，会议记录证明对应会议事实；独立性、制衡效果与决策效率不能由职位叠加或会议次数直接推出。',
 HEADINGS[2]:'明确授权条款只说明对应权限范围，不代表创始人掌握所有采购、研发、营销及预算决策。部门级授权与实际执行仍需权责清单、审批记录核对。',
 HEADINGS[3]:'制度建设、公司自评和外部审计意见分别看待；制度存在不等于执行有效，也不能由营收、产品发布或展会活动证明流程闭环。',
 HEADINGS[4]:'计划额度、已购买、授予、解锁和业绩考核达成属于不同阶段。已披露激励不等于全员覆盖、留存改善或员工满意，也不由单一法人参保数推断集团员工社保不足。',
 HEADINGS[5]:'应急制度与实际应对案例分别核对；产品调价、经营范围变更或参赛传闻不能单独证明组织响应速度及应对成效。',
 HEADINGS[6]:'研发人员与投入说明资源配置；组织创新能力还需研发立项、跨部门协作、成果转化及考核机制证据，专利或获奖不自动证明组织效率。',
}
GAPS={
 HEADINGS[0]:'补充正式组织架构及汇报关系、板块职能与规模的对应材料。',
 HEADINGS[1]:'核对重大决策的议案、表决及跟踪记录，区分制度要求和实际运行。',
 HEADINGS[2]:'补充部门级授权矩阵、预算及跨板块资源分配的实际审批记录。',
 HEADINGS[3]:'核对关键流程的控制点、内控测试、整改及外部鉴证范围。',
 HEADINGS[4]:'核对激励计划后续执行与考核结果，区分购买完成、解锁及真实覆盖人数。',
 HEADINGS[5]:'补充具体冲击、响应动作、耗时与结果，不能以日常发布代替应对案例。',
 HEADINGS[6]:'核对研发组织分工、立项与成果归属制度及转化结果。',
}


def _sentences(raw,target):
    text=re.sub(r'--- PDF page \d+ ---',' ',raw)
    text=re.sub(r'(?m)^#{1,6}[^\n]*\n',' ',text)
    text=re.sub(r'(?m)^\s*\d{1,3}\s*\n',' ',text)
    text=re.sub(re.escape(target)+r'\s*20\d{2}\s*年(?:半年度|年度)报告(?:全文|摘要)?\s*\d{0,3}',' ',text)
    sentences=re.split(r'(?<=[。；])\s*',text)
    for pos,sentence in enumerate(sentences):
        if '本员工持股计划' in sentence and re.search(r'未达成|不会解锁',sentence) and pos:
            previous=sentences[pos-1]
            if re.search(r'解锁期.*业绩考核指标',previous):sentence=previous+sentence
        sentence=re.sub(r'\s+',' ',sentence).strip()
        sentence=re.sub(r'(?<=[\u4e00-\u9fff\d])\s+(?=[\u4e00-\u9fff\d])','',sentence)
        sentence=re.sub(r'^\d{1,3}(?=第[一二三四五六七八九十百]+条)','',sentence)
        # Avoid navigation/table lists, broken checkboxes, personal biographies
        # and subsidiary cases being turned into parent operating evidence.
        if not 8<=len(sentence)<=460 or '|' in sentence or 'http' in sentence:continue
        if re.search(r'子公司|附属公司|先生|女士|任职经历|□||☑|(?:先生|女士)简历',sentence):continue
        if sentence.count('《')>3:continue
        yield sentence


def build_operations_package(cleaned,target,sources=None,*,governance=None,limit=30000):
    by_source=defaultdict(list)
    for f in cleaned.get('facts') or []:
        if isinstance(f,dict) and EID.fullmatch(str(f.get('evidence_id') or '')):
            by_source[str(f.get('source_url') or '')].append(f)
    hosts=_issuer_hosts(sources,target);records=[];counts=Counter();seen={}
    def add(card,aspect,text,period,mode,**extra):
        if not text or len(text)>620:return
        record=dict(kind='operations',aspect=aspect,fact=text,evidence_quote=text,evidence_scope='target_direct',
                    evidence_id=card['evidence_id'],evidence_ids=[card['evidence_id']],source_url=card.get('source_url',''),
                    source_title=card.get('source_title',''),period=period or '文件期未明确',mode=mode,**extra)
        key=(aspect,period,mode,compact(text))
        if key in seen:
            seen[key]['evidence_ids']=list(dict.fromkeys(seen[key]['evidence_ids']+record['evidence_ids']))
            counts['duplicate_claim']+=1;return
        seen[key]=record;records.append(record)

    # Import only exact role fields, without reproducing chapter-2 full tables
    # or treating "非独立董事" as an independent director.
    personnel=[r for r in (governance or {}).get('facts',[]) if r['kind']=='personnel']
    independent=[r for r in personnel if re.search(r'(?<!非)独立董事',r.get('role',''))]
    if independent:
        r=independent[0]
        add(r,HEADINGS[1],'主要人员记录载有独立董事：'+'、'.join(x['entity'] for x in independent),r['period'],'任职字段')
    for src in sources or []:
        raw=str(get(src,'content') or '');url=str(get(src,'url') or '');meta=get(src,'source_metadata',{}) or {}
        if not raw or meta.get('entity_validation') in {'rejected','ambiguous','related_entity_context'}:continue
        primary=_primary_filing(src,target)
        official=(urlparse(url).hostname or '').lower().removeprefix('www.') in hosts
        host=(urlparse(url).hostname or '').lower()
        exchange=any(host==d or host.endswith('.'+d) for d in ('szse.cn','sse.com.cn','cninfo.com.cn','hkexnews.hk'))
        charter=(exchange or official) and bool(re.search(re.escape(compact(target))+r'章程',compact(raw[:400])))
        primary=primary or charter
        cards=[f for f in by_source[url] if f.get('eligible_for_report') is not False
               and f.get('entity_match') not in {'mismatch','ambiguous','out_of_scope'} and f.get('source_entity_validation')!='rejected'
               and ((f.get('evidence_scope','target_direct') in {'','target_direct'} and _company_fact_has_trusted_target_anchor(f,target))
                    or ((primary or official) and f.get('claim_type')=='source_excerpt' and f.get('evidence_scope') in {'industry_context','related_entity_context','target_direct'}))]
        if not cards:continue
        # Whole-source parsing requires verified issuer ownership. A third-
        # party article's surrounding prose may describe competitors/industry.
        if not (primary or official):
            counts['non_primary_context_excluded']+=1;continue
        card=cards[0];period=_filing_period(src)
        if charter and not period:
            m=re.search(r'(20\d{2})\s*年\s*(\d{1,2})\s*月',raw[:400])
            period=m[1]+'年'+m[2]+'月章程' if m else '章程版本日期未载'
        flat=re.sub(r'\s+','',raw)
        if period:
            workforce=[]
            for label,scope in [('报告期末母公司在职员工的数量','母公司'),('报告期末主要子公司在职员工的数量','主要子公司'),('报告期末在职员工的数量合计','母公司及主要子公司合计')]:
                m=re.search(re.escape(label)+r'[（(]人[）)]([\d,]+)(?![\d,.])',flat)
                if m:workforce.append((scope,m[1]))
            if workforce:
                add(card,HEADINGS[0],'；'.join(scope+'在职员工'+value+'人' for scope,value in workforce),period,'人员统计口径')
            segments=re.search(r'本集团目前有[^。]{1,15}报告分部，分别如下[：:](.{1,650}?)管理层出于',flat)
            if segments and 'a)' in segments[1] and 'b)' in segments[1]:
                add(card,HEADINGS[0],segments[0].removesuffix('管理层出于'),period,'财务报告分部／非组织架构')
            # Require the explicit comparative table, preserving its unit and
            # year order; marketing's approximate R&D numbers stay separate.
            for label,unit in [('研发人员数量','人'),('研发投入金额','元'),('研发投入资本化的金额','元')]:
                header=r'公司研发(?:人员|投入)情况(20\d{2})年(20\d{2})年变动比例'
                for h in re.finditer(header,flat):
                    tail=flat[h.end():h.end()+1200]
                    value=r'[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)'+(r'\.\d{2}' if unit=='元' else '')
                    unit_pattern='人' if unit=='人' else r'[^）)]{1,20}'
                    m=re.search(re.escape(label)+r'[（(](?P<unit>'+unit_pattern+r')[）)](?P<current>'+value+r')(?P<prior>'+value+r')(?P<change>[-+]?\d+(?:\.\d+)?%)',tail)
                    if unit=='人':
                        # Flat integer cells have no unambiguous boundary.
                        # Require original whitespace/pipe cell delimiters.
                        section=re.search(r'公司研发人员情况',raw)
                        original=raw[section.end():section.end()+800].replace('|',' ') if section else ''
                        m=re.search(re.escape(label)+r'\s*[（(](?P<unit>人)[）)]\s*(?P<current>[\d,]+)\s+(?P<prior>[\d,]+)\s+(?P<change>[-+]?\d+(?:\.\d+)?%)',original)
                    if m:
                        add(card,HEADINGS[6],f"{label}：{h[1]}年{m['current']}{m['unit']}，{h[2]}年{m['prior']}{m['unit']}；源表变动比例{m['change']}",period,'研发资源披露',metric=label)
                        break
        for sentence in _sentences(raw,target):
            for aspect,pattern in PATTERNS.items():
                if not re.search(pattern,sentence):continue
                if aspect==HEADINGS[0] and re.search(r'报告分部|出于管理目的',sentence):continue
                if aspect==HEADINGS[1] and '员工持股计划' in sentence:continue
                if re.search(r'应聘|招聘|免责声明|若您|例如|假设',sentence):continue
                if not charter and re.search(r'^\d+[）)]|出现以下|存在以下|包括以下|下列情形|根据.*(?:法规|指引).*应当',sentence):continue
                # Normative claims from charters are design; plans in an
                # annual report remain plans, even in an official document.
                mode='制度条款' if charter else '计划／执行待核验' if re.search(r'拟|尚待|计划将|将于',sentence) else '公司运行披露'
                if aspect==HEADINGS[4] and charter:continue
                if aspect==HEADINGS[3] and not charter and re.search(r'有效性进行评价|不存在.{0,18}缺陷|无.{0,5}缺陷|自我评价报告',sentence):mode='公司内控自述'
                if aspect==HEADINGS[3] and '我们在审计过程中' in sentence:mode='外部审计程序／非全面有效结论'
                if aspect==HEADINGS[4]:
                    if re.search(r'未达成|不会解锁|未达到|取消|终止',sentence):mode='执行结果／未达成'
                    elif re.search(r'完成.{0,6}购买|累计买入',sentence):mode='购买执行披露'
                    elif re.search(r'不超过|涉及不超过',sentence):mode='计划额度／非实际人数'
                    elif re.search(r'分三期解锁|解锁时点|考核要求',sentence):mode='解锁及考核条件'
                # Assign an identical statement to its most specific aspect.
                # An authorization should not be repeated as a second meeting
                # record, nor an incentive plan as generic governance praise.
                matches=[h for h,p in PATTERNS.items() if re.search(p,sentence)]
                priority=[HEADINGS[4],HEADINGS[2],HEADINGS[5],HEADINGS[6],HEADINGS[3],HEADINGS[1],HEADINGS[0]]
                if aspect!=next(h for h in priority if h in matches):continue
                if aspect==HEADINGS[3] and '供应商准入制度' in sentence:
                    sentence=re.split(r'(?=从技术、质量)',sentence)[-1]
                    mode='供应商制度自述'
                add(card,aspect,sentence,period,mode)
    # Prefer newest reporting periods, preserve different kinds of evidence,
    # and do not confuse near-identical annual and half-year disclosures.
    selected=[]
    for aspect in HEADINGS:
        rows=sorted([r for r in records if r['aspect']==aspect],key=lambda r:(_period_rank(r['period']),bool(re.search(r'每年至少|每季度至少',r['fact']))),reverse=True)
        unique=[]
        for row in rows:
            duplicate=next((old for old in unique if row['mode']==old['mode'] and
                            SequenceMatcher(None,compact(row['fact']),compact(old['fact'])).ratio()>.9),None)
            if duplicate:
                counts['near_duplicate_claim']+=1;continue
            unique.append(row)
        quota=4 if aspect in {HEADINGS[1],HEADINGS[4],HEADINGS[6]} else 3
        chosen=[]
        # Include role, institutional design and concrete running evidence
        # where present instead of filling all slots with charter clauses.
        for mode in ('人员统计口径','财务报告分部／非组织架构','任职字段','执行结果／未达成','购买执行披露','解锁及考核条件','计划额度／非实际人数',
                     '公司内控自述','外部审计程序／非全面有效结论','供应商制度自述','公司运行披露','制度条款','研发资源披露','计划／执行待核验'):
            row=next((r for r in unique if r['mode']==mode),None)
            if row and len(chosen)<quota:chosen.append(row)
        for row in unique:
            if len(chosen)>=quota:break
            if row not in chosen:chosen.append(row)
        for row in chosen:
            if len(json.dumps(selected+[row],ensure_ascii=False))<max(0,limit-3000):selected.append(row)
            else:counts['budget_excluded']+=1
    gaps=[GAPS[h] for h in HEADINGS]
    return {'version':VERSION,'target_name':target,'facts':selected,'information_gaps':gaps,
            'diagnostic':{'candidate_claims':len(records),'delivered_claims':len(selected),
                          'by_aspect':dict(Counter(r['aspect'] for r in selected)),'filters':dict(counts)}}


def render_operations(package):
    lines=['## 4. '+TITLE,'']
    for aspect in HEADINGS:
        rows=[r for r in package['facts'] if r['aspect']==aspect]
        lines+=['### '+aspect,'']
        if rows:
            lines+=_table(['资料期／口径','已取得的具体记录','证据性质','来源'],[
                [r['period'],r['fact'],r['mode'],refs(r)] for r in rows])
        else:lines+=['本章尚未取得可据以评估该维度的具体记录，结论待核验。']
        lines+=['',BOUNDARIES[aspect],'']
    lines+=['### 后续核验材料','']+['- '+gap for gap in package['information_gaps']]
    return '\n'.join(lines)


def operations_errors(text,package):
    errors=[]
    if text.strip()!=render_operations(package).strip():errors.append('第四章出现未受已核对记录支持的改写')
    allowed={eid for r in package['facts'] for eid in r['evidence_ids']}
    if set(EID.findall(text))-allowed:errors.append('第四章存在未知证据编号')
    if not package['facts']:errors.append('第四章没有可核对的治理及运行记录')
    return errors
