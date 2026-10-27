"""Dated issuer listing facts and actual net proceeds from the same clause."""
import re
from datetime import date
from decimal import Decimal

from .company_evidence import document_pages, source_body
from .company_text import OriginalTextView, match_text

VERSION='company-listing-funding-v1-same-clause-actual-net'
DAY=r'20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日'
MONEY=r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'


def listing_funding_events(source,target,base,as_of):
    # An issuer heading alone cannot bind a subsidiary's or a prospectus's
    # hypothetical proceeds. Authentication and the local action both matter.
    from .company_assessment_sources import assessment_source_context
    from .company_risk_register import later_than_research_cutoff
    from .company_governance import get
    from .company_diligence import issuer_heading
    if (get(source,'source_metadata',{}) or {}).get('entity_validation') in {'rejected','ambiguous','related_entity_context'}:return []
    if as_of and later_than_research_cutoff(source,as_of):return []
    context=assessment_source_context(source,target)
    if not context['usable']:return []
    if context['platform'] and not issuer_heading(context['pages'],target):return []
    name=r'\s*'.join(map(re.escape,match_text(target)))
    start=re.compile(r'(?P<day>'+DAY+r')\s*[，,]?\s*(?:本公司|'+name+r')\s*(?:首次\s*公开\s*)?发行')
    net=re.compile(r'实际\s*募集\s*(?:资金|所得款项|款项)?\s*净额\s*(?:为|是|[：:])?\s*'
                   r'(?P<currency>人民币|港元|美元)\s*(?P<value>'+MONEY+r')\s*(?P<unit>亿元|万元|千元|百万元|元)')
    raw,_=source_body(source)
    pages=document_pages(source) or [{'page':None,'text':raw}]
    result=[]
    for page in pages:
        view=OriginalTextView(page['text'])
        for found in start.finditer(view.text):
            prefix=re.split(r'[。；;]|\n\s*\n',view.text[max(0,found.start()-250):found.start()])[-1]
            if re.search(r'假设|假定|如果|倘|若|拟于|计划于|预计|预期|估计|例如|示例|举例|子公司|附属公司',prefix):continue
            tail=view.text[found.start():found.start()+1800]
            amount=net.search(tail)
            if not amount:continue
            clause=tail[:amount.end()]
            # Never cross a second dated action, sentence or issuer to find
            # the amount. Overallotment is part of the original IPO cycle.
            if re.search(DAY,clause[len(found[0]):]) or '。' in clause:continue
            if re.search(r'拟|将(?:于|会|在|发行)|可能|有望|预定|预计|预期|估计|假设|尚未|尚待|获准|获批|超额配股|子公司|附属公司',clause):continue
            if not re.search(r'并\s*在[^。；]{1,100}?挂牌\s*上市(?:\s*交易)?',clause):continue
            parts=re.findall(r'\d+',found['day'])
            try:dt=date(*map(int,parts)).isoformat()
            except (ValueError,TypeError):continue
            if not as_of or dt>as_of:continue
            cutoff=date.fromisoformat(as_of)
            try:earliest=cutoff.replace(year=cutoff.year-2)
            except ValueError:earliest=cutoff.replace(year=cutoff.year-2,day=28)
            if dt<earliest.isoformat() or Decimal(amount['value'].replace(',',''))<=0:continue
            quote=view.quote(found.start(),found.start()+amount.end())
            if not quote or quote not in raw:continue
            result.append({**base,'entity':target,'kind':'event','event_type':'外部融资',
                'period':dt,'funding_date':dt,'status':'原件披露发行及挂牌上市',
                'fact':quote,'evidence_quote':quote,'original_offset':raw.find(quote),
                'page':page['page'],'pages':[page['page']] if page['page'] is not None else [],
                'value':amount['value'],'currency':amount['currency'],'unit':amount['unit'],
                'native_listing_funding':VERSION,
                'source_attribution':'专业平台所载发行原文；不冒称交易所独立回取' if context['platform'] else '发行人原始披露',
                'mode':'同一原文的具名发行挂牌事实与实际募集净额；不拼接后续配股，不把上市本身当净额到账。'})
    return result
