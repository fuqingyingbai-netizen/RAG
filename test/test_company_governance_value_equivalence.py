import json
import pytest
from report_agents.company_governance import build_governance_package, read_fields

TARGET='青禾精密股份有限公司'
CODE='91110108587665983J'


def package(field,values):
    facts=[];sources=[]
    for i,value in enumerate(values):
        url=f'structured://isolated-governance/{i}'
        sources.append({'url':url,'title':TARGET+'登记信息','content':f'企业名称：{TARGET}\n{field}：{value}',
            'source_metadata':{'entity_validation':'verified','content_kind':'structured_data','tool':'get_company_registration_info'}})
        facts.append({'evidence_id':f'E-{i:012X}','source_url':url,'company_name':TARGET,
            'evidence_scope':'target_direct','eligible_for_report':True,'source_entity_validation':'verified',
            'claim_type':'source_excerpt','fact':TARGET+'登记记录。'})
    return build_governance_package({'facts':facts},TARGET,sources),sources


@pytest.mark.parametrize('variant',['2011 年 12 月 20 日','2011年12月20日','2011/12/20','2011.12.20','2011-12-20'])
def test_calendar_equivalence_keeps_raw_values_without_a_false_conflict(variant):
    values=['2011-12-20',variant]
    result,_=package('成立日期',values)
    assert not [r for r in result['conflicts'] if r['field']=='成立日期']
    assert {r['value'] for r in result['facts'] if r.get('field')=='成立日期'}==set(values)


@pytest.mark.parametrize('other',['2011-12-21','2012-12-20','2011年12月','2011年12月20日整体改制','2011-02-30','20/12/2011'])
def test_distinct_incomplete_invalid_and_narrative_dates_remain_distinct(other):
    result,_=package('成立日期',['2011-12-20',other])
    assert any(r['field']=='成立日期' for r in result['conflicts'])
    assert any(r.get('value')==other for r in result['facts'])


def test_invalid_calendar_dates_are_not_silently_equated():
    result,_=package('成立日期',['2011-02-30','2011年2月30日'])
    assert any(r['field']=='成立日期' for r in result['conflicts'])


@pytest.mark.parametrize('suffix',['） ，公司类型为股份有限','），公司类型为股份有限',')，企业类型为有限责任公司','）'])
@pytest.mark.parametrize('container',['plain','table','json'])
def test_identifier_boundary_is_shared_by_native_record_containers(suffix,container):
    value=CODE+suffix
    if container=='plain':raw=f'企业名称：{TARGET}\n统一社会信用代码：{value}'
    elif container=='table':raw=f'| 字段 | 值 |\n| --- | --- |\n| 企业名称 | {TARGET} |\n| 统一社会信用代码 | {value} |'
    else:raw=json.dumps({'companyName':TARGET,'creditCode':value},ensure_ascii=False)
    original=raw
    fields,_=read_fields(raw,TARGET)
    assert fields['统一社会信用代码']==CODE and raw==original


@pytest.mark.parametrize('value',[
    CODE+'A），公司类型为股份有限',CODE[:-1]+'），公司类型为股份有限',
    CODE+'），旧代码为123456789012345678',CODE+'），公司类型为股份有限，新代码123456789012345678',
    CODE+'，公司类型为股份有限',CODE+'附注',
])
def test_identifier_does_not_guess_across_unknown_or_multiple_values(value):
    fields,_=read_fields(f'企业名称：{TARGET}\n统一社会信用代码：{value}',TARGET)
    assert fields['统一社会信用代码']==value


def test_native_identifier_suffix_does_not_create_a_conflict_and_source_text_is_unchanged():
    result,sources=package('统一社会信用代码',[CODE,CODE+'） ，公司类型为股份有限'])
    assert not [r for r in result['conflicts'] if r['field']=='统一社会信用代码']
    assert '公司类型为股份有限' in sources[1]['content']


@pytest.mark.parametrize('values',[
    ['36000万元','46100万元','46337.2121万元'],['100万元','100万美元'],[CODE,'91110108587665984J']
])
def test_real_capital_currency_and_identifier_differences_are_not_collapsed(values):
    field='统一社会信用代码' if values[0]==CODE else '注册资本'
    result,_=package(field,values)
    assert any(r['field']==field for r in result['conflicts'])
