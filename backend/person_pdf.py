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


def _pdfminer_pages(payload, numbers):
    """Alternate native decoder; physical page IDs must remain unchanged."""
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextContainer
    ordered = sorted(set(numbers))
    layouts = list(extract_pages(BytesIO(payload), page_numbers={n - 1 for n in ordered}))
    # PDFMiner's layout.pageid is sequential within the selected subset,
    # not the physical PDF page. Refuse an incomplete selection rather than
    # silently assigning the next page's text to a missing physical page.
    if len(layouts) != len(ordered):
        raise ValueError('native_fallback_page_count_mismatch')
    return {number: ''.join(item.get_text() for item in layout
            if isinstance(item, LTTextContainer)).replace('\x00', '').strip()
        for number, layout in zip(ordered, layouts)}


def repair_native_pages(payload, pages):
    """Prefer a clean native candidate only on pages with damaged text.

    Both decoder outputs remain attached to the same immutable PDF hash.
    This improves extraction, never independently verifies a source claim.
    """
    damaged = [p for p in pages if p['native_text_issue']]
    receipt = {'method': 'pdfminer_native_fallback', 'status': 'not_needed',
        'attempted_pages': [], 'replaced_pages': [], 'pending_pages': []}
    if not damaged:
        return receipt
    cap = integer('PERSON_PDF_NATIVE_FALLBACK_MAX_PAGES', 12, 1, 100)
    numbers = [p['page'] for p in damaged[:cap]]
    receipt['attempted_pages'] = numbers
    try:
        candidates = _pdfminer_pages(payload, numbers)
    except Exception as exc:
        receipt.update(status='unavailable', error_type=type(exc).__name__,
            pending_pages=[p['page'] for p in damaged])
        return receipt
    for page in damaged:
        candidate = candidates.get(page['page'])
        if candidate is None:
            continue
        issue = native_text_issue(candidate)
        page['native_extraction_alternatives'] = [
            {'decoder': 'pypdf', 'text': page['text'], 'quality_issue': page['native_text_issue']},
            {'decoder': 'pdfminer', 'text': candidate, 'quality_issue': issue}]
        if not issue:
            page.update(text=candidate, text_origin='embedded_pdf_text_pdfminer', native_text_issue='')
            receipt['replaced_pages'].append(page['page'])
    receipt['pending_pages'] = [p['page'] for p in damaged if p['native_text_issue']]
    receipt['status'] = 'partial' if receipt['pending_pages'] else 'completed'
    return receipt


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
        issue = native_text_issue(text)
        pages.append({'page': index + 1, 'text': text, 'text_origin': 'embedded_pdf_text', 'native_text_issue': issue})
    fallback = repair_native_pages(payload, pages)
    retained = []
    for page in pages:
        if used + len(page['text']) > char_cap:
            omitted.append(page['page'])
            continue
        retained.append(page)
        used += len(page['text'])
        if page['native_text_issue']:
            unclear.append(page['page'])
    pages = retained
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
                'needs_ocr_pages': unclear, 'native_fallback': fallback, 'ocr': ocr, 'complete': not omitted and not unclear,
                'boundary': '按物理页保留原文；文本不足或乱码的页待OCR/原页核对，未命中不能作为无记录。'}}
