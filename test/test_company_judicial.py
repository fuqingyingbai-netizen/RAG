import json
from collections import Counter
from types import SimpleNamespace

import pytest

from company_risk import drilldown_tools, document_requests
from report_agents.company_judicial import (
    _structured, build_judicial_package, court_record, judicial_errors,
    litigation_rows, render_judicial, stage,
)
from test_company_history import filing

NAME='青禾食品有限公司'


def structured(tool,body,name=NAME,i=1):
    raw='### 基础字段\n\n| 字段 | 值 |\n| --- | --- |\n| 企业名称 | '+name+' |\n\n'+body
    url='structured://qcc_risk/'+tool+'/'+str(i)
    c={'evidence_id':f'E-{i:012X}','fact':'均已结案，无重大影响。','source_url':url,'source_title':tool,
       'entity_match':'matched','evidence_scope':'target_direct','eligible_for_report':True}
    s={'url':url,'title':tool,'content':raw,'source_metadata':{'provider':'qcc_risk','tool':tool,'target':name,'query':name,'content_kind':'structured_data',
       'entity_validation':'verified','query_status':'success','retrieved_at':'2026-10-15T10:00:00'}}
    return c,s


def package(*pairs,target=NAME,**kwargs):
    return build_judicial_package({'facts':[c for c,s in pairs]},target,[s for c,s in pairs],**kwargs)


SCAN='| 风险因子 | 条目数 | 明细工具 |\n| --- | --- | --- |\n| 裁判文书 | 117 | get_judicial_documents |\n| 行政处罚 | 0 | get_administrative_penalty |\n| 劳动仲裁 | 1 | get_service_announcement |'


def cases(rows):
    h='| 文书ID | 案号 | 案由 | 当事人 | 案件金额 | 裁判结果 | 裁判日期 |\n| --- | --- | --- | --- | --- | --- | --- |\n'
    return h+'\n'.join('| '+' | '.join(r)+' |' for r in rows)


def case_row(result='本案移送某法院处理。',role='被告',name=NAME,date='2025-06-01',did='doc1',case='（2025）粤01民初1号'):
    return [did,case,'合同纠纷',json.dumps({role:[name]},ensure_ascii=False),'待查',result,date]


def test_zero_hit_and_record_counts_never_become_global_assurances():
    p=package(structured('get_company_risk_scan',SCAN));t=render_judicial(p)
    assert len(p['facts'])==3 and '117' in t and '行政处罚' in t
    assert all('均已结案' not in r['fact'] for r in p['facts']) and '0项严重司法负面' not in t and '经营良好' not in t
    assert '不能相加为案件数' in t and judicial_errors(t,p)==[]


def test_provider_nohit_prose_is_cleaned_into_scoped_lookup():
    p=package(structured('get_administrative_penalty','| 字段 | 值 |\n| --- | --- |\n| 摘要 | 当前未发现行政处罚，经营良好，无历史遗留违规。 |'))
    t=render_judicial(p)
    assert '默认查询为当前在册有效记录' in t
    assert '经营良好' in t  # only appears in the explicit prohibition
    assert '无历史遗留违规' not in t


@pytest.mark.parametrize('result,label',[('准许原告撤回起诉。','非实体胜败'),('本案移送乙法院。','管辖'),
    ('本案中止诉讼。','非结案'),('经调解达成协议。','履行待核'),('驳回原告的起诉。','非实体请求'),
    ('驳回原告全部诉讼请求。','实体请求'),('正在执行。','未证明执行完毕')])
def test_procedural_results_keep_their_actual_meaning(result,label):assert label in stage(result)


def test_same_case_multiple_decisions_remain_and_exact_rows_deduplicate():
    rows=[case_row('本案中止诉讼。'),case_row('准许原告撤诉。',did='doc2',date='2025-07-01')]
    p=package(structured('get_judicial_documents',cases(rows+[rows[0]])))
    assert len(p['facts'])==2 and {r['stage'] for r in p['facts']}=={stage(rows[0][-2]),stage(rows[1][-2])}


def test_full_party_list_and_role_are_read_without_name_substring_matching():
    row=case_row(name='青禾食品有限公司二厂')
    p=package(structured('get_judicial_documents',cases([row])))
    assert not p['facts']
    row[3]=json.dumps({'原告':['其他公司',NAME],'被告':['甲公司']},ensure_ascii=False)
    r=package(structured('get_judicial_documents',cases([row])))['facts'][0]
    assert r['role']=='原告' and r['amount']=='待查'


def test_arbitration_announcement_is_not_award_or_closed_case():
    body='| 案号 | 申请人 | 被申请人 | 发布日期 |\n| --- | --- | --- | --- |\n| 成劳人仲案（2023）06501号 | ["胡*"] | ["其他公司", "'+NAME+'"] | 2024-01-08 |'
    p=package(structured('get_service_announcement',body));r=p['facts'][0]
    assert r['role']=='被申请人' and '公告' in r['stage'] and r['amount']=='未取得裁决金额'


def test_guarantee_direction_and_pledge_releases_are_retained():
    guarantee='| 担保方 | 被担保方 | 担保方式 | 担保金额 | 履行状态 | 公告日期 |\n| --- | --- | --- | --- | --- | --- |\n| ["'+NAME+'"] | ["甲公司"] | 连带责任担保 | 18.57亿 | 待查 | 2025-08-30 |'
    pledge='| 质押人 | 质押人参股企业 | 质押权人 | 股份总数 | 股份市值 | 状态 | 公告日期 |\n| --- | --- | --- | --- | --- | --- | --- |\n| ["张某"] | ["'+NAME+'"] | ["乙银行"] | 100.00万 | 8265.19万 | 已解除质押 | 2024-04-23 |'
    p=package(structured('get_guarantee_info',guarantee),structured('get_stock_pledge_info',pledge,i=2));t=render_judicial(p)
    assert '18.57亿' in t and '已解除质押' in t and '股份总数=100.00万' in t and '股份市值=8265.19万' in t
    assert '张某' in t and '合计为当前余额' in t


@pytest.mark.parametrize('status',['failed','unauthorized','quota_exceeded'])
def test_error_status_does_not_admit_zero_hits(status):
    c,s=structured('get_company_risk_scan',SCAN);s['source_metadata']['query_status']=status
    p=package((c,s));assert not p['facts'] and '未成功' in render_judicial(p)


def test_wrong_structured_query_subject_is_rejected_even_if_root_meta_verified():
    c,s=structured('get_company_risk_scan',SCAN,name='其他公司')
    assert not package((c,s))['facts']


def test_discovery_summary_and_quarantined_source_are_not_original_evidence():
    for changes in [{'content_kind':'search_summary'},{'entity_validation':'rejected'}]:
        c,s=structured('get_company_risk_scan',SCAN);s['source_metadata'].update(changes)
        assert not package((c,s))['facts']


def table_page(number=25):
    return {'page':number,'text':'截至2024年12月末，未决诉讼如下。', 'tables':[[
        ['诉讼基本情况','','涉案金额','','是否形成预计负债','','进展','审理结果及影响','执行情况'],
        ['','','（万元）','','','','','',''],
        ['甲子公司与乙公司购销合同纠纷-人民币','1,021','','否','','执行中','乙向甲支付1,621,365美元','正在执行','']]]}


def test_split_vector_cells_keep_case_amount_judgment_currency_and_execution():
    r=litigation_rows([table_page()],{},'2025年度第一期超短期融资券',Counter())[0]
    assert r['amount']=='1,021万元' and r['provision']=='否' and r['stage']=='执行中'
    assert r['result']=='乙向甲支付1,621,365美元' and r['as_of']=='截至2024年12月末'


def test_cross_page_continuation_is_appended_only_to_previous_contiguous_row():
    p=table_page();p['tables'][0][-1][0]='甲公司与乙公司（简称"乙'
    # Use a complete first-page case descriptor with a wrapped closing fragment.
    p['tables'][0][-1][0]+='诉讼纠纷'
    cont={'page':26,'text':'续表','tables':[[['"）的购销合同纠纷-人民币','','','','诉讼费由乙负担','']]]}
    r=litigation_rows([p,cont],{},'2025年',Counter())[0]
    assert r['pages']==[25,26] and '诉讼费由乙负担' in r['result']
    cont['page']=30;r=litigation_rows([p,cont],{},'2025年',Counter())[0]
    assert r['pages']==[25]


def test_unlabeled_units_or_missing_cells_are_not_guessed():
    p=table_page();p['tables'][0][1][2]=''
    assert not litigation_rows([p],{},'2025年',Counter())
    p=table_page();p['tables'][0][-1][-2]=''
    assert not litigation_rows([p],{},'2025年',Counter())


def test_scoped_issuer_declaration_does_not_erase_other_litigation():
    c,s=filing(NAME,'披露。');s['source_metadata']['document_pages']=[{'page':45,'text':'本报告期公司无重大诉讼、仲裁事项。公司报告期不存在重大处罚及整改情况。'}]
    p=package((c,s));assert len(p['facts'])==2 and all(r['kind']=='declaration' for r in p['facts'])
    assert '发行人本报告期披露' in render_judicial(p)


def test_qualification_checks_and_questions_do_not_become_violations():
    c,s=filing(NAME,'');s['source_metadata']['document_pages']=[{'page':1,'text':'不存在以下情形：涉嫌犯罪、受行政处罚。请说明是否存在重大诉讼。'}]
    assert not package((c,s))['facts']


def test_wrong_court_parties_and_anonymous_parties_are_not_resolved_from_body_mentions():
    s={'url':'https://ipc.court.gov.cn/a','title':'（2023）最高法知民终1590号'}
    assert not court_record('原告：浙江吉某公司。被告：威某公司。行业提及'+NAME,s,NAME,{})
    assert not court_record('原告：某公司。'+NAME+'可能关联。',s,NAME,{})
    r=court_record('原告：'+NAME+'。被告：甲公司。',s,NAME,{})[0]
    assert r['role']=='原告' and '1590号' in r['case_number']


def test_anonymous_judgment_detail_requires_provider_party_mapping():
    body='| 字段 | 值 |\n| --- | --- |\n| 案号 | （2024）粤01民初1号 |\n| 当事人原文 | 原告：某公司。被告：某公司。 |\n| 判决结果 | 按撤诉处理。 |'
    assert not package(structured('get_judicial_document_detail',body))['facts']
    p=package(structured('get_judicial_document_detail',body+'\n\n### 被告\n\n- 某有限公司（'+NAME+'）'))
    assert '仅由数据库映射' in p['facts'][0]['mode']


def test_drilldown_only_uses_positive_supported_scan_tools_and_caps_fulltext():
    assert drilldown_tools(SCAN)==['get_judicial_documents','get_service_announcement']
    text=cases([case_row(did=f'doc{i}') for i in range(10)])
    assert [did for case,did in document_requests(text)]==['doc0','doc1']


def test_budget_and_missing_ocr_are_visible_without_risk_inference():
    c,s=filing(NAME,'');s['source_metadata'].update(document_extraction={'needs_ocr_pages':[2],'omitted_pages':7},document_pages=[table_page()])
    p=package((c,s),limit=5);t=render_judicial(p)
    assert '尚未执行OCR' in t and '超出本章证据预算' in t and '尚未提取全文' in t


def test_scoped_platform_cleaning_drops_llm_assurance_even_if_provider_says_it():
    from research_workflow import ResearchWorkflow
    c,s=structured('get_administrative_penalty','| 字段 | 值 |\n| --- | --- |\n| 摘要 | 未发现行政处罚，经营良好，无历史遗留违规。 |')
    source=SimpleNamespace(**s,summary='',source_type='business_database',credibility_score=80)
    project=SimpleNamespace(target_type='company',target_name=NAME,sources=[source])
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    assert not w._sanitize_structured_facts([{'fact':'无历史遗留违规','evidence_quote':'无历史遗留违规','source_url':s['url']}],project)
    facts=w._extract_professional_structured_facts([source],project)
    assert any('当前在册有效' in r['fact'] for r in facts) and not any('无历史遗留违规' in r['fact'] for r in facts)


def test_checked_judicial_chapter_is_protected_and_indexed(monkeypatch):
    from report_agents.company_report_agent import CompanyReportAgent
    from research_workflow import ResearchWorkflow
    c,s=structured('get_judicial_documents',cases([case_row()]));p=SimpleNamespace(target_name=NAME,title='公司',target_type='company',industry='食品',description='',sources=[s])
    a=CompanyReportAgent();monkeypatch.setattr(a,'_write_section',lambda *x,**kw:'');monkeypatch.setattr(a,'_write_summary',lambda *x,**kw:'## 1. 摘要\n摘要。');monkeypatch.setenv('COMPANY_REPORT_EDITOR_ENABLED','true')
    monkeypatch.setattr(a,'_edit_batched',lambda *x,**kw:'\n'.join(f'## {i}. 标题\n'+('全部结案，无上市风险。[E-FFFFFFFFFFFF]' if i==9 else '待核验。') for i in range(1,15)))
    t=a.generate(p,json.dumps({'facts':[c]}),'{}',lambda *x:'',lambda s,n:s[:n],lambda *x,**kw:None)
    chapter=t.split('## 9.')[1].split('## 10.')[0]
    assert '移送' in chapter and '全部结案' not in chapter and 'FFFFFFFFFFFF' not in chapter and '本章引用证据' not in chapter
    t=ResearchWorkflow.__new__(ResearchWorkflow)._append_company_claim_evidence_index(p,t,[c],total_traceable_sources=1,eligible_company_sources=1)
    index=t.split('## 13.')[1];assert '第九章原文核对' in index and '均已结案' not in index


def test_empty_chapter_and_failed_attempts_survive_marker_pass():
    from report_agents.company_report_agent import CompanyReportAgent
    p=package(query_attempts=[{'tool':'qcc_risk初始化','status':'failed'}]);t=render_judicial(p)
    t=CompanyReportAgent._ensure_section_evidence_markers(t,{9:[]})
    assert '初始化' in t and '金额' in t and judicial_errors(t,p)


@pytest.mark.parametrize('kind,positive',[('company',True),('company',False),('person',True)])
def test_collector_drills_only_positive_company_factors_and_retains_failures(monkeypatch,kind,positive):
    from research_workflow import ResearchWorkflow
    w=ResearchWorkflow.__new__(ResearchWorkflow);calls=[];saved=[]
    monkeypatch.setenv('QCC_API_KEY','test-only');monkeypatch.delenv('QCC_ENABLE_IPR_TOOLS',raising=False)
    monkeypatch.setattr(w,'_mcp_initialize',lambda *a,**k:(object(),True,''))
    monkeypatch.setattr(w,'_extract_mcp_text',lambda p,**kw:p.get('text',''))
    def call(url,headers,tool,args,**kw):
        calls.append((tool,args))
        if tool=='get_company_risk_scan':return {'text':structured(tool,SCAN if positive else SCAN.replace('117','0').replace('| 1 |','| 0 |'))[1]['content']},object()
        if tool=='get_judicial_documents':return {'text':structured(tool,cases([case_row(did=f'doc{i}') for i in range(6)]))[1]['content']},object()
        if tool=='get_service_announcement':return {'error':{'message':'temporary failure'}},object()
        return {'text':'valid lookup response'},object()
    monkeypatch.setattr(w,'_mcp_call_tool',call)
    monkeypatch.setattr(w,'_save_structured_source',lambda *a,**kw:saved.append(a[7] if len(a)>7 else a[-1]) or True)
    p=SimpleNamespace(target_type=kind,target_name=NAME,title='',description='',industry='')
    w._collect_qcc_sources(None,p,NAME,{'target_type':kind})
    details=[args for tool,args in calls if tool=='get_judicial_document_detail']
    assert len(details)==(2 if kind=='company' and positive else 0)
    if kind=='company' and positive:
        assert [a['documentId'] for a in details]==['doc0','doc1']
        assert any(a['tool']=='get_service_announcement' and a['status']=='failed' for a in p.company_judicial_query_attempts)
    assert all(tool!='get_guarantee_info' for tool,args in calls)


def test_company_risk_formatter_keeps_100_rows_long_fields_and_extra_columns():
    from research_workflow import ResearchWorkflow
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    rows=[{**{f'列{j}':str(i) for j in range(10)},'完整字段':'甲'*900} for i in range(100)]
    payload={'result':{'content':[{'text':json.dumps({'明细':rows},ensure_ascii=False)}]}}
    generic=w._extract_mcp_text(payload);company=w._extract_mcp_text(payload,preserve_company_risk=True)
    assert '已截取前 80' in generic and '列9' not in generic
    assert '已截取' not in company and '列9' in company and '甲'*900 in company
    assert company.count('甲'*900)==100


def test_formatter_limit_is_explicit_and_original_lookup_remains_a_gap():
    from research_workflow import ResearchWorkflow
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    text=w._dict_list_to_markdown_table([{'长字段':'甲'*12001}],limits=(500,32,12000))
    assert '字段截断' in text
    c,s=structured('get_company_risk_scan',SCAN+'\n\n> 已截取前 80 条记录，完整返回共 100 条。')
    assert '格式化行/字段截断' in render_judicial(package((c,s)))


def test_different_document_ids_with_same_case_date_and_result_are_not_dropped():
    p=package(structured('get_judicial_documents',cases([case_row(did='A'),case_row(did='B')])))
    assert len(p['facts'])==2 and '涉及1个完整案号编号' in render_judicial(p)


def test_structured_quotes_bind_each_guarantee_row_instead_of_only_shared_date():
    body='| 担保方 | 被担保方 | 担保方式 | 担保金额 | 履行状态 | 公告日期 |\n| --- | --- | --- | --- | --- | --- |\n'
    first='| ["'+NAME+'"] | ["甲公司"] | 保证 | 100万 | 待查 | 2025-08-30 |'
    second='| ["'+NAME+'"] | ["乙公司"] | 保证 | 200万 | 待查 | 2025-08-30 |'
    p=package(structured('get_guarantee_info',body+first+'\n'+second))
    assert [r['evidence_quote'] for r in p['facts']]==[first,second]


def test_raw_mcp_response_is_saved_separately_without_mutating_call_metadata(monkeypatch):
    import research_workflow as module
    from unittest.mock import MagicMock
    w=module.ResearchWorkflow.__new__(module.ResearchWorkflow);db=MagicMock();db.query.return_value.filter.return_value.first.return_value=None
    writes={};monkeypatch.setattr(module.research_store,'put_text',lambda key,text,*a:writes.setdefault(key,text) and key)
    monkeypatch.setattr(w,'_save_professional_visual_evidence',lambda *a,**k:[])
    c,s=structured('get_company_risk_scan',SCAN);meta={**s['source_metadata'],'company_qcc_raw_response':{'result':{'complete_data':[1,2,3]}}}
    assert w._save_structured_source(db,SimpleNamespace(id=123),'qcc_risk','诉讼','test',s['content'],meta)
    source=db.add.call_args.args[0]
    assert source.source_metadata['raw_response_key'].endswith('_raw.json')
    assert 'company_qcc_raw_response' not in source.source_metadata and 'company_qcc_raw_response' in meta
    assert json.loads(writes[source.source_metadata['raw_response_key']])==meta['company_qcc_raw_response']


def test_manual_signature_review_is_not_reported_as_completed_ocr():
    c,s=filing(NAME,'');s['content']='北京某律师事务所\n关于'+NAME+'发行2025年度第一期超短期融资券之法律意见书'
    s['source_metadata'].update(document_pages=[{'page':30,'text':'签署页'}],visual_reviews=[{'kind':'document_signature_date','status':'reviewed','page':30,'value':'2025-06-18'}],document_extraction={'needs_ocr_pages':[30]})
    p=package((c,s));t=render_judicial(p)
    assert '签章日期：2025-06-18' in t and '图片人工核对，未执行OCR' in t and '尚未执行OCR' in t


def test_dated_consolidated_guarantee_balance_keeps_exclusion_scope_and_is_not_current():
    c,s=filing(NAME,'');s['source_metadata']['document_pages']=[{'page':25,'text':'截至2024年12月末，发行人及其合并范围内子公司对外担保（不包括对子公司的担保）余额合计254,100万元，占公司净资产的比例为1.28%。'}]
    p=package((c,s));t=render_judicial(p)
    assert p['facts'][0]['kind']=='disclosed_exposure'
    assert '不包括对子公司的担保' in t and '254,100万元' in t and '不代替当前敞口' in t


@pytest.mark.parametrize('name',['星河精密股份有限公司','青禾食品有限公司','Northstar Robotics Limited'])
def test_company_independent_matching_roles_and_money_units(name):
    row=case_row(name=name,role='原告');row[4]='USD 1,200.50'
    p=package(structured('get_judicial_documents',cases([row]),name=name),target=name)
    assert p['facts'][0]['role']=='原告' and p['facts'][0]['amount']=='USD 1,200.50'
    assert '比亚迪' not in render_judicial(p)
