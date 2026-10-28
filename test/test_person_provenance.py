from types import SimpleNamespace

from person_provenance import build_provenance_index


def index(company='甲机构', collected='2026-10-28', status='accepted'):
    fact = {'fact': '陈明于2019年任职甲机构。', 'source_url': 'https://issuer.invalid/bio',
            'evidence_id': 'E-ONE', 'subject': '陈明', 'subject_scope': 'person',
            'published_at': '2025-01-01', 'retrieved_at': collected,
            'observation': {'period': '', 'role_date_fields': [
                {'field': '任职日期', 'source_value': '2019年'}]}}
    source = SimpleNamespace(id=7, url=fact['source_url'], title='履历', content=fact['fact'],
                             source_metadata={'identity_status': status})
    return build_provenance_index('陈明', {'person_anchor': {'known_affiliations': [company]}},
        [source], [fact], [{**fact, 'rejection_reason': 'identity_quarantine'}],
        {2: {'research_facts': [fact]}})


def test_identity_candidate_is_not_name_only_and_collection_date_is_not_event_date():
    first, other = index(), index('乙机构')
    assert first['candidate']['candidate_id'] != other['candidate']['candidate_id']
    obs = first['observations'][0]
    assert obs['event_period'] == '' and obs['event_period_basis'] == 'unknown'
    assert obs['document_published_at'] == '2025-01-01'
    assert obs['role_date_fields'][0]['source_value'] == '2019年'
    assert obs['risk_conclusion'] is None


def test_ids_and_exact_locators_survive_recollection_with_full_quarantine_lineage():
    first, later = index(), index(collected='2026-11-01')
    assert first['observations'][0]['observation_id'] == later['observations'][0]['observation_id']
    assert first['documents'][0]['document_id'] == later['documents'][0]['document_id']
    row = first['observations'][0]
    assert row['locators'][0]['match'] == 'exact'
    assert row['chapter_candidates'] == [2]
    assert first['quarantine'][0]['rejection_reason'] == 'identity_quarantine'
    assert first['documents'][0]['rejected_statements'] == [first['quarantine'][0]['observation_id']]


def test_untouched_sources_have_explicit_empty_destinations():
    source = SimpleNamespace(url='https://issuer.invalid/empty', content='', source_metadata={})
    audit = build_provenance_index('陈明', {}, [source], [], [], {})
    assert len(audit['documents']) == 1
    assert audit['documents'][0]['observations'] == []
    assert audit['documents'][0]['identity_status'] == 'not_independently_resolved'
