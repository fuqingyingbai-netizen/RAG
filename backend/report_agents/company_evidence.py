"""Keep retrieved company document text separate from generated search leads."""
import re
from collections import Counter

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
    lead=lead or (status in {'failed','fetch_timeout','blocked_or_challenge','empty','empty_pdf','invalid_pdf_response','unsupported_content_type','skipped'}
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


def without_sequence_footers(pages):
    """A working view; require a repeated physical/printed-page offset."""
    endings=[]
    for page in pages:
        for edge,pattern in [('trailing',r'(?m)^[ \t]*(\d{1,4})[ \t]*\s*\Z'),
                             ('leading',r'\A\s*(\d{1,4})[ \t]*\r?\n')]:
            match=re.search(pattern,page['text'])
            if match:endings.append((page['page'],match,(edge,int(match[1])-page['page'])))
    counts=Counter(key for _,_,key in endings)
    proven={key for key,count in counts.items() if count>=3 and count>=len(pages)*.5}
    result=[]
    for page in pages:
        matches=[(match,key[0]) for number,match,key in endings if number==page['page'] and key in proven]
        if matches:
            body=page['text']
            for match,_ in sorted(matches,key=lambda pair:pair[0].start(),reverse=True):body=body[:match.start()]+body[match.end():]
            result.append({**page,'text':body.strip(),
                           'source_text_transformations':[{'kind':'sequence_page_number','physical_page':page['page'],
                             'edge':edge,'original':match[0],'start':match.start(),'end':match.end()} for match,edge in matches]})
        else:result.append(page)
    return result


def annotate_page_notes(quote,pages):
    """Mark a number only with a same-page definition and a literal quote."""
    compact=lambda value:re.sub(r'\s+','',str(value))
    wanted=compact(quote)
    for page in pages:
        text=page['text']
        if not wanted or wanted not in compact(text):continue
        notes={m[1] for m in re.finditer(r'(?m)^[ \t]*(\d{1,3})[ \t]+(?=[\u4e00-\u9fffA-Za-z])[^\n]{8,}',text)}
        display=quote
        for number in sorted(notes,key=len,reverse=True):
            # Numbered agenda items can resemble footnote definitions. Even
            # when one exists on the page, an ordinary date/quantity is not a
            # note reference (for example "2025年6月12日").
            display=re.sub(r'(?<=[\u4e00-\u9fff])\s*'+re.escape(number)+r'\s*(?![年月日人元股岁次个项倍%％])(?=[\u4e00-\u9fff])','〔注'+number+'〕',display)
        return display
    return quote


def labelled_original_note(text):
    return re.sub(r'^\s*(\d{1,3})\s*(?=[\u4e00-\u9fff])',r'原文标号\1：',text)
