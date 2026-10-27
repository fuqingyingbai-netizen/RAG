import json
import sys
from types import SimpleNamespace

import pytest

from report_agents.company_business import (
    HEADINGS,build_business_package,render_business,business_errors,
    revenue_rows,vector_financial_rows,project_rows,project_status,production_rows,operating_updates,timing_note,
)
from company_pdf import extract_business_tables
from report_agents.company_report_agent import CompanyReportAgent
from research_workflow import ResearchWorkflow
from research_strategies.company import CompanyResearchStrategy
from test_company_history import filing


def financial_page(value='120.00',unit='万元',*,page=10,prior='100.00',share='60.00%'):
    return {'page':page,'text':f'营业收入构成 单位：{unit}\n2025年 2024年',
            'tables':[[['','2025年','','2024年','','同比增减'],
                       ['','金额','占营业收入比重','金额','占营业收入比重',''],
                       ['分产品','','','','',''],['甲产品',value,share,prior,'50.00%','20.00%']]]}


def margin_table(value='120.00',margin='25.00%'):
    return [['','营业收入','营业成本','毛利率','营业收入比上年同期增减','营业成本比上年同期增减','毛利率比上年同期增减'],
            ['分产品','','','','','',''],['甲产品',value,'90.00',margin,'20.00%','25.00%','-3.00%']]


def project_page(progress='2025年6月完成样机试制。',goal='未来达到100GWh并实现全球领先。',*,page=20):
    return {'page':page,'text':'主要研发项目名称 项目目的 项目进展 拟达到的目标 预计影响',
            'tables':[[['主要研发项目名称','项目目的','项目进展','拟达到的目标','预计影响'],
                       ['新品甲','研究新工艺',progress,goal,'预计带来大量收入']]]}


def business_source(name='青禾食品有限公司',*,i=1,pages=None,year=2025):
    pages=pages if pages is not None else [financial_page(),project_page()]
    c,s=filing(name,'\n'+ '\n'.join(p['text'] for p in pages),i=i,year=year)
    s['source_metadata']['document_pages']=pages
    return c,s


def package(name,*pairs,**kw):
    return build_business_package({'facts':[p[0] for p in pairs]},name,[p[1] for p in pairs],**kw)


@pytest.mark.parametrize('name,unit',[('星河精密股份有限公司','千元'),('青禾食品有限公司','万元'),('Northstar Robotics Limited','USD')])
def test_other_company_business_retains_own_units_and_no_example_conclusions(name,unit):
    p=package(name,business_source(name,pages=[financial_page(unit=unit),project_page()]))
    t=render_business(p)
    assert all('### '+h in t for h in HEADINGS)
    assert '120.00'+unit in t and '比亚迪' not in t
    assert '100GWh' not in t and '预计带来大量收入' not in t
    assert business_errors(t,p)==[]


def test_vector_merged_sliver_cells_and_unit_not_misread_as_yuan():
    p=financial_page(unit='千元');p['tables'][0][3]=['甲产品',None,'120.00',None,'60.00%',None,'100.00','50.00%','20.00%']
    rows=vector_financial_rows([p],'2025年年度报告')
    assert len(rows)==1 and rows[0]['unit']=='千元' and rows[0]['value']=='120.00'


def test_main_business_table_uses_header_percent_units_and_literal_point_changes():
    text = '''主营业务分行业、分产品、分地区、分销售模式情况
单位：元 币种：人民币
主营业务分产品情况
分产品 营业收入 营业成本 毛利率（%）
营业收入比上年增减（%） 营业成本比上年增减（%） 毛利率比上年增减（%）
工业设备 120,000,000.00 90,000,000.00 25.00 20.00 25.00 减少 3.00 个百分点
服务 80,000,000.00 40,000,000.00 50.00 -10.00 -20.00 增加 5.00 个百分点
主营业务分地区情况的说明'''
    for name in ('远山设备股份有限公司', '青禾服务股份有限公司'):
        packet = package(name, business_source(name, pages=[{'page': 10, 'text': text}]))
        rows = [r for r in packet['facts'] if r['kind'] == 'margin']
        assert len(rows) == 2
        assert rows[0]['entity'] == '工业设备'
        assert rows[0]['margin'] == '25.00%' and rows[0]['currency'] == '人民币'
        assert rows[0]['revenue_yoy'] == '20.00%'
        assert rows[0]['margin_change_source'] == '减少3.00个百分点'
        assert rows[1]['cost_yoy'] == '-20.00%'
        assert rows[0]['evidence_quote'] in text
        assert rows[0]['context_quote'] in text
        assert '毛利率（%）' in rows[0]['context_quote']
        assert business_errors(render_business(packet), packet) == []
    wrapped=text.replace('毛利率比上年增减（%）', '毛利率比上年增减\n（%）').replace('工业设备 ', '工业设\n备 ')
    from report_agents.company_business import main_business_margin_rows
    rows=main_business_margin_rows([{'page':10,'text':wrapped}], '2025年年度报告')
    assert rows[0]['entity']=='工业设备' and rows[0]['evidence_quote'] in wrapped


def test_main_business_table_does_not_guess_a_percent_unit_or_parse_plans():
    from report_agents.company_business import main_business_margin_rows
    raw = '''主营业务分产品情况
单位：元 币种：人民币
分产品 营业收入 营业成本 毛利率
营业收入比上年增减 营业成本比上年增减 毛利率比上年增减
工业设备 120,000,000.00 90,000,000.00 25.00 20.00 25.00 减少 3.00 个百分点'''
    assert main_business_margin_rows([{'page': 10, 'text': raw}], '2025年年度报告') == []
    plan = raw.replace('主营业务分产品情况', '预计主营业务分产品情况').replace('毛利率\n', '毛利率（%）\n')
    assert main_business_margin_rows([{'page': 10, 'text': plan}], '2025年年度报告') == []


def test_reversed_year_columns_keep_current_and_comparison():
    p=financial_page();p['tables'][0][0]=['','2024年','','2025年','','同比增减']
    r=vector_financial_rows([p],'2025年年度报告')[0]
    assert (r['value'],r['previous_value'],r['share'])==('100.00','120.00','50.00%')


def test_interim_current_prior_header_not_full_year():
    p=financial_page();p['tables'][0][0]=['','本报告期','','上年同期','','同比增减']
    r=vector_financial_rows([p],'2026年半年度报告')[0]
    assert r['period']=='2026年半年度报告' and r['previous_period']=='2025年半年度报告'


@pytest.mark.parametrize('bad',['营业收入构成 2025年 2024年','营业收入构成 单位：未知 2025年 2024年'])
def test_unknown_currency_not_filled_as_yuan(bad):
    p=financial_page();p['text']=bad
    assert vector_financial_rows([p],'2025年年度报告')==[]


def test_flat_text_fallback_bounded_and_header_required():
    raw='营业收入构成 单位：万元\n2025年 2024年\n金额 占营业收入比重 金额 占营业收入比重 同比增减\n分产品\n甲产品 120.00 60.00% 100.00 50.00% 20.00%\n（2）其他表乙产品999.0099%111.0011%20%'
    r=revenue_rows(raw,'2025年年度报告')
    assert len(r)==1 and r[0]['entity']=='甲产品' and r[0]['unit']=='万元'
    assert revenue_rows(raw.replace('2025年 2024年','无年份'),'2025年年度报告')==[]


def test_margin_continuation_on_next_physical_page_keeps_product_dimension():
    p=financial_page();p['tables'].append(margin_table()[:2])
    q={'page':11,'text':'原表续页','tables':[[margin_table()[2]]]}
    r=vector_financial_rows([p,q],'2025年年度报告')
    m=next(x for x in r if x['kind']=='margin')
    assert m['dimension']=='分产品' and m['unit']=='万元' and m['page']==11


def test_margin_join_requires_same_unit_period_entity_and_amount():
    name='青禾食品有限公司';p=financial_page();p['tables'].append(margin_table(value='130.00'))
    t=render_business(package(name,business_source(name,pages=[p])))
    revenue=t.split('### 生产与销售')[0]
    assert '毛利率25.00%' not in revenue


def test_margin_cross_page_citation_includes_actual_metric_page():
    name='青禾食品有限公司';p=financial_page();p['tables'].append(margin_table()[:2]);q={'page':11,'text':'续页','tables':[[margin_table()[2]]]}
    t=render_business(package(name,business_source(name,pages=[p,q])))
    assert '毛利率25.00%' in t and '物理页11' in t


def test_product_and_industry_views_are_not_added_or_repeated():
    name='青禾食品有限公司';p=financial_page();p['tables'][0]+=[['分行业','','','','',''],['制造业','120.00','60.00%','100.00','50.00%','20.00%']]
    t=render_business(package(name,business_source(name,pages=[p])))
    assert '分产品：甲产品' in t and '分行业：制造业' not in t and '240.00' not in t


def test_project_progress_not_goals_and_postperiod_release_not_annual_completion():
    p=project_page(progress='2026 年 3 月 5 日发布新品，计划后续扩产。')
    r=project_rows([p],'2025年年度报告')[0]
    assert r['after_period'] and '并存' in r['status'] and '100GWh' not in r['fact']


def test_explicit_cross_page_project_progress_stitched_without_goal_contamination():
    p=project_page(progress='2025年12月30日，一期生');q={'page':21,'text':'原表续页','tables':[[['','','产线通线，一期产能14GWh，远期规划40GWh。','未来零失效','预计市场第一']]]}
    r=project_rows([p,q],'2025年年度报告')
    assert len(r)==1 and r[0]['pages']==[20,21] and '14GWh' in r[0]['progress']
    assert '未来零失效' not in r[0]['progress'] and '并存' in r[0]['status']


def test_unrelated_five_column_table_after_rd_section_not_project():
    p=project_page();q={'page':21,'text':'公司研发人员情况','tables':[[['销售部','100','80','20','25%']]]}
    assert len(project_rows([p,q],'2025年年度报告'))==1


@pytest.mark.parametrize('text,expected',[
    ('完成预研，达到A样，预 计2026年上市。','并存'),
    ('计划生产40GWh。','计划／拟议'),
    ('尚未完成量产。','尚未完成'),
    ('2025年已量产，计 划搭载更多产品。','并存'),
    ('2025年10月发布产品。','发布/上市'),
])
def test_project_stage_including_wrapped_plan_words(text,expected):
    assert expected in project_status(text)


def production_page(monthly=False):
    header=['','产量','销量','本月','去年同期','本年累计','去年累计','累计同比'] if monthly else ['','快报产量','快报销量','本报告期','上年同期']
    data=['合计','100','90','1000','900','11.11%','80','70','800','750','6.67%'] if monthly else ['合计','100','90','11.11%','80','70','14.29%']
    return {'page':1,'text':'单位：辆 产能状况指报告期产量，单位为辆。','tables':[[header,data]]}


def test_capacity_named_actual_production_not_design_capacity_or_utilization():
    rows=production_rows([production_page()],'2025年年度报告')
    assert rows[0]['produced']=='100' and rows[0]['sold']=='80' and '指报告期产量' in rows[0]['capacity_note']
    name='青禾食品有限公司';t=render_business(package(name,business_source(name,pages=[production_page()])))
    assert '不作为设计产能' in t and '100%利用率' in t and '利用率100%' not in t


def test_monthly_and_cumulative_columns_remain_separate():
    r=production_rows([production_page(True)],'2026年9月')[0]
    assert (r['sold'],r['cumulative_sold'],r['sales_yoy'])==('80','800','6.67%')
    assert '审计' in r['mode']


def test_duplicate_total_and_supercategory_not_repeated_or_summed():
    name='青禾食品有限公司';p=production_page(True);row=p['tables'][0][1];p['tables'][0].append(['全部产品']+row[1:])
    c,s=business_source(name,pages=[p]);s['content']=name+'2026年9月产销快报\n'+p['text']
    b=package(name,(c,s));assert len(b['facts'])==1 and b['facts'][0]['entity']=='合计'


def test_wrong_issuer_subsidiary_and_search_preface_not_operating_evidence():
    name='青禾食品有限公司';c,s=business_source('青禾食品包装有限公司');s['content']+='与'+name+'开展合作。';c['source_title']=s['title']=name+'年报'
    assert not package(name,(c,s))['facts']
    c,s=business_source(name);s['source_metadata']['content_kind']='search_snippet'
    assert not package(name,(c,s))['facts']


@pytest.mark.parametrize('field,value',[('eligible_for_report',False),('source_entity_validation','rejected'),('entity_match','ambiguous')])
def test_rejected_evidence_not_recovered_as_financial_data(field,value):
    name='青禾食品有限公司';c,s=business_source(name);c[field]=value
    assert not package(name,(c,s))['facts']


def test_verified_primary_issuer_recovers_page_misclassified_as_context():
    name='青禾食品有限公司';c,s=business_source(name);c['evidence_scope']='industry_context'
    assert package(name,(c,s))['facts']


def test_rating_forecast_not_issuer_actual_and_generated_card_not_used():
    name='青禾食品有限公司';c,s=business_source(name);s['url']=c['source_url']='https://rating.test/report';s['content']='评级机构预计'+name+'2025年收入120万元。';c['fact']='收入9000万元。'
    assert not package(name,(c,s))['facts']


def test_exact_mirrors_dedup_but_same_period_conflicts_and_sources_retained():
    name='青禾食品有限公司';a=business_source(name,i=1,pages=[financial_page()]);b=business_source(name,i=2,pages=[financial_page()]);c=business_source(name,i=3,pages=[financial_page(value='200.00')])
    p=package(name,a,b,c);t=render_business(p)
    assert len(p['facts'])==2 and p['conflicts'] and '120.00' in t and '200.00' in t
    assert all(e in t for e in ('E-000000000001','E-000000000002','E-000000000003'))
    assert '差异待核' in t and p['diagnostic']['filters']['duplicate_claim']==1


def test_missing_document_pages_ocr_and_budget_do_not_claim_no_disclosure():
    name='青禾食品有限公司';c,s=business_source(name)
    s['source_metadata']['document_extraction']={'omitted_pages':135,'needs_ocr_pages':[4], 'business_tables':{'pending_pages':[2]}}
    p=package(name,(c,s),limit=3800)
    assert len(json.dumps(p['facts'],ensure_ascii=False))<300
    t=render_business(p);assert '尚未覆盖全文' in t and '未实际执行OCR' in t and '不等于企业未披露' in t
    assert business_errors(t,p)


def test_missing_vector_library_marks_pending_not_ocr_success(monkeypatch):
    monkeypatch.setitem(sys.modules,'pdfplumber',None)
    d=extract_business_tables(b'fixture',[{'page':1,'text':'营业收入构成'}])
    assert d=={'method':'library_unavailable','processed_pages':[],'pending_pages':[1]}


def test_vector_selected_pages_and_empty_grids_are_diagnostic(monkeypatch):
    class Page:
        page_number=1
        def extract_tables(self):return []
        def close(self):pass
    class Doc:
        pages=[Page()]
        def __enter__(self):return self
        def __exit__(self,*args):pass
    captured=[]
    monkeypatch.setitem(sys.modules,'pdfplumber',SimpleNamespace(open=lambda payload,**kw:captured.append(kw) or Doc()))
    pages=[{'page':1,'text':'营业收入构成'},{'page':2,'text':'续页'},{'page':3,'text':'普通说明'}]
    monkeypatch.setenv('COMPANY_PDF_TABLE_MAX_PAGES','1')
    d=extract_business_tables(b'fixture',pages)
    assert captured==[{'pages':[1]}] and d['pending_pages']==[2]
    assert pages[0]['tables']==[] and d['method']=='pdf_vector_grid'


def test_source_index_retains_recovered_business_metric_and_period():
    name='青禾食品有限公司';c,s=business_source(name,pages=[financial_page()]);c['evidence_scope']='industry_context'
    b=package(name,(c,s));p=SimpleNamespace(target_name=name,target_type='company',company_business_package=b)
    t=render_business(b)+'\n\n## 13. 信息来源\n\n## 14. 后续研究建议\n待核验。'
    result=ResearchWorkflow.__new__(ResearchWorkflow)._append_company_claim_evidence_index(p,t,[c],total_traceable_sources=1,eligible_company_sources=0)
    index=result.split('## 13.')[1]
    assert '第六章原文核对' in index and '120.00万元' in index and '第 6 章' in index


def test_sixth_chapter_editor_cannot_replace_checked_values_or_append_eids(monkeypatch):
    name='青禾食品有限公司';c,s=business_source(name)
    p=SimpleNamespace(target_name=name,title=name,target_type='company',industry='食品',description='',sources=[s]);a=CompanyReportAgent()
    monkeypatch.setattr(a,'_write_section',lambda *x,**kw:'');monkeypatch.setattr(a,'_write_summary',lambda *x,**kw:'## 1. 摘要\n摘要。')
    monkeypatch.setenv('COMPANY_REPORT_EDITOR_ENABLED','true')
    monkeypatch.setattr(a,'_edit_batched',lambda *x,**kw:'\n'.join(f'## {i}. 章节\n'+('计划产能100GWh已经全部达产。[E-FFFFFFFFFFFF]' if i==6 else '待核验。') for i in range(1,15)))
    result=a.generate(p,json.dumps({'facts':[c]}),'{}',lambda *x:'',lambda s,n:s[:n],lambda *x,**kw:None)
    chapter=result.split('## 6.')[1].split('## 7.')[0]
    assert '120.00万元' in chapter and '全部达产' not in chapter and 'FFFFFFFFFFFF' not in chapter and '本章引用证据' not in chapter
    assert p.company_business_diagnostic['degraded'] is False


def test_sparse_sixth_chapter_keeps_specific_gaps_after_evidence_marking():
    p=build_business_package({'facts':[]},'青禾食品有限公司',[]);t=render_business(p)
    result=CompanyReportAgent._ensure_section_evidence_markers(t,{6:[]})
    assert '设计产能' in result and '尚未取得' in result and business_errors(t,p)


def test_business_queries_cover_periods_progress_and_execution():
    qs=' '.join(q for m,q in CompanyResearchStrategy.query_templates if m=='主营业务真实经营情况核验')
    assert all(s in qs for s in ['营业收入构成','拟达到的目标','本年累计','回款'])


def test_original_report_period_overrides_misleading_retrieval_title():
    name='青禾食品有限公司';c,s=business_source(name);c['source_title']=s['title']=name+'2026年半年度报告'
    assert {r['period'] for r in package(name,(c,s))['facts']}=={'2025年年度报告'}
    assert not vector_financial_rows([financial_page()],'2026年年度报告')


def test_foreign_scaled_currency_not_read_as_unscaled_usd():
    row=vector_financial_rows([financial_page(unit='USD million')],'2025年年度报告')[0]
    assert row['unit']=='USD million'


def test_final_project_on_same_page_as_rd_staff_heading_is_retained():
    p=project_page();q=project_page('2025年12月完成产线小批试制。',page=21)
    q['text']='新品甲的项目目的与进展。'*20+'公司研发人员情况'
    q['tables'][0][1][0]='新品乙'
    r=project_rows([p,q],'2025年年度报告')
    assert {x['entity'] for x in r}=={'新品甲','新品乙'}


def test_project_continuation_with_purpose_text_uses_only_progress_cell():
    p=project_page(progress='2025年6月完成');q={'page':21,'text':'续页','tables':[[['','项目目的续写','产线试制，计划下期投产。','目标100GWh','未来收入1亿']]]}
    r=project_rows([p,q],'2025年年度报告')[0]
    assert '产线试制' in r['progress'] and '项目目的' not in r['progress'] and '100GWh' not in r['progress']


def test_project_selection_covers_tail_pages_not_only_first_business_line():
    name='青禾食品有限公司';pages=[]
    for i in range(15):
        p=project_page('2025年6月完成样机试制。',page=20+i//5);p['tables'][0][1][0]='新品'+str(i);pages.append(p)
    b=package(name,business_source(name,pages=pages));r=[x for x in b['facts'] if x['kind']=='project']
    assert len(r)==12 and {20,21,22}<={x['page'] for x in r}


def test_conflicting_margin_values_not_silently_chosen_for_revenue_join():
    name='青禾食品有限公司';p=financial_page();p['tables'].append(margin_table(margin='25.00%'));q=financial_page();q['tables'].append(margin_table(margin='18.00%'))
    t=render_business(package(name,business_source(name,i=1,pages=[p]),business_source(name,i=2,pages=[q])))
    assert '25.00%' in t and '18.00%' in t and '来源差异待核' in t
    assert '毛利率25.00%' not in t.split('### 生产与销售')[0]


def test_literal_issuer_factory_update_not_inferred_from_wiki_or_forecast():
    name='青禾食品有限公司'
    raw='七月，本集团工厂实现首件产品下线，已向客户交付90台设备，后续规划新增1条产线，但未披露设计年产能。'
    r=operating_updates([{'page':26,'text':raw}],'2025年年度报告',name)
    assert len(r)==1 and r[0]['fact']==raw and '并存' in r[0]['status']
    assert operating_updates([{'page':26,'text':raw.replace('本集团','竞品集团')}],'2025年年度报告',name)==[]


def test_product_subcategories_resolved_only_when_both_years_reconcile():
    p=financial_page();t=p['tables'][0];t[3]=['主业务','120.00','60.00%','100.00','50.00%','20.00%']
    t += [['其中：甲业务','50.00','25%','40.00','20%','25%'],['乙业务','70.00','35%','60.00','30%','16.67%'],['其他','80.00','40%','100.00','50%','-20%']]
    r=vector_financial_rows([p],'2025年年度报告')
    assert r[1]['parent_entity']==r[2]['parent_entity']=='主业务' and 'parent_entity' not in r[3]
    t[5][3]='55.00'
    r=vector_financial_rows([p],'2025年年度报告')
    assert r[1]['parent_entity']=='主业务' and 'parent_entity' not in r[2]


def test_chinese_pdf_word_wrap_does_not_split_line_or_model_names():
    p=project_page(progress='2025 年在郑州园 区线与济南云巴市 政线运行验证。')
    r=project_rows([p],'2025年年度报告')[0]
    assert '郑州园区线' in r['progress'] and '济南云巴市政线' in r['progress']


def test_interim_after_period_month_not_rewritten_as_first_half_completion():
    assert '年份按原文核对' in timing_note('七月，本集团工厂第10万台下线。','2026年半年度报告')
    assert '报告期后日期' in timing_note('2026年7月5日正式发布。','2026年半年度报告')
    assert timing_note('2025年7月完成投产。','2026年半年度报告')==''
    assert timing_note('2026年3月完成投产。','2026年半年度报告')==''
    assert timing_note('2026年12月31日完成投产。','2026年年度报告')==''
