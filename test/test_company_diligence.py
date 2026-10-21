import json
from collections import Counter
from copy import deepcopy
from types import SimpleNamespace

import pytest

from report_agents.company_diligence import (
    _cash_checks, _sentences, build_diligence_package, classify_quote,
    diligence_errors, disclosure_rows, english_aliases, folded,
    identity_registry, issuer_heading, money_rows, render_diligence,
    scoped_government_pages, select_rows,
    diligence_discovery_queries,
)

ROOT='青禾食品股份有限公司'
CHILD='青禾电子（国际）有限公司'
ENGLISH='Qinghe Electronics (International) Company Limited'


def page(text,n=1):return {'page':n,'text':text}


def source(name=ROOT,body='',i=1,year=2025,pages=None,url=None):
    pages=pages or [page(name+'\n'+str(year)+'年年度报告\n'+body)]
    url=url or f'https://www.hkexnews.hk/{i}.pdf'
    s={'title':name+str(year)+'年度报告','url':url,'content':'\n\n'.join(f"--- PDF page {p['page']} ---\n{p['text']}" for p in pages),
       'source_metadata':{'document_pages':pages,'content_kind':'pdf_text_extracted','document_extraction':{'method':'embedded_pdf_text'}}}
    c={'evidence_id':f'E-{i:012X}','source_url':url,'source_title':s['title'],'fact':'公司无融资，无异常资金往来。',
       'evidence_scope':'target_direct','eligible_for_report':True}
    return c,s


def package(*pairs,target=ROOT,**kw):
    return build_diligence_package({'facts':[c for c,s in pairs]},target,[s for c,s in pairs],**kw)


def root_pair():return source(body='消费电子业务主要通过子公司'+CHILD+'开展。')


def child_pair(i=2,year=2025):
    return source(CHILD,i=i,year=year,pages=[page(CHILD+'\n'+ENGLISH+' (“Company”; together with its subsidiaries known as the “Group”).\nANNUAL REPORT '+str(year)),page('The Company obtained a loan of USD1,200,000 from Parent Holdings Limited, the intermediate holding company.',20)])


def money_page(unit='RMB’000',n=232):
    return page(unit+'\nCash consideration* 对价* 14,669,793\nCash consideration not paid yet* 未付* (322,723)\nCash and bank balances acquired 并入现金 (269,301)\nNet outflow of cash and cash equivalents included in cash flows from investing activities\n净流出 14,077,769\n* The final cash consideration is still under negotiation.',n)


BASE={'source_url':'https://www.hkexnews.hk/acquisition.pdf','source_title':'Acquisition Report','entity':CHILD,'period':'2023年度报告','evidence_id':'E-000000000001','evidence_ids':['E-000000000001']}


def test_registry_requires_explicit_parent_relation_and_owner_heading():
    root=root_pair();child=child_pair();p=package(root,child)
    assert CHILD in p['diagnostic']['linked_entities']
    assert any(r['entity']==CHILD and r['kind']=='related_funding' for r in p['facts'])
    assert not package(child)['facts']  # A subsidiary report alone cannot describe the parent.


def test_traditional_simplified_name_matching_does_not_merge_legal_entities():
    c,s=child_pair();s['source_metadata']['document_pages'][0]['text']=s['source_metadata']['document_pages'][0]['text'].replace('青禾电子（国际）有限公司','青禾電子（國際）有限公司')
    p=package(root_pair(),(c,s));assert any(r['entity']==CHILD for r in p['facts'])
    assert folded('青禾電子（國際）有限公司')==folded(CHILD)
    assert folded('青禾電子（國際）控股有限公司')!=folded(CHILD)


def test_english_only_circular_needs_authenticated_alias_and_shareholder_scope():
    circular=source('OTHER',i=3,pages=[page('If you have sold all your shares in '+ENGLISH+', pass this circular to the purchaser.\n25 February 2024'),page('The final Consideration paid by the Group for the Acquisition was approximately RMB1.2 billion.',9)])
    p=package(root_pair(),child_pair(),circular)
    assert any(r['source_url'].endswith('/3.pdf') for r in p['facts'])
    assert not any(r['source_url'].endswith('/3.pdf') for r in package(root_pair(),circular)['facts'])


def test_target_in_body_and_search_title_do_not_own_a_document():
    c,s=source('其他股份有限公司','本集团与'+ROOT+'合作；本公司完成配售，净额100万元。')
    c['source_title']=s['title']=ROOT+'融资'
    assert not package((c,s))['facts']


def government_pair():
    return source(i=9,url='https://www.csrc.gov.cn/case.pdf',pages=[
        page('一、甲集团收购目标\n甲集团股份有限公司（以下简称甲集团或公司）收购'+ROOT+'（以下简称青禾或标的）。\n融资100亿元。'),
        page('二、青禾收购制造业务\n'+ROOT+'（以下简称青禾或公司），通过子公司'+CHILD+'开展电子业务。\n交易对价为约人民币20亿元，旨在提高收购业务的竞争力。',2),
        page('三、其他公司收购资产\n其他股份有限公司（以下简称其他或公司），交易对价人民币99亿元。',3)])


def test_government_multi_company_cases_use_the_case_subject_and_stop_boundary():
    c,s=government_pair();selected=scoped_government_pages(s,ROOT)
    assert [p['page'] for p in selected]==[2]
    assert '99亿元' not in render_diligence(package((c,s)))
    assert '100亿元' not in render_diligence(package((c,s)))


def test_regulatory_contents_page_does_not_admit_all_case_pages():
    c,s=government_pair();s['source_metadata']['document_pages']=[page('目录\n二、青禾收购资产........2\n'+ROOT)]
    assert not scoped_government_pages(s,ROOT)


def test_discovery_summary_is_not_a_retrieved_document_even_with_trusted_host():
    c,s=source(body='本公司完成配售，净额100万元。');s['source_metadata']['content_kind']='search_summary'
    assert not package((c,s))['facts']


def test_related_mentions_in_a_wrong_issuer_document_do_not_create_an_alias():
    pair=source('其他有限公司','青禾电子（国际）有限公司\n'+ENGLISH+' acquired assets for RMB100 million.',i=3)
    assert not any(r['source_url'].endswith('/3.pdf') for r in package(root_pair(),pair)['facts'])


def test_legal_suffixes_and_multiword_companies_are_not_split_at_pte_ltd():
    sentences=_sentences('The Group acquired Juno Newco Target Holdco Singapore Pte. Ltd. from Seller Inc. at RMB100 million. The loan was repaid.')
    assert len(sentences)==2 and 'Pte. Ltd.' in sentences[0] and 'Seller Inc.' in sentences[0]


@pytest.mark.parametrize('unit,expected',[('RMB’000','人民币千元'),("US$'000",'美元千元'),('HKD’000','港元千元')])
def test_cash_rows_keep_currency_unit_and_unpaid_prefix(unit,expected):
    rs=money_rows(money_page(unit),BASE);bykind={r['kind']:r for r in rs}
    assert len(rs)==4 and bykind['accounting_consideration']['value']=='14,669,793'
    assert bykind['unpaid_consideration']['value']=='(322,723)' and all(r['unit']==expected for r in rs)
    assert all('仍在协商' in r['negotiation_note'] for r in rs)
    c=_cash_checks(rs)[0];assert c['matched'] and c['unit']==expected and '银行收付认证' in c['scope']


def test_cash_rows_refuse_two_year_columns_or_multiple_currency_headers():
    p=money_page();p['text']=p['text'].replace('14,669,793','14,669,793 13,000,000')
    assert not any(r['kind']=='accounting_consideration' for r in money_rows(p,BASE))
    p=money_page();p['text']+="\nUSD'000"
    assert not money_rows(p,BASE)


def test_money_table_note_number_is_not_an_extra_value_or_hardcoded_note_id():
    p=page('RMB’000\nGoodwill on acquisition 商誉 27 4,361,657')
    assert money_rows(p,BASE)[0]['value']=='4,361,657'


def test_cash_reconciliation_is_scoped_and_does_not_join_two_transactions():
    rs=money_rows(money_page(),BASE)
    assert not _cash_checks(rs+rs)
    rs[-1]['source_url']='https://other.example/file.pdf'
    assert not _cash_checks(rs)


def test_cash_reconciliation_difference_is_preserved_without_inventing_an_explanation():
    rs=money_rows(money_page(),BASE);rs[-1]['value']='14,000,000'
    result=_cash_checks(rs)[0]
    assert result['matched'] is False and '交易调整' not in result['equation']


def test_pro_forma_loan_is_not_actual_drawdown_even_without_same_sentence_heading():
    p=page('The Consideration will be satisfied by cash, by the Group’s internal resources and shareholder’s loan to be provided by Parent Company Limited in the aggregate loan facility amount of US$2,150,000,000.\nAPPENDIX IV UNAUDITED PRO FORMA FINANCIAL INFORMATION',114)
    rs=disclosure_rows({},[p],BASE)
    assert rs and all(r['kind']=='pro_forma' for r in rs) and '非实际提款' in rs[0]['mode']


def test_actual_related_loan_is_separate_from_its_unsecured_interest_clause():
    p=page('(a) Qinghe Precision, a wholly-owned subsidiary of the Company, obtained an entrusted loan of RMB5,000,000,000 from Parent Company Limited through Example Bank. The loan was unsecured, bearing a fixed interest rate of 2.5%.',227)
    rs=disclosure_rows({},[p],BASE)
    assert len(rs)==1 and rs[0]['kind']=='related_funding' and '未自动归入本次收购' in rs[0]['mode']


def test_fund_use_preserves_all_bullets_and_stops_before_next_section():
    body='截至2025年12月31日，本集团已使用年内配售事项所得款项净额人民币40,075百万元，其中（i）13,178百万元用于研发；（ii）19,697百万元用于海外；及（iii）7,200百万元用于营运。\n2、募集资金承诺项目情况\n不适用。'
    p=package(source(body=body));rs=[r for r in p['facts'] if r['kind']=='fund_use']
    assert len(rs)==1 and '7,200百万元' in rs[0]['fact'] and '承诺项目' not in rs[0]['fact']


@pytest.mark.parametrize('raw',[
    'The Board shall take into consideration the experience of the candidates.',
    '详情请见公司披露的关于完成配售新H股的公告。',
    '五、重要会计政策及会计估计\n收购商誉人民币100万元应当按如下方法处理。',
    'SUMMARY OF MATERIAL ACCOUNTING\nPOLICIES\nThe asset acquired for RMB100 million would be subject to impairment.',
])
def test_references_policies_and_general_consideration_are_not_actual_disclosures(raw):
    assert not disclosure_rows({},[page(raw)],BASE)


def test_current_relevant_financing_is_not_drowned_by_initial_listing_history():
    history={'facts':[{'kind':'event','period':'2002-07-31','fact':'2002年完成首次配售募集资金。','evidence_id':'E-000000000002','evidence_ids':['E-000000000002'],'source_url':'https://x/old','source_title':'历史'},
                      {'kind':'event','period':'2025-03-11','fact':'2025年完成配售募集资金100万元。','evidence_id':'E-000000000003','evidence_ids':['E-000000000003'],'source_url':'https://x/new','source_title':'本期'}]}
    p=package(source(body='报告。'),prior_packages={'history':history})
    assert not any('2002年' in r['fact'] for r in p['facts']) and any('2025年' in r['fact'] for r in p['facts'])


def test_generic_input_and_existing_clients_are_not_client_designation():
    p=package(source(body='本公司于2025年完成配售，所得净额100万元。'),intake={'focus_questions':['主营业务与公开风险有哪些？'],'special_requirements':'验证公司真实经营。'})
    t=render_diligence(p)
    assert not p['client_specified_checks'] and '未明确指定专项对象' in t and '项目输入的研究要求' in t
    assert all('待核验' in task['status'] for task in p['tasks']) and '不代表已完成' in t


def test_explicit_client_tasks_are_input_scope_and_not_new_company_facts():
    p=package(intake={'client_specified_checks':['核对境外投资的资金来源。']})
    assert not p['facts'] and '属于研究任务' in render_diligence(p) and diligence_errors(render_diligence(p),p)


def test_missing_documents_ocr_and_budget_remain_explicit_without_risk_grades():
    c,s=source(body='本公司于2025年完成配售，所得净额100万元。');s['source_metadata']['document_extraction']={'needs_ocr_pages':[2],'omitted_pages':50}
    p=package((c,s),limit=1);t=render_diligence(p)
    assert '尚未执行OCR' in t and '未提取全文' in t and '超出本章证据预算' in t and '中（信息缺口）' not in t


def test_judicial_followups_keep_role_and_distinct_states_without_repeating_100_rows():
    def guarantee(i,status):
        return {**BASE,'kind':'guarantee','date':'2025-08-'+str(i).zfill(2),'fact':'担保方=甲；被担保方=乙；100万元；'+status,'fields':{'履行状态':status}}
    case={**BASE,'kind':'disclosed_case','case_description':'甲子公司与乙公司购销合同纠纷','stage':'执行中','execution':'乙暂无财产可供执行','fact':'乙赔偿甲100万元，执行中。','page':86}
    p=package(prior_packages={'judicial':{'facts':[guarantee(i,'待查') for i in range(1,20)]+[guarantee(20,'已解除'),case]}})
    assert len([r for r in p['facts'] if r['kind']=='encumbrance_followup'])==2
    assert any(t['stream']=='追偿与执行' and '回款' in t['action'] for t in p['tasks'])


def test_kind_diversity_preserves_old_accounting_cashflow_beside_new_loan():
    rows=[{**BASE,'kind':'related_funding','period':'2025年度报告','fact':'新贷款'+str(i),'page':i} for i in range(20)]
    rows+=money_rows(money_page(),BASE)
    selected=select_rows(rows,5)
    assert {r['kind'] for r in selected}=={'related_funding','accounting_consideration','unpaid_consideration','acquired_cash','acquisition_net_outflow'}


@pytest.mark.parametrize('name',['星河精密股份有限公司','青禾食品有限公司','Northstar Robotics Limited'])
def test_company_independent_fundraising_sources_and_actions(name):
    pair=source(name,body='本公司于2025年完成配售，所得净额USD1,200,000，用于研发。')
    p=package(pair,target=name);assert any(t['stream']=='融资情况' for t in p['tasks'])
    assert '比亚迪' not in render_diligence(p) and 'USD1,200,000' in render_diligence(p)


def test_checked_chapter10_is_protected_from_editor_and_source_index_uses_originals(monkeypatch):
    from report_agents.company_report_agent import CompanyReportAgent
    from research_workflow import ResearchWorkflow
    c,s=source(body='本公司于2025年完成配售，所得净额100万元。')
    p=SimpleNamespace(target_name=ROOT,title=ROOT,target_type='company',industry='食品',description='',sources=[s],company_research_intake={})
    agent=CompanyReportAgent();monkeypatch.setattr(agent,'_write_section',lambda *a,**k:'');monkeypatch.setattr(agent,'_write_summary',lambda *a,**k:'## 1. 摘要\n摘要。');monkeypatch.setenv('COMPANY_REPORT_EDITOR_ENABLED','true')
    monkeypatch.setattr(agent,'_edit_batched',lambda *a,**k:'\n'.join(f'## {i}. 标题\n'+('资金完全合规，无融资。[E-FFFFFFFFFFFF]' if i==10 else '待核验。') for i in range(1,15)))
    t=agent.generate(p,json.dumps({'facts':[c]}),'{}',lambda *a:'',lambda s,n:s[:n],lambda *a,**k:None)
    chapter=t.split('## 10.')[1].split('## 11.')[0]
    assert '100万元' in chapter and '资金完全合规' not in chapter and 'FFFFFFFFFFFF' not in chapter
    result=ResearchWorkflow.__new__(ResearchWorkflow)._append_company_claim_evidence_index(p,t,[c],total_traceable_sources=1,eligible_company_sources=1)
    index=result.split('## 13.')[1]
    assert '第 10 章' in index and '100万元' in index and '公司无融资，无异常资金往来' not in index


def test_empty_chapter_keeps_specific_scope_gaps_after_marker_pass():
    from report_agents.company_report_agent import CompanyReportAgent
    p=package();t=CompanyReportAgent._ensure_section_evidence_markers(render_diligence(p),{10:[]})
    assert '备考' in t and '集团合并' in t and diligence_errors(t,p)


def test_parent_shareholder_seller_subsidiary_is_not_target_company_subsidiary():
    c,s=source(body='交易标的为控股股东甲集团全资子公司乙运营有限公司100%的股权。')
    registry,_=identity_registry({'facts':[c]},ROOT,[s])
    assert len(registry)==1


def test_wrapped_possessive_relationship_is_kept_but_others_are_not():
    c,s=source(body='其消费电\n子业务主要通过子公司'+CHILD+'开展。')
    registry,_=identity_registry({'facts':[c]},ROOT,[s])
    assert folded(CHILD) in registry


def test_discovery_queries_use_relationship_proof_and_deduplicate_between_rounds():
    root=root_pair();seen=set()
    q=diligence_discovery_queries([root[1]],ROOT,seen)
    assert len(q)==2 and all(x['diligence_entity']==CHILD and x['diligence_relationship_source']==root[1]['url'] for x in q)
    assert all(x['evidence_scope']=='related_entity_context' for x in q)
    assert not diligence_discovery_queries([root[1]],ROOT,seen)
    bad=deepcopy(root[1]);bad['source_metadata']['content_kind']='search_summary'
    assert not diligence_discovery_queries([bad],ROOT)


def test_discovery_does_not_repeat_when_report_and_circular_are_present():
    root=root_pair();child=child_pair();circular=source('OTHER',i=3,pages=[page('shares in '+ENGLISH+'\n25 February 2024')]);circular[1]['title']='Acquisition Circular'
    assert not diligence_discovery_queries([root[1],child[1],circular[1]],ROOT)


def test_small_unseparated_amount_and_glyph_adjacent_amount_are_not_truncated():
    for raw,value in [('Cash consideration 100','100'),('Total identifiable net assets at fair value ࠽10,308,136','10,308,136')]:
        rows=money_rows(page('RMB’000\n'+raw),BASE)
        assert rows[0]['value']==value


def test_equity_and_cash_funding_plan_is_not_already_completed_financing():
    p=package(source(body='本次交易方案为公司采用发行股份及支付现金购买资\n产并募集配套资金方式收购资产。'))
    r=next(r for r in p['facts'] if r['kind']=='financing_plan')
    assert '完成、到账' in r['mode'] and '非' not in r['fact']


def test_short_cash_price_is_not_lost_and_does_not_equal_valuation():
    p=package(source(body='评估基准日为2022年10月31日，标的净资产账面价值43.52亿元，评估值100.10亿元。现金对价15.02亿元，占交易金额15%。'))
    assert {r['kind'] for r in p['facts']}=={'valuation','consideration'}
    assert any(r['kind']=='consideration' and '15.02亿元' in r['fact'] for r in p['facts'])


def test_zero_contribution_since_year_end_acquisition_is_not_business_failure():
    quote='Since the acquisition, there are no revenue and profit were contributed from the Target and its subsidiaries for the year ended 31 December 2023.'
    r=disclosure_rows({},[page(quote)],BASE)[0]
    assert r['kind']=='acquired_contribution' and '不归因全部增长或机械年化' in r['mode']


def test_english_price_earnings_is_not_misidentified_as_evidence_id():
    p=package(source(body='The cash consideration for the acquisition was RMB100 million, based on price-earnings ratios.'))
    assert not diligence_errors(render_diligence(p),p)


def test_representative_proforma_keeps_financing_assumption_instead_of_only_price():
    rows=[{**BASE,'kind':'pro_forma','page':114,'fact':'Shareholder loan facility US$2,150,000,000'},
          {**BASE,'kind':'pro_forma','page':115,'fact':'Purchase consideration US$2.2 billion'}]
    assert 'loan facility' in select_rows(rows,1)[0]['fact']


def test_wrong_issuer_heading_precedes_target_name_in_customer_table():
    c,s=source('其他股份有限公司','客户名单\n'+ROOT+'\n本公司于2025年完成配售，净额100万元。')
    assert not package((c,s))['facts']


@pytest.mark.parametrize('status',['failed','invalid_pdf_response','blocked_or_challenge'])
def test_failed_fetch_with_stale_document_pages_is_not_admitted_as_current_source(status):
    c,s=source(body='本公司于2025年完成配售，净额100万元。');s['source_metadata']['fetch_status']=status
    assert not package((c,s))['facts']


def test_historical_target_goodwill_does_not_become_new_purchase_accounting():
    raw='Goodwill acquired in a previous acquisition had a carrying amount of RMB110 million.\nAPPENDIX II ACCOUNTANTS’ REPORT OF THE TARGET GROUP'
    assert not disclosure_rows({},[page(raw)],BASE)


def test_biography_and_general_consolidated_asset_mentions_are_not_consolidation_events():
    raw='Mr. Smith was named a successful business leader. The Target Group’s consolidated net assets were US$100 million.'
    assert not disclosure_rows({},[page(raw)],BASE)


def test_overdue_bill_preserves_reason_without_copying_unlabelled_comparative_table():
    raw='应付票据\n2025年 2024年\n10,000 9,000\n于2025年12月31日，由于持票人未发起到期托收，本集团尚有余额为人民币7,109千元的应付票据到期未付。'
    r=disclosure_rows({},[page(raw)],BASE)[0]
    assert r['fact'].startswith('于2025年12月31日') and '持票人未发起到期托收' in r['fact']
    assert '不直接等同违约' in r['mode'] and '10,000' not in r['fact']


def test_common_control_no_goodwill_declaration_is_kept_without_global_zero_inference():
    p=package(source(body='本次交易为同一控制下资产收购，公司不形成商誉。'))
    r=p['facts'][0]
    assert r['kind']=='accounting_treatment' and '非公司全部历史商誉为零' in r['mode']


def test_work_order_names_actual_trigger_not_only_generic_checklist():
    p=package(source(body='本公司于2025年完成配售，所得净额100万元，用于研发。'))
    assert p['tasks'] and all(ROOT in t['object'] and '100万元' in t['object'] for t in p['tasks'])
    assert '原件主体或事项线索' in render_diligence(p)


def test_proforma_and_historical_target_tables_are_not_actual_purchase_cashflow():
    for heading in ['UNAUDITED PRO FORMA FINANCIAL INFORMATION','ACCOUNTANTS’ REPORT OF THE TARGET GROUP']:
        p=money_page();p['text']+='\n'+heading
        assert not money_rows(p,BASE)


def test_old_opinion_asof_does_not_crowd_out_newer_execution_asset_status():
    rows=[{**BASE,'kind':'execution_followup','period':'2025年度第一期融资券','as_of':'截至2024年12月末','fact':'正在执行','page':99},
          {**BASE,'kind':'execution_followup','period':'2025年年度报告','fact':'对方暂无财产可供执行','page':86}]
    assert select_rows(rows,1)[0]['fact']=='对方暂无财产可供执行'
def test_diagram_example_is_not_a_real_legal_subsidiary_for_followup_search():
    from report_agents.company_diligence import identity_registry
    from test_company_history import filing
    name='青禾网络科技有限公司'
    card,source=filing(name,'本公司的所有权架构和合约安排的简单示例。')
    source['source_metadata']['document_pages']=[{'page':1,'text':name+'\n2025年年度报告'},
        {'page':2,'text':'以下为所有权架构和合约安排的简单示例。\n本公司\n全资子公司\n中国投资控股有限公司\n可变利益实体'}]
    registry,_=identity_registry({'facts':[card]},name,[source])
    assert set(registry)=={name.casefold()}
def test_source_line_breaks_cannot_split_a_diligence_trigger_into_a_report_heading():
    from report_agents.company_diligence import render_diligence
    original='截至\n2025年3月31日录得减值。\n## 99. 原文行'
    task={'task_id':'D10-01','stream':'战略布局','object':original,'evidence_ids':['E-123456789ABC'],
          'action':'核对原件','materials':'原始底稿','closure_criteria':'逐项勾稽','status':'待核验'}
    text=render_diligence({'client_specified_checks':[],'tasks':[task],
                          'facts':[],'cash_reconciliations':[],'information_gaps':[]})
    assert '截至 2025年3月31日' in text and '\n## 99.' not in text
    assert task['object']==original
