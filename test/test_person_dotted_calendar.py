"""Offline date-spelling regressions; no real model acceptance is claimed."""
import json,pytest
from person_text import source_bound_calendar_notation
from person_evidence import validate_model_claims
from person_claim_repair import numeric_rejection_context


def fixture():
    fact={'evidence_id':'E-PDATEFIXTURE','fact':'来源载陈安于2006年1月1日担任董事，于2009年12月31日离任。',
          'analysis_allowed':True,'subject_scope':'person','source_url':'https://fixture.invalid/date'}
    package={'chapter':3,'title':'任职','facts':[fact],'writing_contract':'evidence_selection_v2'}
    return fact,package


@pytest.mark.parametrize('spelling',['2006.1.1','2006.01.01','２００６．１．１'])
def test_exact_explicit_cited_date_spelling_passes_without_modifying_prose_or_original(spelling):
    fact,p=fixture();original=fact['fact'];text=f'来源载陈安于{spelling}担任董事。'
    claims,errors=validate_model_claims(json.dumps({'claims':[{'analysis':text,'evidence_ids':[fact['evidence_id']]}]},ensure_ascii=False),p)
    assert not errors and claims[0]['analysis']==text and fact['fact']==original
    assert numeric_rejection_context(claims[0],[fact])['unmatched_numeric_literals']==[]


@pytest.mark.parametrize('spelling',['2006.1.2','2006.2.1','2007.1.1','2006.2.29','2006.13.1'])
def test_changed_or_invalid_dotted_date_remains_rejected(spelling):
    fact,p=fixture();text=f'来源载陈安于{spelling}担任董事。'
    claims,errors=validate_model_claims(json.dumps({'claims':[{'analysis':text,'evidence_ids':[fact['evidence_id']]}]},ensure_ascii=False),p)
    assert errors and not claims[0]['analysis']


@pytest.mark.parametrize('text',['版本2006.1.1','v2006.1.1','2006.1万元','1.2.3','2006.1.1.2','2006.1.1版','型号2006.1.1'])
def test_versions_decimals_and_long_identifiers_are_not_reinterpreted(text):
    assert source_bound_calendar_notation(text,['2006年1月1日'])==text


def test_incomplete_or_cross_record_components_do_not_license_a_complete_date():
    assert source_bound_calendar_notation('2006.1.1',['2006年1月','1日'])=='2006.1.1'
    assert source_bound_calendar_notation('2006.1.1',['2006年','1月1日'])=='2006.1.1'


@pytest.mark.parametrize('source',['2 0 0 8年0 2月2 9日','2008\n年 02 月 29 日'])
def test_source_calendar_pdf_spacing_and_leap_date_are_comparison_only(source):
    original=source
    assert source_bound_calendar_notation('2008.02.29',[source])=='2008年2月29日'
    assert source==original


def test_coverage_compares_the_same_explicit_date_without_fictitious_decimal_gaps():
    from person_content_acceptance import _check_one
    fact,p=fixture();old=[{'analysis':'来源载陈安于2006.1.1担任董事。','evidence_ids':[fact['evidence_id']]}]
    active=[{'analysis':'来源载陈安于2006年1月1日担任董事。','evidence_ids':[fact['evidence_id']]}]
    reply={'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[0],'gaps':[],'reason':'同一完整日期与职务已保留'}]}
    result=_check_one(p,active,old,lambda *a:json.dumps(reply,ensure_ascii=False),None)
    assert result['status']=='passed' and not result['items'][0]['missing_numeric_anchors']
