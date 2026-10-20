"""Local OCR of contents and nominated biography pages, with visible limits."""
import re
import time
import os
from datetime import datetime
from io import BytesIO

from person_text import folded


def contents_targets(lines):
    """Use labelled contents rows, never a company/person-specific page number."""
    result = []
    for box, value, score in lines:
        text = folded(value)
        if score < .8 or not re.search(r'董事.*管理|管理.*简历|管理.*履历|directors.*management|biograph', text, re.I) or re.search(r'身份|顾问|adviser|identity', text, re.I):
            continue
        y = sum(p[1] for p in box) / len(box)
        height = max(p[1] for p in box) - min(p[1] for p in box)
        numbers = [(abs(sum(p[1] for p in b) / len(b)-y), int(t)) for b, t, confidence in lines
                   if confidence >= .8 and re.fullmatch(r'\d{1,4}', str(t).strip())
                   and min(p[0] for p in b) > max(p[0] for p in box)
                   and abs(sum(p[1] for p in b) / len(b)-y) < max(12, height)]
        if numbers:
            logical = min(numbers)[1]
            # Cover the common cover-page offset without guessing a precise
            # physical page. Actual physical pages stay labelled in receipts.
            result.extend([logical, logical+1, logical+2])
    return list(dict.fromkeys(result))


def paragraph_text(lines):
    groups, current, previous_bottom, previous_height = [], [], None, None
    for box, text, score in lines:
        if not str(text).strip():
            continue
        top, bottom = min(p[1] for p in box), max(p[1] for p in box)
        height = max(1, bottom-top)
        if current and previous_bottom is not None and top-previous_bottom > max(height, previous_height or height) * .8:
            groups.append('\n'.join(current)); current = []
        current.append(str(text).strip())
        previous_bottom, previous_height = bottom, height
    if current:
        groups.append('\n'.join(current))
    return '\n\n'.join(groups)


def enrich_person_pdf(payload, pages, page_cap=6, seconds=45):
    from company_ocr import _pdfium_lock, _transcribe_page
    import pypdfium2 as pdfium
    receipt = {'method': 'local_contents_directed_ocr', 'attempted_pages': [], 'transcribed_pages': [],
               'status': 'not_needed', 'requires_visual_review': True, 'paid_model_requests': 0}
    deadline = os.getenv('RESEARCH_USER_DEADLINE_UTC')
    if deadline:
        remaining = datetime.fromisoformat(deadline.replace('Z', '+00:00')).timestamp() - time.time() - 10
        if remaining < 5:
            receipt['status'] = 'user_time_budget_exhausted'; return receipt
        seconds = min(seconds, remaining)
    damaged = [p for p in pages if p.get('native_text_issue')]
    if not pages or len(damaged) / len(pages) < .2:
        return receipt
    if not _pdfium_lock.acquire(timeout=3):
        receipt['status'] = 'busy'; return receipt
    started, document = time.monotonic(), None
    try:
        document = pdfium.PdfDocument(BytesIO(payload))
        by_page = {p['page']: p for p in pages}
        queue = [p['page'] for p in damaged if p['page'] <= 3]
        while queue and len(receipt['attempted_pages']) < page_cap and time.monotonic()-started < seconds:
            number = queue.pop(0)
            if number not in by_page or number in receipt['attempted_pages']:
                continue
            receipt['attempted_pages'].append(number)
            try:
                lines, render = _transcribe_page(document, number)
                targets = contents_targets(lines)
                if targets:
                    queue = targets + [n for n in queue if n not in targets]
                weighted = sum(len(str(t))*float(c) for _, t, c in lines) / max(1, sum(len(str(t)) for _, t, _ in lines))
                text = paragraph_text(lines)
                by_page[number].update(ocr_text=text, ocr_render=render, ocr_confidence=round(weighted, 6),
                    ocr_lines=[{'box': [[float(x), float(y)] for x,y in b], 'text': str(t), 'confidence': float(c)} for b,t,c in lines],
                    ocr_status='transcription_requires_visual_review')
                if weighted >= .9 and len(text) >= 30:
                    receipt['transcribed_pages'].append(number)
            except Exception as exc:
                by_page[number]['ocr_error_type'] = type(exc).__name__
        receipt.update(status='partial_requires_visual_review', elapsed_seconds=round(time.monotonic()-started, 2))
        return receipt
    finally:
        if document is not None:
            document.close()
        _pdfium_lock.release()
