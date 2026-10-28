"""Local, page-selective company PDF transcription; never a fact verifier.

Healthy embedded text is never sent through OCR. Damaged bilingual text keeps
its native English and an OCR alternative until layout/figures are reviewed.
Page limits, failures and low confidence remain visible to downstream writers.
"""
import hashlib
import os
import re
import threading
import time
import unicodedata
from importlib.metadata import version
from io import BytesIO

VERSION = 'company-page-ocr-v1'
LEGACY_AUDIT_REFRESH_VERSION = 'company-legacy-audit-original-v1'
_engine = None
_engine_lock = threading.RLock()
_pdfium_lock = threading.Lock()


def legacy_audit_original_needed(source, target):
    """Provider text without physical pages cannot rule out scanned opinions."""
    from report_agents.company_diligence import exchange, issuer_heading
    from report_agents.company_evidence import source_body
    from report_agents.company_governance import get
    if not str(target or '').strip():
        return False
    meta = get(source, 'source_metadata', {}) or {}
    if meta.get('entity_validation') in {'rejected', 'ambiguous', 'related_entity_context'}:
        return False
    if meta.get('document_pages') or meta.get('document_extraction'):
        return False
    url = str(get(source, 'url') or '').split('?', 1)[0].lower()
    if not url.endswith('.pdf') or not exchange(source):
        return False
    raw, origin = source_body(source)
    if origin == 'discovery_summary' or not re.search(r'内部控制审计报告|內部控制審計報告', raw):
        return False
    return issuer_heading([{'page': None, 'text': raw}], target)


def _integer(name, default, low, high):
    try:
        value = int(os.getenv(name, str(default)))
    except (ValueError, TypeError):
        value = default
    return max(low, min(high, value))


def native_text_issue(text):
    """Conservative signals for empty scans or a broken PDF character map.

    PUA checkboxes, traditional Chinese, accented Latin and a genuine single
    foreign script are not enough to classify a page as damaged text.
    """
    compact = re.sub(r'\s+', '', text or '')
    if len(compact) < 25:
        return 'low_text'
    if len(re.findall(r'\(cid:\d+\)|\ufffd', compact)) >= 3:
        return 'broken_character_map'
    unexpected = []
    for char in compact:
        name = unicodedata.name(char, '')
        script = name.split(' ', 1)[0]
        if unicodedata.category(char).startswith('L') and script not in {
            'CJK', 'LATIN', 'HIRAGANA', 'KATAKANA', 'HANGUL', 'BOPOMOFO',
            'MODIFIER', 'FULLWIDTH', 'HALFWIDTH',
        }:
            unexpected.append(script)
    if len(unexpected) >= 12 and len(set(unexpected)) >= 3:
        return 'mixed_script_character_map'
    return ''


def _recognize(image):
    global _engine
    # A shared CPU engine is serialized: mutable recognizer options are not
    # thread safe, and report collection must not spawn an ONNX pool per PDF.
    with _engine_lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1,
                               max_side_len=3200, det_use_cuda=False,
                               cls_use_cuda=False, rec_use_cuda=False)
        lines, _ = _engine(image)
    return lines or []


def _transcribe_page(pdf, page_number):
    import numpy as np
    page = pdf[page_number - 1]
    bitmap = None
    try:
        # Bound image memory even for poster-sized pages. Coordinates are
        # retained in pixels with the actual physical-page scale recorded.
        width, height = page.get_size()
        scale = min(2.5, 3200 / max(width, height))
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil().convert('RGB')
        image_size = list(image.size)
        lines = _recognize(np.asarray(image))
        return lines, {'scale': round(scale, 6), 'image_size': image_size}
    finally:
        if bitmap is not None:
            bitmap.close()
        page.close()


def enrich_pdf_pages(payload, pages):
    """Mutate selected page records and return honest coverage diagnostics.

    High confidence is transcription confidence, not numeric/table accuracy.
    Only low-native-text pages can replace their primary body automatically.
    Damaged character maps retain both alternatives for explicit visual review.
    """
    candidates = [p for p in pages if p.get('native_text_issue')]
    result = {
        'version': VERSION, 'engine': 'rapidocr_onnxruntime',
        'source_sha256': hashlib.sha256(payload).hexdigest(),
        'candidate_pages': [p['page'] for p in candidates],
        'attempted_pages': [], 'accepted_pages': [], 'alternative_pages': [],
        'pending_pages': [], 'failed_pages': [], 'status': 'not_needed',
        'boundary': 'OCR仅为机器转录；数字、表格列关系、签署日期和法律含义仍须原页核对。',
    }
    if not candidates:
        return result
    if os.getenv('COMPANY_PDF_OCR_ENABLED', 'true').lower() in {'false', '0', 'off'}:
        result.update(status='disabled', pending_pages=result['candidate_pages'])
        return result
    max_pages = _integer('COMPANY_PDF_OCR_MAX_PAGES', 8, 1, 100)
    max_seconds = _integer('COMPANY_PDF_OCR_MAX_SECONDS', 60, 1, 600)
    # PDFium is not thread safe, including opening/closing different files.
    # Bound waiting too, so concurrent collection cannot build an endless OCR
    # queue inside fetch threads. Busy pages remain available for a later pass.
    if not _pdfium_lock.acquire(timeout=max_seconds):
        result.update(status='busy', pending_pages=result['candidate_pages'])
        return result
    try:
        result['engine_version'] = version('rapidocr-onnxruntime')
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(BytesIO(payload))
    except Exception as exc:
        _pdfium_lock.release()
        result.update(status='unavailable', error_type=type(exc).__name__,
                      pending_pages=result['candidate_pages'])
        return result
    started = time.monotonic()
    try:
        for record in candidates:
            n = record['page']
            if len(result['attempted_pages']) >= max_pages or time.monotonic() - started >= max_seconds:
                record['ocr_status'] = 'budget_pending'
                result['pending_pages'].append(n)
                continue
            result['attempted_pages'].append(n)
            try:
                raw_lines, render = _transcribe_page(pdf, n)
                lines = []
                for box, text, score in raw_lines:
                    if str(text).strip():
                        lines.append({'box': [[round(float(x), 2) for x in point] for point in box],
                                      'text': str(text).strip(), 'confidence': round(float(score), 6)})
                text = '\n'.join(line['text'] for line in lines)
                total = sum(len(line['text']) for line in lines)
                confidence = sum(len(line['text']) * line['confidence'] for line in lines) / max(1, total)
                low = sum(len(line['text']) for line in lines if line['confidence'] < .8) / max(1, total)
                vertical = sum(len(line['text']) for line in lines
                               if max(p[1] for p in line['box']) - min(p[1] for p in line['box'])
                               > 1.3 * (max(p[0] for p in line['box']) - min(p[0] for p in line['box']))) / max(1, total)
                record.update(ocr_text=text, ocr_lines=lines, ocr_render=render,
                              ocr_confidence=round(confidence, 6), native_text=record['text'],
                              ocr_vertical_text_ratio=round(vertical, 6))
                plausible = len(re.sub(r'\s+', '', text)) >= 25 and confidence >= .9 and low <= .05 and not native_text_issue(text)
                if plausible and vertical <= .2 and record['native_text_issue'] == 'low_text':
                    record.update(text=text, text_origin='local_ocr', ocr_status='accepted_transcription',
                                  requires_numeric_layout_review=True)
                    result['accepted_pages'].append(n)
                else:
                    status = 'orientation_requires_review' if vertical > .2 else 'alternative_requires_review' if plausible else 'low_confidence' if text else 'no_text_detected'
                    record.update(ocr_status=status, text_origin='embedded_pdf_text')
                    if plausible:
                        result['alternative_pages'].append(n)
                    result['pending_pages'].append(n)
            except Exception as exc:
                record.update(ocr_status='failed', ocr_error_type=type(exc).__name__)
                result['failed_pages'].append(n)
                result['pending_pages'].append(n)
    finally:
        try:
            pdf.close()
        finally:
            _pdfium_lock.release()
    result.update(elapsed_seconds=round(time.monotonic() - started, 3),
                  status='partial' if result['pending_pages'] else 'transcribed')
    return result
