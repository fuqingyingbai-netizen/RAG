import json
from types import SimpleNamespace

from person_identity import affiliations
from person_platforms import validated_records, xiniu_plan
from person_source_flow import can_fetch, fetch_budget, summarize
from person_structured_tables import structured_tables
from person_company_records import company_records
from person_records import chapter_relevant, observation
from research_workflow import ResearchWorkflow
from person_chapter_selection import useful_for_chapter


def test_all_returned_professional_rows_survive_beyond_one_hundred():
    rows = [{'企业名称':f'测试企业{i}', '职位':'董事长'} for i in range(157)]
    payload = {'result':{'content':[{'text':json.dumps({'人员名称':'林知远','企业名称':'恒川有限公司','任职':rows})}]}}
    matched, quotes = validated_records(payload, '林知远','恒川有限公司','get_executive_positions')
    assert matched and len(quotes)==157
    assert '测试企业156' in quotes[-1]
    assert validated_records(payload,'另一人','恒川有限公司','get_executive_positions') == (False,[])


def test_fields_from_historical_tools_merge_without_becoming_current():
    facts=[]
    for eid,tool,row in [('E-ONE','historical_related_companies',{'企业名称':'旧企业','曾担任角色':['董事'],'成立日期':'2000-01-01'}),
                         ('E-TWO','historical_positions',{'企业名称':'旧企业','职位':'董事','任职起止时间':'开始时间:[],结束时间:2021-11-08'})]:
        facts.append({'evidence_id':eid,'claim_type':'person_platform_record','source_url':'structured://qcc/'+tool,
                      'fact':'林知远；历史记录；'+json.dumps(row,ensure_ascii=False)})
    table='\n'.join(structured_tables({'chapter':9,'facts':facts}))
    assert '旧企业（历史）' in table and '归并为1行' in table
    assert '[E-ONE]' in table and '[E-TWO]' in table
    assert '开始时间:[],结束时间:2021-11-08' in table


def test_default_fetch_processing_has_no_implicit_source_quota(monkeypatch):
    monkeypatch.delenv('PERSON_WEB_FETCH_BUDGET',raising=False)
    assert fetch_budget() is None and can_fetch(300,fetch_budget())
    monkeypatch.setenv('PERSON_WEB_FETCH_BUDGET','2')
    assert can_fetch(1,fetch_budget()) and not can_fetch(2,fetch_budget())
    summary=summarize([{'candidate_id':1,'canonical_url':'https://a/','disposition':'retained'},
                       {'candidate_id':2,'canonical_url':'https://a/','disposition':'duplicate_url'}])
    assert summary['returned_candidate_rows']==2 and summary['unique_returned_urls']==1
    assert summary['unresolved_candidate_rows']==[]


def test_role_connector_is_not_part_of_company_name():
    assert affiliations('并担任融捷投资控股集团有限公司董事长') == ['融捷投资控股集团有限公司']


def test_all_requested_company_background_tools_are_planned():
    tasks=xiniu_plan({'special_requirements':'基金管理人融资、团队、近期事件','as_of_date':'2026-10-20'},'恒川有限公司')
    assert len(tasks)==4 and tasks[-1][0]=='get_project_events'


def test_all_company_table_rows_are_retained_beyond_one_hundred():
    source=SimpleNamespace(url='structured://xiniu/test',title='测试公司融资',source_type='business_database',
        source_metadata={'person_affiliation':{'affiliation_name':'恒川有限公司'}},
        content='### 公司融资\n| 字段 | 值 |\n| --- | --- |\n'+
                '\n'.join(f'| 融资事项{i} | 待核验记录{i} |' for i in range(157)))
    rows=company_records(source)
    assert len(rows)==157 and '融资事项156' in rows[-1]['fact']


def test_zero_is_kept_as_a_literal_platform_value():
    row={'企业名称':'测试企业','注册资本':0}
    fact={'evidence_id':'E-ZERO','claim_type':'person_platform_record','source_url':'structured://qcc/positions',
          'fact':'林知远；平台所列记录；'+json.dumps(row,ensure_ascii=False)}
    assert '注册资本：0' in '\n'.join(structured_tables({'chapter':9,'facts':[fact]}))


def test_interbank_rate_does_not_turn_a_loan_into_peer_comparison():
    fact={'fact':'林知远获公司贷款，利率为一月期港元同业拆息加60基点。'}
    assert chapter_relevant(fact,9) and not chapter_relevant(fact,8)
    assert chapter_relevant({'fact':fact['fact']+'另有对标可比人物资料。'},8)


def test_structured_entity_intake_strips_role_connector_before_lookup(monkeypatch):
    workflow=ResearchWorkflow.__new__(ResearchWorkflow)
    seen=[]
    monkeypatch.setattr(workflow,'_structured_entity_candidates',lambda project,intake,target:seen.append(target) or [target])
    project=SimpleNamespace(target_type='person',target_name='林知远',title='测试')
    result=workflow._prepare_structured_entity_intake(project,{'target_type':'person','target_name':'林知远',
        'affiliation':'并担任融捷投资控股集团有限公司董事长'})
    assert seen==['融捷投资控股集团有限公司'] and result['associated_company']==seen[0]


def test_a_teachers_biography_is_not_the_named_entrepreneurs_education():
    row=observation({'fact':'王老师的职业生涯始于电力施工企业，随后读研究生并任大学教师。她与海底捞创始人张勇相识后，参与企业管理研究。'},'张勇')
    assert row['subject_scope']=='other_person' and row['source_named_person']=='王老师'
    fact={'fact':'王老师在合作中研究管理团队的培训体系。','subject_scope':'other_person','observation':row}
    assert not useful_for_chapter(fact,6)


def test_holding_relation_routes_without_the_literal_keyword_for_shareholding():
    from person_evidence import build_packages
    from report_agents.person_report_agent import PERSON_REPORT_OUTLINE
    text='陈雨安直接及间接透过其控制的实体持有远山公司合共20.82亿股股份，占公司已发行股份约37.36%。'
    c=build_packages({'facts':[{'fact':text,'source_url':'https://fixture.invalid/holding','identity_match':'confirmed'}]},'陈雨安',PERSON_REPORT_OUTLINE)
    assert text in [f['fact'] for f in c['chapters'][9]['research_facts']]


def test_all_qualified_company_background_fields_reach_the_report_table_without_topic_keywords():
    from person_evidence import build_packages,render_section
    from report_agents.person_report_agent import PERSON_REPORT_OUTLINE
    text='远山科技有限公司的平台记录（公司信息）：经营状态：存续；法定代表：陈雨安。'
    row={'fact':text,'source_url':'structured://qcc/company','identity_match':'confirmed','claim_type':'person_company_record',
        'person_chapters':[6,9],'person_affiliation':{'person_name':'陈雨安','affiliation_name':'远山科技有限公司'}}
    c=build_packages({'facts':[row]},'陈雨安',PERSON_REPORT_OUTLINE)
    p=c['chapters'][4]
    assert p['research_facts'] and not p['research_facts'][0]['analysis_allowed']
    assert text in render_section(p,[])


def test_judicial_platform_fields_are_rendered_even_without_a_company_group_key():
    f={'evidence_id':'E-TEST0001','subject':'陈雨安','claim_type':'person_platform_record','source_url':'structured://qcc/judicial',
        'fact':'陈雨安；平台所列司法记录；{"案号":"（2025）测试001号","当事人角色":"原告","程序状态":"待核"}'}
    table='\n'.join(structured_tables({'chapter':12,'facts':[f]}))
    assert '当事人角色' in table and '原告' in table and '[E-TEST0001]' in table
