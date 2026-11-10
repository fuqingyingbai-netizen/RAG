"""Bounded evidence assembly, independent of model/provider and agent loops."""
import hashlib
import math
import re

VERSION = 'evidence-v3'
BROAD = re.compile(r'比较|对比|汇总|各(?:个|项目|公司)|分别|共同|差异|所有|全部|清单|表格|哪些|compare|across|summari', re.I)


def evidence_id(doc_id, text):
    return hashlib.sha256((str(doc_id) + '\0' + text).encode()).hexdigest()[:24]


def candidates(nodes, allowed, index_id):
    ranked, seen = [], set()
    def score(node):
        try:
            value = float(node.get('score') or 0)
            return value if math.isfinite(value) else 0
        except (TypeError, ValueError):
            return 0
    for node in sorted(nodes, key=score, reverse=True):
        meta = node.get('metadata') or {}
        doc_id = meta.get('doc_id')
        if doc_id not in allowed or (meta.get('pipeline_id') and meta['pipeline_id'] != index_id):
            continue
        text = str(meta.get('content') or node.get('text') or '').strip()
        key = evidence_id(doc_id, text)
        if text and key not in seen:
            ranked.append((doc_id, {**meta, '_evidence_id': key}, text))
            seen.add(key)
    return ranked


def excerpt(text, query, limit):
    """Keep a contiguous, attributable window near query matches, not always the prefix."""
    if len(text) <= limit:
        return text, 0
    terms = re.findall(r'[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}', query)
    # Chinese questions lack spaces: add overlapping bigrams for locating passages.
    terms += [t[i:i+2] for t in terms if len(t) > 3 for i in range(len(t)-1)]
    terms = sorted(set(terms), key=lambda term: (-len(term),term))[:100]
    hits = []
    for term in terms:
        for n,match in enumerate(re.finditer(re.escape(term), text, re.I)):
            if n >= 1000: break
            hits.append(match.start())
    if not hits:
        start = 0
    else:
        hits.sort()
        left = best_left = 0
        best_count = 0
        for right, position in enumerate(hits):
            while position - hits[left] >= limit - min(500, limit // 4):
                left += 1
            if right-left+1 > best_count:
                best_count, best_left = right-left+1, hits[left]
        start = max(0, min(len(text)-limit, best_left-min(500, limit//4)))
    return text[start:start+limit], start


def select_evidence(nodes, allowed, index_id, query='', *, legacy=False):
    ranked = candidates(nodes, allowed, index_id)
    broad = bool(BROAD.search(query))
    max_items, char_budget = (12, 120000) if legacy else ((48, 80000) if broad else (24, 48000))
    selected, used, counts, characters = [], set(), {}, 0
    def add(position):
        nonlocal characters
        doc_id, meta, raw = ranked[position]
        remaining = char_budget-characters
        if remaining < 200 or len(selected) >= max_items:
            return
        # Reserve space for diverse documents before adding more from one source.
        cap = 10000 if legacy else min(10000, max(1500, char_budget // max(1, min(max_items, len({r[0] for r in ranked})))) )
        cap = min(cap, remaining)
        text, offset = (raw[:cap], 0) if legacy else excerpt(raw, query, cap)
        selected.append((doc_id, {**meta, '_excerpt_start': offset, '_excerpt_end': offset+len(text),
            '_source_chars': len(raw), '_excerpted': len(text) != len(raw)}, text))
        used.add(position)
        counts[doc_id] = counts.get(doc_id, 0)+1
        characters += len(text)
    for position, (doc_id, _, _) in enumerate(ranked):
        if doc_id not in counts:
            add(position)
    quota = (12 if len(counts) == 1 else 4) if legacy else (4 if not broad and len(counts) > 1 else max_items)
    for position, (doc_id, _, _) in enumerate(ranked):
        if position not in used and counts.get(doc_id, 0) < quota:
            add(position)
    trace = {'version': 'legacy-v1' if legacy else VERSION, 'query': query, 'allowed_documents': len(allowed),
        'candidate_count': len(ranked), 'selected_count': len(selected), 'context_chars': characters,
        'candidate_ids': [r[1]['_evidence_id'] for r in ranked], 'selected_ids': [r[1]['_evidence_id'] for r in selected],
        'candidate_documents': len({r[0] for r in ranked}), 'selected_documents': len(counts),
        'excerpted_count': sum(r[1]['_excerpted'] for r in selected),
        'selection_limited': len(selected) < len(ranked) or any(r[1]['_excerpted'] for r in selected),
        'exhaustive': False}
    return selected, trace
