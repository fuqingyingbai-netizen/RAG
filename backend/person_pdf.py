"""Retain bounded complete PDF text before selecting person research excerpts."""
import hashlib
import os
import re
from io import BytesIO

from pypdf import PdfReader
from company_ocr import native_text_issue


def integer(name, default, low, high):
    try:
        return max(low, min(high, int(os.getenv(name, str(default)))))
    except (ValueError, TypeError):
        return default


def extract_person_pdf(payload):
    reader = PdfReader(BytesIO(payload))
    if reader.is_encrypted:
        reader.decrypt('')
    page_cap = integer('PERSON_PDF_MAX_PAGES', 1000, 1, 3000)
    char_cap = integer('PERSON_PDF_MAX_CHARS', 2000000, 1000, 6000000)
    pages, omitted, unclear, used = [], [], [], 0
    for index, page in enumerate(reader.pages):
        if index >= page_cap:
            omitted.extend(range(index + 1, len(reader.pages) + 1))
            break
        text = (page.extract_text() or '').replace('\x00', '').strip()
        if used + len(text) > char_cap:
            omitted.append(index + 1)
            continue
        issue = native_text_issue(text)
        if issue:
            unclear.append(index + 1)
        pages.append({'page': index + 1, 'text': text, 'text_origin': 'embedded_pdf_text', 'native_text_issue': issue})
        used += len(text)
    ocr = {'status': 'disabled'}
    if os.getenv('PERSON_PDF_OCR_ENABLED', 'true').lower() == 'true':
        from person_pdf_ocr import enrich_person_pdf
        ocr = enrich_person_pdf(payload, pages, integer('PERSON_PDF_OCR_MAX_PAGES', 6, 1, 12), integer('PERSON_PDF_OCR_MAX_SECONDS', 45, 5, 90))
    blocks = [f"--- PDF page {p['page']} ---\n{p['text']}" for p in pages if p['text']]
    blocks.extend(f"--- PDF page {p['page']} local OCR transcription pending visual review ---\n{p['ocr_text']}"
                  for p in pages if p.get('ocr_text') and p['page'] in ocr.get('transcribed_pages', []))
    return {'content': '\n\n'.join(blocks),
            'pages': len(reader.pages), 'document_pages': pages,
            'document_extraction': {'method': 'person_bounded_native_pdf_text', 'source_sha256': hashlib.sha256(payload).hexdigest(),
                'extracted_pages': len(pages), 'omitted_pages': len(omitted), 'omitted_page_numbers': omitted,
                'needs_ocr_pages': unclear, 'ocr': ocr, 'complete': not omitted and not unclear,
                'boundary': '按物理页保留原文；文本不足或乱码的页待OCR/原页核对，未命中不能作为无记录。'}}
