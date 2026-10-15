"""Company-only PDF collection: retain physical pages beyond the introduction."""
import os
import re
from io import BytesIO

from pypdf import PdfReader


def _limit(name,default,minimum,maximum):
    try:value=int(os.getenv(name,str(default)))
    except (TypeError,ValueError):value=default
    return max(minimum,min(maximum,value))


def extract_company_pdf(payload):
    reader=PdfReader(BytesIO(payload))
    if reader.is_encrypted:reader.decrypt('')
    max_pages=_limit('COMPANY_PDF_MAX_PAGES',300,1,500)
    max_chars=_limit('COMPANY_PDF_MAX_CHARS',800000,10000,2000000)
    pages=[];blocks=[];used=0;needs_ocr=[]
    for index,page in enumerate(reader.pages):
        if index>=max_pages:break
        text=(page.extract_text() or '').replace('\x00','').strip()
        if len(re.sub(r'\s+','',text))<25:
            needs_ocr.append(index+1)
        if used+len(text)>max_chars:continue
        record={'page':index+1,'text':text}
        # Two-column metric tables need both labels and cell alignment. Keep
        # layout for relevant pages without pretending text extraction is OCR.
        if re.search(r'满意度|投诉|员工流失率|market share|satisfaction',text,re.I):
            try:record['layout_text']=(page.extract_text(extraction_mode='layout') or '').replace('\x00','')
            except Exception:pass
        pages.append(record)
        if text:blocks.append(f'--- PDF page {index+1} ---\n{text}')
        used+=len(text)
    return {'content':'\n\n'.join(blocks),'pages':len(reader.pages),'document_pages':pages,
            'document_extraction':{'method':'embedded_pdf_text','extracted_pages':len(pages),
                                   'omitted_pages':len(reader.pages)-len(pages),'needs_ocr_pages':needs_ocr,
                                   'complete':len(pages)==len(reader.pages) and not needs_ocr}}
