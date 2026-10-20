"""Search recall, deterministic rank fusion and source-preserving URL grouping.

Search relevance, engine agreement and source credibility are different things.
No provider's native score or legacy constant is a cross-engine authority score.
"""
import copy
import hashlib
from collections import defaultdict, deque
from urllib.parse import unquote_plus, urlsplit, urlunsplit


TRACKING_KEYS = frozenset({'spm', 'gclid', 'fbclid', 'msclkid', 'mc_cid', 'mc_eid', '_ga', '_gl'})


def canonical_source_url(value):
    """Drop known trackers, preserve document IDs, signatures and SPA routes.

    This is an identity key only. Fetches and citations keep an original URL.
    Do not guess that www/no-www, http/https or trailing slashes are equivalent.
    """
    raw = str(value or '').strip()
    try:
        parts = urlsplit(raw)
        if parts.scheme.lower() not in {'http', 'https'} or not parts.hostname:
            return raw
        host = parts.hostname.lower()
        host = '[' + host + ']' if ':' in host else host
        if parts.port and parts.port != (443 if parts.scheme.lower() == 'https' else 80):
            host += ':' + str(parts.port)
        # Preserve userinfo and raw nontracking parameter order/encoding.
        # In particular source/from/fr can be business selectors, not trackers.
        if parts.username is not None:
            host = parts.netloc.rsplit('@', 1)[0] + '@' + host
        query = []
        for component in parts.query.split('&'):
            key = unquote_plus(component.split('=', 1)[0]).lower()
            if component and not key.startswith('utm_') and key not in TRACKING_KEYS:
                query.append(component)
        fragment = parts.fragment if parts.fragment.startswith(('/', '!')) else ''
        return urlunsplit((parts.scheme.lower(), host, parts.path or '/', '&'.join(query), fragment))
    except ValueError:
        return raw


class SearchResults(list):
    """A list-compatible result with per-request audit (safe across threads)."""
    def __init__(self, rows=(), *, audit=None):
        super().__init__(rows)
        self.audit = audit or {}


def interleave_research_candidates(batches):
    """Spend a fixed admission budget across questions, not one query's tail.

    Modules get turns; inside a module, queries get turns at each rank depth.
    Every candidate survives and each query keeps its own fused rank order.
    """
    modules = defaultdict(list)
    for query, rows in batches:
        modules[str(query.get('module') or 'general')].append((query, rows))
    queues = []
    for queries in modules.values():
        queue = deque()
        for rank in range(max((len(rows) for _, rows in queries), default=0)):
            for query, rows in queries:
                if rank < len(rows):queue.append((query, [rows[rank]]))
        if queue:queues.append(queue)
    while queues:
        active=[]
        for queue in queues:
            yield queue.popleft()
            if queue:active.append(queue)
        queues=active


def _content_quality(row):
    meta = row.get('metadata') or {}
    body = str(row.get('content') or '').strip()
    summary = str(row.get('summary') or '').strip()
    usable = meta.get('fetch_status') not in {
        'blocked_or_challenge', 'blocked', 'error', 'failed', 'empty', 'timeout'}
    if any(word in body[:200].lower() for word in ('access denied', 'verify you are human', '正在进行安全检测')):
        usable = False
    original = usable and bool(body) and (
        meta.get('content_origin') in {'original_page', 'provider_raw_content', 'provider_text'}
        or bool(meta.get('document_pages')) or (meta.get('fetch_status') == 'done' and body != summary)
        or (body != summary and len(body) > len(summary)))
    return (int(original), int(usable), len(body), len(summary),
            len(meta.get('document_pages') or []),
            hashlib.sha256(body.encode()).hexdigest(), str(meta.get('provider') or ''), str(row.get('url') or ''))


def fuse_search_results(batches, *, result_limit):
    """One RRF vote per provider/document; keep the best body with its metadata.

    Engine order and completion order cannot determine the retained body.
    RRF orders retrieval candidates, and does not assert source reliability.
    """
    grouped = defaultdict(list)
    raw_count = 0
    empty_url_count = 0
    engine_counts = {}
    for provider, rows in sorted(batches.items()):
        engine_counts[provider] = len(rows)
        raw_count += len(rows)
        for rank, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                empty_url_count += 1
                continue
            key = canonical_source_url(row.get('url'))
            if key:
                grouped[key].append((provider, rank, row))
            else:
                empty_url_count += 1
    merged = []
    for key, matches in grouped.items():
        winner = max(matches, key=lambda value: (_content_quality(value[2]), value[0], -value[1]))
        row = copy.deepcopy(winner[2])
        metadata = row.setdefault('metadata', {})
        if not isinstance(metadata, dict):
            metadata = row['metadata'] = {}
        metadata['provider'] = winner[0]
        ranks = {}
        for provider, rank, _ in matches:
            ranks[provider] = min(rank, ranks.get(provider, rank))
        score = sum(1.0 / (60 + rank) for provider, rank in sorted(ranks.items()))
        provenance = [
            {'provider': provider, 'rank': rank, 'url': str(original.get('url') or ''),
             'native_score': (original.get('metadata') or {}).get('score'),
             'legacy_credibility_score': original.get('credibility_score')}
            for provider, rank, original in sorted(matches, key=lambda value: (value[0], value[1], str(value[2].get('url') or '')))]
        metadata.update(canonical_url=key, search_providers=sorted(ranks),
                        search_matches=provenance, search_rank_by_provider=ranks,
                        original_urls=sorted({str(r.get('url') or '') for _, _, r in matches}),
                        search_score_kind='reciprocal_rank_fusion', search_fusion_score=score)
        # Legacy provider constants remain auditable in search_matches, but
        # must not become a credibility floor in downstream source scoring.
        row['credibility_score'] = 0
        merged.append(row)
    merged.sort(key=lambda row: (-(row['metadata']['search_fusion_score']), row['metadata']['canonical_url']))
    kept = merged[:max(0, result_limit)]
    return SearchResults(kept, audit={
        'method': 'canonical_url_rrf_v1', 'engine_counts': engine_counts,
        'raw_count': raw_count, 'unique_count': len(merged), 'kept_count': len(kept),
        'deduplicated_count': raw_count - empty_url_count - len(merged),
        'invalid_or_empty_url_count': empty_url_count,
        'trimmed_count': len(merged) - len(kept), 'result_limit': result_limit})
