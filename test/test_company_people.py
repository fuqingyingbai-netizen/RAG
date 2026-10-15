import json
from types import SimpleNamespace

import pytest

from report_agents.company_people import table_metrics,formula_notes,source_notes,policy_rows,build_people_package,render_people,people_errors
from test_company_history import filing


def page(raw,number=155):return {'page':number,'text':raw}


def sample(name='青禾食品有限公司',*,i=1):
    raw='指标 单位 2024年 2025年\n员工总人数 人 1000 900\n员工流失率\n68\n% 2.53 2.89\n员工培训次数 次 5000 9000\n员工ESG相关培训覆盖人次 人次 2000 33000\n68 员工流失率=(年度主动离职人数+年度被动离职人数)/(年度主动离职人数+年度被动离职人数+年末在职人数)/12；按各类别划分的员工流失率=该类别年度主动离职人数/(该类别年度主动离职人数+该类别年度被动离职人数+该类别年末在职人数)/12'
    c,s=filing(name,'\n'+raw,i=i);s['source_metadata']['document_pages']=[page(raw)]
    return c,s


def package(name,*pairs,**kw):return build_people_package({'facts':[x[0] for x in pairs]},name,[x[1] for x in pairs],**kw)


@pytest.mark.parametrize('name',['星河精密股份有限公司','青禾食品有限公司','Northstar Robotics Limited'])
def test_company_independent_people_metrics_keep_formula_and_units(name):
    p=package(name,sample(name));t=render_people(p)
    assert '2.89%' in t and '/12' in t and '9,000' not in t and '9000次' in t and '33000人次' in t
    assert '比亚迪' not in t and people_errors(t,p)==[]


def test_reversed_and_three_year_headers_choose_latest_two_cells():
    r=table_metrics(page('指标 单位 2025年 2024年 2023年\n员工流失率 % 10.62 8.66 6.23'))[0]
    assert (r['value'],r['previous_value'],r['period'])==('10.62','8.66','2025年')


def test_separate_tables_on_same_page_do_not_share_first_header_years():
    rows=table_metrics(page('指标 单位 2023年 2024年\n员工总数 人 100 200\n指标 单位 2024年 2025年\n员工培训次数 次 500 600'))
    assert [(r['period'],r['value']) for r in rows]==[('2024年','200'),('2025年','600')]


def test_wrapped_internal_superscript_not_inserted_into_metric_or_value():
    r=table_metrics(page('指标 单位 2024年 2025年\n绩效管理制度\n75\n的员工覆盖率 % 100 100'))
    assert len(r)==1 and r[0]['metric']=='绩效管理制度的员工覆盖率' and r[0]['value']=='100'


def test_missing_prior_value_not_zero_and_money_scale_preserved():
    r=table_metrics(page('指标 单位 2023年 2024年\n员工培训总支出\n1\n万元人民币 / 291.76'))[0]
    assert r['previous_value']=='/' and r['unit']=='万元人民币' and r['value']=='291.76'


@pytest.mark.parametrize('raw',['员工流失率 % 2.53 2.89','指标 单位 2024年 2025年\n员工总数 人 100900','指标 单位 2024年 2025年\n员工总数 人 100 /'])
def test_no_header_no_cell_boundaries_or_missing_latest_not_guessed(raw):
    assert not table_metrics(page(raw))


def test_turnover_definition_not_converted_to_standard_annual_rate():
    c,s=sample();p=package('青禾食品有限公司',(c,s));t=render_people(p)
    assert '年度主动离职人数+年度被动离职人数' in t and '不机械换算为年度离职率' in t
    assert '34.68%' not in t and '裁员100人' not in t and '高流失风险' in t


def test_different_formula_stays_original_and_no_same_denominator_assumption():
    text='注 1：【计算公式】各类别员工流失率 = 年内该类别员工流失人数 / 年末该类别员工总数 *100%。'
    assert formula_notes(page(text))==[text]


def test_table_average_training_share_not_relabelled_as_skill_coverage():
    raw='指标 单位 2024年 2025年\n受训员工占比 % 100 100\n74 按各类别划分的受训员工占比=该类别受培训员工人数/受训员工总人数'
    notes=formula_notes(page(raw));assert len(notes)==1 and '受训员工总人数' in notes[0]


def test_wrong_issuer_and_generated_search_abstract_not_people_evidence():
    c,s=sample('青禾食品包装有限公司');s['title']=c['source_title']='青禾食品有限公司年报'
    assert not package('青禾食品有限公司',(c,s))['facts']
    c,s=sample();s['source_metadata']['content_kind']='search_snippet'
    assert not package('青禾食品有限公司',(c,s))['facts']


def test_scope_note_management_population_not_statutory_top_officers():
    text='60 指公司管理架构下口径，不适用《中华人民共和国公司法》或本公司《公司章程》中的相关定义'
    assert source_notes([page(text)])[0]['text']==text


def test_budget_does_not_truncate_metric_into_another_value():
    p=package('青禾食品有限公司',sample(),limit=5100)
    assert len(json.dumps(p['facts'],ensure_ascii=False))<=100 and people_errors(render_people(p),p)


def test_multi_stakeholder_target_table_not_flattened_into_employee_execution():
    raw='政府股东客户员工供应商关注领域 • 文化 • 薪酬 • 员工发展培训 • 产业合作 • 推动行业发展，公司建立绩效管理体系，到2030年覆盖100%员工。'
    assert not policy_rows([page(raw)],'2025年','青禾食品有限公司')


def test_employee_development_paragraph_prioritised_and_plan_label_kept():
    raw='人才培养与发展我们建立多层次人才培养体系，针对性开展管理与技术人才专项培训，并完善员工职业发展过渡计划。'
    r=policy_rows([page(raw)],'2025年','青禾食品有限公司')[0]
    assert r['selection_priority']>=1 and r['fact'].startswith('我们建立')


def test_formula_on_next_page_stays_with_turnover_not_headcount():
    c,s=sample();s['source_metadata']['document_pages']=[page('指标 单位 2024年 2025年\n员工总数 人 100 90\n员工流失率 % 2.53 2.89'),page('68 员工流失率=年度离职人数/年末人数/12',156)]
    b=package('青禾食品有限公司',(c,s));r={x['kind']:x for x in b['facts']}
    assert r['turnover']['definitions'][0]['page']==156 and r['workforce']['definitions']==[]


def test_same_value_different_formulas_not_merged_or_silently_ranked():
    a=sample(i=1);b=sample(i=2);b[1]['source_metadata']['document_pages'][0]['text']=b[1]['source_metadata']['document_pages'][0]['text'].replace('/12','*100%')
    p=package('青禾食品有限公司',a,b);t=render_people(p)
    assert len([r for r in p['facts'] if r['kind']=='turnover'])==2
    assert p['diagnostic']['filters']['same_name_differences']==1 and '公式差异待核' in t and '/12' in t and '*100%' in t


def test_newer_metric_keeps_own_comparison_not_duplicate_old_year_row():
    a=sample(i=1);b=sample(i=2)
    s=b[1];s['source_metadata']['document_pages'][0]['text']=s['source_metadata']['document_pages'][0]['text'].replace('2024年 2025年','2023年 2024年')
    p=package('青禾食品有限公司',a,b)
    assert {r['period'] for r in p['facts']}=={'2025年'}


def test_plan_and_goal_narrative_not_called_achieved_effect():
    raw='我们计划建立员工人才培养体系，未来将设立专业导师团队，通过长期培训支持员工能力发展，但具体完成数量尚待后续统计。'
    r=policy_rows([page(raw)],'2025年','青禾食品有限公司')[0]
    assert '非完成或效果证明' in r['mode']


def test_ambiguous_and_explicitly_rejected_cards_not_recovered():
    for changes in [{'eligible_for_report':False},{'entity_match':'ambiguous'},{'source_entity_validation':'rejected'}]:
        c,s=sample();c.update(changes)
        assert not package('青禾食品有限公司',(c,s))['facts']


def test_missing_scan_or_document_pages_are_explicit():
    c,s=sample();s['source_metadata']['document_extraction']={'omitted_pages':10,'needs_ocr_pages':[1]}
    t=render_people(package('青禾食品有限公司',(c,s)))
    assert '尚未提取全文' in t and '尚未执行OCR' in t and '不等于未披露' in t


def test_recovered_people_index_uses_actual_metric_not_generated_abstract():
    from research_workflow import ResearchWorkflow
    c,s=sample();c['evidence_scope']='industry_context';c['fact']='员工流失率34.68%。'
    b=package('青禾食品有限公司',(c,s));p=SimpleNamespace(target_type='company',target_name='青禾食品有限公司',company_people_package=b)
    t=render_people(b)+'\n\n## 13. 信息来源\n\n## 14. 后续研究建议\n待核验。'
    result=ResearchWorkflow.__new__(ResearchWorkflow)._append_company_claim_evidence_index(p,t,[c],total_traceable_sources=1,eligible_company_sources=0)
    index=result.split('## 13.')[1]
    assert '第八章原文核对' in index and '第 8 章' in index and '34.68' not in index


def test_source_note_only_citation_has_traceable_index_not_key_error():
    from research_workflow import ResearchWorkflow
    c,s=sample();s['source_metadata']['document_pages']=[page('60 指公司管理架构下口径，不适用《中华人民共和国公司法》或本公司《公司章程》中的相关定义')]
    b=package('青禾食品有限公司',(c,s));p=SimpleNamespace(target_type='company',target_name='青禾食品有限公司',company_people_package=b)
    result=ResearchWorkflow.__new__(ResearchWorkflow)._append_company_claim_evidence_index(p,render_people(b)+'\n\n## 13. 信息来源\n\n## 14. 后续研究建议\n待核验。',[c],total_traceable_sources=1,eligible_company_sources=0)
    assert '第八章原文核对' in result and '管理架构' in result


def test_checked_people_chapter_cannot_be_overwritten_or_pad_unused_eids(monkeypatch):
    from report_agents.company_report_agent import CompanyReportAgent
    c,s=sample();p=SimpleNamespace(target_name='青禾食品有限公司',title='青禾',target_type='company',industry='食品',description='',sources=[s]);a=CompanyReportAgent()
    monkeypatch.setattr(a,'_write_section',lambda *x,**kw:'');monkeypatch.setattr(a,'_write_summary',lambda *x,**kw:'## 1. 摘要\n摘要。');monkeypatch.setenv('COMPANY_REPORT_EDITOR_ENABLED','true')
    monkeypatch.setattr(a,'_edit_batched',lambda *x,**kw:'\n'.join(f'## {i}. 标题\n'+('员工年度离职率34.68%，信息缺口证明高风险。[E-FFFFFFFFFFFF]' if i==8 else '待核验。') for i in range(1,15)))
    t=a.generate(p,json.dumps({'facts':[c]}),'{}',lambda *x:'',lambda s,n:s[:n],lambda *x,**kw:None)
    chapter=t.split('## 8.')[1].split('## 9.')[0]
    assert '2.89%' in chapter and '/12' in chapter and '34.68' not in chapter and 'FFFFFFFFFFFF' not in chapter and '本章引用证据' not in chapter


def test_empty_people_chapter_keeps_specific_unknowns_after_evidence_marker_pass():
    from report_agents.company_report_agent import CompanyReportAgent
    p=build_people_package({'facts':[]},'青禾食品有限公司',[])
    t=CompanyReportAgent._ensure_section_evidence_markers(render_people(p),{8:[]})
    assert '流失率' in t and '高风险或无人员流失' in t and people_errors(t,p)


def test_issuer_pdf_can_identify_its_owner_without_prior_exchange_website_field():
    c,s=sample();c['source_url']=s['url']='https://issuer.example/report.pdf'
    s['content']='青禾食品有限公司\n2025年度可持续发展报告\n本报告是青禾食品有限公司的可持续发展报告。\n'+s['content']
    s['source_metadata']['document_extraction']={'method':'embedded_pdf_text'}
    assert package('青禾食品有限公司',(c,s))['facts']
    s['content']=s['content'].replace('青禾食品有限公司\n','青禾食品包装有限公司\n',1)
    # The second, retained original issuer heading is removed too: a title
    # or a parent's mention in the description must not replace the cover.
    s['content']=s['content'].replace('青禾食品有限公司2025年年度报告。','青禾食品包装有限公司2025年年度报告。')
    assert not package('青禾食品有限公司',(c,s))['facts']


def test_company_sustainability_target_system_not_employee_incentive_evidence():
    raw='报告期内，我们围绕六大核心维度制定量化目标，同步搭建绩效指标管理体系，将目标拆解至各业务单元，通过跟踪确保可持续发展战略得到落实。'
    assert not policy_rows([page(raw)],'2025年','青禾食品有限公司')


def test_statistical_senior_management_turnover_not_legal_officer_roster():
    c,s=sample();s['source_metadata']['document_pages'][0]['text']+='\n高级管理层流失率 % 0.23 0.57\n60 指公司管理架构下口径，不适用《中华人民共和国公司法》中的相关定义'
    p=package('青禾食品有限公司',(c,s));r=next(x for x in p['facts'] if x.get('metric')=='高级管理层流失率')
    assert '不等同第七章法定高管名单' in r['population_note'] and '0.57%' in render_people(p)


def test_repeated_general_training_statements_do_not_crowd_out_specific_programmes():
    c,s=sample();texts=['我们建立多层次人才培养体系，为不同层级的人才提供持续的培养机会，明确发展方向。']*5+['我们建立博士后培养体系，与高校联合培养专业研究人才，设置科研导师并提供项目实践机会。','我们组织新员工入职培训，针对应届生提供导师带教，帮助员工熟悉各岗位的业务要求。']
    s['source_metadata']['document_pages'] += [page(t,160+i) for i,t in enumerate(texts)]
    b=package('青禾食品有限公司',(c,s));t=render_people(b)
    assert '博士后培养体系' in t and '新员工入职培训' in t


def test_environmental_performance_training_not_salary_or_employee_incentive():
    r=policy_rows([page('我们每年积极开展专项培训，强化全员参与的环境管理水平与环境绩效表现，进一步完善节能工作要求。')],'2025年','青禾食品有限公司')
    assert not any(x['aspect']=='团队激励与人才结构现状' for x in r)


def test_same_named_course_rephrasing_not_repeated_as_two_culture_practices():
    c,s=sample();s['source_metadata']['document_pages'] += [page('我们在新员工入职培训中增加《员工沟通训练》课程，涵盖反歧视和反骚扰等平等包容相关内容。',100),page('我们已在新员工的入职培训中增加《员工沟通训练》课程，进一步涵盖反歧视和反骚扰等核心内容。',101)]
    p=package('青禾食品有限公司',(c,s))
    assert len([r for r in p['facts'] if r['kind']=='practice' and '《员工沟通训练》' in r['fact']])==1
