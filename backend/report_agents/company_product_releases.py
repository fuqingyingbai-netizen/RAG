"""Dated product announcements, never sales or commercial performance."""
import re
from datetime import date
from urllib.parse import urlparse

from .company_evidence import source_body
from .company_governance import get
from .company_text import OriginalTextView,match_text


def product_release_rows(source,target,as_of):
    try:cutoff=date.fromisoformat(str(as_of))
    except ValueError:return []
    meta=get(source,'source_metadata',{}) or {}
    if meta.get('entity_validation') in {'rejected','ambiguous','related_entity_context'}:return []
    parsed=urlparse(str(get(source,'url') or ''))
    if parsed.scheme!='https' or not parsed.hostname:return []
    raw,origin=source_body(source)
    if origin=='discovery_summary':return []
    view=OriginalTextView(raw);text=view.text
    # Self-attribution is deliberately narrower than authenticating all
    # content on a domain. Do not add the host to a global issuer allowlist.
    footer_offset=max(0,len(text)-1200)
    footer=re.search(r'(?:©|Copyright)\s*20\d{2}\s*'+re.escape(match_text(target))+r'\s*版权所有',text[footer_offset:],re.I)
    if not footer:return []
    native_footer=view.quote(footer_offset+footer.start(),footer_offset+footer.end())
    pattern=r'(?:动态|产品更新|产品动态)\s*(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*\n+\s*([^\n]{5,160})\s*\n+\s*([^\n]{8,650})'
    result=[]
    for m in re.finditer(pattern,text):
        try:when=date(*(int(m[i]) for i in (1,2,3)))
        except ValueError:continue
        if when>cutoff:continue
        title,description=m[4].strip(),m[5].strip()
        if not re.search(r'发布|上线|更新|开源',description):continue
        if re.search(r'拟|预计|计划|将于|尚未|即将',description):continue
        native_title=view.quote(m.start(4),m.end(4)).strip()
        native_description=view.quote(m.start(5),m.end(5)).strip()
        result.append({'kind':'product_release','entity':native_title,'period':when.isoformat(),'release_date':when.isoformat(),
                       'release_description':native_description,'owner_binding_quote':native_footer,
                       'evidence_quote':view.quote(m.start(),m.end()).strip(),
                       'fact':when.isoformat()+'；发布页标题：'+native_title+'；发布页原文：'+native_description,
                       'mode':'网页页脚自署目标企业名称的产品发布自述；署名不等于独立验证，发布/开源不证明收入、订单、交付或性能领先'})
    return result
