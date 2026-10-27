from copy import deepcopy

import pytest

from report_agents.company_listing_funding import listing_funding_events
from report_agents.company_assessment import funding_score
from test_company_assessment import ROOT, CHILD, src, base, build

QUOTE=('2025年6月19日，本公司发行1,000万股H股并在香港联交所挂牌上市交易，'
       '募集资金总额为人民币120,000,000.00元，扣除发行费用人民币20,000,000.00元，'
       '实际募集资金净额为人民币100,000,000.00元。')


def parse(quote=QUOTE,**kwargs):
    source=src(extra=[{'page':15,'text':quote}],**kwargs)
    return source,listing_funding_events(source,ROOT,base(source),'2026-10-24')


def test_dated_listing_and_actual_net_proceeds_are_not_lost_without_word_completed():
    source,rows=parse()
    assert len(rows)==1 and rows[0]['value']=='100,000,000.00'
    assert rows[0]['currency']=='人民币' and rows[0]['unit']=='元'
    assert rows[0]['fact'] in source['content']
    assert rows[0]['funding_date']=='2025-06-19'
    dimension=next(d for d in build(source)['dimensions'] if d['id']=='funding')
    assert dimension['score']==3 and dimension['records'][0]['original_quote_verified']


@pytest.mark.parametrize('old,new',[
    ('本公司发行','本公司拟发行'),('本公司发行','本公司获准发行'),
    ('本公司发行','本公司子公司发行'),('实际募集资金净额','预计实际募集资金净额'),
    ('实际募集资金净额','募集资金总额'),('人民币100,000,000.00元','100,000,000.00元'),
    ('100,000,000.00','0.00'),('2025年6月19日','2026年12月19日'),
    ('2025年6月19日','2020年6月19日'),
    ('扣除发行费用','2025年7月1日，另一项融资扣除发行费用'),
])
def test_plans_gross_amounts_unknown_currency_and_separate_events_are_not_actual_net(old,new):
    assert parse(QUOTE.replace(old,new))[1]==[]


def test_subsidiary_issuer_and_modified_native_values_cannot_inherit_parent_grade():
    assert parse(owner=CHILD)[1]==[]
    source,rows=parse();forged=deepcopy(rows[0]);forged['value']='120,000,000.00'
    assert funding_score({'facts':[forged]},ROOT,'2026-10-24',{source['url']:source})['score'] is None
    source['content']=source['content'].replace('100,000,000.00','99,000,000.00')
    assert funding_score({'facts':rows},ROOT,'2026-10-24',{source['url']:source})['score'] is None


@pytest.mark.parametrize('prefix',['假设','如果','预计于','计划于','例如：','附属公司公告称：'])
def test_preceding_conditional_or_nested_child_subject_is_not_removed_at_date(prefix):
    assert parse(prefix+QUOTE)[1]==[]


def test_future_publication_cannot_supply_an_as_of_funding_grade():
    source=src(extra=[{'page':15,'text':QUOTE}])
    source['url']='https://www.hkexnews.hk/listedco/listconews/sehk/2026/1224/2026122400001_c.pdf'
    assert listing_funding_events(source,ROOT,base(source),'2026-10-24')==[]


def test_platform_original_copy_is_admitted_with_platform_attribution():
    source=src(extra=[{'page':15,'text':QUOTE}])
    source['url']='https://pilu.tianyancha.com/announcement/original.pdf'
    source['source_metadata']['provider']='tyc'
    rows=listing_funding_events(source,ROOT,base(source),'2026-10-24')
    assert len(rows)==1 and '专业平台' in rows[0]['source_attribution']
    assert next(d for d in build(source)['dimensions'] if d['id']=='funding')['score']==3


def test_platform_profile_name_does_not_bind_an_unowned_quoted_listing_event():
    source={'title':ROOT+'平台记录','url':'structured://qcc_company/'+ROOT,
        'content':f'| 字段 | 值 |\n| 公司名称 | {ROOT} |\n\n'+QUOTE,
        'source_metadata':{'provider':'qcc_company','content_kind':'structured_data'}}
    assert listing_funding_events(source,ROOT,base(source),'2026-10-24')==[]


@pytest.mark.parametrize('state',['rejected','ambiguous','related_entity_context'])
def test_explicit_entity_rejection_is_preserved(state):
    source=src(extra=[{'page':15,'text':QUOTE}]);source['source_metadata']['entity_validation']=state
    assert listing_funding_events(source,ROOT,base(source),'2026-10-24')==[]


def test_two_independent_years_can_score_but_cross_year_overallotment_is_not_a_new_cycle():
    first=QUOTE.replace('2025年6月19日','2024年12月19日')
    source,rows=parse(first+'\n'+QUOTE)
    assert len(rows)==2
    assert funding_score({'facts':rows},ROOT,'2026-10-24',{source['url']:source})['score']==5
    extra=QUOTE.replace('2025年6月19日','2026年1月9日').replace('H股并在','H股（因超额配股权获行使）并在')
    source,rows=parse(first+'\n'+extra)
    assert len(rows)==1
    assert funding_score({'facts':rows},ROOT,'2026-10-24',{source['url']:source})['score']==3
