from copy import deepcopy

import pytest

from report_agents.company_regulatory import regulatory_records
from report_agents.company_judicial import build_judicial_package,render_judicial
from report_agents.company_risk_register import build_risk_register,render_risk_register

TARGET='青禾网络科技有限公司'
URL='https://www.samr.gov.cn/xw/2023/original.html'


def penalty(target=TARGET):
    return (target+'行政处罚\n\n发布时间：2021-04-10 09:00 信息来源：市场监管总局\n\n'
        '2020年12月，市场监管总局对'+target+'（以下简称青禾集团）立案调查。\n\n'
        '根据相关规定，2021年4月10日，市场监管总局依法作出行政处罚决定，责令青禾集团停止违法行为，'
        '并处以其2019年销售额4%的罚款，计12.28亿元。\n\n附件：国市监处〔2021〕28号')


def fixture(raw=None,url=URL,**metadata):
    raw=raw or penalty()
    s={'url':url,'title':TARGET+'监管公告','content':raw,'source_metadata':{'content_kind':'full_text',**metadata}}
    c={'source_url':url,'source_title':s['title'],'evidence_id':'E-000000000001',
       'fact':TARGET+'原件定位。','claim_type':'source_excerpt','evidence_scope':'target_direct'}
    return c,s


def test_original_decision_uses_action_date_not_url_year_and_preserves_amount_quote():
    c,s=fixture();before=deepcopy(s);rows=regulatory_records(s,TARGET,c)
    assert len(rows)==1
    r=rows[0]
    assert r['date']=='2021-04-10' and r['publication_date']=='2021-04-10'
    assert r['penalty_amount_text']=='12.28亿元' and r['decision_id']=='国市监处〔2021〕28号'
    assert r['fact'] in s['content'] and s==before


@pytest.mark.parametrize('change',[
    {'url':'https://news.example.test/republished'},
    {'source_metadata':{'content_kind':'search_summary'}},
    {'source_metadata':{'entity_validation':'rejected'}},
    {'source_metadata':{'fetch_status':'failed'}},
])
def test_republication_summary_and_rejected_fetches_are_not_regulator_originals(change):
    c,s=fixture();s.update(change)
    assert regulatory_records(s,TARGET,c)==[]


def test_parent_comention_does_not_transfer_a_childs_penalty():
    c,s=fixture(penalty('青禾网络技术有限公司')+'\n\n其股东是'+TARGET+'。')
    assert regulatory_records(s,TARGET,c)==[]


def test_regulator_domain_does_not_assign_a_local_agencys_decision_to_the_national_publisher():
    c,s=fixture(penalty().replace('市场监管总局依法作出','某省市场监管局依法作出'))
    assert regulatory_records(s,TARGET,c)==[]


def test_hypothetical_risk_and_proposed_penalty_are_not_decisions():
    c,s=fixture(penalty().replace('依法作出行政处罚决定','拟作出行政处罚决定'))
    assert regulatory_records(s,TARGET,c)==[]
    c,s=fixture(penalty().replace('依法作出行政处罚决定','可能作出行政处罚决定'))
    assert regulatory_records(s,TARGET,c)==[]


def test_month_only_historical_date_is_not_replaced_with_current_publication_day():
    raw=penalty().replace('发布时间：2021-04-10','发布时间：2024-08-30').replace('2021年4月10日','2021年4月')
    c,s=fixture(raw)
    assert regulatory_records(s,TARGET,c)==[]
    c,s=fixture(raw.replace('\n\n',' '))
    assert regulatory_records(s,TARGET,c)==[]


def test_regulator_followup_keeps_scope_and_does_not_erase_the_original_penalty():
    raw=(TARGET+'完成三年整改\n\n发布时间：2024-08-30 16:00 信息来源：市场监管总局\n\n'
         '2021年4月，市场监管总局对'+TARGET+'（以下简称青禾集团）作出行政处罚。\n\n'
         '三年来，监管部门对青禾集团整改落实情况开展核查和评估，青禾集团全面停止相关垄断行为，'
         '合规整改工作取得良好成效。下一步，市场监管总局将指导青禾集团持续规范经营。')
    c,s=fixture(raw,url=URL+'-followup');p=fixture()
    rows=regulatory_records(s,TARGET,c)
    assert len(rows)==1 and rows[0]['kind']=='regulatory_remediation' and rows[0]['date']=='2024-08-30'
    assert '下一步' not in rows[0]['fact'] and rows[0]['fact'] in s['content']
    c['evidence_id']='E-000000000002'
    cleaned={'facts':[p[0],c]};sources=[p[1],s]
    judicial=build_judicial_package(cleaned,TARGET,sources)
    assert {r['kind'] for r in judicial['facts']}=={'administrative_penalty','regulatory_remediation'}
    text=render_judicial(judicial)
    assert '行政监管决定与后续整改' in text and '12.28亿元' in text
    assert '尚无绑定完整当事人和案号' in text
    risk=build_risk_register(cleaned,TARGET,sources,intake={'as_of_date':'2026-10-20'})
    assert len(risk['checklist'])==75 and risk['overall_score'] is None
    assert len(risk['entries'])==2
    assert '当前应付' in render_risk_register(risk)


def test_future_regulatory_notice_is_not_admitted_at_the_research_cutoff():
    c,s=fixture(penalty().replace('2021-04-10','2027-04-10').replace('2021年4月10日','2027年4月10日'))
    risk=build_risk_register({'facts':[c]},TARGET,[s],intake={'as_of_date':'2026-10-20'})
    assert not risk['entries']
