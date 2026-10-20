"""Neutral statement fixtures; live original checks are retained separately."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from report_agents.company_assessment import financial_observations, _financial_scores, METRICS
from report_agents.company_diligence import period_of
from report_agents.company_governance import _filing_period, _primary_filing
from report_agents.company_risk_register import filing_cutoff
from report_agents.company_summary import _chapter_summary_cards, fallback_company_summary, summary_errors, _numbers

TARGET = '星河控股有限公司'


def statement_source():
    header = '截至3月31日止年度\n2024 2025 2026\n人民幣 人民幣 人民幣 美元\n（附註2(a)）\n（百萬元）\n附註\n'
    pages = [
        {'page': 1, 'text': TARGET+'\n海外監管公告\n截至2026年3月31日止財務年度的20-F表格年度報告。'},
        {'page': 2, 'text': TARGET+'\n2026財年20-F表格年度報告'},
        {'page': 18, 'text': '母公司及主要VIE實體調節表\n母公司 主要VIE 合併總額\n經營活動產生的現金流量淨額 999 888 150'},
        {'page': 225, 'text': TARGET+'\n合併利潤表\n'+header+
         '收入 5, 25 900 1,000 1,100 160\n淨利潤 80 90 100 15\n'
         '歸屬於'+TARGET+'\n股東的淨利潤 60 70 80 11\n'
         '歸屬於普通股股東的淨利潤 61 73 87 12'},
        {'page': 232, 'text': TARGET+'\n合併現金流量表\n'+header+
         '將淨利潤調整為經營活動產生的現金流量淨額：\n'
         '經營活動產生的現金流量淨額 100 200 150 22'},
    ]
    return {'title':'海外監管公告','url':'https://www.hkexnews.hk/reports/fiscal.pdf',
            'content':'\n\n'.join(p['text'] for p in pages),
            'source_metadata':{'content_kind':'pdf_text_extracted','fetch_status':'done','document_pages':pages}}


def extract(source):
    return financial_observations(source, {'entity':TARGET,'evidence_id':'E-000000000001',
        'evidence_ids':['E-000000000001'],'source_url':source['url'],'source_title':source['title']})


def test_explicit_march_fiscal_year_is_shared_by_all_period_readers():
    s=statement_source();pages=s['source_metadata']['document_pages']
    assert filing_cutoff(pages)=='2026-03-31'
    assert _filing_period(s)==period_of(s,pages)=='2026财年年度报告（截至2026-03-31）'
    assert _primary_filing(s,TARGET)


def test_future_guidance_later_in_cover_text_does_not_relabel_filed_fiscal_year():
    from report_agents.company_financial_statements import fiscal_report_period
    s=statement_source()
    text=s['content']+'\n展望截至2027年3月31日止財務年度，投資計劃仍待核實。'
    assert fiscal_report_period(text)['cutoff']=='2026-03-31'


def test_a_prospectus_reference_to_an_annual_period_is_not_a_fiscal_report_cover():
    from report_agents.company_financial_statements import fiscal_report_period
    assert fiscal_report_period(TARGET+'首次公开发行招股说明书\n引用年度报告中截至2026年3月31日止财务年度数据。') is None


def test_consolidated_rmb_columns_keep_owners_profit_not_ordinary_or_vie_values():
    rows=extract(statement_source());by={r['metric']:r for r in rows}
    assert [by[m]['value'] for m in METRICS]==['1,100','80','150']
    assert [by[m]['previous_value'] for m in METRICS]==['1,000','70','200']
    assert [by[m]['page'] for m in METRICS]==[225,225,232]
    assert all(r['currency']=='人民币' and r['unit']=='百万元' for r in rows)
    assert all(r['statement_scope']=='consolidated_group' for r in rows)
    assert '歸屬於' in by[METRICS[1]]['source_metric'] and '普通股' not in by[METRICS[1]]['source_metric']
    assert '歸屬於' in by[METRICS[1]]['evidence_quote']


@pytest.mark.parametrize('change', ['unit','currency','year','quarter','scope','month'])
def test_ambiguous_headers_never_bind_statement_amounts(change):
    s=statement_source()
    for p in s['source_metadata']['document_pages']:
        if p['page'] not in {225,232}:continue
        text=p['text']
        if change=='unit':text=text.replace('（百萬元）','（單位未載）')
        if change=='currency':text=text.replace('人民幣 人民幣 人民幣 美元','人民幣 美元 人民幣 美元')
        if change=='year':text=text.replace('2024 2025 2026','2023 2024 2025')
        if change=='quarter':text=text.replace('止年度','止三個月')
        if change=='month':text=text.replace('截至3月31日止年度','截至9月30日止年度')
        if change=='scope':text=text.replace('合併利潤表','母公司及主要VIE實體調節表').replace('合併現金流量表','母公司及主要VIE實體調節表')
        p['text']=text
    assert extract(s)==[]


def test_ordinary_share_profit_does_not_fill_missing_company_owner_profit():
    s=statement_source();p=s['source_metadata']['document_pages'][3]
    p['text']=p['text'].replace('歸屬於'+TARGET+'\n股東的淨利潤 60 70 80 11\n','')
    rows=extract(s)
    assert not any(r['metric']==METRICS[1] for r in rows)
    assert _financial_scores(rows)[1]['score'] is None


def test_wrong_issuer_cover_and_parent_comention_cannot_supply_financials():
    s=statement_source()
    s['source_metadata']['document_pages'][0]['text']='遠山科技有限公司\n2026年年度報告\n母公司為'+TARGET+'。'
    s['source_metadata']['document_pages'][1]['text']='遠山科技有限公司\n2026財年20-F表格年度報告'
    assert extract(s)==[]


def test_negative_parentheses_keep_their_sign_and_do_not_become_positive_cash():
    s=statement_source();p=s['source_metadata']['document_pages'][-1]
    p['text']=p['text'].replace('100 200 150 22','100 200 (150) (22)')
    rows=extract(s)
    assert rows[-1]['value']=='-150' and _financial_scores(rows)[1]['score']==2


def test_financial_pair_and_same_date_conflicts_include_currency():
    rows=extract(statement_source())
    rows[-1]['currency']='美元'
    assert _financial_scores(rows)[1]['score'] is None
    extra=deepcopy(rows[0]);extra['currency']='美元'
    assert _financial_scores(rows+[extra])[0]['score'] is None


def test_fiscal_summary_keeps_original_names_currency_period_and_calculation_basis():
    rows=_chapter_summary_cards({'assessment':{'financial_observations':extract(statement_source())}})
    assert all('人民币' in r['fact'] and '截至2026-03-31' in r['fact'] for r in rows)
    assert all('据原表同币种计算' in r['fact'] for r in rows)
    for r in rows:r.update(source_kind='checked_chapter_field',summary_topic='financial')
    p={'facts':rows};text=fallback_company_summary(SimpleNamespace(target_name=TARGET),p)
    assert summary_errors(text,p)==[]
    assert summary_errors(text.replace('人民币','美元'),p)


def test_million_and_thousand_units_are_compared_as_amounts_not_plain_numbers():
    assert _numbers('收入1百万元')==_numbers('收入100万元')==_numbers('收入1,000,000元')
    assert _numbers('收入1千元')==_numbers('收入1000元')
    assert _numbers('收入1百万元')!=_numbers('收入1万元')
