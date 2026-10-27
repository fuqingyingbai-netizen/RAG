import pytest
from person_source_boundaries import annual_meeting_year_errors


def source(text='6月9日，公司召开2022年度股东会。林知远表示展望未来三到五年持续增长。'):
    return {'fact':text,'subject':'林知远','source_url':'https://fixture.invalid/annual-meeting'}


@pytest.mark.parametrize('text',['2022年股东会其称未来三到五年持续增长。',
    '其于2022年6月9日在股东会上表示未来三到五年持续增长。'])
def test_reporting_year_does_not_establish_calendar_year(text):
    assert annual_meeting_year_errors(text,[source()])==['annual_meeting_reporting_year_as_event_year']


@pytest.mark.parametrize('text',['2022年度股东会其称未来三到五年持续增长。',
    '其在股东会上预期未来三到五年持续增长。',
    '不能据2022年度名称认定2022年召开股东会。'])
def test_exact_annual_label_or_unknown_occurrence_year_is_allowed(text):
    assert not annual_meeting_year_errors(text,[source()])


def test_explicit_same_meeting_calendar_year_can_be_used():
    assert not annual_meeting_year_errors('其于2022年股东会表示未来三到五年持续增长。',
        [source('2022年6月9日，公司召开2022年度股东会。林知远预期未来三到五年持续增长。')])


def test_same_document_separate_date_passage_remains_usable():
    assert not annual_meeting_year_errors('其于2022年股东会表示未来三到五年持续增长。',
        [source(),source('本次股东会于2022年6月9日召开。')])


def test_separately_cited_same_subject_same_annual_meeting_with_explicit_date():
    dated={**source('2022年6月9日，公司召开2022年度股东会。'),'source_url':'https://fixture.invalid/other'}
    assert not annual_meeting_year_errors('其在2022年股东会上发言。',[source(),dated])


def test_a_nearby_profit_year_does_not_date_the_annual_meeting():
    assert annual_meeting_year_errors('其在2022年股东会上发言。',
        [source('2022年利润增长，公司召开2022年度股东会。')])


@pytest.mark.parametrize('event',['董事会','业绩说明会'])
def test_other_meeting_names_and_other_years_use_the_same_rule(event):
    assert annual_meeting_year_errors('2019年'+event+'讨论预算。',[source('公司召开2019年度'+event+'。')])
