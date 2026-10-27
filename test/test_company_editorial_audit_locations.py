"""A malformed citation needs a real new audit, with the same unchanged prose."""
from copy import deepcopy
import json
import pytest

from report_agents.company_editorial import (
    audit_location_only,build_editorial_package,numeric_tokens,parse_proposal,
    native_propositions,validate_audit,bind_proposition_spans,
)
from test_company_editorial import record,proposal,audit,OUTLINE


def short_fragment_review():
    row=record(text='开发办公软件。\n（市场\n主体依法自主选择经营项目。）',field='经营范围')
    findings=[{'finding_id':'F','text':'开发办公软件；市场主体依法自主选择经营项目。','information_ids':['I-a']}]
    review=audit([row],findings)
    review['information'][0]['spans']=[{'proposition_id':p['proposition_id'],'finding_id':'F',
        'output_excerpt':findings[0]['text']} for p in native_propositions(row)]
    return row,findings,bind_proposition_spans([row],review)


def test_pdf_short_fragment_is_bound_by_its_complete_immutable_proposition():
    row,findings,review=short_fragment_review();before=deepcopy((row,findings,review))
    fragment=next(p for p in native_propositions(row) if p['text']=='（市场')
    assert any(s['source_excerpt']=='（市场' and s['proposition_id']==fragment['proposition_id']
               for s in review['information'][0]['spans'])
    assert not validate_audit([row],findings,review)
    assert (row,findings,review)==before


@pytest.mark.parametrize('mutation',['missing_id','wrong_id','partial_quote','changed_quote','missing_output'])
def test_short_locator_exception_cannot_authorize_partial_or_invented_source_support(mutation):
    row,findings,review=short_fragment_review()
    span=next(s for s in review['information'][0]['spans'] if s['source_excerpt']=='（市场')
    if mutation=='missing_id':span.pop('proposition_id')
    if mutation=='wrong_id':span['proposition_id']='I-a-P1'
    if mutation=='partial_quote':span['source_excerpt']='市场'
    if mutation=='changed_quote':span['source_excerpt']='（销售'
    if mutation=='missing_output':span['output_excerpt']='市场不在正文中'
    assert 'unbound_semantic_span:I-a' in validate_audit([row],findings,review)


@pytest.mark.parametrize('verb',['分别','分別'])
def test_division_verb_does_not_invent_a_currency_or_score_unit(verb):
    row=record(text='原表重复列示653,650.00与653,650.00，单位未明。')
    text='原表两个653,650.00'+verb+'列示，单位未明。'
    assert numeric_tokens(text)=={'653650.00'}
    assert not parse_proposal({'findings':[{'finding_id':'p','text':text,'information_ids':[row['information_id']]}]},
                              [row],6,OUTLINE[5][1][0])[1]


def test_real_denomination_stays_bound_and_cannot_be_dropped_or_added():
    assert numeric_tokens('100分分别列示')=={'100分'}
    for original,text in [('原值100分。','原值100分别列示。'),('原值100。','原值100分。')]:
        row=record(text=original)
        assert parse_proposal({'findings':[{'finding_id':'p','text':text,'information_ids':[row['information_id']]}]},
                              [row],6,OUTLINE[5][1][0])[1]


@pytest.mark.parametrize('error',[
    'lost_numeric_information:I-a','lost_information:I-a','lost_currency_scale:I-a',
    'unsupported_finding','editorial_criterion:semantic_retention','unresolved_editorial_issues',
])
def test_substantive_loss_is_not_a_location_only_repair(error):
    rows=[record()];qa=audit(rows,proposal(rows)['findings'])
    assert not audit_location_only(['unbound_semantic_span:I-a',error],qa)


def test_true_flags_with_an_explicit_issue_cannot_enter_location_only_repair():
    rows=[record()];qa=audit(rows,proposal(rows)['findings']);qa['issues']=['原文条件未完整表达。']
    assert not audit_location_only(['unbound_semantic_span:I-a'],qa)
    qa['issues']=[];qa['criteria']['factual_support']=False
    assert not audit_location_only(['unbound_semantic_span:I-a'],qa)


def review_payload(prompt):
    return json.JSONDecoder().raw_decode(prompt.split('资料：\n',1)[1])[0]


def test_location_recheck_uses_a_new_independent_response_and_does_not_rewrite_prose():
    rows=[record()];before=deepcopy(rows);calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        if role=='公司交付正文编写':return json.dumps(proposal(rows),ensure_ascii=False)
        payload=review_payload(prompt);qa=audit(rows,payload['findings'])
        if role=='公司交付正文独立审稿':qa['information'][0]['spans'][0]['output_excerpt']='正文没有这句话。'
        else:
            assert role=='公司交付审稿定位重核'
            assert '重新独立核对全部原文和正文' in prompt
        return json.dumps(qa,ensure_ascii=False)
    package=build_editorial_package({'records':rows},OUTLINE,'青禾食品公司',invoke,workers=1)
    assert calls==['公司交付正文编写','公司交付正文独立审稿','公司交付审稿定位重核']
    batch=package['batches'][0]
    assert batch['accepted'] and len(batch['attempts'])==1
    assert batch['attempts'][0]['audit_recheck']['original_errors']==['unbound_semantic_span:I-a']
    assert batch['findings'][0]['text']==rows[0]['text'] and rows==before


def test_recheck_can_reject_content_and_old_true_flags_cannot_authorize_acceptance():
    rows=[record()];calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        if role=='公司交付正文编写':
            if calls.count(role)>1:raise RuntimeError('further producer calls unavailable')
            return json.dumps(proposal(rows),ensure_ascii=False)
        qa=audit(rows,review_payload(prompt)['findings'])
        if role=='公司交付正文独立审稿':qa['information'][0]['spans'][0]['output_excerpt']='不在正文中的引文。'
        else:
            qa['criteria']['factual_support']=False
            qa['findings'][0]['status']='unsupported';qa['issues']=['本次完整复核发现实质问题。']
        return json.dumps(qa,ensure_ascii=False)
    package=build_editorial_package({'records':rows},OUTLINE,'青禾食品公司',invoke,workers=1)
    batch=package['batches'][0]
    assert not batch['accepted'] and package['diagnostic']['pending_information_ids']==['I-a']
    first=batch['attempts'][0]
    assert first['audit_recheck']['original_audit']['criteria']['factual_support'] is True
    assert first['audit']['criteria']['factual_support'] is False
    assert 'editorial_criterion:factual_support' in first['errors']
