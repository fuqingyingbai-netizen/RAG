"""Bounded, local-only candidate selection. Original bodies are never edited.

The temporary matrix is isolated from the approved-fact index and shared BM25
statistics. Selection is by chapter questions, not a semantic truth classifier.
"""
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import hashlib
import math
import os
import re
import threading
import time

VERSION = 'industry-cleaning-retrieval-v1-local-hybrid'
_CACHE = OrderedDict()
_LOCK = threading.Lock()
_WORKER = None
_BUSY = threading.Lock()

MODULE_CHAPTERS = {'行业定义与边界': [2], '细分赛道与产业链': [2], '政策与监管': [3],
    '市场规模与增长': [4], '行业热度与重大事件': [5], '竞争格局与代表企业': [6],
    '技术路线对比': [7], '技术演进与平台生态': [7], '商业模式与盈利逻辑': [10],
    '前景展望': [11], '行业风险': [13], '行业风险与不确定性': [13]}


def tokens(text):
    words = re.findall(r'[a-z][a-z0-9_-]*|\d+(?:\.\d+)?|[\u4e00-\u9fff]+', text.casefold())
    out = []
    for word in words:
        if re.fullmatch(r'[\u4e00-\u9fff]+', word):
            out.extend(word[i:i+2] for i in range(max(1, len(word)-1)))
        else: out.append(word)
    return out


def original_spans(body):
    """Keep qualification-bearing paragraphs whole, including their offsets."""
    spans = []
    for paragraph in re.finditer(r'[^\r\n]+', body):
        if len(paragraph[0].strip()) < 12: continue
        if len(paragraph[0]) <= 850:
            spans.append((paragraph.start(), paragraph.end())); continue
        start = paragraph.start()
        for sentence in re.finditer(r'[^。！？]+(?:[。！？][”」"]?|$)', paragraph[0]):
            end = paragraph.start()+sentence.end()
            if end-start > 850:
                # An overlong sentence cannot safely be cut to fit a model.
                if paragraph.start()+sentence.start() > start:
                    spans.append((start, paragraph.start()+sentence.start()))
                start = paragraph.start()+sentence.start()
            if end-start <= 850:
                spans.append((start, end)); start = end
            else:
                start = end
    return [s for s in spans if 12 <= s[1]-s[0] <= 850]


def local_vectors(texts):
    from embedding import embedding_service
    return embedding_service.get_local_embeddings(texts)


def cached_vectors(texts, embed, namespace):
    keys = [(namespace, hashlib.sha256(t.encode()).hexdigest()) for t in texts]
    with _LOCK:
        missing = list(dict.fromkeys((key, text) for key, text in zip(keys, texts) if key not in _CACHE))
    if missing:
        values = embed([text for _, text in missing])
        if len(values) != len(missing): raise ValueError('embedding_count_mismatch')
        for vector in values:
            if not vector or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in vector):
                raise ValueError('invalid_embedding')
        if len({len(v) for v in values}) != 1: raise ValueError('embedding_dimension_mismatch')
        with _LOCK:
            for (key, _), value in zip(missing, values): _CACHE[key] = value
            while len(_CACHE) > 2048: _CACHE.popitem(last=False)
    with _LOCK:
        return [_CACHE[key] for key in keys], len(keys)-len(missing)


def bounded_vectors(texts, embed, namespace, timeout):
    """At most one embedding job in flight; timeouts do not queue more work."""
    global _WORKER
    if not _BUSY.acquire(blocking=False): raise RuntimeError('embedding_busy')
    try:
        if _WORKER is None: _WORKER = ThreadPoolExecutor(max_workers=1, thread_name_prefix='industry-local-embedding')
    except Exception:
        _BUSY.release(); raise
    def work():
        try: return cached_vectors(texts, embed, namespace)
        finally: _BUSY.release()
    try:
        future = _WORKER.submit(work)
    except Exception:
        _BUSY.release(); raise
    return future.result(timeout=max(0.01, timeout))


class CleaningRetriever:
    def __init__(self, embed=None, *, dense=True, budget_seconds=30, source_seconds=8, namespace=None):
        self.embed = embed or local_vectors
        self.dense = dense
        self.deadline = time.monotonic()+budget_seconds
        self.source_seconds = source_seconds
        self.namespace = namespace or os.getenv('EMBEDDING_MODEL', 'BAAI/bge-m3')
        # Test/injected backends must explicitly choose their cache namespace.
        if embed and namespace is None: self.namespace = ('injected', embed)
        self.circuit = False
        self.audit = []
        self.initialization = {'attempted': False}

    def warmup(self):
        """First local model load shares the run budget, not every source budget."""
        if self.initialization['attempted'] or not self.dense or self.circuit: return
        started = time.monotonic()
        self.initialization = {'attempted': True, 'status': 'pending'}
        if started >= self.deadline:
            self.circuit = True
            self.initialization.update(status='fallback', error_type='run_budget_exhausted', duration_ms=0)
            return
        try:
            bounded_vectors(['行业研究问题'], self.embed, self.namespace, self.deadline-started)
            self.initialization['status'] = 'ready'
        except Exception as exc:
            self.circuit = True
            self.initialization.update(status='fallback', error_type='timeout' if isinstance(exc, TimeoutError) else type(exc).__name__)
        self.initialization['duration_ms'] = int((time.monotonic()-started)*1000)

    def select(self, source, limit):
        from industry_evidence import stored_body
        from industry_fact_contracts import CHAPTER_QUESTIONS
        body = stored_body(source)
        meta = source.source_metadata or {}
        module = str(meta.get('module') or '')
        chapters = MODULE_CHAPTERS.get(module, [2, 3, 4, 6, 7, 10, 11, 13])
        questions = [q for c in chapters for q, _ in CHAPTER_QUESTIONS.get(c, [])]
        queries = [str(meta.get('industry_name') or '')+' '+q for q in questions]
        spans = original_spans(body)
        record = {'source_id': getattr(source, 'id', None), 'body_sha256': hashlib.sha256(body.encode()).hexdigest(),
                  'candidate_count': len(spans), 'selected': [], 'dense_applied': False,
                  'role': 'extraction_candidates_not_verified_facts'}
        if len(body) <= limit:
            record.update(mode='whole_body', selected=[{'start': 0, 'end': len(body)}] if body else [])
            self.audit.append(record); return body
        counts = [Counter(tokens(body[a:b])) for a, b in spans]
        avg = sum(sum(c.values()) for c in counts)/max(1, len(counts))
        df = Counter(t for c in counts for t in c)
        sparse = []
        for query in queries:
            terms = set(tokens(query))
            scores = []
            for c in counts:
                length = sum(c.values())
                scores.append(sum(math.log(1+(len(counts)-df[t]+0.5)/(df[t]+0.5))*c[t]*2.5/
                    (c[t]+1.5*(0.25+0.75*length/max(1, avg))) for t in terms if c[t]))
            sparse.append(scores)
        # Bound dense work, with a slot for every question and evenly distributed
        # original paragraphs. Disclosure makes this candidate cap auditable.
        candidates = []
        for scores in sparse:
            candidates.extend(sorted(range(len(spans)), key=lambda i: (-scores[i], i))[:2])
        if spans:
            candidates.extend(round(i*(len(spans)-1)/15) for i in range(16))
        candidates = list(dict.fromkeys(candidates))[:48]
        dense = None
        remaining = self.deadline-time.monotonic()
        if self.dense and not self.circuit and candidates and remaining > 0:
            try:
                vectors, hits = bounded_vectors(queries+[body[s:e] for s,e in (spans[i] for i in candidates)],
                    self.embed, self.namespace, min(self.source_seconds, remaining))
                if len({len(v) for v in vectors}) != 1: raise ValueError('embedding_dimension_mismatch')
                unit = lambda v: [x/max(1e-12, math.sqrt(sum(n*n for n in v))) for x in v]
                qv = [unit(v) for v in vectors[:len(queries)]]
                pv = [unit(v) for v in vectors[len(queries):]]
                dense = [[sum(a*b for a,b in zip(q,p)) for p in pv] for q in qv]
                record.update(dense_applied=True, cache_hits=hits)
            except Exception as exc:
                self.circuit = True
                record['dense_error'] = 'timeout' if isinstance(exc, TimeoutError) else type(exc).__name__
        elif self.dense:
            record['dense_error'] = 'circuit_open' if self.circuit else 'run_budget_exhausted'
        fused = []
        for qi, scores in enumerate(sparse):
            values = Counter()
            for rank, i in enumerate(sorted(range(len(spans)), key=lambda i: (-scores[i], i))):
                if scores[i] > 0: values[i] += 1/(60+rank+1)
            if dense is not None:
                for rank, i in enumerate(sorted(range(len(candidates)), key=lambda i: (-dense[qi][i], candidates[i]))):
                    if dense[qi][i] > 0: values[candidates[i]] += 1/(60+rank+1)
            fused.append(sorted(values, key=lambda i: (-values[i], i)))
        # Keep the opening paragraph for subject/sample/date context. Whole
        # paragraphs remain in source order, separated by an explicit gap marker.
        chosen = [0] if spans and spans[0][1]-spans[0][0] <= min(400, limit//3) else []
        marker = '\n[不连续原文片段]\n'
        used = sum(spans[i][1]-spans[i][0] for i in chosen)
        for depth in range(4):
            for qi, ranking in enumerate(fused):
                if depth >= len(ranking): continue
                i = ranking[depth]; start,end = spans[i]
                if i in chosen: continue
                cost = end-start+(len(marker) if chosen else 0)
                if used+cost <= limit:
                    chosen.append(i); used += cost
        if not chosen:
            from industry_research import industry_excerpt
            record.update(mode='legacy_fallback', fallback_reason='no_complete_passage_fits')
            self.audit.append(record); return industry_excerpt(body, module, limit)
        chosen.sort()
        record.update(mode='hybrid' if dense is not None else 'bm25', dense_candidate_count=len(candidates),
            dense_excluded_count=len(spans)-len(candidates),
            selected=[{'start': spans[i][0], 'end': spans[i][1],
                       'question_matches': [questions[q] for q, order in enumerate(fused) if i in order[:2]]} for i in chosen])
        self.audit.append(record)
        return marker.join(body[spans[i][0]:spans[i][1]] for i in chosen)

    def diagnostic(self):
        return {'version': VERSION, 'sources': self.audit, 'circuit_open': self.circuit,
                'initialization': self.initialization,
                'dense_sources': sum(r['dense_applied'] for r in self.audit),
                'original_sources_preserved': True, 'writes_approved_fact_index': False}
