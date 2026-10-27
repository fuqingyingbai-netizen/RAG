"""Offline controller checks: a missing receipt cannot create a writing task."""
import copy
import json
import pytest
import person_content_acceptance as acceptance
from person_evidence import validate_model_claims
from test_person_content_acceptance import fixture


def setup_case():
    package, prior, current = fixture()
    prior.append({'analysis': '林知远公开介绍工程师文化，称要建立文化认同。',
                  'evidence_ids': current[1]['evidence_ids']})
    review = {'status': 'pending_review', 'requests': 4,
              'issues': ['content_coverage_missing', 'content_review_unavailable'],
              'items': [
                  {'prior_index': 0, 'status': 'missing', 'matched_claim_indices': [0],
                   'gaps': [{'prior_quote': prior[0]['analysis'], 'evidence_ids': prior[0]['evidence_ids']}]},
                  {'prior_index': 1, 'status': 'pending_review', 'matched_claim_indices': [], 'gaps': []}]}
    return package, prior, current, review


@pytest.mark.parametrize('final_pass', [False, True])
def test_known_gap_repair_requires_fresh_complete_review(monkeypatch, final_pass):
    package, prior, current, initial = setup_case()
    original = copy.deepcopy(initial)
    calls = []
    def invoke(role, prompt, *args):
        calls.append(role)
        packet = json.loads(prompt.splitlines()[-1])
        assert [r['prior_index'] for r in packet['missing_items']] == [0]
        assert prior[1] in packet['prior_draft_analyses_not_evidence']
        return json.dumps({'claims': [prior[0]]}, ensure_ascii=False)
    monkeypatch.setattr(acceptance, 'review_analyses', lambda *args, **kwargs: (args[3], [], {'requests': 0}))
    final_calls = []
    def final_review(p, candidate, requirements, *args):
        final_calls.append(candidate)
        assert prior[1] in requirements
        return {'status': 'passed' if final_pass else 'pending_review', 'requests': 2,
                'items': [], 'issues': [] if final_pass else ['content_review_unavailable']}
    monkeypatch.setattr(acceptance, 'check_coverage', final_review)
    result, issues, audit = acceptance._accept_once(package, current, prior,
        {'chapter': 5, 'facts': package['facts']}, invoke, None,
        validate_model_claims, initial_review=initial)
    assert len(calls) == 1 and len(final_calls) == 1
    assert audit['deferred_unreviewed_requirements'] == [1]
    assert initial == original
    assert (not issues) == final_pass
    assert audit['status'] == ('passed_after_targeted_repair' if final_pass else 'pending_final_coverage')


def test_all_unreviewed_stays_pending_without_any_writer():
    package, prior, current, initial = setup_case()
    initial['items'][0].update(status='pending_review', gaps=[])
    def forbidden(*args): raise AssertionError('No diagnosed gap exists')
    result, issues, audit = acceptance._accept_once(package, current, prior,
        {'chapter': 5, 'facts': package['facts']}, forbidden, None,
        validate_model_claims, initial_review=initial)
    assert result == current and issues and audit['status'] == 'pending_review'


@pytest.mark.parametrize('failure', ['unauthorized', 'access_denied', 'quota_exceeded'])
def test_permanent_provider_failure_stops_known_gap_repair(failure):
    package, prior, current, initial = setup_case()
    initial['per_item_checks'] = [{'attempts': [{'status': 'failed', 'failure_kind': failure}]}]
    def forbidden(*args): raise AssertionError('Permanent provider failure')
    result, issues, audit = acceptance._accept_once(package, current, prior,
        {'chapter': 5, 'facts': package['facts']}, forbidden, None,
        validate_model_claims, initial_review=initial)
    assert result == current and issues and audit['status'] == 'pending_review'
