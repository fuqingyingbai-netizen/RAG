"""Neutral platform-roster fixtures, not live company evidence."""
from copy import deepcopy

import pytest

from report_agents.company_governance import build_governance_package
from report_agents.company_management import (
    registered_roster_rows, build_management_package, render_management,
    management_errors, latest_roles,
    platform_team_profiles,
)

TARGET='青禾模型技术有限公司'


def fixture():
    raw='| 企业名称 | '+TARGET+' |\n\n| 持股比例 | 姓名 | 职务 |\n| --- | --- | --- |\n| 待查 | 赵甲 | 经理,董事 |\n| 待查 | 钱乙 | 财务负责人 |'
    source={'url':'structured://qcc/fixture','content':raw,'title':TARGET+'主要人员',
            'created_at':'2026-10-20 10:00:00',
            'source_metadata':{'tool':'get_key_personnel','entity_validation':'verified','content_kind':'structured_data'}}
    card={'evidence_id':'E-000000000001','source_url':source['url'],'source_title':source['title'],
          'evidence_scope':'target_direct','eligible_for_report':True,'entity_match':'matched',
          'source_entity_validation':'verified','claim_type':'source_excerpt','fact':raw}
    clean={'facts':[card]}
    gov=build_governance_package(clean,TARGET,[source])
    return clean,source,gov


def test_registered_roster_reuses_native_fields_but_does_not_create_formal_current_jobs():
    clean,source,gov=fixture()
    p=build_management_package(clean,TARGET,[source],governance=gov)
    assert [(r['entity'],r['role']) for r in p['facts']]==[('赵甲','经理,董事'),('钱乙','财务负责人')]
    assert all(r['kind']=='registered_role' and r['as_of']=='' and r['period']=='' for r in p['facts'])
    assert all(r['temporal_basis']=='undated_platform_snapshot' for r in p['facts'])
    assert latest_roles(p['facts'])==[]
    text=render_management(p)
    assert '不将“财务负责人”直接改写为CFO' in text
    assert '数据基准日未载时不能按查询日认定仍在任' in text
    assert management_errors(text,p)==[]
    assert all(r['evidence_id']=='E-000000000001' for r in p['facts'])


@pytest.mark.parametrize('change',['wrong_subject','wrong_tool','unverified','related','ineligible','meeting'])
def test_registration_fallback_still_requires_exact_target_verified_tool_and_eligible_scope(change):
    _,source,gov=fixture();source=deepcopy(source);gov=deepcopy(gov)
    if change=='wrong_subject':source['content']=source['content'].replace(TARGET,'青禾模型服务有限公司')
    if change=='wrong_tool':source['source_metadata']['tool']='get_company_news'
    if change=='unverified':source['source_metadata']['entity_validation']='ambiguous'
    if change=='related':
        for row in gov['facts']:row['evidence_scope']='related_entity_context'
    if change=='ineligible':
        for row in gov['facts']:row['eligible_for_report']=False
    if change=='meeting':
        for row in gov['facts']:row['role']='董事会会议'
    assert registered_roster_rows(gov,[source],TARGET)==[]


def test_platform_data_date_is_not_replaced_with_query_date():
    _,source,gov=fixture()
    for row in gov['facts']:row['period']='2025-12-31'
    rows=registered_roster_rows(gov,[source],TARGET)
    assert all(r['period']=='2025-12-31' and r['as_of']=='' for r in rows)


def team_fixture():
    clean,source,_=fixture()
    source['source_metadata'].update(provider='xiniu',tool='get_company_info')
    source['content']='| 公司名称 | '+TARGET+' |\n\n| 职位 | 序号 | 姓名 | 教育经历 | 介绍 |\n| --- | --- | --- | --- | --- |\n| 创始人 | 1 | 孙丙 | 青禾大学 | 平台称曾创办研究团队。 |\n| 核心技术人员（已离职） | 2 | 李丁 | 远山学院 | 平台所载历史技术经历。 |'
    return clean,source


def test_platform_team_profile_keeps_departure_qualifier_and_cannot_become_formal_role():
    clean,source=team_fixture()
    p=build_management_package(clean,TARGET,[source])
    assert len(p['facts'])==2 and all(r['kind']=='platform_team_profile' for r in p['facts'])
    assert p['facts'][1]['role']=='核心技术人员（已离职）'
    assert latest_roles(p['facts'])==[]
    assert all(r['as_of']=='' and r['period']=='' for r in p['facts'])
    text=render_management(p)
    assert '未经独立履历核验' in text and '不推定具体离职日期或团队流失率' in text
    assert management_errors(text,p)==[]


@pytest.mark.parametrize('change',['wrong_subject','wrong_provider','wrong_tool','ineligible','related'])
def test_platform_biography_cannot_bypass_source_and_card_subject_guards(change):
    clean,source=team_fixture()
    if change=='wrong_subject':source['content']=source['content'].replace(TARGET,'青禾模型服务有限公司')
    if change=='wrong_provider':source['source_metadata']['provider']='web'
    if change=='wrong_tool':source['source_metadata']['tool']='get_company_news'
    if change=='ineligible':clean['facts'][0]['eligible_for_report']=False
    if change=='related':clean['facts'][0]['evidence_scope']='related_entity_context'
    assert platform_team_profiles(clean,[source],TARGET)==[]
