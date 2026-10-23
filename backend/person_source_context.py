"""Literal document context; source periods never become personal event dates."""
import re
from functools import lru_cache
from person_text import folded


def document_issuer(source):
    """Read a literal cover company name, never infer issuer from mentions."""
    pages = (getattr(source, 'source_metadata', None) or {}).get('document_pages') or []
    cover = next((p for p in pages if p.get('page') == 1), None)
    if not cover:
        return ''
    body = cover.get('ocr_text') or cover.get('text') or ''
    for line in body.splitlines():
        line = line.strip()
        if re.fullmatch(r'[\u4e00-\u9fff]{2,35}(?:股份有限公司|控股有限公司|有限公司)', folded(line)):
            return line
    return ''


@lru_cache(maxsize=48)
def _document(text, title):
    flat = re.sub(r'\s+', '', text)
    markers = [(m.start(), int(m[1])) for m in re.finditer(
        r'---PDFpage(\d+)(?:localOCRtranscriptionpendingvisualreview)?---', flat)]
    header = title + '\n' + text[:4000]
    period = re.search(r'(?:19|20)\d{2}\s*年?\s*(?:年度报告|年度報告|年报|年報|annual\s*report)', header, re.I)
    return flat, markers, period[0] if period else ''


def literal_document_context(source, quote):
    text = str(getattr(source, 'content', '') or '')
    flat, markers, period = _document(text, str(getattr(source, 'title', '') or ''))
    metadata = getattr(source, 'source_metadata', None) or {}
    cover_pages = (metadata.get('document_pages') or [])[:2]
    cover = '\n'.join(p.get('ocr_text') or p.get('text') or '' for p in cover_pages)
    header = str(getattr(source, 'title', '') or '') + '\n' + cover + '\n' + text[:4000]
    if not period:
        cover_period = re.search(r'(?:19|20)\d{2}\s*年?\s*(?:年度报告|年度報告|年报|年報|annual\s*report)', header, re.I)
        period = cover_period[0] if cover_period else ''
    document_kind = ('annual_report' if re.search(r'年度報告|年度报告|annual\s*report', header, re.I) else
                     'prospectus' if re.search(r'招股说明书|招股意向书|招股章程|招股說明書|招股意向書', header) else
                     'research_report' if re.search(r'证券研究报告|證券研究報告', header) else '')
    document_source = bool(markers or metadata.get('document_pages') or
                           getattr(source, 'source_type', '') == 'filing' or
                           str(getattr(source, 'url', '')).lower().endswith('.pdf'))
    if not document_source:
        period = ''
    needle = re.sub(r'\s+', '', quote)
    offset = flat.find(needle) if needle else -1
    pages = []
    if offset >= 0 and markers:
        preceding = [p for start,p in markers if start <= offset]
        if preceding:
            pages.append(preceding[-1])
        pages.extend(p for start,p in markers if offset < start < offset+len(needle))
    # Appended OCR blocks can follow the last native-text page in the body.
    # Prefer the original per-page material so they do not inherit that last
    # native page's number merely because of their append position.
    page_matches = []
    if needle:
        for page in metadata.get('document_pages') or []:
            if isinstance(page.get('page'), int) and any(needle in re.sub(r'\s+','',str(page.get(field) or ''))
                    for field in ['ocr_text','text'] if page.get(field)):
                page_matches.append(page['page'])
    if page_matches:
        pages = page_matches
    return {'source_physical_pages': sorted(set(pages)), 'source_reporting_period_literal': period,
            'source_document_issuer': document_issuer(source), 'source_document_kind': document_kind}
