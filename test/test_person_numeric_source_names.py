import json
import pytest
from person_evidence import validate_model_claims
from person_claim_repair import numeric_rejection_context
from person_text import without_verified_numeric_source_names


def fact(brand='21经济网'):
    return {'evidence_id':'E-PMEDIANAME001','fact':'林知远于2018年任董事。','subject':'林知远',
        'subject_scope':'person','analysis_allowed':True,'source_title':'人物报道 - '+brand,
        'source_url':'https://fixture.invalid/article'}


def rejected(text,f):
    return validate_model_claims(json.dumps({'claims':[{'analysis':text,'evidence_ids':[f['evidence_id']]}]},ensure_ascii=False),
        {'chapter':5,'facts':[f],'writing_contract':'evidence_selection_v2'})[1]


@pytest.mark.parametrize('brand',['21经济网','36氪','21世纪经济报道'])
def test_verified_numeric_media_attribution_is_not_a_new_factual_quantity(brand):
    assert not rejected('据'+brand+'报道，其于2018年任董事。',fact(brand))


def test_explicit_publisher_metadata_also_binds_the_source_name():
    f={**fact(),'source_title':'人物报道','source_publisher':'21经济网'}
    assert not rejected('21经济网载其2018年任董事。',f)


@pytest.mark.parametrize('text',['99经济网载其2018年任董事。',
    '121经济网载其2018年任董事。','2025年21经济网载其2018年任董事。',
    '21经济网称其有99名员工。'])
def test_unknown_names_dates_and_quantities_remain_checked(text):
    assert 'unsupported_analysis' in rejected(text,fact())


def test_article_title_numbers_do_not_license_new_dates_or_amounts():
    f={**fact(),'source_title':'2025年99亿元话题 - 21经济网'}
    assert 'unsupported_analysis' in rejected('2025年21经济网载其投资99亿元。',f)


def test_domain_alone_does_not_prove_a_numeric_publisher_name():
    f={**fact(),'source_title':'人物报道','source_url':'https://www.21jingji.com/example'}
    assert 'unsupported_analysis' in rejected('21经济网载其2018年任董事。',f)


def test_diagnostics_keep_the_real_mismatch_without_accusing_the_verified_name():
    f=fact();row={'analysis':'21经济网称其有99名员工。','evidence_ids':[f['evidence_id']]}
    assert numeric_rejection_context(row,[f])['unmatched_numeric_literals']==['99']


def test_only_the_source_name_occurrence_is_removed_not_a_later_factual_number():
    text='21经济网称其有21名员工。'
    assert without_verified_numeric_source_names(text,[fact()])=='称其有21名员工。'
