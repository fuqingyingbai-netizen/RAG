"""Auditable person/document/observation links, separate from truth or risk scores.

Design references (no upstream implementation copied): FollowTheMoney's typed
Employment/Interest/Document schemas and Dossier's separate collection/review
states. Source snapshots and explicit event fields are the only time inputs.
"""
import hashlib
import json


VERSION = 'person-provenance-v2-typed-time-and-attribution'


def stable_id(kind, value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return kind + '-' + hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]


def source_nature(fact, meta):
    feedback = fact.get('feedback_record') or {}
    if fact.get('opinion_only') or feedback.get('kind') == 'attributed_opinion':
        return 'attributed_statement_not_verified_event'
    if meta.get('content_origin') == 'search_snippet' or meta.get('person_discovery_only'):
        return 'discovery_lead'
    if fact.get('platform_count_only') or fact.get('claim_type') == 'platform_count':
        return 'platform_count_not_event'
    if fact.get('claim_type') in {'person_platform_record', 'person_company_record'}:
        return 'professional_structured_record'
    return 'source_statement_requires_review'


def effective_time(observation):
    """Retain labelled bounds without treating a missing end as current."""
    fields = observation.get('role_date_fields') or []
    starts, ends, ranges = [], [], []
    for row in fields:
        label, literal = row.get('field', ''), row.get('source_value', '')
        if not literal:
            continue
        if any(t in label for t in ('起止', '任期', '日期范围')):
            ranges.append(literal)
        elif any(t in label for t in ('终止', '离任', '结束')):
            ends.append(literal)
        elif any(t in label for t in ('任职日期', '开始', '起始', '生效')):
            starts.append(literal)
    return {'start_literals': starts, 'end_literals': ends, 'range_literals': ranges,
            'snapshot_period': observation.get('period') or '',
            'snapshot_basis': observation.get('period_basis') or 'unknown',
            'current_status': 'not_inferred',
            'boundary': 'Literal source bounds; collection/publication dates and a missing end never establish current tenure.'}


def subject_reference(fact, target, candidate_id):
    scope = fact.get('subject_scope') or 'unresolved'
    name = fact.get('subject') or (fact.get('observation') or {}).get('subject') or ''
    if scope == 'person' and name == target:
        return candidate_id
    peer = fact.get('comparison_context') or {}
    return stable_id('ENTITY-CANDIDATE', {'scope': scope, 'name': name,
        'organization': peer.get('company') or '',
        'source_scope': '' if scope == 'comparison_person' and peer.get('company') else fact.get('source_url')})


def merge_supports(rows, key):
    """Merge byte-equivalent node identities while retaining every source link."""
    result = {}
    for row in rows:
        if row[key] not in result:
            result[row[key]] = row
            continue
        existing = result[row[key]]
        for field in ('evidence_ids', 'observation_ids'):
            if field in row:
                existing[field] = list(dict.fromkeys([*existing.get(field, []), *row[field]]))
    return list(result.values())


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
                    'requirement_ids': list(dict.fromkeys([*(meta.get('person_requirement_ids') or []),
                                                          *(meta.get('requirement_ids') or [])])),
                    'observations': [], 'rejected_statements': []}
        documents.append(document)
        by_url.setdefault(url, []).append((document, original, meta))
    observations, quarantine = [], []
    relationships, events, evaluations, curriculum, citations = [], [], [], [], []
    chapter_ids = {int(n): {f['evidence_id'] for f in p.get('research_facts', p.get('facts', []))}
                   for n, p in chapters.items()}
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
                for number, ids in chapter_ids.items():
                    if evidence_id in ids:
                        routed.append(int(number))
            subject_id = subject_reference(fact, target, candidate_id)
            time = effective_time(obs)
            row = {'observation_id': identifier, 'candidate_id': candidate_id,
                   'subject_id': subject_id,
                   'evidence_id': evidence_id, 'statement': text, 'source_url': url,
                   'subject': fact.get('subject') or obs.get('subject') or '',
                   'subject_scope': fact.get('subject_scope') or obs.get('subject_scope') or 'unresolved',
                   'event_period': obs.get('period') or '',
                   'event_period_basis': obs.get('period_basis') or 'unknown',
                   'role_date_fields': obs.get('role_date_fields') or [],
                   'effective_time': time,
                   'source_events': obs.get('source_events') or [],
                   'document_published_at': fact.get('published_at') or '',
                   'collected_at': fact.get('retrieved_at') or '',
                   'chapter_candidates': routed, 'locators': locators,
                   'identity_confidence_claim': fact.get('identity_confidence') or 'unspecified',
                   'review_status': 'pending_independent_review' if admitted else 'quarantined',
                   'rejection_reason': fact.get('rejection_reason') or '',
                   'risk_conclusion': None}
            (observations if admitted else quarantine).append(row)
            if not admitted:
                continue
            citations.append({'citation_id': evidence_id, 'observation_id': identifier,
                'document_ids': [r['document_id'] for r in locators],
                'excerpt_ids': [r['excerpt_id'] for r in locators],
                'status': 'source_bound_reference_not_truth_verdict'})
            issuer = obs.get('issuer') or ''
            from person_records import payload as literal_payload
            data = literal_payload(text)
            roles = {k: data[k] for k in ('角色', '曾担任角色', '职位', '职务') if data.get(k)}
            for relation in obs.get('relations') or []:
                if relation not in {'appointment', 'holding'} or not issuer:
                    continue
                # This is an explicitly labelled candidate edge. A company
                # mentioned in a source cannot silently become personal control.
                organization_id = stable_id('ORG-CANDIDATE', {'name': issuer, 'source_url': url})
                relationships.append({'relationship_id': stable_id('REL', [subject_id,
                    organization_id, relation, roles, time]), 'subject_id': subject_id,
                    'organization_id': organization_id, 'organization_literal': issuer,
                    'relation_kind': relation, 'role_literals': roles, 'effective_time': time,
                    'evidence_ids': [evidence_id], 'observation_ids': [identifier],
                    'identity_status': 'source_named_candidates_require_review',
                    'responsibility': 'not_determined', 'control': 'not_inferred'})
            for event in obs.get('source_events') or []:
                event_id = stable_id('EVENT', [subject_id, event.get('kind'),
                    event.get('date_literal'), event.get('source_quote')])
                event_row = {'event_id': event_id, 'subject_id': subject_id, **event,
                    'evidence_ids': [evidence_id], 'observation_ids': [identifier],
                    'nature': 'reported_source_event', 'responsibility': 'not_determined'}
                events.append(event_row)
                if event.get('kind') in {'education', 'appointment', 'founding'}:
                    curriculum.append({'entry_id': stable_id('CV', [subject_id, event_id]),
                        'subject_id': subject_id, 'event_id': event_id, 'event_kind': event['kind'],
                        'date_literal': event.get('date_literal') or '',
                        'evidence_ids': [evidence_id], 'state': 'source_statement_requires_review'})
            feedback = fact.get('feedback_record') or {}
            if feedback.get('kind') == 'attributed_opinion':
                evaluations.append({'evaluation_id': stable_id('VIEW', [subject_id, url,
                    feedback.get('evaluator'), feedback.get('statement_quote') or fact.get('fact')]),
                    'subject_id': subject_id, 'evaluator_literal': feedback.get('evaluator') or '',
                    'relationship_literal': feedback.get('relationship') or '',
                    'evaluator_context_quote': feedback.get('evaluator_context_quote') or '',
                    'statement_quote': feedback.get('statement_quote') or fact.get('fact'),
                    'period_literal': feedback.get('period') or '',
                    'source_published_at': feedback.get('source_published_at') or '',
                    'evidence_ids': [evidence_id], 'fact_or_opinion': 'attributed_opinion',
                    'truth_status': 'not_established', 'risk_severity': 'not_assessed'})
    return {'version': VERSION, 'candidate': {'candidate_id': candidate_id, **candidate,
                'status': 'user_clues_not_verified_identity'},
            'documents': documents, 'observations': observations, 'quarantine': quarantine,
            'relationships': merge_supports(relationships, 'relationship_id'),
            'events': merge_supports(events, 'event_id'),
            'curriculum_entries': merge_supports(curriculum, 'entry_id'),
            'evaluations': merge_supports(evaluations, 'evaluation_id'), 'citations': citations,
            'boundary': 'Lineage and chapter candidates are not adoption, independent verification, or personal liability.'}
