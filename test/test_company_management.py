import json
from types import SimpleNamespace

import pytest

from report_agents.company_management import (
    HEADINGS,iso,issuer,roster_rows,change_rows,appointments,biography_rows,
    relationship_rows,outside_roles,build_management_package,latest_roles,render_management,management_errors,
)
from report_agents.company_report_agent import CompanyReportAgent,COMPANY_SECTION_FEW_SHOTS,COMPANY_REPORT_OUTLINE
from research_workflow import ResearchWorkflow
from test_company_history import filing


def roster_page(name='赵一',role='董事长、总裁',*,page=8):
    return {'page':page,'text':'董事和高级管理人员情况 任期起始日期 任职状态',
            'tables':[[['姓名','性别','年龄','职务','任职状态','任期起始日期','任期终止日期'],
                       [name,'男','50',role,'现任','2024年7月1日','2027年6月30日']]]}


def source(name='青禾食品有限公司',*,pages=None,i=1):
    pages=pages or [roster_page(),{'page':9,'text':'赵一先生，硕士研究生学历。赵先生曾任甲公司总经理，现任本公司董事长兼总裁，负责经营管理。'}]
    c,s=filing(name,'\n'+ '\n'.join(p['text'] for p in pages),i=i)
    s['source_metadata']['document_pages']=pages
    return c,s


def package(name,*pairs,**kw):
    return build_management_package({'facts':[p[0] for p in pairs]},name,[p[1] for p in pairs],**kw)


def announcement(text,*,page=2):
    return [{'page':page,'text':text}],text+'\n公司董事会2026年9月29日'


@pytest.mark.parametrize('name',['星河精密股份有限公司','青禾食品有限公司','Northstar Robotics Limited'])
def test_company_independent_roster_and_biography_no_example_conclusions(name):
    b=package(name,source(name));t=render_management(b)
    assert all('### '+h in t for h in HEADINGS) and '赵一' in t and '硕士研究生学历' in t
    assert '比亚迪' not in t and '治理联盟' not in t and '≥30%' not in t
    assert management_errors(t,b)==[]


def test_original_chapter_few_shot_mismatch_does_not_seed_supply_chain_assurance():
    assert '整体保持运转稳定' not in COMPANY_SECTION_FEW_SHOTS[7]
    assert '供应商/经销体系关系型合作信号研判' not in COMPANY_REPORT_OUTLINE[6][1]


def test_merged_role_rows_inherit_person_not_signatory_or_other_director():
    p=roster_page('钱二','董事');p['tables'][0]+=[['','','','执行总裁','现任','2025/9/24','2027/7/1'],['','','','副总裁','离任','2017/12/14','2025/9/24']]
    r=roster_rows([p],'2025年年度报告')
    assert [(x['entity'],x['role'],x['status']) for x in r]==[('钱二','董事','现任'),('钱二','执行总裁','现任'),('钱二','副总裁','离任')]


def test_cross_page_merged_role_with_blank_state_uses_previous_person():
    p=roster_page('钱二','副总裁');q={'page':9,'text':'续页','tables':[[['','','','首席财务官','','2022/2/22','2027/7/1']]]}
    r=roster_rows([p,q],'2025年年度报告')
    assert r[-1]['entity']=='钱二' and r[-1]['role']=='首席财务官' and r[-1]['status']=='现任' and r[-1]['page']==9


def test_pdf_sliver_columns_and_actual_term_not_holding_number():
    p=roster_page();p['tables'][0][1]=[v for c in p['tables'][0][1] for v in (c,None,None)]+['100000']
    r=roster_rows([p],'2025年年度报告')[0]
    assert r['start']=='2024-07-01' and r['end']=='2027-06-30'


def test_source_status_current_bound_to_fiscal_date_not_today():
    b=package('青禾食品有限公司',source());t=render_management(b)
    assert '2025年年度报告' in t and '未另认定为精确年末时点' in t and '不保证今天状态' in t and '本届董事会统一起始日' in t


@pytest.mark.parametrize('value',['2026年2月30日','2026/13/1','2026年7月','20260203'])
def test_dates_not_completed_or_corrected_from_invalid_ambiguous_fields(value):
    assert iso(value)==''


def test_formal_appointment_list_expands_exact_names_and_role():
    pages,raw=announcement('董事会同意聘任赵一先生、钱二女士为公司副总裁，同意聘任孙三女士为公司副总裁兼财务总监；同意聘任周四先生为董事会秘书及公司秘书。')
    r=appointments(pages,raw)
    assert [(x['entity'],x['role']) for x in r]==[('赵一','副总裁'),('钱二','副总裁'),('孙三','副总裁兼财务总监'),('周四','董事会秘书及公司秘书')]
    assert {x['start'] for x in r}=={'2026-09-29'}


def test_nomination_not_appointment_and_qualification_list_not_risk_event():
    pages,raw=announcement('董事会同意提名赵一先生为公司独立董事候选人。赵一先生不存在以下情形：（1）受过处罚；（2）涉嫌犯罪被司法机关立案。')
    assert appointments(pages,raw)==[]
    b=package('青禾食品有限公司',source());t=render_management(b)
    assert '不能改写为本项目完成司法' in t and '不能把条款列举当作已发生处罚' in t


def test_actual_election_results_cross_page_keep_independent_categories():
    pages=[{'page':2,'text':'关于公司董事会换届选举非独立董事的议案\n表决结果：通过。'},
           {'page':3,'text':'赵一先生 4,445 90.71 279 85.56 当选\n关于公司董事会换届选举独立董事的议案\n表决结果：通过。\n钱二女士 4,872 99.42 314 96.10 当选'}]
    r=appointments(pages,'公司董事会2026年9月29日')
    assert [(x['entity'],x['role'],x['page']) for x in r]==[('赵一','非独立董事',3),('钱二','独立董事',3)]


def test_new_director_class_replaces_prior_term_instead_of_silent_merge():
    old=roster_rows([roster_page(role='独立董事')],'2025年年度报告')
    pages,raw=announcement('董事会同意选举赵一先生为公司董事长。')
    new=appointments(pages,raw);roles=latest_roles(old+new)
    assert roles[0][1][0]['role']=='董事长' and not any(r['role']=='独立董事' for _,rs in roles for r in rs)


def test_partial_executive_appointment_does_not_erase_concurrent_board_role():
    old=roster_rows([roster_page(role='董事、总裁')],'2025年年度报告')
    pages,raw=announcement('董事会同意聘任赵一先生为公司总裁。')
    roles=latest_roles(old+appointments(pages,raw));r=roles[0][1]
    assert {x['role'] for x in r}=={'董事','总裁'}
    assert next(x for x in r if x['role']=='董事')['as_of']=='2025-12-31'


def test_departed_position_not_displayed_as_current_but_other_role_preserved():
    p=roster_page('赵一','董事');p['tables'][0]+=[['','','','副总裁','离任','2020/1/1','2025/3/28']]
    r=latest_roles(roster_rows([p],'2025年年度报告'))
    assert [x['role'] for _,rows in r for x in rows]==['董事']


def test_role_specific_departure_reasons_and_merged_name_rows():
    p={'page':10,'text':'变动','tables':[[['姓名','担任的职务','类型','日期','原因'],['赵一','董事','离任','2025/3/28','工作安排变动'],['','副总裁','离任','2025/12/26','个人原因']]]}
    r=change_rows([p],'2025年年度报告')
    assert [(x['entity'],x['role'],x['reason']) for x in r]==[('赵一','董事','工作安排变动'),('赵一','副总裁','个人原因')]


def test_biography_anchored_to_exact_person_not_same_surname_or_search_preface():
    pages=[{'page':9,'text':'赵一先生，一九七零年出生，硕士学历。赵先生曾任甲公司总经理。钱二女士，博士。钱女士现任财务总监。'}]
    r=biography_rows(pages,{'赵一','钱二'},'2025年年度报告','青禾食品有限公司')
    assert len(r)==2 and '财务总监' not in r[0]['fact'] and '甲公司' not in r[1]['fact']


def test_explicit_family_relation_not_inferred_from_same_surname_or_number():
    rows=relationship_rows([{'page':9,'text':'赵一先生与赵二先生为兄弟关系；赵三先生关联企业36家。'}],{'赵一','赵二','赵三'},'2025年年度报告','青禾食品有限公司')
    assert len(rows)==1 and rows[0]['entity']=='赵一、赵二'


def test_other_unit_role_keeps_end_date_and_compensation_not_owner_control():
    p={'page':9,'text':'在其他单位任职情况','tables':[[['任职人员姓名','其他单位名称','在其他单位担任的职务','任期起始日期','任期终止日期','是否领取报酬津贴'],['赵一','甲投资有限公司','董事长','2020年1月1日','2025年12月31日','否']]]}
    r=outside_roles([p],'2025年年度报告')[0]
    assert r['end']=='2025-12-31' and r['remunerated']=='否' and '不推导控制权' in r['mode']


def test_wrong_issuer_source_title_or_parent_mention_cannot_authenticate():
    c,s=source('青禾食品包装有限公司');s['title']=c['source_title']='青禾食品有限公司2025年年度报告';s['content']+='其母公司青禾食品有限公司拥有丰富资源。'
    assert not package('青禾食品有限公司',(c,s))['facts']


@pytest.mark.parametrize('field,value',[('eligible_for_report',False),('source_entity_validation','rejected'),('entity_match','ambiguous')])
def test_rejected_card_never_admitted_by_whole_document_recovery(field,value):
    c,s=source();c[field]=value
    assert not package('青禾食品有限公司',(c,s))['facts']


def test_source_generated_snippet_not_actual_management_record():
    c,s=source();s['source_metadata']['content_kind']='search_snippet'
    assert not package('青禾食品有限公司',(c,s))['facts']


def test_primary_issuer_related_page_scope_recovered_and_mirrors_merged():
    a=source(i=1);b=source(i=2);a[0]['evidence_scope']='related_entity_context'
    p=package('青禾食品有限公司',a,b)
    assert p['diagnostic']['filters']['duplicate_claim']>0
    assert len([r for r in p['facts'] if r['kind']=='role'])==1


def test_sparse_or_budgeted_management_keeps_limits_and_no_clean_bill():
    c,s=source();s['source_metadata']['document_extraction']={'omitted_pages':12,'needs_ocr_pages':[9],'management_tables':{'pending_pages':[8]}}
    p=package('青禾食品有限公司',(c,s),limit=4100);t=render_management(p)
    assert management_errors(t,p) and '尚未执行OCR' in t and '不能写为企业未披露' in t
    assert '未发现任何派系斗争' not in t and '不能据此判断不存在风险' in t


def test_index_records_chapter_seven_recovered_role_instead_of_generated_claim():
    c,s=source();c['evidence_scope']='related_entity_context';p=package('青禾食品有限公司',(c,s));project=SimpleNamespace(target_name='青禾食品有限公司',target_type='company',company_management_package=p)
    t=render_management(p)+'\n\n## 13. 信息来源\n\n## 14. 后续研究建议\n待核验。'
    r=ResearchWorkflow.__new__(ResearchWorkflow)._append_company_claim_evidence_index(project,t,[c],total_traceable_sources=1,eligible_company_sources=0)
    assert '第七章原文核对' in r and '赵一' in r and '第 7 章' in r


def test_checked_management_chapter_survives_editor_and_no_unused_eids(monkeypatch):
    c,s=source();p=SimpleNamespace(target_name='青禾食品有限公司',title='青禾',target_type='company',industry='食品',description='',sources=[s]);a=CompanyReportAgent()
    monkeypatch.setattr(a,'_write_section',lambda *x,**kw:'');monkeypatch.setattr(a,'_write_summary',lambda *x,**kw:'## 1. 摘要\n摘要。');monkeypatch.setenv('COMPANY_REPORT_EDITOR_ENABLED','true')
    monkeypatch.setattr(a,'_edit_batched',lambda *x,**kw:'\n'.join(f'## {i}. 标题\n'+('关联企业36家证明管理层派系联盟。[E-FFFFFFFFFFFF]' if i==7 else '待核验。') for i in range(1,15)))
    t=a.generate(p,json.dumps({'facts':[c]}),'{}',lambda *x:'',lambda s,n:s[:n],lambda *x,**kw:None)
    ch=t.split('## 7.')[1].split('## 8.')[0]
    assert '赵一' in ch and '派系联盟' not in ch and 'FFFFFFFFFFFF' not in ch and '本章引用证据' not in ch


def test_later_departure_only_removes_that_position_not_other_jobs():
    p=roster_page(role='董事、副总裁、首席财务官');old=roster_rows([p],'2025年年度报告')
    q={'page':10,'text':'变动','tables':[[['姓名','担任的职务','类型','日期','原因'],['赵一','副总裁','离任','2026年4月28日','工作安排']]]}
    r=latest_roles(old+change_rows([q],'2026年半年度报告'))
    assert {x['role'] for _,rows in r for x in rows}=={'董事','首席财务官'}


def test_management_pdf_selector_retains_cross_page_roster_and_finite_part_time_pages(monkeypatch):
    import company_pdf
    captured=[]
    monkeypatch.setattr(company_pdf,'_extract_grids',lambda payload,pages,selected,name:captured.append((set(selected),name)) or {})
    pages=[{'page':n,'text':t} for n,t in [(1,'任期起始日期 任职状态'),(2,'续页'),(3,'其他文字'),(4,'在其他单位任职情况'),(5,'兼职续页'),(6,'董事报酬情况'),(7,'无关')]]
    company_pdf.extract_management_tables(b'fixture',pages)
    assert captured==[({1,2,4,5,6},'COMPANY_PDF_MANAGEMENT_MAX_PAGES')]


def test_appointment_term_is_literal_not_guessed_calendar_end_date():
    pages,raw=announcement('董事会同意聘任赵一先生为公司总裁，任期三年，自本次董事会审议通过之日起至本届董事会任期届满为止。')
    r=appointments(pages,raw)[0]
    assert r['end']=='任期三年，自本次董事会审议通过之日起至本届董事会任期届满为止' and '2029' not in r['end']


def test_table_preface_removed_without_losing_explicit_cousin_relationship():
    p={'page':10,'text':'上述股东关联关系或一致行动的说明1、赵二先生为赵一先生之表兄，持有甲公司股份。'}
    r=relationship_rows([p],{'赵一','赵二'},'2025年年度报告','青禾食品有限公司')
    assert len(r)==1 and r[0]['entity']=='赵二、赵一' and '表兄' in r[0]['fact']


def test_previous_biography_subject_cannot_contaminate_full_named_family_table():
    p={'page':10,'text':'周四先生，一九七零年出生，博士学历。上述股东关联关系或一致行动的说明赵二先生为赵一先生之表兄。'}
    r=relationship_rows([p],{'赵一','赵二','周四'},'2025年年度报告','青禾食品有限公司')
    assert len(r)==1 and '周四' not in r[0]['entity'] and r[0]['entity']=='赵二、赵一'


def test_unbound_abbreviated_subject_not_turned_into_edge_between_other_people():
    p={'page':10,'text':'周四先生，一九七零年出生。赵先生为钱二先生的兄长，与孙三先生为表兄弟。'}
    assert relationship_rows([p],{'周四','钱二','孙三'},'2025年年度报告','青禾食品有限公司')==[]
