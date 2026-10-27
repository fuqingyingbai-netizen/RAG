"""Real PDF layout must not become business quantities or missing facts."""
from copy import deepcopy
import json

import pytest

from report_agents.company_editorial import (
    native_propositions,semantic_source_text,numeric_tokens,parse_proposal,
    validate_audit,build_editorial_package,missing_numeric_tokens,
)
from test_company_editorial import record,audit,OUTLINE


def comparison_page(footer='5',marker='5',row='| 第六条 注册资本100万元。 | 第六条 注册资本120万元。 |'):
    return f'--- PDF page {marker} ---\n附件：公司章程修订对照表\n| 修订前 | 修订后 |\n| --- | --- |\n{row}\n{footer}'


@pytest.mark.parametrize('traditional,newline',[(False,'\n'),(True,'\n'),(False,'\r\n')])
def test_native_comparison_grid_footer_binds_to_the_same_explicit_page(traditional,newline):
    text=comparison_page().replace('\n',newline)
    if traditional:text=text.replace('修订前','修訂前').replace('修订后','修訂後')
    row=record(text=text);before=deepcopy(row);projected=semantic_source_text(row)
    assert numeric_tokens(projected)=={'100万元','120万元'}
    assert projected.endswith(' ') and len(projected)==len(row['text']) and row==before
    assert row['text'].endswith(newline+'5')


@pytest.mark.parametrize('text,field',[
    (comparison_page(footer='4'),None),
    (comparison_page().replace('--- PDF page 5 ---\n',''),None),
    (comparison_page(), '原始字段'),
    (comparison_page(footer='单位：万元\n5'),None),
    ('--- PDF page 5 ---\n| 项目 | 原值 |\n| --- | --- |\n| 余额 | 100万元 |\n5',None),
])
def test_comparison_footer_projection_does_not_drop_unbound_values_or_typed_fields(text,field):
    row=record(text=text)
    if field:row['context']['field']=field
    assert text.splitlines()[-1] in semantic_source_text(row)


def test_actual_table_cell_equal_to_its_page_number_stays_a_business_value():
    row=record(text=comparison_page(row='| 第五条 指标原值5。 | 第五条 指标原值6。 |'))
    projected=semantic_source_text(row)
    assert '5' in numeric_tokens(projected) and '6' in numeric_tokens(projected)


NOTICE='公司代码：600000 第一节 重要提示 1本年度报告摘要来自年度报告全文。2重大风险提示：营业收入120万元。'


def test_paired_abstract_notice_labels_are_layout_while_code_and_amount_stay_native():
    row=record(text=NOTICE);before=deepcopy(row);projected=semantic_source_text(row)
    assert numeric_tokens(projected)=={'600000','120万元'} and row==before
    assert '重要提示' in projected and '重大风险提示' in projected


def test_literal_proposition_still_covers_internal_layout_masks_without_losing_amounts():
    rows=[record(text=NOTICE)];text='原件重要提示称年度报告摘要来自年度报告全文，公司代码为600000；重大风险提示处列示营业收入120万元。'
    findings,review=checked(rows,text)
    assert not validate_audit(rows,findings,review)
    bad_findings=deepcopy(findings);bad_findings[0]['text']=text.replace('120万元','120元')
    bad_review=deepcopy(review)
    for span in bad_review['information'][0]['spans']:span['output_excerpt']=bad_findings[0]['text']
    assert 'lost_numeric_information:I-a' in validate_audit(rows,bad_findings,bad_review)


@pytest.mark.parametrize('text,field',[
    (NOTICE,'原始字段'),
    (NOTICE.replace('第一节 重要提示','摘要'),None),
    (NOTICE.replace('2重大风险提示','重大风险提示'),None),
    ('第一节 重要提示 1本年度报告摘要来自年度报告全文，实际购入2本报告。',None),
])
def test_unpaired_heading_like_values_and_explicit_fields_are_not_projected(text,field):
    row=record(text=text)
    if field:row['context']['field']=field
    assert '1' in numeric_tokens(semantic_source_text(row))


@pytest.mark.parametrize('native,expected',[
    ('证券代码603288第一节 重要提示',{'603288','1'}),
    ('编码603288第007期',{'603288','007'}),
    ('code603288first section',{'603288','1'}),
    ('2026第一季度',{'2026','1'}),
])
def test_normalized_ordinal_cannot_fuse_with_an_adjacent_code_or_year(native,expected):
    assert numeric_tokens(native)==expected


def test_actual_contiguous_security_code_is_not_split_as_an_ordinal():
    assert numeric_tokens('证券代码6032881')=={'6032881'}


@pytest.mark.parametrize('body',['第四十七条 下列事项由股东会以普通决议通过。','（三）全体股东均有权出席股东会。'])
def test_legal_document_printed_folio_can_differ_from_physical_cover_page_count(body):
    row=record(text='--- PDF page 19 ---\n17\n'+body)
    row['provenance'][0]['source_title']='华舟软件股东会议事规则'
    before=deepcopy(row);text=semantic_source_text(row)
    assert '17' not in numeric_tokens(text) and body in text
    assert row==before and '17' in row['text']


@pytest.mark.parametrize('text,field',[
    ('--- PDF page 19 ---\n17\n单位：人\n员工人数17人。',None),
    ('--- PDF page 19 ---\n17\n第四十七条 公司登记信息。','原始编号'),
    ('--- PDF page 19 ---\n0017\n第四十七条 公司登记信息。',None),
    ('--- PDF page 19 ---\n2025\n第四十七条 公司登记信息。',None),
])
def test_legal_document_folio_rule_preserves_table_values_typed_fields_and_codes(text,field):
    row=record(text=text);row['provenance'][0]['source_title']='华舟软件公司章程'
    if field:row['context']['field']=field
    projected=semantic_source_text(row)
    assert text.splitlines()[1] in projected


def checked(rows,text):
    findings,errors=parse_proposal({'findings':[{'finding_id':'p','text':text,
        'information_ids':[r['information_id'] for r in rows]}]},rows,6,OUTLINE[5][1][0])
    assert not errors
    result=audit(rows,findings)
    for review,row in zip(result['information'],rows):
        review['spans']=[{'proposition_id':p['proposition_id'],'source_excerpt':p['text'],
                         'finding_id':'p','output_excerpt':text}
                        for p in native_propositions(row) if not p.get('presentation_only')]
    return findings,result


def test_pdf_page_and_enumeration_stay_in_originals_without_becoming_prose_facts():
    native=('--- PDF page 143 ---\n华舟软件2026年半年度报告\n143 / 198\n'
            '1. 公司概况：公司累计发行股本462,525,643股，注册资本462,525,643元。\n'
            '2. 合并财务报表范围：本公司范围包括52家公司。')
    rows=[record(text=native)];before=deepcopy(rows)
    text='华舟软件2026年半年度报告披露，公司累计发行股本462,525,643股，注册资本462,525,643元，合并财务报表范围包括52家公司。'
    findings,result=checked(rows,text)
    assert not validate_audit(rows,findings,result)
    assert rows==before and rows[0]['text']==native
    props=native_propositions(rows[0])
    assert any(p.get('presentation_only') and '143 / 198' in p['text'] for p in props)
    assert any(p.get('semantic_text','').startswith('公司概况：') for p in props)
    assert any(p['text'].startswith('1. 公司概况：') for p in props)


def test_year_or_page_followed_by_equity_or_item_heading_is_not_a_share_count():
    assert '198项' not in numeric_tokens('143 / 198\n项目 期末余额')
    assert '198' in numeric_tokens('143 / 198\n项目 期末余额')
    assert numeric_tokens('2016年股份公司设立')=={'2016'}
    assert numeric_tokens('第六届股东大会')=={'6'}
    assert numeric_tokens('本公司持股2016股')=={'2016股'}
    assert numeric_tokens('2016年股份公司设立')!=numeric_tokens('本公司持股2016股')


def test_calendar_boundary_does_not_turn_yen_into_a_date_or_allow_dropped_unit():
    rows=[record(text='公司披露支出10日元。')]
    errors=parse_proposal({'findings':[{'finding_id':'p','text':'公司披露支出10。',
        'information_ids':['I-a']}]},rows,6,OUTLINE[5][1][0])[1]
    assert any('new_or_changed_number_unit' in e for e in errors)


def test_source_wrap_inside_a_quantity_keeps_its_unit_and_decimal_precision():
    assert numeric_tokens('184,450.45\n万元为基准')==numeric_tokens('184,450.45万元为基准')
    assert numeric_tokens('245,949\n股；')==numeric_tokens('245,949股；')
    assert numeric_tokens('245,949.00\n股；')!=numeric_tokens('245,949股；')


def test_complete_native_quantity_covers_repeated_bare_cell_but_not_a_calendar_component():
    assert not missing_numeric_tokens('注册资本46,317.9293元；原表另列数值46,317.9293。','注册资本46,317.9293元。')
    assert missing_numeric_tokens('公司成立于2026年，持股2026股。','公司持股2026股。')=={'2026'}
    assert missing_numeric_tokens('截至July 4, 2026，持股4股、员工7人。','持股4股、员工7人。')
    assert missing_numeric_tokens('本期金额0.50亿元。','本期金额0.5亿元。')


def test_roman_folio_is_optional_but_an_actual_negative_amount_is_still_required():
    native='--- PDF page 544 ---\n– VI-1 –\n公司披露净利润-1亿元，现金流-0.50亿元。'
    rows=[record(text=native)]
    findings,result=checked(rows,'公司披露净利润-1亿元，现金流-0.50亿元。')
    assert not validate_audit(rows,findings,result)
    changed=deepcopy(findings);changed[0]['text']='公司披露净利润1亿元，现金流-0.50亿元。'
    assert 'lost_numeric_information:I-a' in validate_audit(rows,changed,audit(rows,changed))


@pytest.mark.parametrize('text',[
    '公司2026年半年度报告披露注册资本462,525,643元，合并范围包括52家公司。',
    '公司2026年半年度报告披露累计发行股本462,525,643股，合并范围包括52家公司。',
])
def test_document_layout_does_not_excuse_a_missing_real_quantity_or_unit(text):
    rows=[record(text='--- PDF page 6 ---\n公司2026年半年度报告\n6 / 199\n'
                      '1. 公司概况：累计发行股本462,525,643股，注册资本462,525,643元。\n'
                      '2. 合并范围包括52家公司。')]
    findings,result=checked(rows,text)
    assert 'lost_numeric_information:I-a' in validate_audit(rows,findings,result)


@pytest.mark.parametrize('text',['2.1 万元','1.00万元','2026. 公司披露当年业务增长。',
                               '第23条规定公司应履行披露义务。','0','未知','False',
                               '(2)万元','（0）元','1.00 公司有明确经营记录。'])
def test_real_values_dates_and_legal_references_are_not_document_layout(text):
    row=record(text=text)
    assert semantic_source_text(row)==text


def test_hierarchical_company_heading_keeps_all_following_facts_and_original_ids():
    row=record(text='2.1 公司基本情况：公司成立于2010年，注册资本10万元。')
    props=native_propositions(row)
    assert props[0]['proposition_id']=='I-a-P1'
    assert props[0]['text']==row['text']
    assert props[0]['semantic_text']=='公司基本情况：公司成立于2010年，注册资本10万元。'
    findings,result=checked([row],'公司基本情况为成立于2010年，注册资本10万元。')
    assert not validate_audit([row],findings,result)


def test_actual_ratio_elsewhere_on_page_is_not_pagination():
    row=record(text='--- PDF page 6 ---\n公司2026年半年度报告\n6 / 199\n'
                    '公司披露产品合格率原值为：\n2 / 3')
    projected=semantic_source_text(row)
    assert '6 / 199' not in projected and '2 / 3' in projected


def test_bare_header_page_before_security_identifier_is_preserved_only_as_source_locator():
    native='--- PDF page 1 ---\n1\n证券代码：603288 公告编号：2026-008\n公司披露注册资本10万元。'
    row=record(text=native)
    assert '1' not in numeric_tokens(semantic_source_text(row))
    findings,result=checked([row],'证券代码603288、公告编号2026-008所载公司披露注册资本10万元。')
    assert not validate_audit([row],findings,result)


def test_a_real_value_before_an_explicit_unit_header_is_not_reclassified_as_page_number():
    native='--- PDF page 1 ---\n1\n单位：万元\n公司年度报告中的经营金额。'
    assert '1' in numeric_tokens(semantic_source_text(record(text=native)))


@pytest.mark.parametrize('native,body',[
    ('2） 权益法\n公司采用权益法核算。','权益法\n公司采用权益法核算。'),
    ('3、登记时间为2022年9月26日。','登记时间为2022年9月26日。'),
    ('2.华舟软件概述2.1公司简介华舟软件成立于1995年。','华舟软件概述   公司简介华舟软件成立于1995年。'),
])
def test_section_indices_can_be_omitted_without_losing_the_business_text(native,body):
    projected=semantic_source_text(record(text=native))
    assert ''.join(projected.split())==''.join(body.split())


def test_numbered_legal_document_folio_does_not_remove_a_real_business_identifier():
    row=record(text='公司注册资本10万元。\n8-1-68\n经营范围为软件开发。')
    row['provenance'][0]['source_title']='华舟软件补充法律意见书'
    assert '8-1-68' not in semantic_source_text(row)
    row['text']='公司合同号：\n8-1-68\n合同金额10万元。'
    assert '8-1-68' in semantic_source_text(row)


@pytest.mark.parametrize('value',['0','False','未知','2.1 万元','1. 公司概况：完整字段原值'])
def test_explicit_native_fields_never_use_the_layout_projection(value):
    row=record(text=value,field='原字段')
    assert semantic_source_text(row)==value


def test_locator_only_record_is_not_automatically_excused_as_retained():
    row=record(text='--- PDF page 6 ---')
    assert semantic_source_text(row)==row['text']
    findings,errors=parse_proposal({'findings':[{'finding_id':'p','text':'原件没有业务信息。',
        'information_ids':['I-a']}]},[row],6,OUTLINE[5][1][0])
    assert not errors
    assert 'lost_numeric_information:I-a' in validate_audit([row],findings,audit([row],findings))


def test_layout_flags_cannot_overrule_a_real_semantic_failure():
    rows=[record(text='--- PDF page 6 ---\n公司2026年半年度报告\n6 / 199\n'
                      '1. 公司计划新增产线，尚未获批。')]
    def invoke(role,prompt,trace):
        text='公司2026年半年度报告披露新增产线已获批。'
        if role=='公司交付正文编写':
            return json.dumps({'findings':[{'finding_id':'p','text':text,'information_ids':['I-a']}]},ensure_ascii=False)
        data=json.loads(prompt.split('资料：\n',1)[1]);result=audit(rows,data['findings'])
        result['criteria']['factual_support']=False;result['findings'][0]['status']='unsupported'
        result['issues']=['计划且尚未获批被错误写成已获批。']
        return json.dumps(result,ensure_ascii=False)
    result=build_editorial_package({'records':rows},OUTLINE,'任意公司',invoke,workers=1)
    assert result['diagnostic']['pending_information_ids']==['I-a'] and not result['findings']
