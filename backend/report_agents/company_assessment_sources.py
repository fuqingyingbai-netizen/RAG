"""Admit original platform data by its subject and fields, not its publisher class."""
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation

from .company_corpus import platform_source
from .company_diligence import exchange, folded, issuer_heading
from .company_evidence import blocked_original_reason, document_pages, source_body
from .company_governance import get


def markdown_tables(raw):
    blocks=[];current=[]
    for line in raw.splitlines()+['']:
        if line.strip().startswith('|') and line.strip().endswith('|'):
            current.append(line)
        elif current:
            blocks.append(current);current=[]
    for lines in blocks:
        if len(lines)<3 or not re.fullmatch(r'[ :|\-]+',lines[1].strip()):continue
        cells=lambda line:[c.strip() for c in line.strip().strip('|').split('|')]
        headers=cells(lines[0])
        for line in lines[2:]:
            values=cells(line)
            if len(values)==len(headers):
                yield dict(zip(headers,values)),line.strip()


def original_field_rows(raw):
    """Read native grids and JSON objects, preserving each literal quote."""
    yield from markdown_tables(raw)
    aliases={'company_name':'企业名称','field':'字段','value':'值','metric':'指标','current_value':'本期','previous_value':'上年同期',
        'unit':'单位','currency':'币种','scope':'统计范围','report_period':'报告期','report_end_date':'报告截至日',
        'funding_date':'融资日期','funding_amount':'融资金额','funding_round':'融资轮次',
        'investors':'投资方','completion_status':'完成状态','recipient':'收款主体','net_proceeds':'实际募集净额'}
    decoder=json.JSONDecoder(parse_float=str,parse_int=str)
    # Decode bounded objects at their original offsets rather than rebuilding
    # JSON text. Nested row objects retain their own native quote and precision.
    nodes=[]
    for match in re.finditer(r'\{',raw):
        try:value,end=decoder.raw_decode(raw,match.start())
        except (ValueError,json.JSONDecodeError):continue
        if not isinstance(value,dict):continue
        row={k:str(v) for k,v in value.items() if isinstance(v,(str,int,float)) and not isinstance(v,bool)}
        row.update({aliases[k]:v for k,v in list(row.items()) if k in aliases and aliases[k] not in row})
        if row:nodes.append((match.start(),end,row))
    for start,end,row in nodes:
        if not row.get('企业名称',row.get('公司名称')):
            parents=[(a,b,r) for a,b,r in nodes if a<start and end<=b and r.get('企业名称',r.get('公司名称'))]
            if parents:
                parent=max(parents,key=lambda n:n[0])[2]
                row={**row,'企业名称':parent.get('企业名称',parent.get('公司名称'))}
        yield row,raw[start:end]


def assessment_source_context(source,target):
    raw,origin=source_body(source)
    platform=platform_source(source)
    result={'platform':platform,'usable':False,'subject_bound':False,'pages':[],
            'reason':'original_text_unavailable','original_sha256':hashlib.sha256(raw.encode()).hexdigest()}
    if not raw or origin=='discovery_summary' or blocked_original_reason(raw):return result
    meta=get(source,'source_metadata',{}) or {}
    if meta.get('entity_validation') in {'rejected','ambiguous','related_entity_context'}:
        result['reason']='entity_validation:'+meta['entity_validation']
        return result
    if not platform and str(meta.get('fetch_status') or '').lower() in {
            'failed','fetch_timeout','blocked_or_challenge','empty','empty_pdf','invalid_pdf_response','unsupported_content_type'}:return result
    pages=document_pages(source) or [{'page':None,'text':raw}]
    heading_bound=issuer_heading(pages,target)
    if not platform:
        # Native grids cannot authorize another issuer's exchange disclosure.
        # The non-platform decision has always depended only on the exchange
        # and issuer heading; avoid parsing rows whose result it discards.
        bound=exchange(source) and heading_bound
        result.update(subject_bound=bool(bound),pages=pages,scoped_fields_only=False,
                      reason='field_level_review' if bound else 'subject_not_bound')
        if bound:result['usable']=True
        return result
    # A publication about another issuer cannot inherit the queried target.
    rows=list(original_field_rows(raw))
    names=[row.get('企业名称',row.get('公司名称','')) for row,_ in rows]
    names=[name for name in names if name]
    profiles=[row.get('值','') for row,_ in rows if row.get('字段') in {'企业名称','公司名称'}]
    names+=profiles
    profile_bound=any(folded(n)==folded(target) for n in profiles)
    # A mixed-company table is usable row by row. Other companies in a peer
    # comparison cannot disqualify a target's explicitly labelled row.
    bound=heading_bound or profile_bound or any(folded(n)==folded(target) for n in names)
    row_only=bool(platform and bound and not heading_bound and not profile_bound)
    result.update(subject_bound=bool(bound),pages=[] if row_only else pages,scoped_fields_only=row_only,
                  reason='subject_not_bound' if not bound else 'field_level_review')
    if bound:result['usable']=True
    return result


def assessment_anchor(source,cards):
    url=str(get(source,'url') or '')
    if not url:return None
    matches=[c for c in cards.get(url,[]) if re.fullmatch(r'E-[A-Z0-9-]{6,}',str(c.get('evidence_id') or ''))]
    seed='\n'.join(re.sub(r'\s+',' ',str(v or '').strip()) for v in (url,get(source,'title'),''))
    eid=matches[0]['evidence_id'] if matches else 'E-'+hashlib.sha256(seed.encode()).hexdigest()[:12].upper()
    return {'source_url':url,'source_title':str(get(source,'title') or ''),'evidence_id':eid,'evidence_ids':[eid]}


def platform_financial_rows(source,base,target):
    """Explicit platform row schema; no inferred year-end, units or scope."""
    from .company_risk_register import iso_date
    from .company_history import METRICS
    raw,_=source_body(source);records=[]
    row_only=assessment_source_context(source,target).get('scoped_fields_only',False)
    for row,quote in original_field_rows(raw):
        if row.get('指标') not in METRICS:continue
        period=row.get('报告期','');cutoff=iso_date(row.get('报告截至日',''))
        scope=row.get('统计范围','');currency=row.get('币种','');unit=row.get('单位','')
        if not (cutoff and cutoff[:4] in period and re.fullmatch(r'20\d{2}(?:年)?(?:年度|半年度|中期)(?:报告)?',period)):continue
        if scope not in {'合并','合并口径','公司整体口径','法人单体',target}:continue
        owner=row.get('企业名称',row.get('公司名称','' if row_only else target))
        if folded(owner)!=folded(target) or unit not in {'元','千元','万元','百万元','亿元'}:continue
        if currency not in {'人民币','港元','美元'}:continue
        values=[row.get(k,'') for k in ('本期','上年同期')]
        if not all(re.fullmatch(r'[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?',v) for v in values):continue
        a,b=[Decimal(v.replace(',','')) for v in values]
        computed=(a/b-1)*100 if b>0 else None
        printed=row.get('同比','');conflict=False
        if printed:
            try:conflict=computed is not None and abs(Decimal(printed.rstrip('%'))-computed)>Decimal('.06')
            except InvalidOperation:conflict=True
        records.append({**base,'kind':'financial_metric','entity':target,'metric':row['指标'],
            'period':period,'cutoff':cutoff,'period_kind':'interim' if re.search('半年度|中期',period) else 'annual',
            'value':values[0],'previous_value':values[1],'unit':unit,'currency':currency,'statistical_scope':scope,
            'computed_yoy_pct':str(computed) if computed is not None else None,'printed_yoy_conflict':conflict,
            'fact':quote,'evidence_quote':quote,'original_offset':raw.find(quote),'page':None,
            'mode':'专业平台原始财务字段；按平台所载主体、期间、币种、单位及统计范围评价，不冒称发行人或独立审计。'})
    return records


def platform_funding_records(source,base,target,as_of):
    """Keep platform funding rows, scoring only explicitly completed receipts."""
    from .company_risk_register import iso_date
    raw,_=source_body(source);observations=[];events=[]
    row_only=assessment_source_context(source,target).get('scoped_fields_only',False)
    for row,quote in original_field_rows(raw):
        if not {'融资日期','融资金额'}<=row.keys():continue
        owner=row.get('企业名称',row.get('公司名称','' if row_only else target))
        if folded(owner)!=folded(target):continue
        stamp=iso_date(row['融资日期'][:10])
        if not stamp or stamp>as_of:continue
        completed=row.get('完成状态') in {'已完成','完成','已到账'}
        net=row.get('实际募集净额',row.get('实际到账金额',''))
        net_ok=bool(re.fullmatch(r'\d[\d,.]*\s*(?:元|万元|千元|百万元|亿元)(?:人民币|港元|美元)?',net))
        recipient=row.get('收款主体')==target
        observation={**base,'kind':'platform_funding_observation','entity':target,'period':stamp,
            'fact':quote,'evidence_quote':quote,'original_offset':raw.find(quote),'platform_fields':row,
            'mode':'专业平台融资记录；保留原轮次、日期、金额、投资方及未知字段。',
            'boundary':'平台所列融资金额不自动等于实际募集净额或到账；未载完成状态、收款主体与实际净额时不满足融资执行评分锚点。'}
        observations.append(observation)
        if completed and net_ok and recipient:
            events.append({**base,'kind':'event','period':stamp,'fact':quote,'original_platform_row':True})
    return observations,events
