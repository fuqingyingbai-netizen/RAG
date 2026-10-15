import json
from types import SimpleNamespace

import pytest

import company_pdf
from company_pdf import extract_company_pdf
from report_agents.company_reputation import counterparty_excerpt
from report_agents.company_evidence import source_body,document_pages
from report_agents.company_reputation import (
    HEADINGS,aliases_for_target,build_reputation_package,render_reputation,reputation_errors,
    survey_table_rows,_market_rows,
)
from report_agents.company_report_agent import CompanyReportAgent
from research_workflow import ResearchWorkflow
import research_workflow
import web_search
from test_company_history import filing


def table_rows(years=(2024,2025),value='74.88',prior='73.06'):
    return f'指标 单位 {years[0]}年 {years[1]}年\n员工满意度分数 分数 {prior}（满分100分） {value}（满分100分）\n员工敬业度分数 分数 4（满分5分） 4（满分5分）'


def package(name,*pairs,**kwargs):
    return build_reputation_package({'facts':[p[0] for p in pairs]},name,[p[1] for p in pairs],**kwargs)


def survey(name,raw=None,*,i=1):
    raw=raw or table_rows()
    c,s=filing(name,'',i=i)
    s['source_metadata']['document_pages']=[{'page':155,'text':raw}]
    s['content']+=raw
    return c,s


@pytest.mark.parametrize('name',['星河精密股份有限公司','青禾食品有限公司','Northstar Robotics Limited'])
def test_other_companies_survey_retains_own_values_and_no_example_conclusions(name):
    p=package(name,survey(name));text=render_reputation(p)
    assert all('### '+h in text for h in HEADINGS)
    assert '74.88（满分100分）' in text and '4（满分5分）' in text
    assert '74.88%' not in text and '比亚迪' not in text and '绝对领先' not in text
    assert reputation_errors(text,p)==[]


def test_customer_nps_definition_complaint_scope_and_missing_prior_value():
    name='青禾食品有限公司'
    raw=('指标 单位 2024年 2025年\n客户满意度 % 95以上 97.4\n接获的客户投诉数目 宗 43,392 45,177\n'
         '客户投诉回应率 % / 98.41\n客户投诉解决率 % 96 96\n'
         '76 包含售后阶段对产品和服务质量的投诉；客户投诉回应率为400服务电话的服务指标统计\n77 客户满意度指客户服务售后NPS')
    text=render_reputation(package(name,survey(name,raw)))
    assert '95%以上' in text and '95以上%' not in text
    assert '45,177宗' in text and '客户服务售后NPS' in text and '400服务电话' in text
    assert '2024年 /%' not in text  # Missing is never a percentage value.


def test_survey_header_reversed_and_parenthetical_line_wrapped():
    raw=table_rows(years=(2025,2024),value='73.06',prior='74.88').replace('满分100分','满分100\n分')
    r=survey_table_rows({'page':9,'text':raw})[0]
    assert r['period']=='2025年' and r['value']=='74.88（满分100分）'


def test_three_year_table_selects_latest_two_without_losing_column_alignment():
    raw='指标 单位 2023年 2024年 2025年\n客户满意度 % 80 90 95'
    r=survey_table_rows({'page':1,'text':raw})[0]
    assert (r['period'],r['value'],r['previous_period'],r['previous_value'])==('2025年','95','2024年','90')


def test_wrapped_superscript_is_a_footnote_not_a_complaint_value():
    raw='指标 单位 2022年 2023年 2024年\n接获关于产品及服务的投诉数\n2\n个 109 103 171\n接获关于产品及服务的投诉处理率\n3\n% 100.00 100.00 100.00'
    rows=survey_table_rows({'page':55,'text':raw})
    assert [(r['value'],r['previous_value']) for r in rows]==[('171','103'),('100.00','100.00')]


def test_financial_company_customer_scope_not_expanded_to_entire_group():
    name='星河证券股份有限公司'
    raw='指标 单位 2022年 2023年 2024年\n客户满意度 % 99.16 99.19 99.17\n客户满意度调查次数 次 335,730 402,442 405,603\n注1：客户服务与权益相关数据的统计口径为公司总部财富管理业务。'
    text=render_reputation(package(name,survey(name,raw)))
    assert '总部财富管理业务' in text and '405,603次' in text and '405,603人' not in text


def test_missing_header_unbound_flat_integer_cells_and_absent_value_not_guessed():
    assert survey_table_rows({'page':1,'text':'员工满意度分数 分数 73.06 74.88'})==[]
    assert survey_table_rows({'page':1,'text':'指标 单位 2024年 2025年\n客户投诉解决率 % 9696'})==[]
    assert survey_table_rows({'page':1,'text':'指标 单位 2024年 2025年\n客户满意度 % 98 /'})==[]


def test_same_period_survey_conflicts_retained_not_overwritten():
    name='青禾食品有限公司'
    p=package(name,survey(name,table_rows(value='74.88'),i=1),survey(name,table_rows(value='20.00'),i=2))
    text=render_reputation(p)
    assert '74.88' in text and '20.00' in text and '差异' in text
    assert '[E-000000000001]' in text and '[E-000000000002]' in text


def test_generated_preface_cannot_replace_document_or_create_metrics():
    name='青禾食品有限公司'
    c,s=filing(name,'公司汽车分部收入6486.46亿元。')
    c.update(fact='公司总收入6486.46亿元，研发占比9.78%。',evidence_quote='公司总收入6486.46亿元。')
    text=render_reputation(package(name,(c,s)))
    assert '9.78%' not in text and '总收入6486.46' not in text


def test_company_statement_not_employee_interview_and_no_phantom_interviews():
    name='青禾食品有限公司'
    text=render_reputation(package(name,survey(name)))
    assert '非独立访谈' in text and '尚无本项目已完成的竞品访谈' in text
    assert '访谈证实' not in text and '客户广泛认可' not in text


def test_subsidiary_research_mentioning_parent_not_parent_research_view():
    name='青禾食品股份有限公司'
    c,s=filing(name,'来源：甲证券\n我们认为，公司的产品竞争力有望随青禾食品渠道扩大而提升。')
    s['title']=c['source_title']='青禾食品包装：业务竞争力改善'
    assert not any(r['kind']=='research_view' for r in package(name,(c,s))['facts'])


def test_research_keeps_named_brand_and_historical_opinion_as_original():
    name='青禾食品股份有限公司'
    c,s=filing(name,'来源：甲证券\n发布时间：2024/09/27\n与主要竞品相比，我们认为公司旗下甲品牌营销渠道仍有差距。')
    s['title']=c['source_title']='2024年青禾食品研究报告：品牌渠道'
    p=package(name,(c,s));r=p['facts'][0]
    assert r['mode']=='券商研究观点（转载）' and r['period']=='2024-09-27'
    assert '甲品牌' in r['fact'] and '2024-09-27' in render_reputation(p)


def market_text(month='July',target='NSR',peer='ABC',target_value='14.7',peer_value='39.9'):
    return (f'January-{month} 2026 Global EV Battery Usage. Total battery usage in electric vehicles (EV, PHEV, HEV) registered around the world reached 725.2 GWh. '
            f'{peer} maintained its lead. Its share rose 1.9 percentage points from 38.0% to {peer_value}%. '
            f'{target} posted 106.7 GWh. Its share fell 2.2 percentage points from 16.9% to {target_value}%. '
            'The two companies combined share was 54.6%.')


def test_market_comparison_keeps_current_not_prior_or_combined_share():
    rows=_market_rows(market_text(),{'NSR'})
    assert [(r['entity'],r['value']) for r in rows]==[('ABC','39.9%'),('NSR','14.7%')]
    assert all(r['period']=='2026年1—7月' for r in rows)
    assert '外供市场' in rows[0]['basis'] and '54.6%' not in {r['value'] for r in rows}


def test_updated_release_verbs_do_not_leave_the_benchmark_on_old_period():
    text=market_text('August').replace('NSR posted','NSR grew').replace('ABC maintained','ABC held')
    rows=_market_rows(text,{'NSR'})
    assert len(rows)==2 and all(r['period']=='2026年1—8月' for r in rows)


def test_industry_survey_cannot_become_company_score_or_service_nps_comparison():
    name='青禾食品有限公司';c,s=filing(name,'作者：质量协会\n发布于：2025-12-03 01:02\n协会发布2025年食品行业用户满意度测评结果。数据显示，2025年食品满意度指数达80分（满分100分），同比提升1分。调查覆盖多个地区，共收集有效调查样本25303个。')
    s['source_metadata'].update(publisher_role='independent_survey',scope_verified=True,evidence_scope='industry_context',industry_name='食品',publication_date='2025-12-03')
    p=package(name,(c,s));text=render_reputation(p)
    assert any(r['kind']=='industry_survey' for r in p['facts'])
    assert '未给出目标公司单独得分' in text and '公司满意度80分' not in text


def test_market_comparison_requires_period_population_and_target_peer_group():
    assert _market_rows(market_text().replace('January-July 2026',''),'NSR')==[]
    assert _market_rows(market_text().replace('EV, PHEV, HEV','BEV'),{'NSR'})==[]
    assert _market_rows(market_text(),{'ZZZ'})==[]


def test_english_alias_must_come_from_verified_issuer_filing_not_competitor():
    name='星河精密股份有限公司'
    c,s=filing(name,'公司的外文名称缩写（如有） NSR')
    assert 'NSR' in aliases_for_target(name,[s])
    s['content']='别家公司2025年年度报告。公司的外文名称缩写（如有） BAD'
    assert 'BAD' not in aliases_for_target(name,[s])


def test_latest_benchmark_uses_one_release_without_mixing_periods():
    name='Northstar Robotics Limited'
    c1,s1=filing(name,market_text('May'),i=1)
    c2,s2=filing(name,market_text('July'),i=2)
    c3,s3=filing(name,'公司的外文名称缩写（如有） NSR',i=3)
    p=package(name,(c1,s1),(c2,s2),(c3,s3))
    rows=[r for r in p['facts'] if r['kind']=='benchmark']
    assert len(rows)==2 and {r['period'] for r in rows}=={'2026年1—7月'}


def test_cooperation_is_counterparty_statement_not_endorsement_or_completed_sales():
    name='Northstar Robotics Limited'
    c,s=filing(name,'Northstar Robotics Limited and Partner Ltd. jointly developed a product. It will be sold in the future.')
    s['source_metadata'].update(publisher_role='counterparty_official',publisher_verified=True,publication_date='2022-10-24')
    p=package(name,(c,s));text=render_reputation(p)
    assert 'Partner Ltd. jointly developed' in text and '2022-10-24' in text
    assert '信任背书已确认' not in text and '已实现销售' not in text
    s['source_metadata']['publisher_verified']=False
    assert not any(r['kind']=='partner_statement' for r in package(name,(c,s))['facts'])


def test_unknown_citation_modified_judgment_and_empty_package_fail():
    name='青禾食品有限公司';p=package(name,survey(name))
    assert reputation_errors(render_reputation(p)+'公司市场绝对领先。[E-FFFFFFFFFFFF]',p)
    p=package(name);assert reputation_errors(render_reputation(p),p)


def source(**changes):
    return SimpleNamespace(id=1,title='青禾食品股份有限公司报告',url='https://evidence.test/report',source_type='news',
                           credibility_score=80,**{'content':'青禾食品股份有限公司汽车分部收入6486.46亿元。',
                                                'summary':'概要要点：公司总收入6486.46亿元。','source_metadata':{},**changes})


def test_fast_company_cleaning_original_precedes_and_excludes_generated_summary():
    s=source();project=SimpleNamespace(target_type='company',target_name='青禾食品股份有限公司')
    w=ResearchWorkflow.__new__(ResearchWorkflow);r=w._fast_clean_sources([s],project=project,max_chars_per_source=80)['facts'][0]
    assert '汽车分部收入' in r['fact'] and '概要要点' not in r['fact'] and r['text_origin']=='retrieved_content'


def test_summary_only_retained_as_discovery_but_not_hard_fact_or_llm_input():
    s=source(content='');w=ResearchWorkflow.__new__(ResearchWorkflow);p=SimpleNamespace(target_type='company',target_name='青禾食品股份有限公司')
    r=w._fast_clean_sources([s],project=p)['facts'][0]
    assert r['eligible_for_report'] is False and r['eligible_for_risk_scoring'] is False
    assert r['claim_type']=='discovery_summary'
    assert w._source_context_batches([s],target_type='company')==['']
    ledger=w._build_evidence_ledger([s],[s],target_type='company')[0]
    assert ledger['status']=='discovery_only' and ledger['usable_for_hard_fact'] is False


def test_failed_fetch_abstract_in_content_cannot_masquerade_as_original():
    s=source(content='搜索生成回答',summary='搜索生成回答',source_metadata={'fetch_status':'fetch_timeout'})
    assert source_body(s)==('搜索生成回答','discovery_summary')
    s=source(content='摘要另有一些补写',source_metadata={'content_kind':'summary_only'})
    assert source_body(s)[1]=='discovery_summary'


def test_completed_ocr_only_and_physical_page_recovery():
    s=source(content='',source_metadata={'ocr_text':'原件字段','ocr_status':'pending'})
    assert source_body(s)[1]=='discovery_summary'
    s.source_metadata['ocr_status']='done';assert source_body(s)==('原件字段','completed_ocr')
    s=source(content='--- PDF page 155 ---\n表格原文');assert document_pages(s)==[{'page':155,'text':'表格原文'}]


def test_company_llm_quote_must_exist_in_original_and_extra_numbers_rejected():
    s=source();w=ResearchWorkflow.__new__(ResearchWorkflow);p=SimpleNamespace(target_type='company',target_name='青禾食品股份有限公司',sources=[s])
    good={'fact':s.content,'evidence_quote':s.content,'source_url':s.url,'entity_match':'confirmed'}
    assert w._sanitize_structured_facts([good],p)
    assert not w._sanitize_structured_facts([dict(good,evidence_quote=s.summary)],p)
    assert not w._sanitize_structured_facts([dict(good,fact=s.content+'研发占比9.78%。')],p)


def test_company_evidence_policy_does_not_change_industry_cleaning_order():
    s=source();w=ResearchWorkflow.__new__(ResearchWorkflow);p=SimpleNamespace(target_type='industry',target_name='食品')
    r=w._fast_clean_sources([s],project=p)['facts'][0]
    assert r['fact'].startswith('概要要点')


class Page:
    def __init__(self,index):self.index=index
    def extract_text(self,**kwargs):return f'物理页{self.index} 公司原始正文完整保留表格与注释，具有足够可读文字，并不是扫描页。'+('员工满意度 指标 2025年 2024年' if self.index==155 else '')


def fake_reader(monkeypatch,count):
    monkeypatch.setattr(company_pdf,'PdfReader',lambda _:SimpleNamespace(is_encrypted=False,pages=[Page(i) for i in range(1,count+1)]))


def test_company_pdf_keeps_page_155_and_layout_beyond_old_40_page_limit(monkeypatch):
    fake_reader(monkeypatch,182);p=extract_company_pdf(b'fixture')
    assert p['pages']==182 and len(p['document_pages'])==182
    assert p['document_pages'][154]['page']==155 and 'layout_text' in p['document_pages'][154]
    assert 'PDF page 155' in p['content'] and p['document_extraction']['complete'] is True


def test_company_pdf_does_not_silently_omit_tail_of_435_page_report(monkeypatch):
    fake_reader(monkeypatch,435);p=extract_company_pdf(b'fixture')
    assert p['pages']==435 and p['document_pages'][-1]['page']==435
    assert p['document_extraction']['omitted_pages']==0
    assert p['document_extraction']['complete'] is True


def test_cooperation_passage_deduplicates_mobile_copy_without_losing_new_product():
    a='The Alpha sedan was jointly developed by Example Motors and Vendor Ltd.'
    b='The Beta vehicle was jointly developed by Example Motors and Other Ltd.'
    result=counterparty_excerpt(a+' '+a+' '+b,{'Example Motors'})
    assert result==[a,b]


def test_cooperation_preserves_legal_company_suffix_and_drops_repeated_page_title():
    sentence='The vehicle was jointly developed by Example Motors and Partner Motor Co. Ltd. (Partner).'
    raw=sentence+' '+sentence+'\n\nNewsroom - A vehicle developed through collaboration with Example Motors'
    assert counterparty_excerpt(raw,{'Example Motors'})==[sentence]


def test_company_pdf_page_limit_reports_omissions_without_claiming_complete(monkeypatch):
    fake_reader(monkeypatch,182);monkeypatch.setenv('COMPANY_PDF_MAX_PAGES','40')
    p=extract_company_pdf(b'fixture')
    assert p['document_extraction']['omitted_pages']==142 and p['document_extraction']['complete'] is False


def test_empty_pdf_pages_mark_needs_ocr_not_ocr_done(monkeypatch):
    monkeypatch.setattr(company_pdf,'PdfReader',lambda _:SimpleNamespace(is_encrypted=False,pages=[SimpleNamespace(extract_text=lambda **kw:'')]))
    p=extract_company_pdf(b'fixture')
    assert p['document_extraction']['needs_ocr_pages']==[1] and p['document_extraction']['method']=='embedded_pdf_text'
    assert p['content']==''


def test_company_fetch_profile_retains_page_metadata_and_default_fetch_unchanged(monkeypatch):
    response=SimpleNamespace(content=b'%PDF-fixture',url='https://example.test/report.pdf',
                             headers={'Content-Type':'application/pdf'},raise_for_status=lambda:None)
    monkeypatch.setattr(web_search.requests,'get',lambda *a,**k:response)
    expected={'content':'原件第155页','pages':182,'document_pages':[{'page':155,'text':'原件第155页'}],
              'document_extraction':{'complete':True}}
    monkeypatch.setattr(company_pdf,'extract_company_pdf',lambda payload:expected)
    w=web_search.WebSearchProvider();monkeypatch.setattr(w,'_extract_pdf_text',lambda payload:('旧的默认提取',182))
    company=w._fetch_url_once(response.url,5,30000,'agent','desktop',document_profile='company')
    default=w._fetch_url_once(response.url,5,30000,'agent','desktop')
    assert company['document_pages']==expected['document_pages'] and company['content']=='原件第155页'
    assert default['content']=='旧的默认提取' and 'document_pages' not in default


def test_workflow_timeout_wrapper_forwards_company_profile_only_when_requested(monkeypatch):
    captured=[]
    monkeypatch.setattr(research_workflow.web_search_provider,'fetch_url',lambda *a,**k:captured.append(k) or {'status':'done','content':'原文'})
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    w._fetch_web_url_with_timeout('https://example.test/report.pdf',False,document_profile='company')
    w._fetch_web_url_with_timeout('https://example.test/report.pdf',False)
    assert captured==[{'allow_browser':False,'document_profile':'company'},{'allow_browser':False}]


def test_company_fallback_cleaning_cannot_restore_generated_preface():
    s=source();w=ResearchWorkflow.__new__(ResearchWorkflow);p=SimpleNamespace(target_type='company',target_name='青禾食品股份有限公司',sources=[s])
    result=w._fallback_clean(p)
    assert result['facts'][0]['fact']==s.content and s.summary not in result['facts'][0]['fact']


def test_survey_score_change_is_bounded_and_missing_full_pdf_is_explicit():
    name='青禾食品有限公司';c,s=survey(name)
    s['source_metadata']['document_extraction']={'omitted_pages':10,'needs_ocr_pages':[1]}
    p=package(name,(c,s));text=render_reputation(p)
    assert '差额1.82分' in text and '调查方法的一致性仍需核对' in text
    assert any('尚未覆盖全文' in x for x in p['information_gaps'])
    assert any('未实际执行OCR' in x for x in p['information_gaps'])


def test_recovered_metric_source_index_keeps_metric_unit_period_and_chapter():
    name='青禾食品有限公司';c,s=survey(name);c['evidence_scope']='industry_context'
    p=SimpleNamespace(target_name=name,target_type='company',company_reputation_package=package(name,(c,s)))
    text=render_reputation(p.company_reputation_package)+'\n\n## 13. 信息来源\n\n## 14. 后续研究建议\n待核验。'
    result=ResearchWorkflow.__new__(ResearchWorkflow)._append_company_claim_evidence_index(p,text,[c],total_traceable_sources=1,eligible_company_sources=0)
    index=result.split('## 13.')[1]
    assert '第五章原文核对' in index and '员工满意度分数' in index and '满分100分' in index and '第 5 章' in index


def test_checked_fifth_chapter_survives_editor_without_unused_citation_padding(monkeypatch):
    name='青禾食品有限公司';pair=survey(name)
    p=SimpleNamespace(target_name=name,title=name,target_type='company',industry='食品',description='',sources=[pair[1]])
    a=CompanyReportAgent();monkeypatch.setattr(a,'_write_section',lambda *x,**k:'')
    monkeypatch.setattr(a,'_write_summary',lambda *x,**k:'## 1. 摘要\n摘要。')
    monkeypatch.setenv('COMPANY_REPORT_EDITOR_ENABLED','true')
    monkeypatch.setattr(a,'_edit_batched',lambda *x,**k:'## 1. 摘要\n摘要。\n## 2. 工商\n待核验。\n## 3. 沿革\n待核验。\n## 4. 治理\n待核验。\n## 5. 口碑\n员工访谈证实普遍满意。[E-FFFFFFFFFFFF]\n## 6. 业务\n待核验。')
    text=a.generate(p,json.dumps({'facts':[pair[0]]}),'{}',lambda *x:'',lambda s,n:s[:n],lambda *x,**k:None)
    chapter=text.split('## 5.')[1].split('## 6.')[0]
    assert '74.88' in chapter and '员工访谈证实' not in chapter and 'FFFFFFFFFFFF' not in chapter
    assert '本章引用证据' not in chapter
