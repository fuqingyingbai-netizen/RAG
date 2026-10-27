"""Track returned candidates separately from retained sources and citations."""
import os
from collections import Counter


def configured_budget(name):
    """No implicit source quota; an operator may explicitly bound network work."""
    value = os.getenv(name, '').strip()
    return max(0, int(value)) if value else None


def fetch_budget():
    return configured_budget('PERSON_WEB_FETCH_BUDGET')


def can_fetch(used, budget):
    return budget is None or used < budget


def summarize(candidates):
    keys = {r['canonical_url'] for r in candidates if r.get('canonical_url')}
    return {'returned_candidate_rows': len(candidates), 'unique_returned_urls': len(keys),
            'dispositions': dict(Counter(r['disposition'] for r in candidates)),
            'unresolved_candidate_rows': [r['candidate_id'] for r in candidates
                                          if r['disposition'] == 'pending'],
            'count_boundary': 'Counts cover tool-returned rows, not hidden provider candidates; URL identity is not content independence.'}
