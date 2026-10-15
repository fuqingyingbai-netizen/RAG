"""Chapter 6: operational disclosures, with cells, periods and stages intact."""
import json
import re
from collections import Counter,defaultdict
from decimal import Decimal
from urllib.parse import urlparse

from .company_evidence import source_body,document_pages,pending_ocr_notice
from .company_governance import EID,_table,_filing_period,_period_rank,_primary_filing,compact,get,refs
from .company_history import _issuer_hosts

TITLE='主营业务真实经营情况核验'
HEADINGS=('分部门业务运营数据核验表','核心业务板块运营进展核验表','关键经营事实与核验判断','视觉与原页核对')
VERSION='company-business-v1'
NUMBER=r'[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
PERCENT=r'[-+]?\d+(?:\.\d+)?%'
DIMENSIONS={'分行业','分产品','分地区','分销售模式'}


def _clean(text,target=''):
    text=re.sub(r'--- PDF page \d+ ---',' ',str(text))
    if target:
        text=re.sub(re.escape(target)+r'\s*20\d{2}\s*年(?:半年度|年度)报告(?:全文|摘要)?\s*\d{0,3}',' ',text)
    return text


def _unit(text):
    m=re.search(r'单位\s*[:：]\s*((?:(?:人民币|美元|港元|欧元|日元|英镑|RMB|CNY|USD|HKD|US\$)\s*)?(?:亿|万|千)?元|(?:万|千)?(?:美元|港元|欧元|吨|辆|件|台)|(?:USD|HKD|RMB|CNY|US\$)(?:[\x27’]000|\s+(?:thousand|million|billion)s?)?)',text,re.I)
    return m[1] if m else ''


def _cell(value):
    return re.sub(r'\s+','',value or '')


def _prose(value):
    text=re.sub(r'\s+',' ',value or '').strip()
    return re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])','',text)


def _num(value):
    return bool(re.fullmatch(NUMBER,compact(value)))


def _pct(value):
    return bool(re.fullmatch(PERCENT,compact(value)))


def _periods(header,period):
    years=re.findall(r'(20\d{2})年',compact(header))
    y=re.search(r'20\d{2}',period)
    if len(years)>=2 and years[0]!=years[1]:
        if y and max(years[:2])!=y[0]:return None
        return years[0]+'年',years[1]+'年'
    if y and '本报告期' in compact(header) and '上年同期' in compact(header):
        return period,period.replace(y[0],str(int(y[0])-1),1)
    return None


def revenue_rows(raw,period,target=''):
    """Bound the composition table; numeric signatures survive PDF wrapping.

    This fallback requires two-decimal money cells. Vector grids below also
    handle delimited integer amounts without guessing flat integer boundaries.
    """
    text=compact(_clean(raw,target)).replace('|','')
    start=text.find('营业收入构成')
    if start<0:return []
    section=re.split(r'[（(]2[）)]|占公司营业收入或营业利润|营业收入比上年同期增减',text[start:])[0]
    unit=_unit(raw[raw.find('营业收入构成'):raw.find('营业收入构成')+400])
    periods=_periods(section[:400],period)
    if not unit or not periods:return []
    money=r'[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}'
    signature='('+money+')('+PERCENT+')('+money+')('+PERCENT+')('+PERCENT+')'
    rows=[];dimension='合计'
    for chunk in re.split(r'(分行业|分产品|分地区|分销售模式)',section):
        if chunk in DIMENSIONS:dimension=chunk;continue
        for m in re.finditer(r'([^%]{1,120}?)'+signature,chunk):
            label=m[1].strip('-:：')
            if dimension=='合计':
                if '营业收入合计' not in label:continue
                label='营业收入合计'
            elif re.search(r'同比|金额|占营业收入',label):continue
            a,share,b,prior_share,change=m.groups()[1:]
            if periods[0]>periods[1]:current,previous,ratio,previous_ratio=a,b,share,prior_share
            else:current,previous,ratio,previous_ratio=b,a,prior_share,share
            rows.append({'kind':'revenue','dimension':dimension,'entity':label,'value':current,'previous_value':previous,
                         'share':ratio,'previous_share':previous_ratio,'yoy':change,'unit':unit,
                         'period':period,'value_period':max(periods),'previous_period':min(periods),
                         'evidence_quote':m[0],'page':None})
    return mark_subcategories(rows)


def vector_financial_rows(pages,period):
    rows=[];dimension='';active=False;unit='';periods=None;last_page=0;mode=''
    for page in pages:
        if page['page']>last_page+1:active=False;dimension='';mode=''
        for table in page.get('tables') or []:
            head=''.join(compact(c) for row in table[:3] for c in row if c)
            if '占营业收入' in head and ('金额' in head):
                periods=_periods(head,period);unit=_unit(page['text']);active=bool(periods and unit);dimension='合计'
                mode='revenue'
            elif '营业成本' in head and '毛利率' in head:
                mode='margin';active=False;dimension='';unit=_unit(page['text']) or unit
            for row in table:
                cells=[_cell(c) for c in row if c and compact(c)]
                if len(cells)==1 and cells[0] in DIMENSIONS:dimension=cells[0]
                if mode=='margin' and unit and len(cells)==7 and dimension and _num(cells[1]) and _num(cells[2]) and all(_pct(x) for x in cells[3:]):
                    rows.append({'kind':'margin','dimension':dimension,'entity':cells[0],'value':cells[1],
                                 'cost':cells[2],'margin':cells[3],'revenue_yoy':cells[4],
                                 'cost_yoy':cells[5],'margin_change_source':cells[6],'unit':unit,
                                 'period':period,'page':page['page'],'evidence_quote':' | '.join(cells)})
                if mode=='revenue' and active and len(cells)==6 and _num(cells[1]) and _pct(cells[2]) and _num(cells[3]) and all(_pct(x) for x in cells[4:]):
                    label=cells[0]
                    if label=='营业收入合计':dimension='合计'
                    if not dimension:continue
                    a,share,b,prior_share,change=cells[1:]
                    if periods[0]>periods[1]:current,previous,ratio,previous_ratio=a,b,share,prior_share
                    else:current,previous,ratio,previous_ratio=b,a,prior_share,share
                    rows.append({'kind':'revenue','dimension':dimension,'entity':label,'value':current,'previous_value':previous,
                                 'share':ratio,'previous_share':previous_ratio,'yoy':change,'unit':unit,'period':period,
                                 'value_period':max(periods),'previous_period':min(periods),'page':page['page'],
                                 'evidence_quote':' | '.join(cells)})
        last_page=page['page']
    return mark_subcategories(rows)


def mark_subcategories(rows):
    """Resolve explicit '其中' branches only when both year sums reconcile."""
    for i,row in enumerate(rows):
        if row['kind']!='revenue' or not row['entity'].startswith(('其中：','其中:')) or not i:continue
        parent=rows[i-1]
        if parent['kind']!='revenue' or parent['dimension']!=row['dimension']:continue
        branch=[];current=Decimal(0);prior=Decimal(0)
        for child in rows[i:i+12]:
            if child['kind']!='revenue' or any(child.get(k)!=parent.get(k) for k in ('dimension','unit','period')):break
            try:
                current+=Decimal(child['value'].replace(',',''));prior+=Decimal(child['previous_value'].replace(',',''))
                total=Decimal(parent['value'].replace(',',''));old=Decimal(parent['previous_value'].replace(',',''))
            except Exception:break
            branch.append(child)
            if current==total and prior==old:
                for record in branch:record['parent_entity']=parent['entity']
                break
            if current>total or prior>old:break
        row.setdefault('parent_entity',parent['entity'])  # Explicit first subrow.
    return rows


def project_rows(pages,period):
    """Read only the actual progress column; stitch explicit continuations."""
    rows=[];active=False;last_page=0
    for page in pages:
        stop=re.search(r'公司研发人员情况|公司研发投入情况',compact(page['text']))
        if page['page']>last_page+1 or (stop and stop.start()<150):active=False
        for table in page.get('tables') or []:
            header=''.join(compact(c) for row in table[:2] for c in row if c)
            is_project='项目进展' in header and '项目目的' in header and '拟达到' in header
            if is_project:active=True
            elif active and not (page['page']==last_page+1 and len(table[0])==5):active=False
            if not active:continue
            for row_index,raw_row in enumerate(table):
                cells=[_prose(c) for c in raw_row]
                nonempty=[c for c in cells if c]
                if '项目进展' in ''.join(nonempty) or not nonempty:continue
                if len(cells)==5 and not cells[0] and cells[2] and rows and row_index==0 and page['page']==last_page+1:
                    rows[-1]['progress']=_prose(rows[-1]['progress']+' '+cells[2])
                    rows[-1]['evidence_quote']=rows[-1]['progress']
                    rows[-1]['pages'].append(page['page'])
                    continue
                if len(nonempty)!=5:continue
                name,purpose,progress,goal,impact=nonempty
                if name in {'目名称','主要研发项目名称'} or len(name)>100 or len(progress)<8:continue
                rows.append({'kind':'project','entity':_cell(name),'progress':progress,'goal':goal,
                             'period':period,'page':page['page'],'pages':[page['page']],
                             'evidence_quote':progress,'mode':'公司项目进展披露／非独立性能测试'})
        last_page=page['page']
        if stop:active=False
    for row in rows:
        row['status']=project_status(row['progress'])
        row['timing_note']=timing_note(row['progress'],period)
        row['after_period']=bool(row['timing_note'])
        row['fact']=row['entity']+'：'+row['progress']
    return rows


def project_status(text):
    text=compact(text)
    if re.search(r'尚未|未完成|未投产|未上市',text):return '尚未完成相应节点'
    if re.search(r'预计|计划|拟|将于|规划|即将|未来将',text):
        return '阶段进展与后续计划并存，未将计划视为完成' if re.search(r'完成|达到|发布|交付|量产|投产|通线|下线|应用验证|新增应用|运行',text) else '计划／拟议'
    if re.search(r'交付|量产|规模化生产|投产|通线|下线',text):return '原文记载交付/生产动作；产能与商业成果另核'
    if re.search(r'发布|上市',text):return '原文记载发布/上市动作；不等于销量或量产'
    return '研发阶段或公司技术自述；实际效果待核验'


def timing_note(text,period):
    text=_cell(text);year=re.search(r'20\d{2}',period)
    if not year:return ''
    year=int(year[0]);end=6 if '半年度' in period else 3 if '第一季度' in period else 9 if '第三季度' in period else 12
    dates=list(re.finditer(r'(20\d{2})年(?:([01]?\d)月)?',text))
    if any(int(m[1])>year or (int(m[1])==year and m[2] and int(m[2])>end) for m in dates):
        return '包含报告期后日期，不计为报告期内完成'
    months={'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,'十一':11,'十二':12}
    if end<12:
        for m in re.finditer(r'(十一|十二|[一二三四五六七八九十]|1[012]|0?[1-9])月',text):
            if any(d.start()<=m.start()<d.end() for d in dates):continue
            value=months[m[1]] if m[1] in months else int(m[1])
            if value>end:return '含晚于报告期末的月份，年份按原文核对，不计为报告期内完成'
    return ''


def production_rows(pages,period):
    rows=[];annual=False;monthly=False;unit='';capacity_note=''
    for page in pages:
        text=compact(page['text'])
        note=re.search(r'产能状况指[^。]{1,100}',text)
        if note:capacity_note=note[0]
        for table in page.get('tables') or []:
            head=''.join(compact(c) for row in table[:3] for c in row if c)
            if '本月' in head and '本年累计' in head and '产量' in head and '销量' in head:
                monthly=True;annual=False;unit=_unit(page['text'])
            elif '快报产量' in head and '快报销量' in head and '上年同期' in head:
                annual=True;monthly=False;unit=_unit(page['text'])
            for raw_row in table:
                cells=[_cell(c) for c in raw_row if c and compact(c)]
                if annual and unit and len(cells)==7 and all(_num(cells[i]) for i in (1,2,4,5)) and _pct(cells[3]) and _pct(cells[6]):
                    rows.append({'kind':'production','entity':cells[0].lstrip('-'),'period':period,'unit':unit,
                                 'produced':cells[1],'previous_produced':cells[2],'production_yoy':cells[3],
                                 'sold':cells[4],'previous_sold':cells[5],'sales_yoy':cells[6],
                                 'page':page['page'],'evidence_quote':' | '.join(cells),'mode':'年报产销披露，非终端零售/上险'})
                if monthly and unit and len(cells)==11 and all(_num(cells[i]) for i in (1,2,3,4,6,7,8,9)) and _pct(cells[5]) and _pct(cells[10]):
                    rows.append({'kind':'monthly','entity':cells[0].lstrip('-'),'period':period,'unit':unit,
                                 'produced':cells[1],'previous_produced':cells[2],'cumulative_produced':cells[3],
                                 'previous_cumulative_produced':cells[4],'production_yoy':cells[5],
                                 'sold':cells[6],'previous_sold':cells[7],'cumulative_sold':cells[8],
                                 'previous_cumulative_sold':cells[9],'sales_yoy':cells[10],
                                 'page':page['page'],'evidence_quote':' | '.join(cells),'mode':'月度产销快报，未视为审计确认/终端零售'})
    for row in rows:
        row['capacity_note']=capacity_note
        row['fact']=row['entity']+'：产量'+row['produced']+row['unit']+'，销量'+row['sold']+row['unit']
        if row['kind']=='monthly':row['fact']+='；本年累计销量'+row['cumulative_sold']+row['unit']
    return rows


def _issuer(source,target,hosts):
    meta=get(source,'source_metadata',{}) or {};raw=str(get(source,'content'));host=(urlparse(str(get(source,'url'))).hostname or '').lower().removeprefix('www.')
    if meta.get('entity_validation') in {'rejected','ambiguous','related_entity_context'}:return False
    if _primary_filing(source,target):return True
    exchange=any(host==d or host.endswith('.'+d) for d in ('szse.cn','sse.com.cn','cninfo.com.cn','hkexnews.hk'))
    return (exchange or host in hosts) and bool(re.search(re.escape(compact(target))+r'(?:[（(][^）)]{0,25}[）)])?(?:20\d{2}年|关于)',compact(raw[:1600])))


def operating_updates(pages,period,target):
    """Literal issuer operating updates, separate from table measurements."""
    rows=[]
    for page in pages:
        if page['page']>80:break
        text=_cell(_clean(page['text'],target))
        # Do not parse the annual R&D table twice through its flattened text.
        if any('项目进展' in ''.join(str(c) for row in t[:2] for c in row) for t in page.get('tables') or []):continue
        for sentence in re.split(r'(?<=[。；])',text):
            if not (40<=len(sentence)<=700):continue
            if not re.search(r'本公司|本集团|我们',sentence):continue
            if not re.search(r'工厂|基地|生产线|产线|生产设施',sentence):continue
            if not re.search(r'投产|下线|交付|开通|奠基|扩产|在建|建设|规划',sentence):continue
            if not re.search(r'\d|一月|二月|三月|四月|五月|六月|七月|八月|九月|十月|十一月|十二月',sentence):continue
            rows.append({'kind':'operating_update','entity':'产线/基地进展','period':period,'page':page['page'],
                         'fact':sentence,'evidence_quote':sentence,'status':project_status(sentence),
                         'timing_note':timing_note(sentence,period),
                         'mode':'公司经营自述，开工/首车下线/投产/交付分开，非独立现场核验'})
    return rows


def build_business_package(cleaned,target,sources=None,*,limit=50000):
    by_url=defaultdict(list)
    for card in cleaned.get('facts') or []:
        if isinstance(card,dict) and EID.fullmatch(str(card.get('evidence_id') or '')):by_url[str(card.get('source_url') or '')].append(card)
    hosts=_issuer_hosts(sources,target);records=[];counts=Counter()
    for source in sources or []:
        raw,origin=source_body(source);url=str(get(source,'url'))
        if origin=='discovery_summary' or not _issuer(source,target,hosts):continue
        cards=[c for c in by_url[url] if c.get('eligible_for_report') is not False and c.get('entity_match') not in {'mismatch','ambiguous','out_of_scope'} and c.get('source_entity_validation')!='rejected']
        if not cards:continue
        card=cards[0];period=_filing_period({'content':raw,'title':''})
        if not period:
            m=re.search(r'20\d{2}\s*年\s*\d{1,2}\s*月产销快报',raw[:1600])
            period=compact(m[0]).replace('产销快报','') if m else ''
        if not period:continue
        pages=document_pages(source)
        financial=vector_financial_rows(pages,period)
        revenue=[r for r in financial if r['kind']=='revenue'] or revenue_rows(raw,period,target)
        rows=revenue+[r for r in financial if r['kind']=='margin']+project_rows(pages,period)+production_rows(pages,period)+operating_updates(pages,period,target)
        extraction=(get(source,'source_metadata',{}) or {}).get('document_extraction') or {}
        counts['table_pages_pending']+=len((extraction.get('business_tables') or {}).get('pending_pages') or [])
        counts['empty_grid_pages']+=len((extraction.get('business_tables') or {}).get('empty_grid_pages') or [])
        counts['omitted_document_pages']+=int(extraction.get('omitted_pages') or 0)
        counts['needs_ocr_pages']+=len(extraction.get('needs_ocr_pages') or [])
        for row in rows:
            if row['kind']=='revenue':row['fact']=row['dimension']+'，'+row['entity']+'：收入'+row['value']+row['unit']+'，占比'+row['share']+'，上年同期'+row['previous_value']+row['unit']+'，同比'+row['yoy']
            elif row['kind']=='margin':row['fact']=row['dimension']+'，'+row['entity']+'：收入'+row['value']+row['unit']+'，营业成本'+row['cost']+row['unit']+'，毛利率'+row['margin']
            row.update(evidence_id=card['evidence_id'],evidence_ids=[card['evidence_id']],source_url=url,source_title=card.get('source_title',''),evidence_scope='target_direct')
            records.append(row)
    # Merge mirrors, retain exact period/dimension/unit and any true conflicts.
    unique=[];seen={}
    for row in records:
        data={k:v for k,v in row.items() if k not in {'source_url','source_title','evidence_id','evidence_ids','page','pages','evidence_quote','evidence_scope'}}
        key=json.dumps(data,ensure_ascii=False,sort_keys=True)
        if key in seen:
            seen[key]['evidence_ids']=list(dict.fromkeys(seen[key]['evidence_ids']+row['evidence_ids']));counts['duplicate_claim']+=1
        else:seen[key]=row;unique.append(row)
    groups=defaultdict(list)
    for row in unique:
        if row['kind']!='operating_update':groups[(row['kind'],row['period'],row.get('dimension'),row['entity'],row.get('unit'))].append(row)
    conflicts=[]
    for key,group in groups.items():
        if len(group)>1:
            conflicts.append({'kind':key[0],'period':key[1],'entity':key[3],'evidence_ids':list(dict.fromkeys(e for r in group for e in r['evidence_ids']))})
            for row in group:row['conflict']=True
    periods=sorted({r['period'] for r in unique if r['kind']=='revenue'},key=_period_rank,reverse=True)
    annual=next((p for p in periods if '年度' in p and '半年度' not in p),None)
    interim=next((p for p in periods if '半年度' in p),None)
    selected_periods={p for p in (annual,interim) if p}
    latest=periods[0] if periods else None
    selected=[r for r in unique if r['kind'] in {'revenue','margin'} and r['period'] in selected_periods
              and (r.get('dimension') in {'分产品','合计'} or (r['period']==latest and r.get('dimension') in {'分地区','分销售模式'}))]
    projects=sorted([r for r in unique if r['kind']=='project'],key=lambda r:_period_rank(r['period']),reverse=True)
    # Cover original table pages and stages before filling the remaining slots;
    # first-N rows can omit whole business lines at the end of a filing.
    names=set();covered_pages=set();covered_stages=set();ordered=[]
    for r in projects:
        if (r['period'],r['page']) not in covered_pages:
            ordered.append(r);covered_pages.add((r['period'],r['page']))
    for r in projects:
        if r['status'] not in covered_stages:ordered.append(r);covered_stages.add(r['status'])
    for r in ordered+projects:
        if r['entity'] not in names and len(names)<12:
            selected += [x for x in projects if x['entity']==r['entity'] and x['period']==r['period']]
            names.add(r['entity'])
    updates=sorted([r for r in unique if r['kind']=='operating_update'],key=lambda r:_period_rank(r['period']),reverse=True)
    selected+=updates[:6]
    for kind in ('production','monthly'):
        rows=[r for r in unique if r['kind']==kind]
        if rows:
            if kind=='monthly':newest=max(rows,key=lambda r:tuple(map(int,re.findall(r'\d+',r['period']))))['period']
            else:newest=max(rows,key=lambda r:_period_rank(r['period']))['period']
            eligible=[r for r in rows if r['period']==newest and not r['entity'].startswith(('轿车','SUV','MPV','客车','其他'))]
            totals=[r for r in eligible if r['entity'] in {'合计','总计'}]
            if totals:
                eligible=[r for r in eligible if r in totals or not any(all(r.get(k)==t.get(k) for k in ('produced','sold','cumulative_produced','cumulative_sold')) for t in totals)]
            selected += eligible[:6]
    delivered=[]
    for r in selected:
        if len(json.dumps(delivered+[r],ensure_ascii=False))<max(0,limit-3500):delivered.append(r)
        else:counts['budget_excluded']+=1
    gaps=['核对产品级订单、交付/验收、发票及回款；财务披露不替代业务真实性独立验证。',
          '核对设计产能、可用产能、实际产量和统计期间；不把产量列当设计产能，不据此计算100%利用率。',
          '研发进展、拟达到目标、预计上市及商业化收入分开；报告期后动作不计为报告期内完成。',
          '集团分产品统计不等于部门账或单个业务独立营收，不拆分未单独披露业务的独立收入。']
    if not any(r['kind']=='project' for r in delivered):gaps.append('研发项目进度尚未取得可绑定原表单元格的记录，不能由投入、专利或宣传补写量产。')
    if counts['table_pages_pending']:gaps.append('部分业务表格页尚待单元格提取/原页核对，未选到数据不等于企业未披露。')
    if counts['empty_grid_pages']:gaps.append('部分候选页未识别出向量网格；文字可读也不等于表格单元格已绑定，需补做版面核对。')
    if counts['omitted_document_pages']:gaps.append('部分原件因提取上限尚未覆盖全文；本章仅使用已取得原页，不把未提取部分视为无披露。')
    if counts['needs_ocr_pages']:gaps.append(pending_ocr_notice(sources,'原件含低文字页，尚未实际执行OCR；嵌入文本/向量表格提取不能代表扫描页已识别。'))
    if conflicts:gaps.append('同主体、期间、维度与单位的来源记录存在差异，保留各值及出处，需核对重述、范围或版本；未择一认定。')
    return {'version':VERSION,'target_name':target,'facts':delivered,'information_gaps':gaps,
            'conflicts':conflicts,
            'diagnostic':{'candidate_claims':len(records),'delivered_claims':len(delivered),
                          'by_kind':dict(Counter(r['kind'] for r in delivered)),'filters':dict(counts)}}


def render_business(package):
    records=package['facts'];lines=['## 6. '+TITLE,'','### '+HEADINGS[0],'']
    revenue=[r for r in records if r['kind']=='revenue' and r['dimension']!='合计']
    margins=defaultdict(list)
    for r in records:
        if r['kind']=='margin':margins[(r['period'],r['dimension'],r['entity'],r['unit'])].append(r)
    if revenue:
        rows=[]
        for r in revenue:
            candidates=margins.get((r['period'],r['dimension'],r['entity'],r['unit']),[])
            margin=candidates[0] if len(candidates)==1 and not candidates[0].get('conflict') and not r.get('conflict') else None
            values='收入'+r['value']+r['unit']+'；占营业收入'+r['share']+'；源表同比'+r['yoy']
            if margin and margin['value']==r['value']:values+='；毛利率'+margin['margin']
            citation=refs(r)+(f"（物理页{r['page']}）" if r.get('page') else '')
            if margin and margin['value']==r['value'] and margin['page']!=r.get('page'):citation+='；毛利率'+refs(margin)+f"（物理页{margin['page']}）"
            boundary='同口径来源差异待核，未择一' if r.get('conflict') else '集团披露口径，非单一部门台账'
            if r.get('parent_entity'):boundary+='；包含在“'+r['parent_entity']+'”中，勿与上级加总'
            rows.append([r['dimension']+'：'+r['entity'],r['period'],values,boundary,citation])
        lines+=_table(['市场/业务范围','期间','源表数据','核验边界','来源'],rows)
        lines+=['','分产品、分地区、销售模式各为不同观察维度；同表总项与“其中”子项不能相加。各期名称/范围按原表保留，名称变化不视为完全可比。']
    else:lines+=['尚未形成可核对的分产品收入表，不能把评级预估或经营范围当实际收入。']
    lines+=['','### 生产与销售数量核对','']
    production=[r for r in records if r['kind'] in {'production','monthly'}]
    if production:
        lines+=_table(['范围','期间','当期产量','当期销量','累计及同比口径','性质／来源'],[
            [r['entity'],r['period'],r['produced']+r['unit'],r['sold']+r['unit'],
             ('本年累计销量'+r['cumulative_sold']+r['unit']+'；累计销量同比'+r['sales_yoy']) if r['kind']=='monthly' else '销量较上年同期'+r['sales_yoy'],
             r['mode']+'；'+refs(r)] for r in production])
        notes=list(dict.fromkeys(r['capacity_note'] for r in production if r.get('capacity_note')))
        for note in notes:lines+=['','原表注释：“'+note+'”。该字段不作为设计产能，未据此计算产能利用率。']
        lines+=['','年报、半年报、单月快报与本年累计分开；快报披露不当作审计确认或终端零售/上险。产销差额也不能直接当库存变动。表内总计与下级分类互有包含，不能逐行相加。']
    else:lines+=['本章尚未形成可绑定期间和单位的产销表，产量、产能、交付和终端销量分别待核。']
    lines+=['','### '+HEADINGS[1],'']
    projects=[r for r in records if r['kind']=='project']
    if projects:
        lines+=_table(['技术/项目','披露期与动作时点','项目进展栏原文（公司自述）','阶段边界','来源'],[
            [r['entity'],r['period']+('；'+r['timing_note'] if r['after_period'] else ''),r['progress'],r['status'],
             refs(r)+'（物理页'+','.join(map(str,r['pages']))+'）'] for r in projects])
        lines+=['','上表只使用“项目进展”栏；“拟达到的目标”和“预计影响”未转写为已实现结果。性能、零失效、领先等表述仍为公司自述，需试验条件、样本及外部测试核验。研发投入及资本化见第四章，未由高投入推导商业化效率。']
    else:lines+=['项目级研发/投产进度尚待原表核对，未用目标栏、专利数量或产品官图补写已量产。']
    updates=[r for r in records if r['kind']=='operating_update']
    if updates:
        lines+=['','生产设施进展另按公司经营自述列示；首车下线、周年交付和在建不互相替代，也不证明设计产能达产。','']
        for r in updates:lines+=['- '+r['period']+'：'+r['fact']+'（'+r['status']+('；'+r['timing_note'] if r['timing_note'] else '')+'）'+refs(r)+f"（物理页{r['page']}）"]
    lines+=['','### '+HEADINGS[2],'']
    for r in records:
        if r.get('conflict') and r['kind']=='margin':
            lines+=['- 同口径来源差异待核，未择一：'+r['period']+'，'+r['fact']+'。'+refs(r)+f"（物理页{r['page']}）"]
    for r in records:
        if r['kind']=='margin' and r['dimension']=='分产品':
            try:divergence=Decimal(r['cost_yoy'].rstrip('%'))>Decimal(r['revenue_yoy'].rstrip('%'))
            except Exception:divergence=False
            if divergence and not r.get('conflict'):lines+=['- '+r['period']+'，'+r['entity']+'收入同比'+r['revenue_yoy']+'、营业成本同比'+r['cost_yoy']+'，毛利率'+r['margin']+'；成本变动率高于收入变动率，经营效益仍需结合毛利及其他费用核对。'+refs(r)]
    lines+=['- 经营登记、产品图片和技术发布不能证明订单、实际交付及收款；缺少某一明细也不能直接判定声量大销量弱、海外产能脱节或重炒作轻业务。',
            '','### '+HEADINGS[3],'','表格引用保留物理页及原始单位。可读向量表格按单元格核对，未称为OCR；图片只在实际检查内容和图注后才可支持对应事实，宣传外观图不作为产能、性能或销量证明。',
            '','### 后续经营核验材料','']+['- '+g for g in package['information_gaps']]
    return '\n'.join(lines)


def business_errors(text,package):
    errors=[]
    if text.strip()!=render_business(package).strip():errors.append('第六章出现未受原始业务数据支持的改写')
    allowed={eid for r in package['facts'] for eid in r['evidence_ids']}
    if set(EID.findall(text))-allowed:errors.append('第六章存在未知证据编号')
    if not package['facts']:errors.append('第六章没有可核对的经营数据')
    return errors
