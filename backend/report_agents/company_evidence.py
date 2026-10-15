"""Keep retrieved company document text separate from generated search leads."""
import re

from .company_governance import get


def pending_ocr_notice(sources, untouched_notice):
    attempted = any((((get(source,'source_metadata',{}) or {}).get('document_extraction') or {}).get('ocr') or {}).get('attempted_pages') for source in sources or [])
    if attempted:
        return '仍有页面待识别或原页核对；已尝试OCR不等于全部页面或数字表格均已验收，未取得内容不证明没有披露或风险。'
    return untouched_notice


def source_body(source):
    meta=get(source,'source_metadata',{}) or {}
    content=str(get(source,'content') or '').strip()
    # Collection can persist a search abstract in `content` when fetching
    # failed. It is still a discovery lead, not a retrieved original page.
    kind=str(meta.get('content_kind') or '').lower()
    status=str(meta.get('fetch_status') or meta.get('extraction_status') or '').lower()
    lead=kind in {'summary','summary_only','search_summary','search_snippet','snippet','empty_content'}
    lead=lead or (status in {'failed','fetch_timeout','blocked_or_challenge','empty','invalid_pdf_response'}
                 and content==str(get(source,'summary') or '').strip())
    if content and not lead:
        return content,'retrieved_content'
    ocr=str(meta.get('ocr_text') or '').strip()
    if ocr and str(meta.get('ocr_status') or '').lower() in {'done','success','completed'}:
        return ocr,'completed_ocr'
    return str(get(source,'summary') or content or '').strip(),'discovery_summary'


def document_pages(source):
    """Use persisted physical pages, or recover their labels from raw text."""
    meta=get(source,'source_metadata',{}) or {}
    pages=meta.get('document_pages')
    if isinstance(pages,list):
        return [p for p in pages if isinstance(p,dict) and isinstance(p.get('page'),int) and p.get('text')]
    text,origin=source_body(source)
    if origin=='discovery_summary':return []
    chunks=re.split(r'--- PDF page (\d+) ---\s*',text)
    return [{'page':int(chunks[i]),'text':chunks[i+1]} for i in range(1,len(chunks)-1,2)]
