"""Offline rename invariance; these fixtures are not live-source or model results."""
import json
from types import SimpleNamespace
import pytest
from person_evidence import build_packages,validate_model_claims
from person_company_records import company_records
from person_records import personal_analysis_allowed
from person_platforms import validated_records
from person_structured_tables import structured_tables
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE


TARGETS=[('陈安','远澜软件有限公司','顾海'),('欧阳清和','辰星设备有限公司','陈雨安'),
    ('Alex Morgan','North River Ltd','Jordan Lee')]


@pytest.mark.parametrize('target,company,colleague',TARGETS)
def test_conditional_source_boundary_and_original_retention_are_invariant_under_renaming(target,company,colleague):
    original=f'{target}作出承诺：如{company}因在2012年至2014年未为员工按时足额缴纳社会保险金而遭受损失，由本人全额承担并放弃追索权。'
    contract=build_packages({'facts':[{'fact':original,'source_url':'https://fixture.invalid/letter','identity_match':'confirmed'}]},target,PERSON_REPORT_OUTLINE)
    p=contract['chapters'][3];p['facts']=p['research_facts'];p['writing_contract']='evidence_selection_v2'
    eid=p['facts'][0]['evidence_id']
    rejected,errors=validate_model_claims(json.dumps({'claims':[{'analysis':'2012—2014社保未按时足额缴，承诺全额承担。','evidence_ids':[eid]}]}),p)
    assert 'conditional_contribution_commitment_as_event' in errors and not rejected[0]['analysis']
    assert p['facts'][0]['fact']==original
    allowed,errors=validate_model_claims(json.dumps({'claims':[{'analysis':'承诺若2012—2014社保未按时足额缴而受损，由其全额承担并放弃追索权。','evidence_ids':[eid]}]}),p)
    assert not errors and allowed[0]['analysis']


@pytest.mark.parametrize('target,company,colleague',TARGETS)
def test_company_personnel_field_never_becomes_target_role_after_renaming(target,company,colleague):
    src=SimpleNamespace(url='structured://fixture/company',title=company+'资料',source_type='business_database',
        source_metadata={'identity_confidence':'high','entity_validation':'accepted',
            'person_affiliation':{'person_name':target,'affiliation_name':company}},
        content='### 公司基本信息\n| 字段 | 值 |\n| --- | --- |\n| 企业名称 | '+company+' |\n| 主要人员 | '+json.dumps({'姓名':colleague,'职务':'总经理','任职日期':'2024-01-01'},ensure_ascii=False)+' |')
    contract=build_packages({'facts':company_records(src)},target,PERSON_REPORT_OUTLINE)
    manager=next(f for f in contract['facts'] if '主要人员' in f['fact'])
    assert manager['subject']==company and manager['subject_scope']=='affiliated_company'
    assert not personal_analysis_allowed(manager)
    table='\n'.join(structured_tables(contract['chapters'][4]))
    assert all(value in table for value in [colleague,'总经理','2024-01-01',manager['evidence_id']])


@pytest.mark.parametrize('target,company,colleague',TARGETS)
def test_more_than_300_professional_rows_survive_and_another_person_is_rejected(target,company,colleague):
    rows=[{'企业名称':f'{company}机构{i}','职位':'董事'} for i in range(317)]
    payload={'result':{'content':[{'text':json.dumps({'人员名称':target,'企业名称':company,'任职':rows},ensure_ascii=False)}]}}
    matched,quotes=validated_records(payload,target,company,'get_executive_positions')
    assert matched and len(quotes)==317 and '机构316' in quotes[-1]
    assert validated_records(payload,colleague,company,'get_executive_positions')==(False,[])
