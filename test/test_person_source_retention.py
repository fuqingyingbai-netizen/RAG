import json
from types import SimpleNamespace
from person_chapter_research import personal_feedback_packets,extraction_batches,extract_personal_feedback,validate_discovery,discovery_packets
from person_material_tables import team_table
from person_material_accounting import diagnose_material


def sources(count=20,paragraphs=5):
    rows=[]
    for i in range(count):
        text='\n\n'.join(f'客户顾海表示，林知远按第{j+1}项合同约定交付了产品，仍需核对实际交付和合同原件；这是顾海个人的公开评价，不能由此作信用认证。' for j in range(paragraphs))
        rows.append(SimpleNamespace(id=i,url=f'https://fixture.invalid/feedback/{i}',title='公开评价',content=text,source_type='news',source_metadata={'identity_confidence':'high','content_kind':'full_text','fetch_status':'done'}))
    return rows


def test_all_retained_feedback_sources_and_paragraphs_are_batched_not_capped():
    rows=sources();packets=personal_feedback_packets(rows,{'target_name':'林知远'})
    assert len(packets)==20 and sum(len(p['excerpts']) for p in packets)==100
    batches=list(extraction_batches(packets))
    assert sum(len(p['excerpts']) for batch in batches for p in batch)==100
    assert all(len(batch)<=8 for batch in batches)
    calls=[]
    def invoke(role,prompt,*args):
        data=json.loads(prompt.splitlines()[-1]);calls.append(data)
        assert '最多4条' not in prompt
        return json.dumps({'feedback':[{'kind':'attributed_opinion','evaluator':'顾海','relationship':'客户','source_url':p['source_url'],'quote_id':r['quote_id']} for p in data['sources'] for r in p['excerpts']]},ensure_ascii=False)
    records,rejected,count=extract_personal_feedback(SimpleNamespace(_invoke_person_report_section=invoke),rows,{'target_name':'林知远'})
    assert count==len(calls)==13 and len(records)==100 and not rejected
    assert {r['source_url'] for r in records}=={s.url for s in rows}


def test_validator_retains_more_than_twelve_qualified_feedback_records():
    rows=sources(20,3)
    feedback=[{'kind':'attributed_opinion','evaluator':'顾海','relationship':'客户','source_url':r.url,'quote':r.content.split('\n\n')[0]} for r in rows]
    _,records,rejected=validate_discovery(json.dumps({'feedback':feedback},ensure_ascii=False),rows,{'target_name':'林知远'})
    assert len(records)==20 and not rejected
    assert {p['source_url'] for p in discovery_packets(rows,{'target_name':'林知远'})}=={r.url for r in rows}


def test_team_table_keeps_every_distinct_role_and_date_and_review_sees_actual_cells():
    rows=[{'evidence_id':f'E-PTEAM{i:08d}','fact':f'陈雨安现任远山科技岗位{i}，原文记载对应历史职责。','source_url':'https://fixture.invalid/team','subject':'陈雨安','subject_scope':'other_person','claim_type':'team_member_record','analysis_allowed':False,'team_member_name':'陈雨安','team_affiliation_name':'远山科技','observation':{'role_date_fields':[{'field':f'任期{i}','source_value':f'200{i}年'}]}} for i in range(6)]
    package={'chapter':6,'title':'团队','facts':rows,'research_facts':rows}
    rendered='\n'.join(team_table(package))
    assert all(f'岗位{i}' in rendered and f'200{i}年' in rendered for i in range(6))
    seen=[]
    def invoke(role,prompt,*args):
        data=json.loads(prompt.splitlines()[-1]);seen.append(data)
        assert all(f'岗位{i}' in ''.join(data['body_table_rows']) and f'200{i}年' in ''.join(data['body_table_rows']) for i in range(6))
        return json.dumps({'material_reviews':[{'evidence_id':r['evidence_id'],'disposition':'table','reason':'实际表格已列出该成员对应职务和任期。'} for r in rows]},ensure_ascii=False)
    result=diagnose_material(package,[],invoke,None)
    assert result['status']=='passed' and result['counts']=={'table':6} and len(seen)==1


def test_report_rerun_recovers_unselected_company_fields_without_personal_permission():
    from person_evidence import build_packages
    from person_company_records import company_records
    from person_structured_tables import structured_tables
    from report_agents.person_report_agent import PERSON_REPORT_OUTLINE
    src=SimpleNamespace(url='structured://fixture/company',title='公司平台原字段',source_type='business_database',
        content='### 公司信息\n| 字段 | 值 |\n| --- | --- |\n| 法定代表 | 林知远 |\n| 注册资本 | 1260万元 |\n| 成立时间 | 2020年5月13日 |\n| gsId | internal-token |',
        source_metadata={'identity_confidence':'medium','person_affiliation':{'person_name':'林知远','affiliation_name':'恒川软件有限公司'}})
    raw=company_records(src)
    assert len(raw)==3
    old={'facts':[r for r in raw if '法定代表' in r['fact']]}
    contract=build_packages(old,'林知远',PERSON_REPORT_OUTLINE,sources=[src])
    assert any('注册资本：1260万元' in f['fact'] for f in contract['facts'])
    assert any('成立时间：2020年5月13日' in f['fact'] for f in contract['facts'])
    assert not any('internal-token' in f['fact'] for f in contract['facts'])
    assert any(r.get('reason')=='provider_metadata_not_company_fact' for r in contract['source_material_audit'])
    table='\n'.join(structured_tables(contract['chapters'][4]))
    assert '1260万元' in table and '2020年5月13日' in table
    assert all(not f['analysis_allowed'] for f in contract['chapters'][4]['research_facts'])
    src.source_metadata['entity_validation']='rejected'
    rejected=build_packages(old,'林知远',PERSON_REPORT_OUTLINE,sources=[src])
    assert not rejected['facts'] and rejected['rejected'][0]['rejection_reason']=='identity_quarantine'


def test_added_sources_reuse_only_record_bound_routing_with_unchanged_task():
    from test_person_material_routing import fixture
    from person_material_routing import review_unassigned
    contract=fixture(3);seen=[]
    def invoke(role,prompt,*args):
        packet=json.loads(prompt.splitlines()[-1]);seen.extend(packet['review_evidence_ids'])
        return json.dumps({'routings':[{'evidence_id':f['evidence_id'],'action':'chapter','chapter':2,
            'reason':'首家门店开业是职业创业经历的重要事件。'} for f in packet['facts']]})
    old=review_unassigned(contract,'林知远',invoke);seen.clear()
    extra={'evidence_id':'E-NEW000000001','fact':'公司注册资本1260万元。','subject':'恒川软件','subject_scope':'affiliated_company'}
    contract['facts'].append(extra);contract['chapters'][4]['research_facts'].append(extra)
    def forbidden(*args):raise AssertionError('unchanged original was re-requested')
    reused=review_unassigned(contract,'林知远',forbidden,previous=old)
    assert reused['status']=='passed' and reused['requests']==0 and reused['cached_record_decisions_revalidated']==3
    contract['facts'][1]['source_reporting_period_literal']='2025年度'
    changed=review_unassigned(contract,'林知远',invoke,previous=reused)
    assert seen==[contract['facts'][1]['evidence_id']] and changed['status']=='passed'
    seen.clear();contract['chapters'][2]['task']='逐人核对学习时期和学历'
    reviewed=review_unassigned(contract,'林知远',invoke,previous=changed)
    assert len(seen)==3 and reviewed['cached_record_decisions_revalidated']==0
