"""Neutral website-attributed release fixtures, not real company claims."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from report_agents.company_product_releases import product_release_rows
from report_agents.company_business import build_business_package,render_business,business_errors
from report_agents.company_report_agent import CompanyReportAgent

TARGET='青禾模型技术有限公司'


def source():
    return {'url':'https://example.test/news/','title':'研究与动态',
            'content':'动态 2026 年 9 月 10 日\n\n青禾 V4.1：多模态预览版\n\n青禾 V4.1 预览版正式发布，新增图像理解功能。\n\n动态 2026 年 11 月 1 日\n\n青禾 V5 正式版发布\n\n青禾 V5 正式发布。\n\n© 2026 '+TARGET+' 版权所有',
            'source_metadata':{'fetch_status':'done','content_kind':'original_page'}}


def test_dated_announcement_keeps_preview_self_attribution_and_does_not_claim_revenue():
    s=source();rows=product_release_rows(s,TARGET,'2026-10-20')
    assert len(rows)==1 and rows[0]['release_date']=='2026-09-10'
    assert '预览版' in rows[0]['release_description'] and rows[0]['evidence_quote'] in s['content']
    assert TARGET in rows[0]['owner_binding_quote'] and '不证明收入' in rows[0]['mode']


@pytest.mark.parametrize('change',['no_cutoff','bad_date','planned','other_owner','http','summary','rejected'])
def test_unbound_future_planned_and_discovery_materials_are_not_release_observations(change):
    s=deepcopy(source());cutoff='2026-10-20'
    if change=='no_cutoff':cutoff=''
    if change=='bad_date':s['content']=s['content'].replace('9 月 10 日','2 月 30 日')
    if change=='planned':s['content']=s['content'].replace('预览版正式发布','预览版预计发布')
    if change=='other_owner':s['content']=s['content'].replace(TARGET,'青禾模型服务有限公司')
    if change=='http':s['url']=s['url'].replace('https:','http:')
    if change=='summary':s['source_metadata']['content_kind']='search_summary'
    if change=='rejected':s['source_metadata']['entity_validation']='rejected'
    assert product_release_rows(s,TARGET,cutoff)==[]


def test_cleaner_explicit_exclusion_is_not_resurrected_by_a_copyright_footer():
    s=source();card={'evidence_id':'E-000000000001','source_url':s['url'],'source_title':s['title'],
                    'evidence_scope':'target_direct','eligible_for_report':False}
    p=build_business_package({'facts':[card]},TARGET,[s],as_of='2026-10-20')
    assert p['facts']==[]
    card['eligible_for_report']=True
    p=build_business_package({'facts':[card]},TARGET,[s],as_of='2026-10-20')
    assert len(p['facts'])==1 and p['facts'][0]['kind']=='product_release'
    text=render_business(p)
    assert '不当作已实现收入' in text and '署名不等于独立真实性/性能核验' in text
    assert business_errors(text,p)==[]


def test_clipped_auto_noise_card_stays_excluded_while_new_native_fields_bind_full_page_footer():
    s=source();card={'evidence_id':'E-000000000001','source_url':s['url'],'source_title':s['title'],
                    'evidence_scope':'noise','eligible_for_report':False,'claim_type':'source_excerpt',
                    'entity_match':'unknown','text_origin':'retrieved_content','fact':'导航及宽泛产品节选...[truncated]'}
    p=build_business_package({'facts':[card]},TARGET,[s],as_of='2026-10-20')
    assert len(p['facts'])==1 and p['facts'][0]['locator_recovery']
    assert p['facts'][0]['eligible_for_risk_scoring'] is False
    assert card['eligible_for_report'] is False and card['evidence_scope']=='noise'
    card['rejected_reason']='人工核验排除'
    assert build_business_package({'facts':[card]},TARGET,[s],as_of='2026-10-20')['facts']==[]


def test_production_summary_receives_the_admitted_business_release_fields():
    s=source();row=product_release_rows(s,TARGET,'2026-10-20')[0]
    row.update(evidence_id='E-000000000001',evidence_ids=['E-000000000001'],source_url=s['url'],evidence_scope='target_direct')
    project=SimpleNamespace(target_name=TARGET,title='企业研究',industry='模型技术服务',description='',sources=[s],
                            company_business_package={'facts':[row]})
    text=CompanyReportAgent()._write_summary(project,'{}',{},lambda *a:'',lambda *a,**k:None)
    assert '2026-09-10' in text and '预览版' in text and '不证明收入' in text
    assert project.company_summary_package['facts'][0]['summary_topic']=='business'
