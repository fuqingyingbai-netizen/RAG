"""Recover omitted literal person statements from every retained original.

This is a source scan, not a new retrieval or truth check. Existing cards do
not determine whether a source is visited. Discovery snippets, failed fetches,
identity quarantine and index headlines remain outside the research pool.
"""
import re

from person_text import folded
from person_identity import discovery_index


def retained_source_statements(sources, intake, existing=(), audit=None):
    names = [intake.get('target_name'), *((intake.get('person_anchor') or {}).get('aliases') or [])]
    names = [str(n) for n in names if n and len(folded(n)) >= 2]
    has_name = lambda text: any(folded(n) in folded(text) for n in names)
    known = {}
    for fact in existing:
        known.setdefault(fact.get('source_url'), []).append(folded(fact.get('fact') or ''))
    rows = []
    for source in sources:
        meta, body = source.source_metadata or {}, source.content or ''
        record = {'source_url': source.url, 'source_title': source.title,
                  'retained_chars_scanned': len(body), 'candidate_statements': 0,
                  'added_statements': 0, 'covered_by_existing_statements': 0,
                  'rejected_spans': [], 'status': 'scanned'}
        reason = ''
        if source.url.startswith('structured://'):
            reason = 'structured_records_processed_by_typed_adapter'
        elif meta.get('identity_confidence') not in {'high', 'medium'} or meta.get('identity_status') == 'quarantined':
            reason = 'identity_not_admitted'
        elif meta.get('person_discovery_only') or meta.get('content_kind') in {'summary_only', 'low_content', 'empty_content'}:
            reason = 'discovery_or_low_content_not_original_evidence'
        elif meta.get('fetch_status') in {'failed', 'blocked', 'empty', 'skipped', 'challenge'} or not body:
            reason = 'original_unavailable'
        elif discovery_index(source.title, body):
            reason = 'discovery_index_not_original_article'
        if reason:
            record.update(status='not_admitted', reason=reason, retained_chars_scanned=0)
            if audit is not None:
                audit.append(record)
            continue
        seen = set()
        paragraphs = list(re.finditer(r'\S[\s\S]*?(?=\n\s*\n|\Z)', body))
        profile_spans = []
        field = re.compile(r'^(?:职务|職務|职位|職位|单位|單位|出生年月|出生日期|国籍|國籍|籍贯|籍貫|毕业院校|畢業院校|学历|學歷|教育经历|個人財富|个人财富)\s*[:：]')
        for index, paragraph in enumerate(paragraphs):
            if folded(paragraph[0]) not in {folded(n) for n in names}:
                continue
            end = paragraph.end()
            for following in paragraphs[index+1:]:
                if not field.match(following[0].strip()):
                    break
                end = following.end()
            if end > paragraph.end():
                profile_spans.append(body[paragraph.start():end].strip())
        candidates = [(text, True) for text in profile_spans]
        for paragraph in paragraphs:
            text = paragraph[0].strip()
            # Keep complete paragraphs, including adjacent response sentences.
            # Oversized PDF blocks are split on sentence boundaries, never
            # truncated to the first N characters or N person mentions.
            pieces = [text] if len(text) <= 1800 else [m[0].strip() for m in re.finditer(r'[^。！？!?]+[。！？!?]?|[。！？!?]', text)]
            candidates.extend((text, False) for text in pieces)
        for quote, profile in candidates:
                if not has_name(quote) or len(folded(quote)) < 24:
                    continue
                canonical = folded(quote)
                if canonical in seen:
                    continue
                seen.add(canonical)
                # Titles, related links, menus and dated news feeds are leads,
                # even if the surrounding fetched page is otherwise useful.
                if ((not profile and not re.search(r'[。！？!?]|[.!?]\s+[A-Z]', quote))
                        or re.search(r'^(?:相关文章|相关阅读|推荐阅读|本文关键词|本文标题|本文链接|题图|（题图)', quote)
                        or (not profile and re.search(r'加入收藏|最新新闻|最新新聞|更多新闻|详细资料>>|全部新闻|全部新聞', quote))
                        or (not profile and re.search(r'\((?:19|20)\d{2}-\d{2}-\d{2}[^)]*\)\s*$', quote) and '。' not in quote)
                        or re.search(r'\.{3}|…{2}', quote)
                        or re.search(r'比如另一公司的|同名(?:的)?(?:人士|企业家|高管)|并非本文(?:研究)?对象', quote)
                        or re.search(r'(?:有人|网友|网民).{0,12}(?:形容|认为|评价).{0,20}(?:性格|人格|品行)', quote)
                        or len(quote) > 1800):
                    record['rejected_spans'].append({'quote': quote, 'reason': 'heading_navigation_or_oversized_unsplit_span'})
                    continue
                record['candidate_statements'] += 1
                if any(canonical in previous for previous in known.get(source.url, []) if previous):
                    record['covered_by_existing_statements'] += 1
                    continue
                row = {'fact': quote, 'evidence_quote': quote, 'source_url': source.url,
                       'source_title': source.title, 'claim_type': 'source_statement',
                       'identity_match': 'confirmed', 'identity_confidence': meta['identity_confidence'],
                       'source_grade': meta.get('source_grade') or 'C',
                       'provider': meta.get('provider'), 'platform': meta.get('platform'),
                       'retrieved_at': meta.get('retrieved_at', ''),
                       'extraction_method': 'retained_original_full_scan'}
                if profile:
                    row['literal_profile_fields'] = True
                # Discovery purpose must not discard a useful original. Keep
                # these newly recovered statements as attributed context until
                # the opinion/event/actor-specific extraction validates them.
                if meta.get('person_feedback_only'):
                    row.update(opinion_only=True, eligible_for_risk_scoring=False,
                               retained_attributed_context=True)
                rows.append(row)
                known.setdefault(source.url, []).append(canonical)
                record['added_statements'] += 1
        if not record['candidate_statements']:
            record['reason'] = 'no_complete_target_anchored_statement'
        if audit is not None:
            audit.append(record)
    return rows
