from copy import deepcopy
import re

import pytest

from report_agents.company_evidence import without_sequence_footers,annotate_page_notes
from report_agents.company_management import biography_rows
from report_agents.company_people import table_metrics,policy_rows
from report_agents.company_diligence import display_diligence_fact
from report_agents.company_delivery import source_excerpt,company_followup_rows,company_followup_plan
from research_workflow import ResearchWorkflow


def test_verified_page_number_sequence_does_not_become_a_biographical_headcount():
    pages=[{'page':15,'text':'赵一先生，硕士研究生学历。赵先生曾任研发负责人。\n14'},
           {'page':16,'text':'钱二女士，硕士研究生学历。钱女士历任财务负责\n15'},
           {'page':17,'text':'人等职，现任公司董事会秘书。\n16'}]
    original=deepcopy(pages)
    rows=biography_rows(pages,['赵一','钱二'],'2026-09-29','青禾制造有限公司')
    person=next(r for r in rows if r['entity']=='钱二')
    assert '财务负责人等职' in person['fact'] and '15人' not in person['fact']
    assert person['pages']==[16,17] and person['source_text_transformations']
    assert pages==original


def test_unproven_numbers_and_actual_personnel_numbers_are_not_deleted():
    pages=[{'page':1,'text':'负责管理16人。\n25'}, {'page':2,'text':'负责管理28人。\n29'}, {'page':3,'text':'负责管理36人。\n47'}]
    assert without_sequence_footers(pages)==pages


def test_pdf_object_order_can_put_proven_page_furniture_before_continuation_text():
    pages=[{'page':15,'text':'14\n赵一先生，硕士研究生学历。赵先生曾任研发负责人。'},
           {'page':16,'text':'15\n钱二女士，硕士研究生学历。钱女士历任财务负责'},
           {'page':17,'text':'16\n人等职，现任公司董事会秘书。'}]
    record=next(r for r in biography_rows(pages,['赵一','钱二'],'2026-09-29','青禾制造有限公司') if r['entity']=='钱二')
    assert '财务负责人等职' in record['fact'] and '16人' not in record['fact']
    assert any(c['edge']=='leading' for c in record['source_text_transformations'])


def test_same_page_note_definition_marks_reference_but_keeps_original_number():
    quote='我们建立双重采购36策略，并布局后备制造基地37，增强保障能力。'
    page={'page':113,'text':quote+'\n36 同一物料选择两家独立供应商以分散风险\n37 在原有基地外布局的备用制造基地'}
    assert annotate_page_notes(quote,[page])=='我们建立双重采购〔注36〕策略，并布局后备制造基地37，增强保障能力。'
    assert page['text'].startswith(quote)
    assert annotate_page_notes(quote,[{'page':1,'text':quote},{'page':2,'text':'36 同一物料选择两家独立供应商以分散风险'}])==quote


def test_metric_note_id_is_labelled_without_changing_value_or_original_quote():
    page={'page':158,'text':'指标 单位 2024年 2025年\n绩效管理制度\n75\n的员工覆盖率 % 100 100\n75 所有全职员工均纳入绩效评估制度范围'}
    row=table_metrics(page)[0]
    assert row['display_metric']=='绩效管理制度〔注75〕的员工覆盖率'
    assert row['value']=='100' and '75' in row['evidence_quote'] and '75' in row['source_metric']


@pytest.mark.parametrize('name',['青禾制造股份有限公司','星河科技股份有限公司'])
def test_pension_accounting_table_is_not_a_culture_practice(name):
    quote=name+'2026年半年度报告全文 138 合并财务报表主要项目注释 应付职工薪酬 设定提存计划列示期初余额本期增加本期减少期末余额 基本养老保险费 100 200 300 0 本集团的设定提存计划是按照当地政策要求，以员工工资为缴费基数按比例计提和缴纳。'
    assert policy_rows([{'page':139,'text':quote}],'2026年',name)==[]
    good=name+'建立全员绩效管理制度，实行公开晋升机制，为员工依法缴纳养老保险，并定期提供职业发展培训。'
    assert policy_rows([{'page':90,'text':good}],'2026年',name)


def test_goodwill_sentence_display_keeps_amount_date_and_raw_audit_excerpt():
    raw='年报87 INDEPENDENT AUDITOR’S REPORT జѓ Impairment assessments of goodwill൙П As at 31 December 2025, the net carrying amount of goodwill amounted to RMB4,361,657,000.'
    record={'kind':'purchase_accounting','fact':raw};saved=deepcopy(record)
    assert display_diligence_fact(record)=='As at 31 December 2025, the net carrying amount of goodwill amounted to RMB4,361,657,000.'
    assert record==saved


@pytest.mark.parametrize('cut',[18,20,23,27])
def test_index_excerpt_never_silently_changes_a_clipped_number(cut):
    text='公司公告已成功发行债券，发行总额人民币5,000,000,000元，按原公告核对。'
    excerpt=source_excerpt(text,cut)
    assert excerpt.endswith('…（节选）')
    prefix=excerpt.removesuffix('…（节选）')
    assert text.startswith(prefix)
    if prefix and prefix[-1].isdigit():assert not text[len(prefix):len(prefix)+1].isdigit()


def test_followup_covers_later_chapters_deduplicates_prefixes_and_preserves_originals():
    report='\n'.join(f'## {i}. 章节\n### 核验重点\n- 待核验重点：需核对第{i}章的具体材料和执行记录。\n- 待核验：需核对第{i}章的具体材料和执行记录。\n- 需补充第{i}章后续正式公告及原始文件。' for i in range(1,13))
    report+='\n## 14. 后续研究建议\n旧待核验段落。'
    rows=company_followup_rows(report)
    assert [r['chapter'] for r in rows]==list(range(1,13)) and all(len(r['items'])==2 for r in rows)
    workflow=ResearchWorkflow.__new__(ResearchWorkflow)
    result=workflow._consolidate_report_verification_gaps(report,target_type='company')
    assert result.split('## 14.')[0]==report.split('## 14.')[0]
    assert '第12章：' in result and '旧待核验段落' not in result
    assert workflow._consolidate_report_verification_gaps(result,target_type='company')==result


def test_followup_does_not_turn_generic_risk_disclaimer_into_a_task():
    report='## 11. 风险核查\n已取得的原件支持具体事项，尚未量化集团重大性保留待核验。\n### 核验重点\n- 需核对具体召回批次的整改凭证。'
    rows=company_followup_rows(report)
    assert len(rows)==1 and len(rows[0]['items'])==1 and '召回' in rows[0]['items'][0]
    assert 'OCR' in company_followup_plan('需对原页进行OCR/版面核对。')[0]
    assert company_followup_plan('平台风险扫描返回117条案件，需调取裁判案卷核验。')[1]=='高'
    assert 'OCR' not in company_followup_plan('平台风险扫描返回117条案件，需调取裁判案卷核验。')[0]


def test_company_postprocess_does_not_rewrite_quoted_legal_or_performance_terms():
    report='## 9. 司法\n原文记载：违反《公司法》第十条；具体履行状态为未履约。\n## 12. 评价\n目标未兑现。'
    result=ResearchWorkflow.__new__(ResearchWorkflow)._consolidate_report_verification_gaps(report,target_type='company')
    assert result.startswith(report)


def test_company_source_index_ignores_learning_word_but_keeps_real_bracketed_citation():
    from types import SimpleNamespace
    project=SimpleNamespace(target_type='company',target_name='青禾制造有限公司',company_people_package={'facts':[
        {'kind':'practice','fact':'公司搭建E-learning员工在线培训平台。','source_url':'https://issuer.test/report.pdf',
         'source_title':'青禾制造有限公司2025年报告','evidence_ids':['E-123456ABCDEF']}]})
    facts=[{'evidence_id':'E-123456ABCDEF','source_url':'https://issuer.test/report.pdf','source_title':'原件','fact':'原件定位','evidence_scope':'target_direct'}]
    report='## 8. 企业文化\n公司搭建E-learning员工在线培训平台。[E-123456ABCDEF]\n## 13. 信息来源\n## 14. 后续研究建议\n'
    indexed=ResearchWorkflow.__new__(ResearchWorkflow)._append_company_claim_evidence_index(project,report,facts,total_traceable_sources=1,eligible_company_sources=1)
    index=indexed.split('## 13.')[1]
    assert 'E-LEARNING' not in index and '| E-123456ABCDEF |' in index


def test_recall_display_only_reuses_identical_relationship_and_keeps_each_batch():
    from report_agents.company_risk_register import _recall_lines
    link={'entity':'青禾汽车有限公司','as_of':'2025-12-31','direct_pct':'90','indirect_pct':'10','page':227,
          'evidence_ids':['E-123456ABCDEF']}
    def event(number):return {'fact_record':{'publication_date':'2026-09-18','effective_date':'2026-09-18',
        'evidence_ids':['E-123456ABCDEF'],'entity':'青禾汽车有限公司','recall_number':number,
        'scope_parts':[{'production_from':'2021-01-01','production_to':'2022-01-01','product_scope':'甲型车辆','reported_quantity':100,'unit':'辆'}],
        'defect_quote':'该批次存在独有缺陷'+number,'remedy_quote':'免费更换部件。','relationship':link,
        'relationship_timing':'公告前截至日关系','boundary':'召回不等于已发生事故。'}}
    first,second=event('R-01'),event('R-02');before=deepcopy([first,second]);context={}
    text='\n'.join(_recall_lines([first],context)+_recall_lines([second],context))
    assert text.count('直接/间接持股列分别为90/10')==1 and 'R-01' in text and 'R-02' in text
    assert text.count('召回不等于已发生事故。')==1 and '持股及责任边界同本节前项相同原件' in text
    assert [first,second]==before


def test_company_date_preface_stays_with_its_table():
    from test_company_export_layout import exported,W,INDEX
    doc,_=exported('## 11. 风险核查\n### 某召回事项\n2026-09-18公告；实施日：2026-09-18。\n\n| 车型 | 数量 |\n| --- | --- |\n| 甲型 | 100辆 |\n\n'+INDEX)
    para=next(p for p in doc.iter(W+'p') if '2026-09-18公告' in ''.join(t.text or '' for t in p.iter(W+'t')))
    assert para.find('.//'+W+'keepNext') is not None


def test_table_only_company_citations_survive_fullwidth_brackets_through_delivery_gate():
    from types import SimpleNamespace
    from test_company_risk_register import report,build,ROOT
    from report_agents.company_report_agent import CompanyReportAgent,COMPANY_REPORT_OUTLINE
    source=report()
    text='于2025年12月31日，由于持票人未发起到期托收，本集团尚有余额为人民币7,109千元的应付票据到期未付。'
    source['source_metadata']['document_pages'].append({'page':40,'text':text})
    source['content']+='\n'+text
    packet=build(source,intake={'as_of_date':'2026-10-16'})
    project=SimpleNamespace(target_name=ROOT,title=ROOT,target_type='company',industry='制造',description='',sources=[source],company_risk_register_package=packet)
    body=CompanyReportAgent()._write_risk_register(project,packet,lambda *a,**kw:None)
    assert '［E-' in body and project.company_risk_register_diagnostic['cited_evidence_ids']
    notice='本次已检索公开来源未形成可引用记录；相关核验事项见第14章。'
    report_text='\n\n'.join(body if i==11 else f'## {i}. {title}\n'+notice for i,(title,_) in enumerate(COMPANY_REPORT_OUTLINE,1))
    workflow=ResearchWorkflow.__new__(ResearchWorkflow)
    indexed=workflow._append_company_claim_evidence_index(project,report_text,[],total_traceable_sources=1,eligible_company_sources=1)
    workflow._validate_delivery_report(project,indexed)
