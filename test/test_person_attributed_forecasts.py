import pytest
from person_records import comparison_errors


def source():
    return {'evidence_id':'E-PFORECASTONE','subject':'林知远','subject_scope':'person',
        'source_url':'https://fixture.invalid/speech',
        'fact':'林知远在2022年度股东会上表示，展望未来三到五年，公司都将保持持续增长。他表示，预期到2034年，公司将获得很大的增长。'}


@pytest.mark.parametrize('text',['其在2022年度股东会上预期未来三到五年持续增长、2034年获得很大增长。',
    '来源称其在股东会上预期未来三到五年持续增长。'])
def test_attributed_matching_forecast_is_not_a_new_arithmetic_comparison(text):
    assert comparison_errors(text,[source()])==[]


def test_a_quoted_speakers_we_is_not_the_report_authors_new_forecast():
    f={**source(),'fact':source()['fact'].replace('公司','我们公司')}
    assert comparison_errors('其表示：我们公司未来三到五年将保持持续增长。',[f])==[]


@pytest.mark.parametrize('text',['公司未来三到五年持续增长。',
    '本报告预计公司未来三到五年持续增长。',
    '其预期未来三到五年持续增长；由此可见其能力高于同行。',
    '其预期到2040年公司持续增长。',
    '其预期未来三到五年利润持续增长。',
    '其表示2034年已经实现持续增长。',
    '其预期未来三到五年不会增长。'])
def test_new_inference_mismatched_horizon_metric_or_achieved_result_is_still_checked(text):
    assert comparison_errors(text,[source()])


def test_a_source_question_does_not_establish_a_positive_forecast():
    f={**source(),'fact':'林知远讨论是否预期未来三到五年公司会增长，未给出答案。'}
    assert comparison_errors('其预期未来三到五年公司将增长。',[f])
