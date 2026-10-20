"""A separately labelled overseas issuer identity route, never a registry API."""
import re
from urllib.parse import urlparse

from .company_text import OriginalTextView
from .company_financial_statements import fiscal_report_period,consolidated_statement_rows


def overseas_filing_identity(sources,target):
    from .company_governance import get,_primary_filing
    from .company_evidence import document_pages,source_body
    for source in sources or []:
        host=(urlparse(str(get(source,'url') or '')).hostname or '').lower()
        if not (host=='hkexnews.hk' or host.endswith('.hkexnews.hk')) or not _primary_filing(source,target):continue
        raw,origin=source_body(source)
        if origin=='discovery_summary':continue
        meta=get(source,'source_metadata',{}) or {}
        if meta.get('entity_validation') in {'rejected','ambiguous','related_entity_context'}:continue
        view=OriginalTextView(raw[:6000]);text=view.text
        jurisdiction=re.search(re.escape(target)+r'\s*[（(]\s*于\s*(开曼群岛|百慕大|英属维尔京群岛|香港|新加坡)\s*注册成立[^）)]{0,50}[）)]',text)
        fiscal=fiscal_report_period(raw)
        if not jurisdiction or not fiscal:continue
        rows=consolidated_statement_rows(document_pages(source),target,{},fiscal['period'],fiscal['cutoff'],('营业收入','归母净利润','经营现金流'))
        if len({r['metric'] for r in rows})<3:continue
        return {'route':'official_overseas_filing','issuer_name':target,'jurisdiction':jurisdiction[1],
                'period':fiscal['period'],'identity_quote':view.quote(jurisdiction.start(),jurisdiction.end()),
                'source_url':str(get(source,'url')),'source_title':str(get(source,'title')),
                'financial_fields_verified':3,'financial_physical_pages':sorted({r['page'] for r in rows}),
                'boundary':'境外发行人官方原件身份/财年及原币报表字段路径；不是专业数据库命中、独立工商核验或司法/制裁无记录证明。'}
    return None
