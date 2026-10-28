"""Source identity decisions survive stale cleaning/replay and all fact types."""
from types import SimpleNamespace

import pytest

from person_evidence import normalize_facts


@pytest.mark.parametrize('claim_type', ['', 'person_platform_record', 'person_company_record'])
def test_namesake_source_quarantine_cannot_be_overridden_by_extractor(claim_type):
    text = '张勇于2015年加入阿里巴巴，担任集团首席执行官。'
    source = SimpleNamespace(url='https://issuer.invalid/namesake', content=text,
                             source_metadata={'identity_status': 'quarantined',
                                              'identity_reason': '不同公司与任职时期，身份待核验'})
    raw = {'fact': text, 'source_url': source.url, 'identity_match': 'confirmed',
           'identity_confidence': 'high', 'claim_type': claim_type}
    accepted, rejected = normalize_facts({'facts': [raw]}, '张勇', sources=[source])
    assert accepted == []
    assert rejected[0]['rejection_reason'] == 'identity_quarantine'
    assert rejected[0]['source_identity_quarantine_reason'] == source.source_metadata['identity_reason']
    assert rejected[0]['fact'] == text


def test_matching_professional_record_is_retained_with_literal_provenance():
    text = '张勇的平台人员记录：{"姓名":"张勇","企业名称":"海底捞","职位":"董事"}'
    source = SimpleNamespace(url='https://platform.invalid/record', content=text,
                             source_metadata={'identity_status': 'accepted', 'identity_confidence': 'high'})
    accepted, rejected = normalize_facts({'facts': [{'fact': text, 'source_url': source.url,
        'claim_type': 'person_platform_record', 'identity_match': 'confirmed'}]}, '张勇', sources=[source])
    assert not rejected
    assert accepted[0]['original_excerpt_match'] is True
    assert accepted[0]['fact'] == text


def test_untrusted_peer_label_cannot_override_source_quarantine():
    text = '陈明是乙机构董事，2019年加入乙机构。'
    source = SimpleNamespace(url='https://issuer.invalid/peer', content=text,
                             source_metadata={'identity_status': 'quarantined'})
    raw = {'fact': text, 'source_url': source.url, 'identity_match': 'confirmed',
           'claim_type': 'person_peer_record', 'comparison_subject': '陈明',
           'validated_peer_subject': '陈明'}
    assert not normalize_facts({'facts': [raw]}, '陈明', sources=[source])[0]
    # Only the caller which revalidated the nomination and original excerpts
    # can choose a different peer identity scope; payload flags cannot do so.
    assert normalize_facts({'facts': [raw]}, '陈明', sources=[source],
                           validated_peer_subject='陈明')[0]
