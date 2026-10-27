import json
import pytest
from person_source_boundaries import source_context_errors
from person_evidence import validate_model_claims


@pytest.mark.parametrize('quantity',['5%','5.5%','10名','50万元','1000万元'])
def test_quantity_immediately_after_a_month_is_not_an_invented_day(quantity):
    source=f'2009年9月，涉及{quantity}的公司历史披露。'
    assert 'unsupported_date_combination' not in source_context_errors(f'2009年9月{quantity}的公司历史披露。',[{'fact':source}])


def test_explicit_invented_day_is_still_rejected_even_with_same_percentage_in_source():
    source='2009年9月，持有5%以上股份的股东签署《不竞争承诺》。'
    assert 'unsupported_date_combination' in source_context_errors('2009年9月5日5%以上股东签署《不竞争承诺》。',[{'fact':source}])
    assert 'unsupported_date_combination' in source_context_errors('2009年9月5签署《不竞争承诺》。',[{'fact':source}])


def test_real_explicit_and_iso_calendar_days_still_compare_at_day_precision():
    assert 'unsupported_date_combination' not in source_context_errors('2009年9月5日签署。',[{'fact':'2009-09-05签署。'}])
    assert 'unsupported_date_combination' in source_context_errors('2009年9月6日签署。',[{'fact':'2009-09-05签署。'}])


def test_actual_condensed_shareholder_condition_passes_whole_claim_validation():
    fact={'evidence_id':'E-PMONTHPERCENT','fact':'2009年9月，持有本公司5%以上股份的股东签署《不竞争承诺》。',
        'source_url':'https://fixture.invalid/legal','subject_scope':'person','analysis_allowed':True}
    p={'chapter':3,'facts':[fact],'research_facts':[fact],'writing_contract':'evidence_selection_v2'}
    text='2009年9月5%以上股东签署《不竞争承诺》。'
    rows,errors=validate_model_claims(json.dumps({'claims':[{'analysis':text,'evidence_ids':[fact['evidence_id']]}]}),p)
    assert not errors and rows[0]['analysis']==text
