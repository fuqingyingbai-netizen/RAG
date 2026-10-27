from types import SimpleNamespace

from person_company_records import company_records
from person_evidence import build_packages
from person_records import observation,personal_analysis_allowed
from person_structured_tables import structured_tables
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE


def source():
    return SimpleNamespace(content='### 公司基本信息\n| 字段 | 值 |\n| --- | --- |\n'
        '| 企业名称 | 恒川软件有限公司 |\n'
        '| 主要人员 | {"姓名":"陈雨安","职务":"总经理","任职日期":"2024-01-01"} |',
        url='structured://fixture/xiniu/company',title='恒川软件公司资料',source_type='business_database',
        source_metadata={'provider':'xiniu','identity_confidence':'high','entity_validation':'accepted',
            'person_affiliation':{'person_name':'林知远','affiliation_name':'恒川软件有限公司'}})


def test_other_named_actor_in_a_company_field_stays_in_company_table_without_personal_promotion():
    raw=source();rows=company_records(raw)
    package=build_packages({'facts':rows},'林知远',PERSON_REPORT_OUTLINE)
    manager=next(f for f in package['facts'] if '主要人员' in f['fact'])
    assert manager['subject_scope']=='affiliated_company' and manager['subject']=='恒川软件有限公司'
    assert manager['observation']['source_named_person']=='陈雨安'
    assert manager['observation']['subject']=='恒川软件有限公司'
    assert not manager['observation']['direct_person_link'] and not personal_analysis_allowed(manager)
    table='\n'.join(structured_tables(package['chapters'][4]))
    assert all(value in table for value in ['陈雨安','总经理','2024-01-01'])
    assert manager['evidence_id'] in table and len(package['chapters'][4]['facts'])==2
    assert not package['chapters'][3]['facts'] and not package['chapters'][7]['facts']


def test_a_personnel_bio_is_still_other_person_even_with_an_affiliation_context():
    row={'fact':'恒川软件人员资料：{"姓名":"陈雨安","职务":"总经理"}',
        'claim_type':'person_team_member_record','subject_scope':'person',
        'person_affiliation':{'person_name':'林知远','affiliation_name':'恒川软件有限公司'}}
    obs=observation(row,'林知远')
    assert obs['subject_scope']=='other_person' and obs['subject']=='陈雨安'
    assert not personal_analysis_allowed({**row,'observation':obs,'subject_scope':obs['subject_scope']})


def test_rejected_or_low_confidence_company_sources_remain_excluded():
    for field,value in [('entity_validation','rejected'),('identity_confidence','low')]:
        raw=source();raw.source_metadata[field]=value
        assert company_records(raw)==[]


def test_a_raw_company_type_alone_cannot_override_an_unconfirmed_actor_scope():
    row={'fact':'{"姓名":"陈雨安","职务":"总经理"}',
        'claim_type':'person_company_record','subject_scope':'person',
        'person_affiliation':{'person_name':'另一个调查对象','affiliation_name':'未经本轮确认的公司'}}
    obs=observation(row,'林知远')
    assert obs['subject_scope']=='other_person' and obs['subject']=='陈雨安'
