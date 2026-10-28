"""Auditable person/document/observation links, separate from truth or risk scores.

Design references (no upstream implementation copied): FollowTheMoney's typed
Employment/Interest/Document schemas and Dossier's separate collection/review
states. Source snapshots and explicit event fields are the only time inputs.
"""
import hashlib
import json


VERSION = 'person-provenance-v1'


def stable_id(kind, value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return kind + '-' + hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]


def source_nature(fact, meta):
    if fact.get('opinion_only') or fact.get('feedback_record'):
        return 'attributed_statement_not_verified_event'
    if meta.get('content_origin') == 'search_snippet' or meta.get('person_discovery_only'):
        return 'discovery_lead'
    if fact.get('platform_count_only') or fact.get('claim_type') == 'platform_count':
        return 'platform_count_not_event'
    if fact.get('claim_type') in {'person_platform_record', 'person_company_record'}:
        return 'professional_structured_record'
    return 'source_statement_requires_review'


def build_provenance_index(target, intake, sources, facts, rejected, chapters):
    """Keep all retained sources and rejected statements visible to reviewers.

    Stable IDs are scoped by the identity clues, never by a person's name alone.
    A document's publication/retrieval dates never fill an unknown event period.
    Existing citation IDs stay intact; new IDs describe lineage only.
    """
    anchor = intake.get('person_anchor') or {}
    candidate = {'name': target,
                 'affiliations': sorted(anchor.get('known_affiliations') or []),
                 'other_clues': sorted(anchor.get('identity_anchors') or [])}
    candidate_id = stable_id('PERSON-CANDIDATE', candidate)
    documents, by_url = [], {}
    for source in sources:
        url = str(getattr(source, 'url', '') or '')
        original = str(getattr(source, 'content', '') or '')
        meta = getattr(source, 'source_metadata', None) or {}
        document = {'document_id': stable_id('DOC', {'url': url, 'content': original}),
                    'source_record_id': getattr(source, 'id', None), 'url': url,
                    'title': getattr(source, 'title', '') or '',
                    'content_sha256': hashlib.sha256(original.encode('utf-8')).hexdigest(),
                    'content_chars': len(original),
                    'identity_status': meta.get('identity_status', 'not_independently_resolved'),
                    'identity_reason': meta.get('identity_reason', ''),
                    'requirement_ids': meta.get('requirement_ids') or [],
                    'observations': [], 'rejected_statements': []}
        documents.append(document)
        by_url.setdefault(url, []).append((document, original, meta))
    observations, quarantine = [], []
    for admitted, rows in [(True, facts), (False, rejected)]:
        for fact in rows:
            text, url = str(fact.get('fact') or ''), str(fact.get('source_url') or '')
            obs = fact.get('observation') or {}
            evidence_id = fact.get('evidence_id')
            identifier = stable_id('OBS' if admitted else 'PENDING',
                {'candidate': candidate_id, 'source_url': url, 'statement': text,
                 'subject': fact.get('subject'), 'scope': fact.get('subject_scope')})
            locators = []
            for document, original, meta in by_url.get(url, []):
                start = original.find(text) if text else -1
                locator = {'document_id': document['document_id'],
                           'excerpt_id': stable_id('EXCERPT', [document['document_id'], text]),
                           'match': 'exact' if start >= 0 else 'not_exact_requires_review',
                           'start_char': start if start >= 0 else None,
                           'end_char': start + len(text) if start >= 0 else None,
                           'source_physical_pages': fact.get('source_physical_pages') or [],
                           'evidence_nature': source_nature(fact, meta)}
                locators.append(locator)
                document['observations' if admitted else 'rejected_statements'].append(identifier)
            routed = []
            if admitted:
                for number, package in chapters.items():
                    ids = {f['evidence_id'] for f in package.get('research_facts', package.get('facts', []))}
                    if evidence_id in ids:
                        routed.append(int(number))
            row = {'observation_id': identifier, 'candidate_id': candidate_id,
                   'evidence_id': evidence_id, 'statement': text, 'source_url': url,
                   'subject': fact.get('subject') or obs.get('subject') or '',
                   'subject_scope': fact.get('subject_scope') or obs.get('subject_scope') or 'unresolved',
                   'event_period': obs.get('period') or '',
                   'event_period_basis': obs.get('period_basis') or 'unknown',
                   'role_date_fields': obs.get('role_date_fields') or [],
                   'source_events': obs.get('source_events') or [],
                   'document_published_at': fact.get('published_at') or '',
                   'collected_at': fact.get('retrieved_at') or '',
                   'chapter_candidates': routed, 'locators': locators,
                   'identity_confidence_claim': fact.get('identity_confidence') or 'unspecified',
                   'review_status': 'pending_independent_review' if admitted else 'quarantined',
                   'rejection_reason': fact.get('rejection_reason') or '',
                   'risk_conclusion': None}
            (observations if admitted else quarantine).append(row)
    return {'version': VERSION, 'candidate': {'candidate_id': candidate_id, **candidate,
                'status': 'user_clues_not_verified_identity'},
            'documents': documents, 'observations': observations, 'quarantine': quarantine,
            'boundary': 'Lineage and chapter candidates are not adoption, independent verification, or personal liability.'}
