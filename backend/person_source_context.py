"""Literal document context; source periods never become personal event dates."""
import re
from functools import lru_cache


@lru_cache(maxsize=48)
def _document(text, title):
    flat = re.sub(r'\s+', '', text)
    markers = [(m.start(), int(m[1])) for m in re.finditer(r'---PDFpage(\d+)---', flat)]
    header = title + '\n' + text[:4000]
    period = re.search(r'(?:19|20)\d{2}\s*年?\s*(?:年度报告|年度報告|年报|年報)', header)
    return flat, markers, period[0] if period else ''


def literal_document_context(source, quote):
    text = str(getattr(source, 'content', '') or '')
    flat, markers, period = _document(text, str(getattr(source, 'title', '') or ''))
    metadata = getattr(source, 'source_metadata', None) or {}
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
    return {'source_physical_pages': sorted(set(pages)), 'source_reporting_period_literal': period}
