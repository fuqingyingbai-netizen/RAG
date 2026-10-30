from types import SimpleNamespace

from person_provenance import build_provenance_index, effective_time


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


def test_multiple_tenures_have_separate_relationship_ids_and_no_inferred_current_status():
    facts = []
    for start, end in [('2010-01-01', '2012-12-31'), ('2020-01-01', '')]:
        facts.append({'evidence_id': 'E-' + start, 'fact': '陈明任甲机构董事：' + start,
            'source_url': 'https://issuer.invalid/roles', 'subject': '陈明', 'subject_scope': 'person',
            'observation': {'issuer': '甲机构', 'relations': ['appointment'], 'role_date_fields': [
                {'field': '任职日期', 'source_value': start}, {'field': '离任日期', 'source_value': end}]}})
    audit = build_provenance_index('陈明', {}, [], facts, [], {})
    rels = audit['relationships']
    assert len(rels) == 2 and rels[0]['relationship_id'] != rels[1]['relationship_id']
    assert rels[0]['effective_time']['end_literals'] == ['2012-12-31']
    assert not rels[1]['effective_time']['end_literals']
    assert all(r['effective_time']['current_status'] == 'not_inferred' for r in rels)
    assert all(r['responsibility'] == 'not_determined' and r['control'] == 'not_inferred' for r in rels)


def test_named_evaluation_stays_separate_from_reported_event_and_risk_severity():
    f = {'evidence_id': 'E-OPINION', 'fact': '顾海评价陈明。', 'subject': '陈明', 'subject_scope': 'person',
         'source_url': 'https://issuer.invalid/interview', 'feedback_record': {
             'kind': 'attributed_opinion', 'evaluator': '顾海', 'period': '2020',
             'statement_quote': '顾海评价陈明。', 'source_published_at': '2025-01-01'}}
    audit = build_provenance_index('陈明', {}, [], [f], [], {})
    view = audit['evaluations'][0]
    assert view['period_literal'] == '2020' and view['source_published_at'] == '2025-01-01'
    assert view['truth_status'] == 'not_established' and view['risk_severity'] == 'not_assessed'
    assert not audit['events']


def test_a_range_stays_literal_and_an_empty_end_never_means_current():
    time = effective_time({'role_date_fields': [{'field': '任期起止原文', 'source_value': '2020年至2022年'}]})
    assert time['range_literals'] == ['2020年至2022年']
    assert time['current_status'] == 'not_inferred'
