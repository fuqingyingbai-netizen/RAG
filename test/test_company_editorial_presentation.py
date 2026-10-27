from copy import deepcopy
import pytest
from report_agents.company_editorial import native_propositions,semantic_source_text,bind_proposition_spans,validate_audit,parse_proposal,numeric_tokens
from test_company_editorial import record,audit,OUTLINE


def checked(row,text):
    findings,errors=parse_proposal({'findings':[{'finding_id':'f','text':text,'information_ids':[row['information_id']]}]},[row],6,OUTLINE[5][1][0])
    assert not errors
    result=audit([row],findings)
    result['information'][0]['spans']=[{'proposition_id':p['proposition_id'],'finding_id':'f','output_excerpt':text}
                                     for p in native_propositions(row) if not p.get('presentation_only') and len(p['text'].strip())>=8]
    return findings,bind_proposition_spans([row],result)


def test_markdown_alignment_is_optional_but_every_actual_profile_field_remains_substantive():
    row=record(text='| 字段 | 值 |\n| --- | --- |\n| 企业名称 | 青禾食品公司 |\n| 注册资本 | 0万元 |')
    original=deepcopy(row);props=native_propositions(row)
    assert props[1]['text']=='| --- | --- |' and props[1]['presentation_only'] is True
    assert all(not p.get('presentation_only') for p in props[2:])
    findings,review=checked(row,'平台列示企业名称为青禾食品公司，注册资本为0万元。')
    assert not validate_audit([row],findings,review) and row==original


def test_later_all_dash_data_rows_and_explicit_field_values_are_not_alignment_syntax():
    row=record(text='| 项目 | 值 |\n| --- | --- |\n| 状态 | 待查 |\n| --- | --- |')
    props=native_propositions(row)
    assert props[1]['presentation_only'] and not props[3].get('presentation_only')
    typed=record(text='| --- | --- |',field='平台原始标志')
    assert semantic_source_text(typed)==typed['text'] and not native_propositions(typed)[0].get('presentation_only')


def test_issuer_reply_folio_requires_native_page_position_and_keeps_business_quantities():
    row=record(text='--- PDF page 12 ---\n8-1-11\n经核查，发行人不存在股东超200人的情形。')
    row['provenance'][0]['source_title']='关于青禾食品公司首次公开发行申请文件第四轮审核问询函的回复'
    before=deepcopy(row)
    assert '8-1-11' not in semantic_source_text(row)
    assert '200人' in semantic_source_text(row) and row==before
    elsewhere=deepcopy(row);elsewhere['text']='--- PDF page 12 ---\n合同编号\n8-1-11\n已登记。'
    assert '8-1-11' in semantic_source_text(elsewhere)
    typed=deepcopy(row);typed['context']['field']='合同号'
    assert semantic_source_text(typed)==typed['text']
    unbound=deepcopy(row);unbound['provenance'][0]['source_title']='企业记录'
    assert '8-1-11' in semantic_source_text(unbound)


def test_native_no_space_decimal_dot_list_label_is_optional_but_not_a_decimal_quantity():
    row=record(text='1.本公司在承诺期间内不得从事竞争业务。')
    assert semantic_source_text(row).strip()=='本公司在承诺期间内不得从事竞争业务。'
    for value in ['1.23万元为期末金额。','1.万元为披露单位。']:
        row=record(text=value)
        assert semantic_source_text(row)==value


def test_a_condition_closing_bracket_does_not_become_an_extra_business_fact():
    row=record(text='经营食品业务。（依法须经批准的项目，经相关部门批准后方可开展经营活动。）',field='经营范围')
    original=deepcopy(row);props=native_propositions(row)
    assert props[-1]['text']=='）' and props[-1]['presentation_only']
    assert '批准后方可开展' in props[-2]['text'] and not props[-2].get('presentation_only')
    text='平台经营范围列示经营食品业务，并保留“依法须经批准的项目，经相关部门批准后方可开展经营活动”的条件。'
    findings,review=checked(row,text)
    review['information'][0]['spans'].append({'proposition_id':props[-1]['proposition_id'],'finding_id':'f',
        'source_excerpt':'）','output_excerpt':'依法须经批准的项目，经相关部门批准后方可开展经营活动'})
    assert not validate_audit([row],findings,review) and row==original
    broken=deepcopy(review);broken['information'][0]['spans'][-1]['finding_id']='unknown'
    assert any(e.startswith('unbound_semantic_span:') for e in validate_audit([row],findings,broken))
    missing=[{**findings[0],'text':'平台经营范围列示经营食品业务。'}]
    assert any(e.startswith('unbound_semantic_span:') for e in validate_audit([row],missing,review))


@pytest.mark.parametrize('value',['）','0','待查','False'])
def test_short_explicit_field_values_are_never_silently_classified_as_layout(value):
    row=record(text=value,field='原始字段')
    assert semantic_source_text(row)==value and not native_propositions(row)[0].get('presentation_only')


def test_original_prospectus_header_can_bind_a_folio_when_provider_title_is_only_a_url():
    row=record(text='青禾食品股份有限公司 招股说明书（注册稿）\n1-1-313\n原文列示注册资本301万元。')
    row['provenance'][0]['source_title']='https://exchange.test/original.pdf'
    original=deepcopy(row);text=semantic_source_text(row)
    assert '313' not in text and '301万元' in text and row==original
    assert native_propositions(row)[1]['presentation_only']


@pytest.mark.parametrize('text',[
    '青禾食品股份有限公司 招股说明书（注册稿）\n合同编号：\n1-1-313\n原文列示注册资本301万元。',
    '青禾食品股份有限公司 招股说明书（注册稿）\n2025-01-01\n原文列示注册资本301万元。',
])
def test_contract_identifiers_dates_and_company_quantities_stay_in_the_matching_view(text):
    row=record(text=text)
    assert numeric_tokens(semantic_source_text(row))==numeric_tokens(text)
