"""Document names may identify a source without inventing business figures."""
from copy import deepcopy
import pytest
from report_agents.company_editorial import parse_proposal
from test_company_editorial import record,OUTLINE


def parse(row,text):
    return parse_proposal({'findings':[{'finding_id':'p','text':text,'information_ids':[row['information_id']]}]},
                          [row],2,OUTLINE[1][1][0])


@pytest.mark.parametrize('text',[
    '平台转载的、标注为青禾食品2022年半年度报告的文本称，公司由有限责任公司整体变更设立。',
    '平台转载《青禾食品2022年半年度报告》记载，公司由有限责任公司整体变更设立。',
    '青禾食品2022年半年度报告载明，公司由有限责任公司整体变更设立。',
])
def test_literal_short_report_identity_preserves_attribution_and_original_input(text):
    row=record(text='公司由有限责任公司整体变更设立。')
    row['provenance'][0]['source_title']='青禾食品2022年半年度报告(146页).PDF_报告平台'
    before=deepcopy(row)
    assert not parse(row,text)[1]
    assert row==before


def test_ordinal_meeting_notice_used_as_a_bound_document_name():
    row=record(text='联系地址为文沙路16号，邮政编码528000。')
    row['provenance'][0]['source_title']='青禾食品股份有限公司 第六届监事会第三次会议决议公告_上市_市场'
    assert not parse(row,'公司第六届监事会第三次会议决议公告载明，联系地址为文沙路16号，邮政编码528000。')[1]


@pytest.mark.parametrize('text',[
    '平台转载《青禾食品2023年半年度报告》记载，公司营业收入100元。',
    '公司2022年营业收入100元。',
    '《青禾食品2022年半年度报告》披露，公司2022年营业收入100元。',
    '《青禾食品2022年半年度报告》披露，公司持有2022股，营业收入100元。',
])
def test_title_cannot_authorize_unknown_titles_operating_periods_or_company_quantities(text):
    row=record(text='公司营业收入100元，期间未载。')
    row['provenance'][0]['source_title']='青禾食品2022年半年度报告(146页).PDF_报告平台'
    assert parse(row,text)[1]


def test_title_from_an_uncited_row_cannot_authorize_a_document_identity():
    row=record(text='公司完成产品交付。');row['provenance'][0]['source_title']='另一份披露'
    assert parse(row,'《青禾食品2022年半年度报告》载明，公司完成产品交付。')[1]


def test_ambiguous_native_table_still_cannot_gain_an_inferred_share_unit():
    row=record(text='单位：元 币种：人民币\n股份总数 462,525,643.00 653,650.00 463,179,293.00')
    assert parse(row,'该表本次变动653,650.00股。')[1]


def test_misordered_table_does_not_license_reconstructing_a_deadline_from_common_knowledge():
    row=record(text='公司将在法定代表人辞任之日起 日内确定新的法定代表 30 人。')
    assert parse(row,'公司将在法定代表人辞任之日起30日内确定新的法定代表人。')[1]
