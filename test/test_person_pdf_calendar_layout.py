import json,pytest
from person_source_boundaries import source_context_errors
from person_text import calendar_layout
from person_evidence import validate_model_claims

@pytest.mark.parametrize('raw',['2 0 0 8年1 2月3日','2 0 0 8 年 1 2月 3日','2008 年12月3日','2 0 0 8年1 2月'])
def test_explicit_pdf_calendar_components_can_have_character_spacing(raw):
    day='3日' if '日' in raw else ''
    assert calendar_layout(raw)=='2008年12月'+day
    source='资料载'+raw+'，董事会通过议案。'
    original=source
    assert 'unsupported_date_combination' not in source_context_errors('2008年12月'+day+'董事会通过议案。',[{'fact':source}])
    assert source==original

@pytest.mark.parametrize('text',['2008年12月4日通过议案。','2008年11月3日通过议案。','2009年12月3日通过议案。'])
def test_changed_calendar_component_is_still_blocked(text):
    assert 'unsupported_date_combination' in source_context_errors(text,[{'fact':'2 0 0 8年1 2月3日通过议案。'}])

def test_separate_dates_never_supply_a_synthetic_combination():
    assert 'unsupported_date_combination' in source_context_errors('2008年12月3日通过议案。',[{'fact':'2 0 0 8年1 2月讨论；2 0 0 9年3月3日通过。'}])

def test_spaced_year_month_does_not_promote_a_following_percentage_to_a_day():
    assert 'unsupported_date_combination' not in source_context_errors('2008年12月5%以上股东承诺。',[{'fact':'2 0 0 8年1 2月，5%以上股东承诺。'}])
    assert 'unsupported_date_combination' in source_context_errors('2008年12月5日股东承诺。',[{'fact':'2 0 0 8年1 2月，5%以上股东承诺。'}])
