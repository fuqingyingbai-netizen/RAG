"""Legal responsibility, business harm and procedure/date roles stay distinct."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from report_agents.company_event_evidence import (
    VERSION, REVIEW_CRITERIA, BOUNDARIES, case_state_errors, event_period,
    review_primary_events, reviewed_event_records, validate_event,
)
from report_agents.company_risk_register import build_risk_register, render_risk_register
from report_agents.company_corpus_writer import collect_statements


TARGET = '青禾食品股份有限公司'
AS_OF = '2026-10-24'
STAMP = '2026-10-24 11:46:49'
BODY = (TARGET + '为原告及商标权利人。乙地法院责令第三方停止侵权；原告商誉和销量受到影响。'
        '法院酌定销量下降利润损失350万元，并将合理广告费300万元、律师费5万元纳入655万元赔偿范围。'
        '被告应在判决生效后十日内办理字号变更，后在二审阶段主动申请撤回上诉。')


def source(extra=''):
    return {'id': 1, 'title': TARGET + '第三方侵权典型案例',
            'url': 'https://court.example.gov.cn/case', 'content': STAMP + '\n' + BODY + extra,
            'source_metadata': {'fetch_status': 'done'}}


def check(**changes):
    return {'status': 'supported', 'criteria': {**dict.fromkeys(REVIEW_CRITERIA, True), **changes},
            'reason': '逐项区分责任、原文明示影响、日期性质和申请状态。'}


def selection(s=None):
    s = s or source(); raw = s['content']
    row = {'target_name': TARGET, 'kind': 'external_impersonation', 'source_url': s['url'],
           'source_title': s['title'], 'quote': BODY, 'subject_quote': TARGET, 'date_quote': STAMP,
           'source_date': '2026-10-24', 'source_date_role': 'unverified_display', 'publication_date': None,
           'summary': '法院责令第三方停止侵权，目标公司为原告。原告商誉和销量受损，法院认定利润损失350万元，'
                      '广告费300万元和律师费5万元，判赔共655万元。被告在二审申请撤回上诉。',
           'subject_scope': '第三方承担侵权责任；目标公司为原告及受损权利人，事件日期未明确。',
           'original_sha256': hashlib.sha256(raw.encode()).hexdigest(), 'independent_check': check()}
    for key in ('quote', 'subject_quote', 'date_quote'):
        row[key + '_offset'] = raw.find(row[key])
    return row


def package(row, as_of=AS_OF):
    return {'version': VERSION, 'target_name': TARGET, 'as_of_date': as_of, 'events': [row]}


def test_display_time_preserves_case_without_fabricating_publication_or_event_date():
    s = source(); row = selection(s); before = deepcopy((s, row))
    assert not validate_event(row, s, TARGET, AS_OF)
    assert event_period(row) == '事件日期原文未确认；原页所见时间仅作定位'
    assert (s, row) == before
    p = build_risk_register({'facts': []}, TARGET, [s], intake={'as_of_date': AS_OF}, event_reviews=package(row))
    text = render_risk_register(p)
    assert p['entries'] and p['overall_score'] is None
    fact = p['entries'][0]['fact_record']
    assert fact['publication_date'] is None and fact['source_date_role'] == 'unverified_display'
    assert '350万元' in text and '300万元' in text and '5万元' in text and '655万元' in text
    assert '受损影响及法院损失认定按原文保留' in text
    assert '不记为目标公司的违法或罚款' in text
    assert '不记为目标公司的违法、罚款或经营损失' not in text
    project = SimpleNamespace(target_name=TARGET, sources=[s], company_risk_register_package=p)
    rows = [r for r in collect_statements(project, {}) if r['context'].get('kind') == 'external_impersonation']
    assert rows and rows[0]['context']['source_date_role'] == 'unverified_display'
    assert rows[0]['context']['source_date_quote'] == STAMP


def test_explicit_publication_date_and_document_date_keep_their_own_meaning():
    s = source(); s['content'] = '发布日期：2026-10-24\n' + BODY
    row = selection(s); row.update(source_date_role='publication', publication_date='2026-10-24',
                                   date_quote='发布日期：2026-10-24', date_quote_offset=0)
    assert not validate_event(row, s, TARGET, AS_OF)
    assert event_period(row).startswith('资料发布日期2026-10-24')
    assert 'after_research_cutoff' in validate_event(row, s, TARGET, '2026-10-23')
    row.update(source_date_role='document_date', publication_date=None)
    assert event_period(row).startswith('文书署明日期2026-10-24')
    assert 'after_research_cutoff' in validate_event(row, s, TARGET, '2026-10-23')


def test_undated_event_does_not_require_a_made_up_date_quote():
    s = source(); row = selection(s)
    row.update(source_date_role='unknown', source_date=None, publication_date=None, date_quote=None, date_quote_offset=-1)
    assert not validate_event(row, s, TARGET, AS_OF)


@pytest.mark.parametrize('changes,error', [
    ({'publication_date': '2026-10-24'}, 'nonpublication_time_used_as_publication'),
    ({'source_date': '2025-02-31'}, 'unproven_source_date'),
    ({'source_date_role': 'publication', 'publication_date': None}, 'unproven_publication_date'),
    ({'source_date_role': []}, 'unproven_source_date_role'),
    ({'source_date': True}, 'unproven_source_date'),
    ({'date_quote': None}, 'unproven_source_date'),
])
def test_bad_date_claims_are_rejected_even_with_a_green_overall_verdict(changes, error):
    row = selection(); row.update(changes)
    assert error in validate_event(row, source(), TARGET, AS_OF)


@pytest.mark.parametrize('criterion', REVIEW_CRITERIA)
def test_each_independent_criterion_is_mandatory(criterion):
    row = selection(); row['independent_check'] = check(**{criterion: False})
    assert 'independent_criterion:' + criterion in validate_event(row, source(), TARGET, AS_OF)


def test_literal_precheck_never_inserts_an_independent_verdict():
    row = selection(); row.pop('independent_check'); before = deepcopy(row)
    assert not validate_event(row, source(), TARGET, AS_OF, require_independent=False)
    assert row == before
    assert 'independent_check_missing' in validate_event(row, source(), TARGET, AS_OF)


@pytest.mark.parametrize('summary,error', [
    ('二审被告主动撤回上诉。', 'unproven_withdrawal_completion'),
    ('上诉已撤回。', 'unproven_withdrawal_completion'),
    ('程序阶段为一审判决生效。', 'unproven_judgment_finality'),
    ('原判已经生效。', 'unproven_judgment_finality'),
    ('目标公司已收到655万元赔偿。', 'unproven_compensation_receipt'),
    ('赔偿款已经到账。', 'unproven_compensation_receipt'),
])
def test_requests_and_awards_cannot_become_completed_states(summary, error):
    row = selection(); row['summary'] = summary
    assert error in validate_event(row, source(), TARGET, AS_OF)


@pytest.mark.parametrize('summary', [
    '被告主动申请撤回上诉。',
    '法院判赔655万元，被告在二审申请撤回上诉。',
    '原文未载明申请是否获准，不能据此认定判决已生效。',
    '应在判决生效后十日内办理字号变更。',
    '需核验撤回上诉申请的处理结果。',
    '尚待判决生效。',
])
def test_requests_qualifications_and_future_conditions_remain_allowed(summary):
    row = selection(); row['summary'] = summary
    assert not case_state_errors(row, source()['content'])


@pytest.mark.parametrize('scope', [
    '二审准许撤回、判决生效、判赔履行与款项到账均为不同状态。',
    '申请撤回上诉、法院准许撤回、判决生效、判赔义务与赔偿款实际到账系不同状态。',
    '申请撤诉、法院准许撤诉、判决生效与赔偿到账是不同的程序阶段。',
    '申請撤回上訴、法院准許撤回上訴、判決生效與款項到賬均為不同狀態。',
])
def test_explanation_of_distinct_states_is_not_a_completed_act(scope):
    row = selection(); row['subject_scope'] += scope
    assert not validate_event(row, source(), TARGET, AS_OF)
    assert row['subject_scope'].endswith(scope)


@pytest.mark.parametrize('summary,error', [
    ('原判已生效且申请撤诉与法院准许撤诉系不同状态。', 'unproven_judgment_finality'),
    ('法院裁定准许撤回上诉与判决生效系不同状态。', 'unproven_withdrawal_completion'),
    ('二审撤回上诉已获准、判决已生效与赔偿款已到账均为不同状态。', 'unproven_judgment_finality'),
    ('二审撤回上诉已获准、判决已生效与赔偿款已到账均为不同状态。', 'unproven_compensation_receipt'),
    ('2026年判决生效与赔款到账是不同状态。', 'unproven_judgment_finality'),
    ('本案原判已经生效。申请撤诉与准许撤诉是不同状态。', 'unproven_judgment_finality'),
])
def test_distinction_reminder_does_not_hide_an_actual_completed_act_claim(summary, error):
    row = selection(); row['summary'] = summary
    assert error in case_state_errors(row, source()['content'])


def test_concept_list_in_source_does_not_prove_withdrawal_or_finality():
    row = selection()
    row['quote'] += '申请撤回上诉、法院准许撤回上诉、判决生效与赔偿到账是不同状态。'
    row['summary'] = '被告撤回上诉，原判已生效。'
    errors = case_state_errors(row, source()['content'])
    assert 'unproven_withdrawal_completion' in errors
    assert 'unproven_judgment_finality' in errors


def test_state_distinction_still_requires_a_fresh_complete_independent_review():
    s = source(); row = selection(s)
    row.pop('independent_check')
    row['subject_scope'] += '申请撤回上诉、法院准许撤回上诉、判决生效与赔款到账是不同状态。'
    assert 'independent_check_missing' in validate_event(row, s, TARGET, AS_OF)
    calls = []
    def invoke(role, prompt, trace):
        calls.append(role)
        if role == '公司监管原件提取':
            return json.dumps({'event': row}, ensure_ascii=False)
        assert role == '公司监管原件独立核对'
        return json.dumps(check(), ensure_ascii=False)
    result = review_primary_events([s], TARGET, AS_OF, invoke)
    assert calls == ['公司监管原件提取', '公司监管原件独立核对']
    assert result['receipts'][0]['state'] == 'accepted'
    assert result['events'][0]['independent_check']['criteria'] == dict.fromkeys(REVIEW_CRITERIA, True)


def test_granted_withdrawal_does_not_also_prove_judgment_finality():
    row = selection(); row['quote'] += '法院准许撤回上诉。'
    row['summary'] = '上诉已撤回，原判已生效。'
    errors = case_state_errors(row, source()['content'])
    assert 'unproven_withdrawal_completion' not in errors
    assert 'unproven_judgment_finality' in errors
    row['quote'] += '原判已经生效。'
    assert not case_state_errors(row, source()['content'])


def test_another_case_on_the_page_cannot_supply_receipt_or_grant():
    s = source('另案法院准许撤回上诉，另案原告已收到655万元赔偿。')
    row = selection(s); row['summary'] = '上诉已撤回，目标公司已收到655万元赔偿。'
    errors = case_state_errors(row, s['content'])
    assert 'unproven_withdrawal_completion' in errors and 'unproven_compensation_receipt' in errors


def test_denied_grant_is_not_positive_evidence():
    row = selection(); row['quote'] += '法院没有准许撤回上诉。'
    row['summary'] = '上诉已撤回。'
    assert 'unproven_withdrawal_completion' in case_state_errors(row, source()['content'])


def test_event_cache_binds_target_cutoff_and_contract_version():
    row = selection(); p = package(row)
    assert reviewed_event_records(p, [source()], TARGET, AS_OF)
    assert not reviewed_event_records(p, [source()], TARGET, '2026-10-23')
    assert not reviewed_event_records({**p, 'target_name': '其他公司'}, [source()], TARGET, AS_OF)
    assert not reviewed_event_records({**p, 'version': 'old'}, [source()], TARGET, AS_OF)


@pytest.mark.parametrize('repairs', [True, False])
def test_semantic_repair_receives_a_fresh_complete_check(repairs):
    s = source(); corrected = selection(s)
    initial = deepcopy(corrected); initial.update(source_date_role='publication', publication_date='2026-10-24')
    calls = []; checks = []

    def invoke(role, prompt, trace):
        calls.append(role)
        if role == '公司监管原件提取': return json.dumps({'event': initial}, ensure_ascii=False)
        if role == '公司监管原件语义修复': return json.dumps({'event': corrected}, ensure_ascii=False)
        assert role == '公司监管原件独立核对'
        assert '责任' in prompt and '研究截至日：' + AS_OF in prompt
        assert '"independent_check"' not in prompt
        answer = check(date_meaning=(repairs and len(checks) > 0))
        checks.append(answer)
        return json.dumps(answer, ensure_ascii=False)

    p = review_primary_events([s], TARGET, AS_OF, invoke)
    assert calls.count('公司监管原件独立核对') == 2
    receipt = p['receipts'][0]
    assert len(receipt['semantic_attempts']) == 2
    assert len(receipt['untrusted_self_checks']) == 2
    assert receipt['semantic_attempts'][0]['check']['criteria']['date_meaning'] is False
    if repairs:
        assert p['events'][0]['publication_date'] is None
        assert p['events'][0]['source_date_role'] == 'unverified_display'
        assert receipt['state'] == 'accepted'
    else:
        assert not p['events'] and receipt['state'] == 'requires_review'


def test_source_date_context_does_not_change_unrelated_specialized_records():
    fact = {'fact': '公司披露本期完成产品交付。', 'publication_date': '2026-10-24',
            'evidence_ids': ['E-123456ABCDEF'], 'source_url': 'https://issuer.test/report', 'kind': 'business'}
    p = SimpleNamespace(target_name=TARGET, sources=[], company_business_package={'facts': [fact]})
    rows = collect_statements(p, {})
    assert rows and 'publication_date' not in rows[0]['context']
