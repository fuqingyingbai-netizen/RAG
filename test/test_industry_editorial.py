"""Editorial feedback cannot expand evidence or bypass factual review."""
import json
import time

import pytest

import industry_editorial as editorial


@pytest.fixture
def draft():
    claim = {'question': '适用条件是什么？', 'conclusion': '先验证适用条件。',
             'text': '材料仅覆盖样本场景，应先验证适用条件再推广。',
             'claim_kind': 'conditional', 'evidence_ids': ['e1']}
    packet = {'chapter': '行业判断', 'questions': [
        {'question': claim['question'], 'allowed_refs': ['F1']}],
        '_refs': {'F1': 'e1'}, '_facts': {'e1': {
            'source_title': '样本报告', 'fact_contract': {'statement': '样本存在适用边界。'}}}}
    return [claim], packet


def feedback(claims, packet, decision='revise'):
    record = editorial._records(claims, packet)['D1'][1]
    return {'reviews': [{'draft_id': 'D1', 'fingerprint': record['fingerprint'],
        'decision': decision, 'issues': [] if decision == 'keep' else [{
            'code': 'missing_conditions', 'quote': '先验证适用条件',
            'instruction': '明确说明只在相同样本条件下验证后推广。'}]}]}


def run(draft, invoke, parse=lambda *args: pytest.fail('Unexpected revision parser'), max_calls=2):
    claims, packet = draft
    return editorial.refine_packet(claims, packet, invoke, parse, lambda packet: '局部修订',
        {'calls': 0, 'max_calls': max_calls, 'deadline': time.monotonic()+30})


def test_keep_is_quality_opinion_and_never_factual_approval(draft):
    result, diagnostic = run(draft, lambda *args: json.dumps(feedback(*draft, 'keep')))
    assert result == draft[0] and diagnostic['status'] == 'reviewed_keep'
    assert diagnostic['human_review_required'] is True
    assert diagnostic['semantic_support_authorized'] is False


@pytest.mark.parametrize('tamper', ['fingerprint', 'invented_quote', 'duplicate'])
def test_unbound_or_fabricated_feedback_cannot_rewrite(draft, tamper):
    reviews = feedback(*draft)
    if tamper == 'fingerprint': reviews['reviews'][0]['fingerprint'] = 'other-draft'
    if tamper == 'invented_quote': reviews['reviews'][0]['issues'][0]['quote'] = '不存在的逐字引文'
    if tamper == 'duplicate': reviews['reviews'] *= 2
    result, diagnostic = run(draft, lambda *args: json.dumps(reviews))
    assert result == draft[0] and not diagnostic['revised']


def test_revision_with_changed_evidence_is_rejected_even_if_parser_accepts(draft):
    replies = iter([feedback(*draft), {'answers': [{'question_id': 'D1', 'status': 'answered',
        'conclusion': '修订判断。', 'analysis': '修订分析。', 'kind': 'conditional', 'refs': ['F1']}]}])
    def parse(raw, packet):
        return [{**draft[0][0], 'text': '修订分析。', 'evidence_ids': ['e2']}], [], {
            'D1': {'answer_status': 'answered'}}
    result, diagnostic = run(draft, lambda *args: json.dumps(next(replies)), parse)
    assert result == draft[0] and diagnostic['status'] == 'original_retained'
    assert diagnostic['retained_original'] == ['D1']


def test_budget_exhaustion_keeps_original_without_an_extra_model_call(draft):
    calls = []
    def invoke(*args):
        calls.append(args[0]); return json.dumps(feedback(*draft))
    result, diagnostic = run(draft, invoke, max_calls=1)
    assert len(calls) == 1 and result == draft[0]
    assert diagnostic['status'] == 'revision_unavailable' and diagnostic['calls'] == 1
