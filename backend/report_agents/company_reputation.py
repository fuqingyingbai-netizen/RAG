"""Chapter 5: attributed feedback and genuinely comparable market evidence."""
import json
import re
from collections import Counter,defaultdict
from decimal import Decimal
from urllib.parse import urlparse

from .company_evidence import source_body,document_pages,pending_ocr_notice
from .company_governance import EID,_table,_period_rank,compact,get,refs,_primary_filing
from .company_history import _issuer_hosts

TITLE='行业口碑、产品认可度与同业竞争地位研判'
HEADINGS=('员工评价','竞品评价','合作方评价','行业地位','技术实力','综合软实力','同业对标')
VERSION='company-reputation-v1'
METRICS={
 '员工满意度分数':('员工评价','分数'), '员工敬业度分数':('员工评价','分数'),
 '客户满意度':('综合软实力','%'), '接获的客户投诉数目':('综合软实力','宗'),
 '客户投诉回应率':('综合软实力','%'), '客户投诉解决率':('综合软实力','%'),
 '客户满意度调查次数':('综合软实力','次'),
 '接获关于产品及服务的投诉数':('综合软实力','个'),
 '接获关于产品及服务的投诉处理率':('综合软实力','%'),
}


def _value(value,unit):
    if value in {'/','—','-'}:return '未载'
    if '满分' in value:return value
    if unit=='分数':return value+'分'
    if unit=='%' and value.endswith(('以上','以下')):return value[:-2]+'%'+value[-2:]
    return value+unit


def counterparty_excerpt(raw, aliases):
    """One original cooperation passage, excluding repeated mobile headers.

    Do not deduplicate on numbers or approximate similarity: a later sentence
    may disclose a different product, geography or stage of the cooperation.
    """
    pieces=re.split(r'(?<=[。；])\s*|(?<!\bCo\.)(?<=[.!?])\s+(?=[A-Z])|\n\s*\n',raw)
    selected=[];seen=set()
    for piece in pieces:
        piece=re.sub(r'\s+',' ',piece).strip()
        key=compact(piece)
        if not piece or key in seen:continue
        seen.add(key)
        if re.search(r'[A-Za-z]',piece) and not re.search(r'[。；.!?]["”’)]*$',piece):continue
        if _mentions(piece,aliases) and re.search(r'jointly developed|collaboration|共同开发|签订合约|签署协议',piece,re.I):
            if 30<=len(piece)<=1000:selected.append(piece)
    # Each retained passage independently contains the target and action;
    # fragments around another legal entity are not joined by proximity.
    return selected[:2]


def aliases_for_target(target,sources):
    aliases={target}
    short=re.sub(r'(?:股份有限公司|有限责任公司|有限公司)$','',target)
    if len(short)>=2:aliases.add(short)
    for source in sources or []:
        if not _primary_filing(source,target):continue
        head=str(get(source,'content'))[:7000]
        m=re.search(r'公司(?:的)?外文名称缩写(?:[（(]如有[）)])?\s*[:：|]?\s*([A-Z][A-Z0-9.-]{1,20})',head)
        if m:aliases.add(m[1])
    return aliases


def _mentions(text,aliases):
    return any(re.search(r'(?<![A-Za-z0-9])'+re.escape(a)+r'(?![A-Za-z0-9])',text,re.I)
               if a.isascii() else a in text for a in aliases)


def _research_issuer(title,aliases):
    # Mentioning the parent inside a subsidiary's research headline does not
    # identify the parent as the issuer being assessed.
    title=re.sub(r'^\s*(?:20\d{2}年)?\s*','',title)
    return any(re.match(re.escape(a)+r'(?:[（(]\d{4,6}(?:\.[A-Z]+)?[）)])?(?:[:：|]|研究报告|研报|$)',title,re.I)
               for a in sorted(aliases,key=len,reverse=True))


def survey_table_rows(page):
    """Use explicit year headers and delimited cells, including score scales."""
    raw=str(page.get('text') or '').replace('|',' ')
    header=re.search(r'指标\s+单位\s+((?:20\d{2}年\s*){2,4})',raw)
    if not header:return []
    # PDF line wrapping can occur inside the score's parenthetical scale.
    raw=re.sub(r'[（(][^）)]{0,40}[）)]',lambda m:re.sub(r'\s+','',m[0]),raw)
    for metric,(_aspect,unit) in METRICS.items():
        raw=re.sub(r'(?m)^('+re.escape(metric)+r')\s*\n\s*(\d{1,2})\s*\n\s*('+re.escape(unit)+r')',r'\1 \2 \3',raw)
    value=r'(?:[-+]?\d[\d,]*(?:\s*\.\s*\d+)?(?:以上|以下)?(?:[（(]满分\d+分[）)])?|[/—-])'
    rows=[]
    years=re.findall(r'20\d{2}',header[1])
    for line in raw.splitlines():
        next_header=re.search(r'指标\s+单位\s+((?:20\d{2}年\s*){2,4})',line)
        if next_header:years=re.findall(r'20\d{2}',next_header[1]);continue
        for metric,(aspect,unit) in METRICS.items():
            cells=r'\s+'.join('('+value+')' for _ in years)
            m=re.fullmatch(r'\s*'+re.escape(metric)+r'\s+(?:\d{1,2}\s+)?'+re.escape(unit)+r'\s+'+cells+r'\s*',line)
            if not m:continue
            values=[re.sub(r'\s+','',x) for x in m.groups()];order=sorted(range(len(years)),key=lambda i:years[i])
            prior,current=order[-2:]
            if values[current] in {'/','—','-'}:continue
            rows.append({'aspect':aspect,'metric':metric,'unit':unit,'value':values[current],
                         'previous_value':values[prior],'period':years[current]+'年','previous_period':years[prior]+'年',
                         'fact':metric+'：'+years[current]+'年'+_value(values[current],unit)+'；'+years[prior]+'年'+_value(values[prior],unit),
                         'evidence_quote':line.strip(),'page':page['page']})
    return rows


def _market_period(text):
    months={'Jan':1,'January':1,'Apr':4,'April':4,'May':5,'Jun':6,'June':6,'Jul':7,'July':7,'Aug':8,'August':8,'Sep':9,'September':9}
    m=re.search(r'(?:From Jan(?:uary)? to |January[-– ])([A-Za-z]+)\s+(20\d{2})',text)
    if m and m[1] in months:return f'{m[2]}年1—{months[m[1]]}月'
    return ''


def _market_rows(text,aliases):
    """Narrative benchmark rows require a stated period, scope and metric.

    The EV-battery profile preserves the publication's registered-vehicle
    denominator; no company name, supplier or share is embedded in this rule.
    Other market formats remain attributed context until a comparable row can
    be extracted with the same explicit basis.
    """
    period=_market_period(text)
    if not period or not re.search(r'EV\s*[,，]\s*PHEV\s*[,，]\s*HEV',text):return []
    if not re.search(r'registered\s+(?:around the world|worldwide)|registered\s+worldwide',text,re.I):return []
    entities=list(re.finditer(r'\b([A-Z]{2,15}(?:\s+[A-Z][A-Za-z0-9&.-]+){0,3})\b\s+(?:secured|remained|retained|recorded|posted|maintained|held|ranked|took|grew|kept|fell)\b',text))
    rows=[]
    for pos,m in enumerate(entities):
        end=entities[pos+1].start() if pos+1<len(entities) else len(text)
        quote=re.sub(r'\s+',' ',text[m.start():min(end,m.start()+650)]).strip()
        # Stop at the combined-share sentence: it is not one entity's share.
        quote=re.split(r'(?:The combined|Together,|The two companies)',quote)[0].strip()
        share=None;previous_share=''
        for pattern,group in [(r'share[^;\n]{0,150}?from\s+\d+(?:\.\d+)?%\s+to\s+(\d+(?:\.\d+)?)%',1),
                              (r'(?:market\s+)?share\s+(?:rose|climbed)[^;\n]{0,100}?to\s+(\d+(?:\.\d+)?)%',1),
                              (r'(?:with|capturing|a)\s+(\d+(?:\.\d+)?)%\s+market share',1),
                              (r'market share[^;\n]{0,80}?to\s+(\d+(?:\.\d+)?)%',1)]:
            hit=re.search(pattern,quote,re.I)
            if hit:share=hit[group];break
        if not share:continue
        prior=re.search(r'share[^;\n]{0,150}?from\s+(\d+(?:\.\d+)?)%\s+to\s+'+re.escape(share)+r'%',quote,re.I)
        if prior:previous_share=prior[1]+'%'
        rows.append({'entity':m[1],'value':share+'%','unit':'%', 'period':period,'metric':'全球注册EV/PHEV/HEV电池使用量份额',
                     'fact':quote,'evidence_quote':quote,'target_row':_mentions(m[1],aliases),
                     'previous_value':previous_share,
                     'basis':'全球注册EV、PHEV、HEV电池使用量；不等同第三方外供市场或整车份额'})
    # A source must contain the target as well as a peer under this exact basis.
    return rows if any(r['target_row'] for r in rows) and any(not r['target_row'] for r in rows) else []


def build_reputation_package(cleaned,target,sources=None,*,limit=30000):
    aliases=aliases_for_target(target,sources);hosts=_issuer_hosts(sources,target)
    cards_by_url=defaultdict(list)
    for card in cleaned.get('facts') or []:
        if isinstance(card,dict) and EID.fullmatch(str(card.get('evidence_id') or '')):
            cards_by_url[str(card.get('source_url') or '')].append(card)
    records=[];counts=Counter();seen=set()
    def add(card,kind,aspect,text,**fields):
        if not text or len(text)>1000:return
        record={'kind':kind,'aspect':aspect,'fact':text,'evidence_quote':fields.pop('evidence_quote',text),
                'evidence_id':card['evidence_id'],'evidence_ids':[card['evidence_id']],
                'source_url':card.get('source_url',''),'source_title':card.get('source_title',''),**fields}
        key=(kind,aspect,record.get('period'),compact(text))
        if key in seen:counts['duplicate_claim']+=1;return
        seen.add(key);records.append(record)
    for source in sources or []:
        url=str(get(source,'url'));raw,origin=source_body(source);meta=get(source,'source_metadata',{}) or {}
        if origin=='discovery_summary':counts['discovery_only']+=1;continue
        if meta.get('entity_validation') in {'rejected','ambiguous'}:continue
        cards=[c for c in cards_by_url[url] if c.get('eligible_for_report') is not False
               and c.get('entity_match') not in {'mismatch','ambiguous','out_of_scope'} and c.get('source_entity_validation')!='rejected']
        if not cards:continue
        card=cards[0];title=str(get(source,'title'));host=(urlparse(url).hostname or '').lower().removeprefix('www.')
        extraction=meta.get('document_extraction') or {}
        counts['omitted_pdf_pages']+=int(extraction.get('omitted_pages') or 0)
        counts['low_text_pdf_pages']+=len(extraction.get('needs_ocr_pages') or [])
        exchange=any(host==d or host.endswith('.'+d) for d in ('szse.cn','sse.com.cn','cninfo.com.cn','hkexnews.hk'))
        named_report=bool(re.match(re.escape(compact(target))+r'20\d{2}(?:年|年度).*(?:报告|Report)',compact(title),re.I))
        issuer=(_primary_filing(source,target) or host in hosts or (exchange and named_report)) and compact(target) in compact(raw[:6000])
        if issuer:
            for page in document_pages(source):
                for row in survey_table_rows(page):
                    aspect=row.pop('aspect');claim=row.pop('fact')
                    note='公司披露的调查分数；不是独立访谈，分数与NPS目标不相互替代。' if aspect=='员工评价' else '公司披露指标；不能据此认定市场整体认可或无投诉。'
                    if row['metric']=='客户满意度':
                        foot=re.search(r'客户满意度指[^。\n]{1,100}',page['text'])
                        row['definition']=foot[0] if foot else '本页未明确满意度定义'
                        note+=' '+row['definition']
                    if row['metric'].startswith('客户投诉') or row['metric']=='接获的客户投诉数目':
                        foot=re.search(r'包含售后阶段[^\n]{1,150}',page['text'])
                        row['definition']=foot[0] if foot else '本页统计范围说明待核验'
                    scope=re.search(r'客户(?:服务|权益)[^。\n]{0,35}相关数据的统计口径[^。\n]{1,160}',page['text'])
                    if scope:
                        row['population_scope']=scope[0]
                        row['definition']=(row.get('definition','')+'；'+scope[0]).strip('；')
                    add(card,'survey',aspect,claim,mode='公司披露／非独立访谈',note=note,rank=3,**row)
        # Retain original company/brand attribution in research commentary.
        # Analysts' views are not competitors' or customers' statements.
        publisher=re.search(r'(?:来源[:：]|机构[:：])\s*([^\n]{1,50}证券[^\n]{0,20})',raw)
        if publisher and _research_issuer(title,aliases):
            date=re.search(r'20\d{2}[-/]\d{2}[-/]\d{2}',raw[:2500]);period=date[0].replace('/','-') if date else '研报日期未明确'
            views=[]
            for sentence in re.split(r'(?<=[。；])\s*',raw):
                sentence=re.sub(r'\s+',' ',sentence).strip()
                if not 25<=len(sentence)<=350 or 'http' in sentence or '|' in sentence:continue
                if re.search(r'我们认为|相比竞品|与主要竞品',sentence) and re.search(r'竞争|产品力|智驾|营销|渠道|不足|差距',sentence):
                    views.append(sentence)
            for view in views[-2:]:
                publisher_name=re.split(r'\s+20\d{2}[-/]',publisher[1].strip())[0]
                add(card,'research_view','竞品评价',view,period=period,mode='券商研究观点（转载）',publisher=publisher_name,rank=1)
            if re.search(r'分别为方面|同比\+24pp|3024万辆',compact(raw)):
                counts['layout_noise']+=1
        # Explicit counterparty-issued material may support a dated cooperation
        # statement. It cannot be upgraded to endorsement or current sales.
        if meta.get('publisher_role')=='counterparty_official' and meta.get('publisher_verified') is True and _mentions(raw,aliases):
            for sentence in counterparty_excerpt(raw,aliases):
                add(card,'partner_statement','合作方评价',sentence,period=meta.get('publication_date') or '公告日期未明确',
                    mode='合作方公开公告／非访谈',rank=3)
        for row in _market_rows(raw,aliases):
            claim=row.pop('fact')
            add(card,'benchmark','同业对标',claim,mode='原发布机构统计' if meta.get('publisher_role')=='statistics_origin' else '转载统计／原发布待核验',rank=3 if meta.get('publisher_role')=='statistics_origin' else 1,**row)
        if meta.get('publisher_role')=='independent_survey' and meta.get('scope_verified') is True and meta.get('evidence_scope')=='industry_context':
            # Industry survey background remains industry-level even when it
            # is issued by an authoritative body. Never assign its score to
            # the target or rank it against the company's own service NPS.
            scope=str(meta.get('industry_name') or '')
            article=raw
            stamp=re.search(r'发布于[：:]\s*20\d{2}[-/]\d{2}[-/]\d{2}\s+\d{2}:\d{2}',article)
            if stamp:article=article[stamp.end():]
            sentences=[re.sub(r'\s+',' ',s).strip() for s in re.split(r'(?<=[。])\s*',article)]
            intro=next((s for s in sentences if 20<len(s)<350 and scope and scope in s and re.search(r'发布20\d{2}年.*用户满意度',s)),None)
            result=next((s for s in sentences if 20<len(s)<350 and re.search(r'指数达\s*\d+(?:\.\d+)?分',s)),None)
            method=next((s for s in sentences if 20<len(s)<500 and '有效调查样本' in s),None)
            if intro and result:
                claim=intro+result+(method or '')
                add(card,'industry_survey','综合软实力',claim,period=meta.get('publication_date') or '发布期未载',
                    mode='独立机构行业调查／非目标公司得分',rank=3,evidence_scope='industry_context')
    selected=[]
    # One latest period per survey metric; preserve source conflicts instead of
    # overwriting values or treating alternative units as equal.
    for metric in METRICS:
        rows=sorted([r for r in records if r['kind']=='survey' and r['metric']==metric],key=lambda r:(_period_rank(r['period']),r['rank']),reverse=True)
        if not rows:continue
        latest=rows[0];same=[r for r in rows if r['period']==latest['period']]
        values={(r['value'],r['unit']) for r in same}
        selected.append(latest)
        if len(values)>1:
            latest['note']+=' 同期来源数值存在差异，暂不形成比较结论。';counts['survey_conflict']+=1
            selected += [r for r in same[1:] if (r['value'],r['unit'])!=(latest['value'],latest['unit'])][:2]
    for kind,quota in [('research_view',2),('partner_statement',2),('industry_survey',1)]:
        selected += sorted([r for r in records if r['kind']==kind],key=lambda r:_period_rank(r['period']),reverse=True)[:quota]
    benchmarks=[r for r in records if r['kind']=='benchmark']
    if benchmarks:
        best=max(benchmarks,key=lambda r:(_period_rank(r['period'])[0],int(re.search(r'—(\d+)月',r['period'])[1]),r['rank']))
        selected += [r for r in benchmarks if r['period']==best['period'] and r['source_url']==best['source_url']][:8]
    delivered=[]
    for r in selected:
        if len(json.dumps(delivered+[r],ensure_ascii=False))<max(0,limit-2500):delivered.append(r)
        else:counts['budget_excluded']+=1
    gaps=['独立员工、客户/竞品及合作方访谈尚需实际开展；公司披露、研究观点与公开合作公告不能替代访谈。',
          '调查样本数、抽样方法、回收率及独立验证范围仍需核对；投诉指标缺客户基数时不计算投诉率。',
          '不同产品、地区、时期、统计分母和自供/外供范围不得混成一个竞争力排名；历史观点需用新资料更新。']
    if counts['layout_noise']:gaps.append('转载研报存在数字/排版错乱，未将其中无法绑定市场和时期的份额作为定量对标。')
    if counts['survey_conflict']:gaps.append('同一调查指标同期来源值存在差异，须核对原页及统计范围。')
    if counts['omitted_pdf_pages']:gaps.append('部分PDF受提取页数或字符预算限制尚未覆盖全文，未选出指标不等于公司未披露。')
    if counts['low_text_pdf_pages']:gaps.append(pending_ocr_notice(sources,'部分PDF页面文字很少（可能含封面），未实际执行OCR；本章仅采用已取得的明确文本与表格。'))
    findings=[]
    score=next((r for r in delivered if r['kind']=='survey' and r['metric']=='员工满意度分数'),None)
    if score and not counts['survey_conflict']:
        numeric=r'([-+]?\d+(?:\.\d+)?)([（(]满分\d+分[）)])?'
        current=re.fullmatch(numeric,score['value']);prior=re.fullmatch(numeric,score['previous_value'])
        if current and prior and current[2]==prior[2]:
            delta=Decimal(current[1])-Decimal(prior[1])
            findings.append({'aspect':'员工评价','fact':'公司披露的员工满意度分数由'+_value(score['previous_value'],score['unit'])+'变为'+_value(score['value'],score['unit'])+'，差额'+str(delta)+'分；样本及调查方法的一致性仍需核对。','evidence_ids':score['evidence_ids']})
    for r in delivered:
        if r['kind']=='benchmark' and r['target_row'] and r.get('previous_value'):
            delta=Decimal(r['value'].rstrip('%'))-Decimal(r['previous_value'].rstrip('%'))
            findings.append({'aspect':'行业地位','fact':'同一统计发布记载，'+r['entity']+'份额由上年同期'+r['previous_value']+'变为'+r['value']+'，变化'+str(delta)+'个百分点；这是细分统计口径内的份额变化，不是整体产品质量结论。','evidence_ids':r['evidence_ids']})
    return {'version':VERSION,'target_name':target,'facts':delivered,'findings':findings,'information_gaps':gaps,
            'diagnostic':{'candidate_claims':len(records),'delivered_claims':len(delivered),
                          'by_kind':dict(Counter(r['kind'] for r in delivered)),'filters':dict(counts)}}


def render_reputation(package):
    facts=package['facts'];lines=['## 5. '+TITLE,'']
    for heading in HEADINGS:
        lines+=['### '+heading,'']
        rows=[r for r in facts if r['aspect']==heading and r['kind']!='industry_survey']
        if heading in {'员工评价','综合软实力'}:
            if rows:
                lines+=_table(['指标','当期值','比较期值','性质与范围','来源／页码'],[
                    [r['metric'],r['period']+' '+_value(r['value'],r['unit']),r['previous_period']+' '+_value(r['previous_value'],r['unit']),
                     r['mode']+'；'+r.get('definition',''),refs(r)+f"（PDF物理页{r['page']}）"] for r in rows])
                lines+=['','以上为公司披露的调查或服务指标，不能当作本次项目已完成的独立访谈。'+('分数和百分比、满意度和敬业度分开，不由一项总分推出各岗位一致满意。' if heading=='员工评价' else '满意度与投诉数量并列；投诉绝对量缺少客户基数，不能直接比较投诉发生率或认定质量改善。')]
                if any('差异' in r.get('note','') for r in rows):lines+=['同期记录存在数值差异，暂不据此下比较结论。']
            else:lines+=['本章尚无可核对的调查结果，独立评价待核验。']
            if heading=='综合软实力':
                for r in facts:
                    if r['kind']=='industry_survey':
                        lines+=['','外部行业背景：'+r['fact']+' '+refs(r),
                                '该机构调查覆盖行业，未给出目标公司单独得分；不能与公司自报售后NPS直接比较，也不能将行业分数赋给目标公司。']
        elif heading=='竞品评价':
            lines+=['尚无本项目已完成的竞品访谈。下列材料如有列示，属于外部研究观点，不能改称竞品、员工或消费者的直接评价。']
            for r in rows:lines+=['- '+r['period']+'，'+r.get('publisher','研究来源')+'：'+r['fact']+' '+refs(r)]
        elif heading=='合作方评价':
            if rows:
                for r in rows:lines+=['- '+r['period']+' '+r['mode']+'：'+r['fact']+' '+refs(r)]
                lines+=['合作公告只支持其记载的产品、伙伴、日期及合作阶段，不证明持续履约、当前销售或对全部技术的认可。']
            else:lines+=['尚无可核对的合作方独立评价；目标公司的合作宣传不作为对方信任背书。']
        elif heading=='行业地位':
            rows=[r for r in facts if r['kind']=='benchmark' and r['target_row']]
            if rows:
                for r in rows:lines+=['- '+r['period']+'，'+r['entity']+'在“'+r['metric']+'”口径下为'+r['value']+'。'+refs(r)]
                lines+=['该位置仅适用于所列细分市场、期间与统计分母，不能外推为整家公司所有业务的领先地位。']
            else:lines+=['本章尚未形成同口径行业位置数据，待补原发布机构统计。']
        elif heading=='技术实力':
            lines+=['技术投入、产品发布、第三方测评和实际用户体验分别核对。研发投入及资本化见第四章、研发落地与经营数据见第六章；本章不重复计算研发占比，也不把业务分部收入当公司总收入。']
            if any(r['kind']=='partner_statement' for r in facts):lines+=['已列的特定产品合作可支持该产品存在技术协作，不能从其他品牌的合作推导目标公司的依赖关系。']
        elif heading=='同业对标':
            if rows:
                lines+=_table(['公司','期间','指标与统计范围','份额','证据性质','来源'],[
                    [r['entity'],r['period'],r['basis'],r['value'],r['mode'],refs(r)] for r in rows])
                lines+=['','只比较同一发布、同一期间和同一指标的公司；不将某同行半年业务毛利率写成全年，也不拿其业务毛利率与目标公司整体毛利率直接对比。']
            else:lines+=['尚无达到同产品、同期间、同地区及同分母条件的完整对标组，暂不拼表。']
        for finding in package.get('findings',[]):
            if finding['aspect']==heading:lines+=['',finding['fact']+refs(finding)]
        lines+=['']
    lines+=['### 需要补充的评价与对标材料','']+['- '+x for x in package['information_gaps']]
    return '\n'.join(lines)


def reputation_errors(text,package):
    errors=[]
    if text.strip()!=render_reputation(package).strip():errors.append('第五章出现未受原文支持的改写')
    allowed={eid for r in package['facts'] for eid in r['evidence_ids']}
    if set(EID.findall(text))-allowed:errors.append('第五章存在未知证据编号')
    if not package['facts']:errors.append('第五章没有可核对的评价及对标材料')
    return errors
