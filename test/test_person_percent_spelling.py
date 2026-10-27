import pytest
from person_evidence import numbers
from person_text import numeric_literals


@pytest.mark.parametrize('source,literal',[('百分之二十五','25%'),('百分之五十','50%'),('百分之二十五点零八','25.08%'),('百分之零点五','0.5%'),('百分之一百','100%'),('百分之二\n十五','25%')])
def test_explicit_chinese_percentage_is_equal_spelling_without_changing_its_value(source,literal):
    assert numbers(source)==numbers(literal)
    assert numeric_literals(source)==literal


def test_different_percentage_or_ratio_or_unit_is_not_licensed():
    source='转让不超过百分之二十五，另有百分之五十的历史限制。'
    assert not numbers('26%')<=numbers(source)
    assert not numbers('0.25')<=numbers(source)
    assert not numbers('25')<=numbers(source)


def test_chinese_numeric_calendar_and_money_spelling_still_work():
    assert numbers('三十六个月及五十万元')==numbers('36个月及50万元')
