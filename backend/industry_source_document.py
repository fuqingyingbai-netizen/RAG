"""Deterministic source structure and bounded, hash-bound qualification context.

Offsets always address the unchanged archived text. Context may restrict a
claim; it does not authorize extra measurements, actors or legal obligations.
"""
import hashlib
import re

VERSION = 'industry-source-document-v1-context-lineage'


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _heading(line):
    match = re.fullmatch(r'\s*(#{1,6})\s+(.+?)\s*#*\s*', line)
    if match:
        return len(match[1]), match[2]
    match = re.fullmatch(r'\s*(第[一二三四五六七八九十百\d]+[章节][^。！？]{1,65})\s*', line)
    return (2, match[1]) if match else None


def build_document(body):
    """Index original blocks, including heading ancestry and Markdown tables."""
    if not isinstance(body, str):
        raise TypeError('source_body_must_be_text')
    identity = digest(body)
    blocks, stack, pending = [], [], None

    def flush():
        nonlocal pending
        if pending:
            start, end, kind, headings = pending
            text = body[start:end]
            headers = []
            if kind == 'table':
                lines = text.splitlines()
                if len(lines) > 1 and re.fullmatch(r'[\s|:\-]+', lines[1]):
                    headers = [cell.strip() for cell in lines[0].strip().strip('|').split('|')]
            blocks.append({'block_id': identity[:16] + ':' + str(start),
                'start': start, 'end': end, 'kind': kind, 'heading_path': headings,
                'table_headers': headers, 'text_sha256': digest(text)})
            pending = None

    for match in re.finditer(r'[^\r\n]+(?:\r?\n|$)|\r?\n', body):
        line = match[0].rstrip('\r\n')
        if not line.strip():
            flush()
            continue
        heading = _heading(line)
        if heading:
            flush()
            level, title = heading
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            pending = (match.start(), match.end(), 'heading', [s[1] for s in stack])
            flush()
            continue
        if re.fullmatch(r'\s*---\s*PDF page\s+\d+\s*---\s*', line, re.I):
            flush()
            continue
        kind = 'table' if '|' in line and line.count('|') >= 2 else 'paragraph'
        headings = [s[1] for s in stack]
        # Keep physical lines intact for tables. Paragraph soft wraps remain
        # one block, without rewriting the characters addressed by locators.
        if pending and pending[2] == kind and pending[3] == headings:
            pending = (pending[0], match.end(), kind, headings)
        else:
            flush()
            pending = (match.start(), match.end(), kind, headings)
    flush()
    return {'version': VERSION, 'document_id': identity, 'body_sha256': identity,
            'characters': len(body), 'blocks': blocks}


def verified_context(fact, body, document=None, limit=1600):
    locator = (fact.get('provenance') or {}).get('locator') or {}
    start, end = locator.get('start'), locator.get('end')
    if (not isinstance(body, str) or locator.get('status') != 'verified'
            or type(start) is not int or type(end) is not int or not 0 <= start < end <= len(body)):
        return {'version': VERSION, 'status': 'unresolved'}
    identity = digest(body)
    expected = locator.get('body_sha256')
    if expected != identity:
        return {'version': VERSION, 'status': 'body_mismatch'}
    quote = str(locator.get('quote') or fact.get('evidence_quote') or '')
    normalize = lambda value: re.sub(r'\s+', '', value).casefold()
    if not quote or normalize(body[start:end]) != normalize(quote):
        return {'version': VERSION, 'status': 'quote_mismatch'}
    document = document or build_document(body)
    if document.get('body_sha256') != identity:
        return {'version': VERSION, 'status': 'index_mismatch'}
    blocks = document['blocks']
    touched = [i for i, b in enumerate(blocks) if b['start'] < end and start < b['end']]
    if not touched:
        return {'version': VERSION, 'status': 'unresolved'}
    current = blocks[touched[0]]
    # A long paragraph must not drop its located sentence or cut a qualifier.
    # Expose only complete neighboring lines; oversized blocks are referenced
    # in metadata and can be reopened through the document workspace.
    candidates = list(dict.fromkeys(touched + [touched[0]-1, touched[-1]+1]))
    spans, used = [], 0
    for i in candidates:
        if not 0 <= i < len(blocks):
            continue
        block = blocks[i]
        if block['kind'] == 'heading' or block['heading_path'] != current['heading_path']:
            continue
        if block['end'] - block['start'] + used > limit:
            if i not in touched:
                continue
            sentences = [(block['start']+m.start(), block['start']+m.end())
                for m in re.finditer(r'.+?(?:[。！？\n]|[.!?](?=\s|$)|$)',body[block['start']:block['end']],re.S)]
            anchors = [j for j,(a,b) in enumerate(sentences) if a < end and start < b]
            selected = list(dict.fromkeys(anchors + [j+d for j in anchors for d in (-1,1)]))
            for j in selected:
                if not 0 <= j < len(sentences):
                    continue
                a,b=sentences[j]
                if used+b-a <= limit:
                    spans.append({'start':a,'end':b,'text':body[a:b]})
                    used += b-a
            continue
        spans.append({'start': block['start'], 'end': block['end'],
                      'text': body[block['start']:block['end']]})
        used += block['end'] - block['start']
    spans.sort(key=lambda row: row['start'])
    text = '\n'.join([*current['heading_path'], *(s['text'] for s in spans)])
    # Recognize explicit experiments and simulated-user roles, not any text
    # merely mentioning testing or a source's generic list of examples.
    sample = bool(re.search(r'τ[²2]?[- ]?bench|tau[²2]?[- ]?bench|模拟用户|simulated\s+users?|Dual[- ]Control|双控机制|本实验|本案例', text, re.I))
    boundary = '特定评测或案例样本；仅适用于所引场景，不能外推通用智能体架构或行业整体' if sample else ''
    record = {'version': VERSION, 'status': 'verified', 'document_id': identity,
        'quote_start': start, 'quote_end': end, 'quote_sha256': digest(body[start:end]),
        'block_ids': [blocks[i]['block_id'] for i in touched],
        'heading_path': current['heading_path'], 'table_headers': current['table_headers'],
        'spans': spans, 'scenario_boundary': boundary,
        'use': 'qualification_only_not_additional_fact_or_metric_authorization'}
    return record


def context_view(fact):
    """Return context only for the exact same archived quote identity."""
    context = fact.get('source_document_context') or {}
    locator = (fact.get('provenance') or {}).get('locator') or {}
    if context.get('version') != VERSION or context.get('status') != 'verified':
        return None
    if (locator.get('status') != 'verified' or not locator.get('body_sha256')
            or type(locator.get('start')) is not int or type(locator.get('end')) is not int
            or context.get('quote_start') != locator.get('start') or context.get('quote_end') != locator.get('end')
            or context.get('document_id') != locator['body_sha256']):
        return None
    quote_digest = digest(locator['quote']) if locator.get('quote') else locator.get('quote_sha256')
    if not quote_digest or quote_digest != context.get('quote_sha256'):
        return None
    return {k: context[k] for k in ('version','document_id','quote_sha256','heading_path',
        'table_headers','spans','scenario_boundary','use')}
