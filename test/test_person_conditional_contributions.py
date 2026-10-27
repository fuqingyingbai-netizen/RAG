import json
import pytest
from person_source_boundaries import conditional_contribution_errors
from person_evidence import build_packages,validate_model_claims
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE


CODE='conditional_contribution_commitment_as_event'


def source(kind='社会保险金'):
    return {'evidence_id':'E-PCONDITIONONE','subject':'林知远','subject_scope':'person',
        'source_url':'https://fixture.invalid/letter.pdf',
        'fact':f'林知远作出如下承诺：如发行人及其下属公司因在2012年1月1日至2014年12月31日之间未为员工按时足额缴纳{kind}而遭受任何损失，该等责任由林知远全额承担，并放弃追索权。'}


@pytest.mark.parametrize('kind,draft',[('社会保险金','2012—2014社保未按时足额缴，承诺全额承担。'),
    ('住房公积金','2012—2014公积金欠缴，承诺承担责任。')])
def test_dated_indemnity_does_not_establish_contribution_nonpayment(kind,draft):
    assert conditional_contribution_errors(draft,[source(kind)])==[CODE]


def test_tax_condition_after_contribution_event_cannot_qualify_the_earlier_event():
    draft='2012—2014社保公积金未按时足额缴、所得税优惠若认定不合法需补缴，承诺全担弃追索。'
    assert conditional_contribution_errors(draft,[source()])==[CODE]


@pytest.mark.parametrize('draft',['社保未按时足额缴，承诺全额承担。','集团社保欠缴，未载处理结果。'])
def test_dropping_the_period_does_not_turn_a_conditional_indemnity_into_an_event(draft):
    assert conditional_contribution_errors(draft,[source()])==[CODE]


def test_an_unrelated_conditional_clause_cannot_qualify_nonpayment_in_the_next_clause():
    draft='税收优惠若被认定不合法由其承担；2012—2014社保未缴，未载处理结果。'
    assert conditional_contribution_errors(draft,[source()])==[CODE]


@pytest.mark.parametrize('draft',['承诺若集团2012—2014社保未按时足额缴而受损，全额承担并弃追索。',
    '不能据此认定2012—2014社保未按时足额缴。',
    '承诺原文为“如发行人2012—2014未按时足额缴纳社会保险金而遭受损失，由其全额承担”。'])
def test_explicit_conditions_or_denial_of_an_established_event_remain_allowed(draft):
    assert conditional_contribution_errors(draft,[source()])==[]


def test_separate_same_actor_direct_evidence_can_establish_an_actual_event():
    direct={**source(),'evidence_id':'E-PCONDITIONTWO','source_url':'https://fixture.invalid/finding.pdf',
            'fact':'经核查，林知远所属集团2012年至2014年确有未按时足额缴纳社会保险费的情形。'}
    assert conditional_contribution_errors('集团2012—2014社保未按时足额缴。',[source(),direct])==[]


@pytest.mark.parametrize('change',[{'subject':'赵青'}, {'fact':'林知远所属集团2015年至2017年确有未按时足额缴纳社会保险费的情形。'},
    {'fact':'林知远所属集团2012年至2014年未按时足额缴纳住房公积金。'}])
def test_another_actor_period_or_contribution_type_cannot_establish_the_claim(change):
    direct={**source(),'evidence_id':'E-PCONDITIONTWO','source_url':'https://fixture.invalid/finding.pdf',
        'fact':'赵青所属集团2012年至2014年未按时足额缴纳社会保险费。',**change}
    assert conditional_contribution_errors('2012—2014社保未按时足额缴。',[source(),direct])==[CODE]


def test_a_promise_to_pay_on_time_is_not_a_conditional_indemnity():
    fact={**source(),'fact':'林知远承诺如期为2012年至2014年的员工缴纳社会保险金。'}
    assert conditional_contribution_errors('2012—2014社保未缴。',[fact])==[]


def test_guard_blocks_unsupported_prose_without_removing_the_original_record():
    f=source();p=build_packages({'facts':[{'fact':f['fact'],'source_url':f['source_url'],'identity_match':'confirmed'}]},
        '林知远',PERSON_REPORT_OUTLINE)['chapters'][3]
    p['facts']=p['research_facts'];p['writing_contract']='evidence_selection_v2';eid=p['facts'][0]['evidence_id']
    original=p['facts'][0]['fact']
    rows,errors=validate_model_claims(json.dumps({'claims':[{'analysis':'2012—2014社保未按时足额缴，承诺全额承担。','evidence_ids':[eid]}]},ensure_ascii=False),p)
    assert CODE in errors and not rows[0]['analysis']
    assert p['facts'][0]['fact']==original and rows[0]['source_support'][0]['quote']==original
    rows,errors=validate_model_claims(json.dumps({'claims':[{'analysis':'承诺若2012—2014社保未按时足额缴而受损，全额承担并放弃追索。','evidence_ids':[eid]}]},ensure_ascii=False),p)
    assert not errors and rows[0]['analysis']
