"""Failures observed in a real run, reproduced without company-specific fixes."""
from copy import deepcopy

import pytest

from report_agents.company_assessment import funding_score, build_assessment_package, render_assessment
from report_agents.company_history import build_history_package
from report_agents.company_management import roster_rows
from research_strategies.company import CompanyResearchStrategy
from report_agents.company_reputation import build_reputation_package, reputation_errors, render_reputation
from test_company_history import filing
from test_company_management import roster_page
from test_company_assessment import funding_event, ROOT


def test_split_project_name_and_all_columns_join_only_across_adjacent_pages():
    from report_agents.company_business import project_rows
    header=['项目名称','项目目的','项目进展','拟达到的目标','未来影响']
    first={'page':7,'text':'研发项目','tables':[[header,
        ['电池车身一体','','','利用结构的','2025年5月发布首款搭','实现更高的','提高整体强度的','','']]]}
    second={'page':8,'text':'续表','tables':[[
        ['化技术','安全优势。','载车型，计划后续推广。','整合效率。','表现。'],
        ['新材料','独立项目目的。','已经完成中试验证。','新目标。','新影响。']]]}
    rows=project_rows([first,second],'2025年')
    assert [r['entity'] for r in rows]==['电池车身一体化技术','新材料']
    assert rows[0]['pages']==[7,8] and rows[0]['purpose']=='利用结构的安全优势。'
    assert '首款搭载车型' in rows[0]['progress'] and '后续计划并存' in rows[0]['status']
    assert rows[0]['goal']=='实现更高的整合效率。'
    assert len(project_rows([first,{**second,'page':9}],'2025年'))==1
    complete=deepcopy(first);complete['tables'][0][-1][4]='2025年5月完成。'
    assert len(project_rows([complete,second],'2025年'))==3


def test_people_recovers_authenticated_original_but_never_excluded_card():
    from report_agents.company_people import build_people_package
    from test_company_people import sample
    target='青禾食品有限公司';card,source=sample(target)
    packet=build_people_package({'facts':[]},target,[source])
    assert any(r['kind']=='turnover' for r in packet['facts'])
    assert packet['diagnostic']['filters']['original_locator_recovered']==1
    assert build_people_package({'facts':[{**card,'eligible_for_report':False}]},target,[source])['facts']==[]


def test_project_display_budget_counts_all_pages_of_a_stitched_project():
    from report_agents.company_business import build_business_package, render_business
    from test_company_business import business_source, project_page
    name='青禾食品有限公司'
    recent=[project_page(page=i) for i in range(10,18)]
    for i,p in enumerate(recent):p['tables'][0][1][0]='近期项目'+str(i)
    newest=business_source(name,pages=recent,year=2025)
    p=project_page(page=20);p['tables'][0].append(['电池车身一体','利用结构的','2023年5月发布首款搭','实现更高的','提高整体的'])
    q={'page':21,'text':'项目续页','tables':[[['化技术','安全优势。','载车型，计划后续推广。','效率。','表现。'],
        ['其他完整项目','另外的目的','已经完成中试验证。','另一个目标','另一个影响'],
        ['整体式大梁','利用结构的','2023年9月开始，','实现更高的','提高整体的']]]}
    r={'page':22,'text':'项目续页','tables':[[['车架','安全优势。','陆续完成量产并交付。','效率。','表现。']]]}
    oldest=business_source(name,i=2,pages=[p,q,r],year=2023)
    packet=build_business_package({'facts':[newest[0],oldest[0]]},name,[newest[1],oldest[1]])
    text=render_business(packet)
    assert '电池车身一体化技术' in text and '整体式大梁车架' in text
    assert len([r for r in packet['facts'] if r['kind']=='project'])<=12


def test_summary_uses_latest_checked_fields_and_preserves_comparison_scope():
    from report_agents.company_summary import build_company_summary_package, fallback_company_summary, summary_errors
    from types import SimpleNamespace
    base={'evidence_id':'E-123456ABCDEF','source_url':'https://example.com/report.pdf','source_title':'年报','evidence_scope':'target_direct'}
    financial=[{**base,'metric':metric,'value':value,'unit':'万元','period':'2026年半年度报告',
                'cutoff':'2026-06-30','yoy':'-20.00%'}
               for metric,value in [('营业收入','100.00'),('归属于上市公司股东的净利润','8.00'),('经营活动产生的现金流量净额','6.00')]]
    old={**financial[0],'cutoff':'2025-12-31','period':'2025年年度报告','value':'999.00'}
    fund={**base,'evidence_id':'E-222222ABCDEF','source_url':'https://example.com/fund.pdf',
          'original_quote_verified':True,'fact':'2025年3月11日本公司完成配售，所得款项净额100百万港元。','period':'2025-03-11'}
    bench={**base,'evidence_id':'E-333333ABCDEF','source_url':'https://example.com/stats','kind':'benchmark','metric':'动力电池使用量份额',
           'value':'15.1%','unit':'%','period':'2026年1—8月','basis':'全球注册口径；不等同整车份额','entity':'甲公司','target_row':True}
    packages={'assessment':{'financial_observations':[old]+financial,'dimensions':[{'id':'funding','records':[fund]}]},
              'reputation':{'facts':[bench,{**bench,'target_row':False,'entity':'乙公司','value':'39.4%'},
                                       {**bench,'target_row':False,'entity':'丙公司','period':'2025年'}]}}
    p=build_company_summary_package({'facts':[]},'甲公司',chapter_packages=packages)
    text=fallback_company_summary(SimpleNamespace(target_name='甲公司'),p)
    assert '999.00' not in text and '100.00万元' in text and '100百万港元' in text
    assert '甲公司' in text and '乙公司' in text and '丙公司' not in text and '不等同整车份额' in text
    assert summary_errors(text,p)==[]


def test_recovered_source_index_has_actual_supporting_chapters_and_own_urls():
    from research_workflow import ResearchWorkflow
    from report_agents.company_risk_register import source_anchor
    from types import SimpleNamespace
    a={'url':'https://example.com/a','title':'原件A','content':'正文','source_metadata':{'content_kind':'primary_page'}}
    b={**a,'url':'https://example.com/b','title':'原件B'}
    workflow=ResearchWorkflow.__new__(ResearchWorkflow)
    e1=workflow._stable_evidence_id(a['url'],a['title']);e2=workflow._stable_evidence_id(b['url'],b['title'])
    r={'evidence_id':e1,'evidence_ids':[e1,e2],'source_url':a['url'],'source_title':a['title'],'fact':'员工原表指标为100人'}
    project=SimpleNamespace(target_name='甲公司',sources=[a,b],company_people_package={'facts':[r]},company_reputation_package={'facts':[r]})
    report=f'## 5. 评价\n指标[{e1}]\n## 8. 员工\n指标[{e1}][{e2}]\n## 13. 信息来源\n## 14. 后续研究建议'
    indexed=workflow._append_company_claim_evidence_index(project,report,[],total_traceable_sources=0,eligible_company_sources=0)
    assert '待回溯' not in indexed
    assert f'| {e1} | 第 5 章、第 8 章 |' in indexed
    assert any(e2 in line and b['url'] in line and '第 8 章' in line for line in indexed.splitlines())


def test_index_claim_does_not_attribute_unused_summary_card_to_chapter_one():
    from research_workflow import ResearchWorkflow
    from types import SimpleNamespace
    eid='E-123456ABCDEF'
    record={'evidence_id':eid,'evidence_ids':[eid],'source_url':'https://example.com/report','source_title':'原件','fact':'实际引用的原表记录'}
    p=SimpleNamespace(target_name='甲公司',sources=[],company_summary_package={'facts':[{**record,'fact':'未被摘要引用的卡'}]},company_people_package={'facts':[record]})
    indexed=ResearchWorkflow.__new__(ResearchWorkflow)._append_company_claim_evidence_index(p,f'## 8. 员工\n原表[{eid}]\n## 13. 信息来源\n## 14. 后续研究建议',[],total_traceable_sources=0,eligible_company_sources=0)
    assert '第八章原文核对：实际引用的原表记录' in indexed and '未被摘要引用的卡' not in indexed


def test_followups_use_actions_instead_of_already_bound_employee_definitions():
    from report_agents.company_delivery import company_followup_rows
    report='## 8. 人员\n### 核验判断与具体缺口\n- 原页范围/说明：原文标号60：公司管理架构口径（物理页152）。\n- 原页公式：原表定义（物理页155）。\n- 核对分岗位离职分母、原始统计及执行记录。\n- 调取培训执行记录并开展员工访谈。\n## 9. 司法'
    rows=company_followup_rows(report)
    assert rows[0]['items']==['核对分岗位离职分母、原始统计及执行记录。','调取培训执行记录并开展员工访谈。']


@pytest.mark.parametrize('owner,other', [
    ('星河精密股份有限公司', '晨光创业投资有限公司'),
    ('青禾食品有限公司', '远山产业投资有限责任公司'),
])
def test_other_company_profile_is_not_an_issuer_founding_event(owner, other):
    body = f'（十五）{other}企业性质：有限责任公司成立时间：1996年9月4日注册资本：人民币15,000万元；经营范围：参与设立创业投资企业。'
    card, source = filing(owner, body)
    package = build_history_package({'facts': [card]}, owner, [source])
    assert not any(other in r['fact'] for r in package['facts'])


def test_meeting_table_ends_roster_context_instead_of_inheriting_person():
    page = roster_page('钱二', '董事')
    page['tables'].append([
        ['会议届次', '召开日期', '披露日期', '会议决议'],
        ['第七届董事会第三十次会议', '2025年2月1日', '2025年2月2日', '审议通过相关议案'],
    ])
    next_page = {'page': 9, 'text': '会议表续页', 'tables': [[
        ['第七届董事会第三十一次会议', '2025年3月1日', '2025年3月2日', '审议通过相关议案'],
    ]]}
    rows = roster_rows([page, next_page], '2025年年度报告')
    assert [(r['entity'], r['role']) for r in rows] == [('钱二', '董事')]


def test_funding_quote_survives_adjacent_pdf_header_without_joining_different_events():
    quote = '2025年3月11日，本公司完成配售，所得款项净额为1,200万元，已发行H股总数增加至200万股。'
    source, record = funding_event(quote)
    split = quote.index('发行H股')
    source['source_metadata']['document_pages'] = [
        {'page': 1, 'text': ROOT + '\n2025年年度报告'},
        {'page': 5, 'text': quote[:split]},
        {'page': 6, 'text': ROOT + ' 2025 年年度报告摘要\n6\n' + quote[split:]},
    ]
    source['content'] = '\n\n'.join(f"--- PDF page {p['page']} ---\n{p['text']}" for p in source['source_metadata']['document_pages'])
    before = deepcopy(source)
    score = funding_score({'facts': [record]}, ROOT, '2026-10-20', {source['url']: source})
    assert score['score'] == 3
    assert score['records'][0]['pages'] == [5, 6]
    assert source == before
    # Removing uncollected pages must never let separate paragraphs become a
    # fabricated continuous quotation.
    source['source_metadata']['document_pages'][2]['page'] = 8
    source['content'] = '\n\n'.join(f"--- PDF page {p['page']} ---\n{p['text']}" for p in source['source_metadata']['document_pages'])
    assert funding_score({'facts': [record]}, ROOT, '2026-10-20', {source['url']: source})['score'] is None
    source['content']=quote
    assert funding_score({'facts': [record]}, ROOT, '2026-10-20', {source['url']: source})['score'] is None


def test_reputation_has_its_own_primary_disclosure_search():
    queries = [q for q in CompanyResearchStrategy.authority_queries if q['module'] == '行业口碑、产品认可度与同业竞争地位研判']
    assert any('可持续发展报告' in q['query'] and '满意度' in q['query'] and 'hkexnews.hk' in q['domains'] for q in queries)


def test_missing_cleaner_card_can_recover_issuer_original_but_not_rejected_or_untrusted_source():
    owner='青禾食品有限公司'
    _,source=filing(owner,'\n指标 单位 2024年 2025年\n客户满意度 % 91 94')
    source['source_metadata']['document_pages']=[{'page':1,'text':source['content']},
        {'page':8,'text':'指标 单位 2024年 2025年\n客户满意度 % 91 94'}]
    package=build_reputation_package({'facts':[]},owner,[source])
    assert any(r.get('value')=='94' for r in package['facts'])
    assert reputation_errors(render_reputation(package),package)==[]
    rejected={'evidence_id':'E-000000000001','source_url':source['url'],'eligible_for_report':False}
    assert not build_reputation_package({'facts':[rejected]},owner,[source])['facts']
    source['url']='https://unverified.example/claim.pdf'
    assert not build_reputation_package({'facts':[]},owner,[source])['facts']


def test_traditional_disclosure_preserves_nps_and_complaint_footnotes():
    owner='青禾食品有限公司'
    raw=('指標 單位 2024年 2025年\n客戶滿意度 % 95以上 97.4\n'
         '接獲的客戶投訴數目 宗 43,392 45,177\n客戶投訴回應率 % 96.08 98.41\n'
         '76 包含售後階段對產品和服務質量的投訴；客戶投訴回應率為400服務電話的服務指標統計\n'
         '77 客戶滿意度指客戶服務售後NPS')
    card,source=filing(owner,raw)
    source['source_metadata']['document_pages']=[{'page':8,'text':raw}]
    package=build_reputation_package({'facts':[card]},owner,[source])
    nps=next(r for r in package['facts'] if r.get('metric')=='客户满意度')
    complaint=next(r for r in package['facts'] if r.get('metric')=='客户投诉回应率')
    assert '售後NPS' in nps['definition'] and '400服務電話' in complaint['definition']
    assert nps['evidence_quote'] in raw


def test_assessment_renders_the_completed_funding_amount_not_only_a_positive_score():
    source,record=funding_event()
    record['evidence_quote']=record['fact']
    packet=build_assessment_package({'facts':[record]},ROOT,[source],intake={'as_of_date':'2026-10-20'})
    text=render_assessment(packet)
    assert '2025-03-11' in text and '1,200万元' in text and '原文融资事实及净额' in text
