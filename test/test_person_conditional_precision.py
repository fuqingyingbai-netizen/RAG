import pytest
from person_source_boundaries import conditional_contribution_errors


@pytest.mark.parametrize('text',['2012—2014社保未披露实际缴纳金额。',
    '2012—2014社保未受处罚且已按时足额缴纳。',
    '2012—2014未按期披露社保缴纳金额。'])
def test_negation_of_disclosure_or_penalties_does_not_assert_nonpayment(text):
    f={'fact':'林知远承诺：如发行人2012年1月1日至2014年12月31日未为员工按时足额缴纳社会保险金而受损，则承担责任。'}
    assert conditional_contribution_errors(text,[f])==[]


def test_nonpayment_with_an_employee_object_still_requires_the_condition():
    f={'fact':'林知远承诺：如发行人2012年1月1日至2014年12月31日未为员工按时足额缴纳社会保险金而受损，则承担责任。'}
    assert conditional_contribution_errors('2012—2014未为员工缴纳社保。',[f])==['conditional_contribution_commitment_as_event']
