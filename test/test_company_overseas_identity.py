"""A foreign public filing remains distinct from a professional registry hit."""
from copy import deepcopy

import pytest

from report_agents.company_overseas_identity import overseas_filing_identity
from test_company_fiscal_statements import statement_source,TARGET


def source():
    s=statement_source()
    s['source_metadata']['document_pages'][0]['text']=TARGET+'\n（於開曼群島註冊成立的有限責任公司）\n截至2026年3月31日止財務年度的20-F表格年度報告。'
    s['content']='\n\n'.join(p['text'] for p in s['source_metadata']['document_pages'])
    return s


def test_official_foreign_issuer_heading_and_three_native_consolidated_fields_allow_separate_identity_route():
    p=overseas_filing_identity([source()],TARGET)
    assert p['route']=='official_overseas_filing' and p['jurisdiction']=='开曼群岛'
    assert p['financial_fields_verified']==3 and p['financial_physical_pages']==[225,232]
    assert '不是专业数据库命中' in p['boundary'] and '開曼群島' in p['identity_quote']


@pytest.mark.parametrize('change',['lookalike_host','subsidiary_issuer','incidental_country','missing_cash','search_summary','rejected'])
def test_news_mirrors_wrong_issuers_and_unverified_fields_cannot_bypass_the_source_gate(change):
    s=deepcopy(source())
    if change=='lookalike_host':s['url']='https://hkexnews.hk.example.test/issuer.pdf'
    if change=='subsidiary_issuer':s['content']=s['content'].replace(TARGET,'星河子公司有限公司')
    if change=='incidental_country':s['content']=s['content'].replace('（於開曼群島註冊成立的有限責任公司）','子公司位於開曼群島。')
    if change=='missing_cash':
        s['source_metadata']['document_pages']=[p for p in s['source_metadata']['document_pages'] if p['page']!=232]
    if change=='search_summary':s['source_metadata']['content_kind']='search_summary'
    if change=='rejected':s['source_metadata']['entity_validation']='rejected'
    assert overseas_filing_identity([s],TARGET) is None
