import json
from types import SimpleNamespace

from report_agents.company_source_review import (
    evidence_id, prepare_review, validate_selection, build_source_review,
    render_reviewed_statements, source_coverage,
    consolidate_reviewed_statements,
    document_date_proof, provenance,
)
from research_workflow import ResearchWorkflow
from report_agents.company_selection_audit import selection_audit

TARGET='青禾模型技术有限公司'


def test_selection_audit_supports_native_personnel_card_row_pairs_and_merged_mirrors():
    candidates=[({'evidence_id':'E-000000000001'},{'value':'董事'}),
                ({'evidence_id':'E-000000000002'},{'value':'董事'}),
                {'evidence_id':'E-000000000003','value':'旧职务'}]
    selected=[{'evidence_ids':['E-000000000001','E-000000000002'],'value':'董事'}]
    result=selection_audit(candidates,selected)
    assert result['E-000000000001']['candidate_claims']==1
    assert result['E-000000000002']['delivered_claims']==1
    assert result['E-000000000003']['state']=='not_selected_by_chapter_policy'


def source(number=1,body=None,**meta):
    return dict(id=number,url=f'https://records.gov.cn/notice/{number}.html',title='技术服务通告',
                content=body or ('2025年2月24日，'+TARGET+'研发的模型引发关注。国家机关依法驳回第三方抢注该模型名称的商标申请，相关申请人不是目标公司。'),
                summary='搜索摘要含有'+TARGET,source_metadata={'content_kind':'full_text',**meta})


def project(sources):
    return SimpleNamespace(target_name=TARGET,target_type='company',sources=sources,
                           company_research_intake={'as_of_date':'2026-10-20'})


def test_full_original_is_reviewable_when_legal_name_was_missing_from_clipped_fact_prefix():
    s=source(body='首页导航和长篇背景。'*500+'\n2025年2月24日，'+TARGET+'研发的技术服务进入公开试用。')
    card=dict(evidence_id=evidence_id(s),source_url=s['url'],fact='导航文字...[truncated]',
              evidence_scope='noise',eligible_for_report=False,claim_type='source_excerpt')
    docs,states=prepare_review(project([s]),{'facts':[card]},{})
    assert len(docs)==1
    assert TARGET in docs[0]['windows'][0]['quote']
    assert card['eligible_for_report'] is False and card['evidence_scope']=='noise'
    assert states['1']['state']=='pending_semantic_review'


def test_generated_search_summary_does_not_become_a_government_original():
    s=source(content_kind='search_summary')
    docs,_=prepare_review(project([s]),{'facts':[]},{})
    assert docs==[]


def test_explicitly_rejected_entity_is_not_recovered_from_a_full_page():
    s=source(entity_validation='rejected')
    assert prepare_review(project([s]),{'facts':[]},{})[0]==[]
    s=source()
    card=dict(source_url=s['url'],exclusion_reason='同名主体错误',eligible_for_report=False)
    assert prepare_review(project([s]),{'facts':[card]},{})[0]==[]


def test_selection_cannot_invent_a_quote_drop_negation_or_fabricate_a_fact_date():
    s=source()
    docs,_=prepare_review(project([s]),{'facts':[]},{})
    doc=docs[0];quote=doc['windows'][0]['quote']
    row=dict(evidence_id=doc['evidence_id'],quote=quote,chapter=9,scope='third_party_about_target',date='2025-02-24',relevance='第三方抢注的处理结果')
    admitted,error=validate_selection(row,{doc['evidence_id']:doc},TARGET,'2026-10-20')
    assert not error and admitted['eligible_for_risk_scoring'] is False
    assert '申请人不是目标公司' in admitted['fact']
    for changed in [dict(quote=quote.replace('不是','是')),dict(quote=quote.split('相关申请人')[0]),
                    dict(date='2024-01-01'),dict(evidence_id='E-FFFFFFFFFFFF'),dict(chapter=12)]:
        assert validate_selection({**row,**changed},{doc['evidence_id']:doc},TARGET,'2026-10-20')[0] is None


def test_bad_or_missing_model_response_remains_pending_instead_of_unusable():
    s=source();p=project([s])
    package=build_source_review(p,{'facts':[]},{},lambda *args:'unparseable',lambda *args,**kwargs:None)
    assert package['facts']==[]
    assert package['source_review']['1']['state']=='review_call_failed'
    p.company_source_review_package=package
    ledger=source_coverage(p,{'facts':[]},'')
    assert ledger['sources'][0]['outcome']=='context_or_unbound_pending_review'
    assert ledger['sources'][0]['review']['state']=='review_call_failed'


def test_all_source_records_have_independent_fetch_and_usage_outcomes():
    first=source();duplicate=source(2,first['content']);failed=source(3,content_kind='search_summary',fetch_status='blocked_or_challenge')
    uncited=source(4,'2025年2月24日，'+TARGET+'发布另一个具体模型服务，暂未独立核验其实际商业效果。')
    p=project([first,duplicate,failed,uncited])
    facts=[dict(source_url=s['url'],evidence_id=evidence_id(s),evidence_scope='target_direct',eligible_for_report=s is not failed) for s in p.sources]
    ledger=source_coverage(p,{'facts':facts},'## 6. 业务\n'+first['content']+'['+evidence_id(first)+']\n## 13. 来源')
    assert len(ledger['sources'])==4
    assert [r['outcome'] for r in ledger['sources']]==['body_cited','exact_original_duplicate','discovery_only_or_failed_original','target_matched_unconsumed_pending_review']
    assert ledger['sources'][2]['fetch_status']=='blocked_or_challenge'
    assert ledger['sources'][3]['body_cited'] is False


def test_reviewed_native_claim_appears_with_its_own_url_in_the_real_index():
    s=source();p=project([s])
    docs,_=prepare_review(p,{'facts':[]},{})
    quote=docs[0]['windows'][0]['quote'];eid=evidence_id(s)
    response=dict(decisions=[dict(evidence_id=eid,disposition='accepted',reason='具体第三方商标事项')],
                  facts=[dict(evidence_id=eid,quote=quote,chapter=9,scope='third_party_about_target',date='2025-02-24',relevance='商标保护')])
    review=build_source_review(p,{'facts':[]},{},lambda *args:json.dumps(response),lambda *args,**kw:None)
    p.company_source_review_package=review
    body='## 9. 企业司法负面核查'+render_reviewed_statements(review['facts'])+'\n\n## 13. 信息来源\n\n## 14. 后续研究建议'
    workflow=ResearchWorkflow.__new__(ResearchWorkflow)
    report=workflow._append_company_claim_evidence_index(p,body,[],total_traceable_sources=0,eligible_company_sources=0)
    assert s['url'] in report and eid in report.split('## 13.')[1]
    assert '申请人不是目标公司' in body
    assert p.company_source_coverage_package['summary']['body_cited_sources']==1
    assert evidence_id(s)==workflow._stable_evidence_id(s['url'],s['title'])


def test_window_id_retrieves_complete_native_quote_and_cannot_promote_a_model_date():
    s=source();docs,_=prepare_review(project([s]),{'facts':[]},{})
    doc=docs[0];window=doc['windows'][0]
    row=dict(evidence_id=doc['evidence_id'],window_id=window['window_id'],chapter=9,
             scope='third_party_about_target',relevance='第三方商标申请处理',date='2024-01-01',quote='伪造内容')
    record,error=validate_selection(row,{doc['evidence_id']:doc},TARGET,'2026-10-20')
    assert not error and record['fact']==window['quote'] and '不是目标公司' in record['fact']
    assert record['period']=='原页时点待核对'
    assert validate_selection({**row,'window_id':'W999'},{doc['evidence_id']:doc},TARGET)[0] is None


def test_label_lists_without_business_action_cannot_be_promoted_to_operating_progress():
    s=source(body='结构：MOS；技术：CMOS；功能：其他；申请主体：'+TARGET+'。')
    docs,_=prepare_review(project([s]),{'facts':[]},{})
    doc=docs[0]
    row=dict(evidence_id=doc['evidence_id'],window_id=doc['windows'][0]['window_id'],chapter=6,
             scope='target',relevance='技术标签')
    assert validate_selection(row,{doc['evidence_id']:doc},TARGET)[1]=='no_concrete_business_statement'


def test_batches_limit_source_count_and_split_retry_retains_failed_parent_response():
    sources=[source(n,body=f'2025年2月24日，{TARGET}董事会审议通过第{n}项具体治理制度，相关公开文件列明了会议表决及实施安排。') for n in range(1,14)]
    sizes=[]
    def invoke(role,prompt,trace):
        docs=json.loads(prompt.rsplit('\n',1)[-1])['originals'];sizes.append(len(docs))
        if len(docs)>3:return 'invalid large response'
        return json.dumps({'decisions':[dict(evidence_id=d['evidence_id'],disposition='needs_context',reason='需补原件时点') for d in docs],'facts':[]})
    result=build_source_review(project(sources),{'facts':[]},{},invoke,lambda *a,**kw:None)
    assert max(sizes)<=6 and result['diagnostic']['candidate_originals']==13
    assert result['diagnostic']['model_requests']==7
    assert all(r['state']=='reviewed_no_accepted_claim' for r in result['source_review'].values())
    assert any(r['response'].get('retry_origin',{}).get('raw_response')=='invalid large response' for r in result['review_receipts'])


def test_navigation_and_unbounded_funding_absence_cannot_be_promoted_to_history():
    s=source(body=TARGET+'自成立以来从未对外融资，这一概括未提供基准日和独立交易核验原件，不能认定为当前状态。')
    assert prepare_review(project([s]),{'facts':[]},{})[0]==[]
    s=source(body='近期，'+TARGET+'研发的模型引发了广泛关注。\n\n设为首页 | 加入收藏 | 无障碍浏览\n\n关于商标注册通告。')
    docs,_=prepare_review(project([s]),{'facts':[]},{})
    assert all('加入收藏' not in w['quote'] and 3 not in w['candidate_chapters'] for d in docs for w in d['windows'])


def test_same_original_and_reprinted_claim_are_consolidated_without_losing_the_appendix():
    quote='近期，'+TARGET+'研发的模型受到关注，个别代理机构涉嫌提供不法服务，国家机关依法驳回第82848449号等63件商标注册申请。'
    def row(number,chapter,text):return dict(source_id=str(number),evidence_id=f'E-{number:012X}',
        evidence_ids=[f'E-{number:012X}'],source_url=f'https://records.gov.cn/{number}',fact=text,
        chapter=chapter,source_kind='government_statement')
    records=[row(1,6,quote),row(1,9,quote),row(2,9,quote.replace('代理机构','代机构'))]
    status={'1':{},'2':{}}
    kept,appendix=consolidate_reviewed_statements(records,status)
    assert len(kept)==1 and kept[0]['chapter']==9 and kept[0]['fact']==quote
    assert status['2']['state']=='reviewed_appendix_only'
    assert any(r['source_id']=='2' and r['source_url'].endswith('/2') for r in appendix)
    assert records[0]['chapter']==6  # never rewrite the retained model response


def test_duplicate_detection_keeps_different_numbers_and_units_as_distinct_claims():
    def row(number,amount):return dict(source_id=str(number),evidence_id=f'E-{number:012X}',
        source_url=f'https://issuer.example/{number}',fact=TARGET+'披露本期业务收入'+amount+'，原文期间与业务统计范围需要分别核对。',chapter=6)
    kept,appendix=consolidate_reviewed_statements([row(1,'1亿元'),row(2,'1万元'),row(3,'2亿元'),row(4,'1亿元')],{str(i):{} for i in range(1,5)})
    assert len(kept)==3 and len(appendix)==1


def test_shorter_quote_and_wire_dateline_do_not_repeat_an_already_selected_statement():
    statement='2020年12月，市场监管总局依据相关法律对'+TARGET+'在中国境内网络零售平台服务市场滥用市场支配地位行为立案调查。'
    def row(number,text):return dict(source_id=str(number),evidence_id=f'E-{number:012X}',
        source_url=f'https://records.gov.cn/{number}',fact=text,chapter=9)
    kept,appendix=consolidate_reviewed_statements([
        row(1,'2021年4月10日。'+statement+'2021年4月，相关机关作出行政处罚决定。'),
        row(2,statement),row(3,'人民网北京4月10日电 （记者李明）据市场监管总局消息，'+statement)],{str(i):{} for i in range(1,4)})
    assert len(kept)==1 and len(appendix)==2
    # A different period is still a different statement, even with the same wording.
    kept,_=consolidate_reviewed_statements([row(1,statement),row(2,statement.replace('2020年','2022年'))],{'1':{},'2':{}})
    assert len(kept)==2


def test_flattened_vie_graph_and_ip_registry_do_not_become_corporate_ownership_rows():
    for body,reason in [
        (TARGET+'股权结构VIE示例：本公司、全资子公司、可变利益实体；50% 20% 20% 10%仅为图示标签，不表示节点间控制关系。','diagram_relationships_require_layout_review'),
        ('布图设计登记号：BS.20190001；布图设计权利人：'+TARGET+'；布图设计名称：测试芯片；申请日期为2019年7月15日。','not_a_corporate_registration_or_ownership_statement')]:
        s=source(body=body);docs,_=prepare_review(project([s]),{'facts':[]},{})
        doc=docs[0];window=doc['windows'][0]
        row=dict(evidence_id=doc['evidence_id'],window_id=window['window_id'],chapter=2,scope='target',relevance='主体字段')
        assert validate_selection(row,{doc['evidence_id']:doc},TARGET)[1]==reason


def test_native_citation_is_audited_when_the_same_source_has_a_different_legacy_card_id():
    s=source();native=evidence_id(s);p=project([s])
    card=dict(source_url=s['url'],evidence_id='E-FFFFFFFFFFFF',eligible_for_report=True,evidence_scope='target_direct')
    docs,states=prepare_review(p,{'facts':[card]},{2:'原件字段['+native+']'})
    assert not docs and states['1']['state']=='already_body_cited'
    audit=source_coverage(p,{'facts':[card]},'## 2. 主体\n['+native+']\n## 13. 来源')
    assert audit['sources'][0]['body_cited'] and native in audit['sources'][0]['evidence_ids']


def test_investor_table_needs_column_validation_even_without_a_pdf_page_marker():
    quote=('根据战略配售方案，拟参与发行人本次发行战略配售的投资者如下：\n序\n号\n投资者名称\n拟认购金额\n上限（万元）\n获配股票限售期\n1\n'
           +TARGET+'\n15,500.00\n36个月\n2\n其他公司\n15,000.00\n12个月')
    eid='E-000000000001'
    doc=dict(evidence_id=eid,source_id='1',source_url='https://filing.gov.cn/report.pdf',source_title='战略配售报告',
             source_kind='government_statement',subject_binding={},windows=[dict(window_id='W1',quote=quote,start=0,candidate_chapters=[10])])
    record,reason=validate_selection(dict(evidence_id=eid,window_id='W1',chapter=10,scope='target',relevance='投资者分类'),{eid:doc},TARGET)
    assert record is None and reason=='tabular_columns_require_specialized_layout_validation'


def test_source_date_is_an_explicit_unique_html_date_not_the_event_or_pdf_table_date():
    s=source(body='公告\n\n2024年8月28日\n\n'+TARGET+'董事会公告，任职事项见下文。')
    proof=document_date_proof(s)
    assert proof['date']=='2024-08-28' and proof['quote']=='2024年8月28日'
    s['content']+='\n\n2025年1月1日\n'
    assert document_date_proof(s)=={}
    s['content']='2024年12月31日\n'+TARGET+'财务表';s['url']='https://records.gov.cn/report.pdf'
    assert document_date_proof(s)=={}


def test_target_name_inside_another_issuers_filing_does_not_authenticate_its_ownership():
    s=source(body='战略配售核查报告\n\n名称\n'+TARGET+'\n注册资本：1000万元。其他事实待核。')
    s.update(url='https://www.hkexnews.hk/third-party.pdf',title='远山证券关于远山科技的核查报告')
    kind,binding=provenance(s,TARGET,{'roots':set(),'bilingual_names':[]})
    assert kind=='third_party_filing' and binding['publisher_not_authenticated_as_target'] is True


def test_short_damaged_pdf_heading_is_not_copied_even_when_the_following_chinese_is_readable():
    quote='--- PDF page 147 ---\nh אڷᗫڌਕሗਞቡ\n据此我们取得关联方33%的股份，原文尚需逐页核对。'
    eid='E-000000000001';doc=dict(evidence_id=eid,source_id='1',source_url='https://issuer.example/report.pdf',source_title=TARGET,
        source_kind='issuer_disclosure',subject_binding={},windows=[dict(window_id='W1',quote=quote,start=0,candidate_chapters=[2])])
    assert validate_selection(dict(evidence_id=eid,window_id='W1',chapter=2,scope='group',relevance='持股'),{eid:doc},TARGET)[1]=='damaged_pdf_heading_requires_original_page_review'


def test_financial_prose_is_routed_to_business_only_with_its_literal_reporting_header():
    quote='净利润为人民币104.44亿元，同比下降75%，主要归因于我们所持有的股权投资按市值计价净收益减少。'
    eid='E-000000000001';window=dict(window_id='W1',quote=quote,start=100,candidate_chapters=[2])
    doc=dict(evidence_id=eid,source_id='1',source_url='https://issuer.example/results',source_title=TARGET+'季度业绩',
        source_kind='issuer_disclosure',subject_binding={},windows=[window])
    row=dict(evidence_id=eid,window_id='W1',chapter=2,scope='group',relevance='季度披露')
    assert validate_selection(row,{eid:doc},TARGET)[0] is None
    window['context_quote']='截至2026年6月30日止季度：'
    record,error=validate_selection(row,{eid:doc},TARGET)
    assert not error and record['chapter']==6 and record['fact']==quote
    assert '截至2026年6月30日止季度' in render_reviewed_statements([record])
