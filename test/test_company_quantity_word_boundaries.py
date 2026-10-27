"""A following verb is not a monetary denomination or a score unit."""
import pytest

from report_agents.company_editorial import numeric_tokens, prose_errors, new_numeric_tokens


@pytest.mark.parametrize('word', ['分别', '分別', '分配', '分属', '分屬'])
@pytest.mark.parametrize('gap', ['', '   \n'])
def test_following_verb_does_not_create_a_unit(word, gap):
    assert numeric_tokens('金额12.34' + gap + word + '不同项目。') == {'12.34'}


@pytest.mark.parametrize('text', ['成绩100分，分配结果另示。', '成绩100分分别列示。', '金额100分。'])
def test_actual_denomination_and_score_remain_required(text):
    assert '100分' in numeric_tokens(text)
    assert new_numeric_tokens('金额100元。', text) == {'100元'}


@pytest.mark.parametrize('native,output', [
    ('减：提取法定盈余公积 123,456.00   \n分配现金股利 9.00', '提取法定盈余公积123,456.00；分配现金股利9.00。'),
    ('偿还债务支付的现金 345,678.90 分配股利、利润或偿付利息支付的现金 1.00', '偿债现金345,678.90；另一项分配股利等现金1.00。'),
    ('本期投入0，累计投入2,091.43。', '本期投入0与累计投入2,091.43分属本期和累计口径。'),
])
def test_wrapped_table_rows_and_prose_keep_the_same_scalars(native, output):
    assert not new_numeric_tokens(output, native)
    row = {'text': native, 'context': {}, 'provenance': []}
    assert not prose_errors(output, [row])


@pytest.mark.parametrize('unit', ['百\n萬元', '百 万 元', '百\n万\n元'])
def test_exact_wrapped_million_yuan_spelling_is_quantity_equivalent(unit):
    native = '現金減少人民幣934.2 ' + unit + '。'
    assert numeric_tokens(native) == {'934.2百万元'}
    assert not new_numeric_tokens('現金減少人民幣934.2百萬元。', native)


@pytest.mark.parametrize('output', ['减少934.2万元。', '减少934.2百萟元。', '减少934.2百美元。', '减少934.20百万元。'])
def test_wrapping_equivalence_does_not_license_changed_scale_glyph_currency_or_precision(output):
    assert new_numeric_tokens(output, '减少934.2百\n萬元。')


def test_numbers_still_need_their_own_cited_record():
    own = {'text': '本项原值12.34，单位未载明。', 'context': {}, 'provenance': []}
    assert any('new_or_changed_number_unit' in e for e in prose_errors('本项12.34万元。', [own]))
