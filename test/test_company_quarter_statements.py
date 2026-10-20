"""Neutral quarterly fixtures; no live issuer figures or aliases."""
from copy import deepcopy
import pytest
from report_agents.company_assessment import financial_observations, build_assessment_package, METRICS
from report_agents.company_financial_statements import quarter_report_period
from report_agents.company_diligence import issuer_heading
from report_agents.company_risk_register import filing_cutoff

TARGET='星河集团控股有限公司'

def source():
    header='截至6月30日止三个月\n2025 2026\n人民币 人民币 美元\n（以百万计，每股数据除外）\n'
    pages=[{'page':1,'text':'季度业绩公告'},
           {'page':2,'text':'中国香港，2026年8月20日 – '+TARGET+'（「星河集团」）今日公布截至2026年6月30日止季度业绩。'},
           {'page':19,'text':TARGET+'\n未经审计合并利润表\n'+header+'收入 100 120 17\n归属于星河集团股东的净利润 20 15 2\n归属于普通股股东的净利润 24 18 3'},
           {'page':22,'text':TARGET+'\n未经审计简明合并现金流量表\n'+header+'经营活动产生的现金流量净额 50 55 8'}]
    return {'title':'季度业绩公告','url':'https://www.hkexnews.hk/reports/quarter.pdf',
            'content':'\n\n'.join(p['text'] for p in pages),
            'source_metadata':{'content_kind':'pdf_text_extracted','fetch_status':'done','document_pages':pages}}

def extract(s):
    return financial_observations(s,{'entity':TARGET,'evidence_id':'E-000000000001','source_url':s['url']})

def test_declared_alias_local_issuer_and_quarter_rmb_columns_are_bound():
    s=source();rows=extract(s)
    assert [r['value'] for r in rows]==['120','15','55']
    assert [r['previous_value'] for r in rows]==['100','20','50']
    assert all(r['period_kind']=='quarterly' and r['unit']=='百万元' and r['audit_status']=='未经审计' for r in rows)
    assert all(r['publication_date']=='2026-08-20' and '上年同季' in r['yoy_basis'] for r in rows)
    assert issuer_heading(s['source_metadata']['document_pages'],TARGET)
    assert filing_cutoff(s['source_metadata']['document_pages'])=='2026-06-30'

@pytest.mark.parametrize('change',['issuer','local_issuer','month','currency','duration'])
def test_ambiguous_or_other_issuer_quarter_is_not_admitted(change):
    s=source()
    for p in s['source_metadata']['document_pages']:
        if change=='issuer' and p['page']==2:p['text']=p['text'].replace(TARGET,'远山集团控股有限公司')
        if change=='local_issuer' and p['page']>=19:p['text']=p['text'].replace(TARGET,'远山集团控股有限公司')
        if change=='month' and p['page']>=19:p['text']=p['text'].replace('6月30日','3月31日')
        if change=='currency':p['text']=p['text'].replace('人民币 人民币 美元','人民币 美元 人民币')
        if change=='duration' and p['page']>=19:p['text']=p['text'].replace('三个月','六个月')
    assert extract(s)==[]

def test_undeclared_alias_and_ordinary_share_profit_cannot_fill_owner_profit():
    s=source();s['source_metadata']['document_pages'][1]['text']=s['source_metadata']['document_pages'][1]['text'].replace('（「星河集团」）','')
    assert not any(r['metric']==METRICS[1] for r in extract(s))

def test_whole_assessment_admits_new_quarter_only_after_publication():
    s=source();clean={'facts':[{'evidence_id':'E-000000000001','source_url':s['url'],'fact':'原件定位','is_noise':False,'evidence_scope':'target_direct'}]}
    before=build_assessment_package(clean,TARGET,[s],intake={'as_of_date':'2026-08-19'})
    after=build_assessment_package(clean,TARGET,[s],intake={'as_of_date':'2026-10-20'})
    assert before['financial_observations']==[]
    assert len(after['financial_observations'])==3
    assert all(r['cutoff']=='2026-06-30' for r in after['financial_observations'])
