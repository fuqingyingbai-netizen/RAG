"""A bounded single request covers chapters and questions before repeats."""
from copy import deepcopy
import json
from types import SimpleNamespace

from industry_reasoning import review_packet, run_support_review, reasoning_markdown
from test_industry_reasoning import review_claim, chain, response, verdict


def test_chapter_slots_survive_many_early_claims_without_more_calls():
    fact = chain()
    claims = [review_claim(fact, chapter=14, text=f'阶段综合{i}') for i in range(20)]
    claims += [review_claim(fact, chapter=ch, text=f'章节{ch}判断') for ch in [13, 10, 7, 4, 6, 11, 3, 2, 5]]
    before = deepcopy(claims)
    packet, excluded = review_packet(claims, [fact])
    assert [c['chapter'] for c in packet['claims']] == [14, 13, 10, 7, 4, 6, 11, 3, 2, 5]
    assert len(excluded) == 19 and claims == before
    assert len(json.dumps(packet, ensure_ascii=False)) <= 18000


def test_question_slots_within_a_chapter_precede_repeated_questions():
    fact = chain()
    claims = [review_claim(fact, question='规模', text=f'规模{i}') for i in range(8)]
    claims += [review_claim(fact, question='口径', text='需要核对口径')]
    packet, _ = review_packet(claims, [fact], max_claims=2)
    assert [c['question'] for c in packet['claims']] == ['规模', '口径']


def test_oversized_or_unlicensed_claim_does_not_consume_other_chapters_slot():
    fact = chain()
    bad = review_claim(fact, chapter=14, text='很长的判断'*5000)
    missing = review_claim(fact, chapter=13, evidence_ids=['E-NOT-ADMITTED'])
    good = review_claim(fact, chapter=7)
    packet, excluded = review_packet([bad, missing, good], [fact], max_chars=3000)
    assert packet['claims'] == [good] and len(excluded) == 2
    assert len(json.dumps(packet, ensure_ascii=False)) <= 3000


def test_submitted_is_not_valid_review_and_pending_includes_outside_packet():
    fact = chain()
    claims = [review_claim(fact, chapter=ch, text=f'判断{ch}') for ch in [14, 7, 4]]
    calls = []
    def invalid(prompt):
        calls.append(prompt)
        return 'not JSON'
    review = run_support_review(claims, [fact], invalid, max_claims=2)
    assert len(calls) == review['attempts'] == 1
    assert review['total_claim_count'] == review['pending_claim_count'] == 3
    assert review['submitted_claim_count'] == 2 and review['valid_review_count'] == 0
    assert review['supported_claim_count'] == 0 and review['coverage_by_chapter']['4']['submitted'] == 0
    text = reasoning_markdown(SimpleNamespace(industry_statement_plans={14: {}}, industry_claim_support_review=review))
    assert '送审2条' in text and '有效复核结果0条' in text


def test_valid_negative_review_is_counted_without_becoming_a_supported_claim():
    fact = chain(); claims = [review_claim(fact, chapter=ch) for ch in [14, 7]]
    def review(prompt):
        packet = json.loads(prompt.split('\n', 1)[1])
        return response(packet, [verdict(packet['claims'][0], fact, 'unsupported'),
                                 verdict(packet['claims'][1], fact)])
    result = run_support_review(claims, [fact], review)
    assert result['valid_review_count'] == 2 and result['supported_claim_count'] == 1
    assert result['pending_claim_count'] == 0
    assert result['review_state_counts'] == {'unsupported': 1, 'supported': 1}


def test_duplicate_judgments_do_not_inflate_coverage_or_consume_extra_slots():
    fact = chain(); claim = review_claim(fact)
    result = run_support_review([claim, deepcopy(claim)], [fact], lambda _: 'invalid')
    assert result['duplicate_claim_count'] == 1
    assert result['total_claim_count'] == result['submitted_claim_count'] == result['pending_claim_count'] == 1


def test_exclusions_distinguish_character_budget_count_limit_and_evidence():
    fact = chain()
    missing = review_claim(fact, chapter=2, evidence_ids=['E-MISSING'])
    long = review_claim(fact, chapter=3, text='判断很长'*5000)
    one, two = [review_claim(fact, chapter=chapter) for chapter in [4, 7]]
    result = run_support_review([missing, long, one, two], [fact], lambda _: 'invalid', max_chars=3000, max_claims=1)
    assert result['exclusion_reasons'] == {missing['claim_id']:'review_evidence_not_admissible',
        long['claim_id']:'review_input_budget', two['claim_id']:'review_claim_limit'}

