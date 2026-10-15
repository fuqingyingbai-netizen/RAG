import json
from types import SimpleNamespace

from report_agents.company_summary import (
    SUMMARY_HEADINGS, build_company_summary_package, build_company_summary_prompt,
    fallback_company_summary, summary_errors,
    _disclosure_financial_claims,
    normalize_company_summary,
)
from report_agents.company_report_agent import CompanyReportAgent


def project(sources=()):
    return SimpleNamespace(target_name="目标科技股份有限公司", title="目标科技研究", industry="制造业",
                           description="主营业务与公开风险核查", sources=list(sources), target_type="company")


def card(i=1, text="目标科技股份有限公司2025年营业收入10亿元。", **changes):
    return dict(evidence_id=f"E-{i:012X}", fact=text, evidence_quote=text,
                source_title="目标科技股份有限公司2025年年度报告", source_url=f"https://evidence.test/{i}",
                evidence_scope="target_direct", claim_type="fact", eligible_for_report=True,
                source_grade="A", **changes)


def source(fact, content, tool="", **meta):
    return SimpleNamespace(url=fact['source_url'], title=fact['source_title'], content=content,
                           source_metadata={"tool":tool, **meta})


def section(text):
    return "## 1. 摘要\n\n" + "\n\n".join(f"### {heading}\n{text if i==1 else '本章证据覆盖有限，相关判断待核验。'}"
                                                for i, heading in enumerate(SUMMARY_HEADINGS))


def test_summary_rejects_related_company_even_when_target_is_in_title():
    direct=card()
    related=card(2,"子公司新能源汽车零部件收入124.5亿元。")
    related['evidence_scope']='related_entity_context'
    package=build_company_summary_package({'facts':[direct,related]},project().target_name)
    assert [f['evidence_id'] for f in package['facts']]==[direct['evidence_id']]


def test_current_structured_shareholders_survive_long_web_excerpts():
    web=card(1,"目标科技股份有限公司。"+'网页摘要。'*500)
    web['claim_type']='source_excerpt'
    share=card(2)
    share.update(source_url='structured://qcc/shareholders',is_structured_evidence=True,
                 source_entity_validation='verified',claim_type='source_excerpt')
    raw='| 企业名称 | 目标科技股份有限公司 |\n| 股东名称 | 持股比例 | 持股数 |\n| 王甲 | 16.90% | 100000 |'
    package=build_company_summary_package({'facts':[web,share]},project().target_name,
        [source(share,raw,'get_shareholder_info',entity_validation='verified')])
    assert any('16.90%' in f['fact'] for f in package['facts'])
    assert all(len(f['fact'])<=650 for f in package['facts'])


def test_summary_uses_original_late_financial_sentence_not_search_summary():
    fact=card();fact.update(claim_type='source_excerpt',fact='目标科技股份有限公司注册资料摘要。')
    raw='目标科技股份有限公司2025年年度报告\n\n'+'目录和导航。'*700+'\n\n本集团2025年营业收入10亿元，同比增长20%。'
    package=build_company_summary_package({'facts':[fact]},project().target_name,[source(fact,raw)])
    assert any('营业收入10亿元' in f['fact'] for f in package['facts'])


def test_summary_recovers_filing_table_column_meanings_and_negative_growth():
    fact=card();fact['claim_type']='source_excerpt'
    raw=('目标科技股份有限公司2025年年度报告\n\n'
         '| | 本报告期 | 上年同期 | 同比增减 |\n'
         '| 营业收入（元） | 10,000,000,000.00 | 12,000,000,000.00 | -16.67% |')
    package=build_company_summary_package({'facts':[fact]},project().target_name,[source(fact,raw)])
    assert any('上年同期为12,000,000,000.00元，同比-16.67%' in f['fact'] for f in package['facts'])
    assert summary_errors(section('营业收入10,000,000,000.00元，同比16.67%。[E-000000000001]'),package)


def test_filing_table_requires_explicit_headers_and_handles_reversed_columns():
    row='| 营业收入（元） | 12,000,000,000.00 | 10,000,000,000.00 | -16.67% |'
    assert _disclosure_financial_claims(row,'2025年年度报告')==[]
    claims=_disclosure_financial_claims('| | 上年同期 | 本报告期 | 同比增减 |\n'+row,'2025年年度报告')
    assert '营业收入为10,000,000,000.00元，上年同期为12,000,000,000.00元' in claims[0]


def test_summary_drops_national_export_number_in_company_filing():
    fact=card();fact['claim_type']='source_excerpt'
    raw='目标科技股份有限公司2025年年度报告\n\n中国新能源汽车出口达128.4万辆，同比增长6.7%。\n\n本集团2025年营业收入10亿元，同比增长20%。'
    package=build_company_summary_package({'facts':[fact]},project().target_name,[source(fact,raw)])
    assert '128.4' not in json.dumps(package,ensure_ascii=False)
    assert '10亿元' in json.dumps(package,ensure_ascii=False)


def test_literal_summary_rebuild_keeps_competition_period_and_passes_validation():
    financial = card()
    competition = card(2, "本集团新能源汽车市占率提升至33.2%。")
    package = build_company_summary_package({'facts':[financial,competition]}, project().target_name)
    assert any(f['summary_topic']=='competition' for f in package['facts'])
    rebuilt = fallback_company_summary(project(), package)
    assert '33.2%' in rebuilt and '[E-000000000002]' in rebuilt
    assert summary_errors(rebuilt, package)==[]


def test_no_hit_is_query_observation_never_positive_company_fact():
    fact=card();fact.update(source_url='structured://qcc/penalty',is_structured_evidence=True,
                           source_entity_validation='verified',claim_type='source_excerpt')
    raw='| 企业名称 | 目标科技股份有限公司 |\n| 搜索结果 | 当前未发现行政处罚相关记录。经营表现良好，无历史遗留违规。 |'
    package=build_company_summary_package({'facts':[fact]},project().target_name,[source(fact,raw,'get_administrative_penalty')])
    assert package['facts']==[]
    assert package['query_observations'][0]['status']=='no_record_in_returned_query'
    assert '经营表现良好' not in json.dumps(package,ensure_ascii=False)


def test_structured_wrong_company_cannot_be_reintroduced_by_target_title():
    fact=card();fact.update(source_url='structured://qcc/register',is_structured_evidence=True,
                           source_entity_validation='verified',claim_type='source_excerpt')
    raw='| 企业名称 | 另一科技股份有限公司 |\n| 注册资本 | 200万元 |'
    package=build_company_summary_package({'facts':[fact]},project().target_name,[source(fact,raw,'get_company_registration_info')])
    assert package['facts']==[]


def test_summary_budget_keeps_whole_cards_and_removes_mirrored_duplicates():
    facts=[card(i,f'目标科技股份有限公司2025年产品{i}收入{i}亿元，客户合同已披露。') for i in range(1,30)]
    facts.append(card(100,facts[0]['fact']))
    package=build_company_summary_package({'facts':facts},project().target_name,limit=2400)
    raw=json.dumps(package,ensure_ascii=False)
    assert len(raw)<=2400 and json.loads(raw)['facts']
    assert sum(f['fact']==facts[0]['fact'] for f in package['facts'])<=1


def test_summary_validator_rejects_fabricated_id_number_unit_and_rating():
    package=build_company_summary_package({'facts':[card()]},project().target_name)
    assert not summary_errors(section('公司2025年营业收入10亿元。[E-000000000001]'),package)
    for text in ['公司2025年营业收入100亿元。[E-000000000001]',
                 '公司2025年营业收入10万美元。[E-000000000001]',
                 '公司2025年营业收入10亿元。[E-FFFFFFFFFFFF]',
                 '公司评级BBB+。[E-000000000001]']:
        assert summary_errors(section(text),package)


def test_summary_validator_rejects_tables_duplicate_claims_and_bloat():
    package=build_company_summary_package({'facts':[card()]},project().target_name)
    body='目标科技股份有限公司2025年营业收入10亿元，经营收入已经列示。[E-000000000001]'
    assert any('重复' in x for x in summary_errors(section(body+'\n'+body),package))
    assert any('表格' in x for x in summary_errors(section('| 项目 | 数值 |'),package))
    assert any('1400' in x for x in summary_errors(section('待核验。'*500),package))


def test_summary_prompt_contains_complete_json_without_inheriting_other_chapter_claims():
    package=build_company_summary_package({'facts':[card()]},project().target_name)
    prompt=build_company_summary_prompt(project(),package,{2:'已完成章节 [E-000000000001]',9:'未提供证据 [E-FFFFFFFFFFFF]'})
    assert json.dumps(package,ensure_ascii=False) in prompt
    assert 'E-FFFFFFFFFFFF' not in prompt
    assert '无重大历史遗留问题' not in prompt


def test_summary_invalid_repair_falls_back_visibly_without_fabricated_claims():
    p=project();calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        return section('营业收入999亿元。[E-FFFFFFFFFFFF]')
    result=CompanyReportAgent()._write_summary(p,json.dumps({'facts':[card()]}),{},invoke,lambda *a,**k:None)
    assert len(calls)==2 and p.company_summary_diagnostic['rebuilt_from_evidence']
    assert p.company_summary_diagnostic['model_errors']
    assert not p.company_summary_diagnostic['degraded']
    assert '999' not in result and 'FFFFFFFFFFFF' not in result


def test_summary_is_written_after_other_chapters_and_not_auto_padded(monkeypatch):
    p=project();agent=CompanyReportAgent();order=[]
    monkeypatch.setattr(agent,'_write_section',lambda p,c,r,i,*a: order.append(i) or f'## {i}. 正文章节\n事实 [E-000000000001]')
    def summary(*args):
        assert 1 not in order
        assert set(range(2,13)) <= set(args[2])  # includes explicit no-evidence chapters
        return section('目标科技股份有限公司2025年营业收入10亿元。[E-000000000001]')
    monkeypatch.setattr(agent,'_write_summary',summary)
    result=agent.generate(p,json.dumps({'facts':[card()]}),'{}',lambda *a:'',lambda s,n:s[:n],lambda *a,**k:None)
    chapter_one=result.split('## 2.')[0]
    assert '本章引用证据' not in chapter_one


def test_empty_summary_keeps_template_blocks_and_review_boundary():
    p=project();agent=CompanyReportAgent()
    result=agent.generate(p,'{"facts":[]}','{}',lambda *a:'',lambda s,n:s[:n],lambda *a,**k:None)
    chapter_one=result.split('## 2.')[0]
    assert all('### '+heading in chapter_one for heading in SUMMARY_HEADINGS)
    assert '人工复核' in chapter_one and p.company_summary_diagnostic['degraded']


def test_summary_decline_word_keeps_negative_percentage_meaning():
    package=build_company_summary_package({'facts':[card(text='目标科技股份有限公司2025年营业收入10亿元，同比-16.67%。')]},project().target_name)
    assert not summary_errors(section('公司2025年营业收入10亿元，同比下降16.67%。[E-000000000001]'),package)


def test_structured_summary_renders_five_blocks_and_adjacent_references():
    obj={heading:{'text':'本次研究的相关判断待核验。','evidence_ids':[]} for heading in SUMMARY_HEADINGS}
    obj['核心发现点']=[{'text':'公司2025年营业收入10亿元。[E-000000000001]','evidence_ids':['E-000000000001']}]
    obj['需关注信号']=[{'text':'相关案件待核验。','evidence_ids':[]}]
    text=normalize_company_summary('```json\n'+json.dumps(obj,ensure_ascii=False)+'\n```')
    package=build_company_summary_package({'facts':[card()]},project().target_name)
    assert '\n- 公司2025年营业收入10亿元。[E-000000000001]' in text
    assert text.count('[E-000000000001]')==1
    assert not summary_errors(text,package)


def test_summary_rejects_merging_distinct_nominee_and_clearing_nodes():
    package=build_company_summary_package({'facts':[card()]},project().target_name)
    errors=summary_errors(section('HKSCC NOMINEES LIMITED即香港中央结算有限公司。[E-000000000001]'),package)
    assert any('登记节点' in error for error in errors)


def test_summary_financial_conclusion_cannot_cite_only_judicial_record():
    fact=card(text='目标科技股份有限公司本次平台扫描裁判文书为117条。')
    package=build_company_summary_package({'facts':[fact]},project().target_name)
    errors=summary_errors(section('公司营收与利润同比下滑，待核验。[E-000000000001]'),package)
    assert any('财务判断' in error for error in errors)


def test_summary_legal_representative_needs_registration_not_just_management_card():
    fact=card(text='目标科技股份有限公司主要人员：王甲，董事长、总裁。')
    package=build_company_summary_package({'facts':[fact]},project().target_name)
    errors=summary_errors(section('王甲为公司法定代表人、董事长及总裁。[E-000000000001]'),package)
    assert any('工商登记' in error for error in errors)


def test_summary_uncertainty_label_cannot_hide_an_uncited_number():
    package=build_company_summary_package({'facts':[card()]},project().target_name)
    errors=summary_errors(section('公司营业收入可能为999亿元，待核验。'),package)
    assert any('来源引用' in error for error in errors)


def test_near_duplicate_claims_with_different_amounts_are_not_erased():
    a=card(1,'目标科技股份有限公司2024年营业收入10亿元，相关业务维持稳定。')
    b=card(2,'目标科技股份有限公司2025年营业收入12亿元，相关业务维持稳定。')
    package=build_company_summary_package({'facts':[a,b]},project().target_name)
    assert len(package['facts'])==2


def test_mcp_tool_level_quota_error_is_not_a_successful_no_hit(monkeypatch):
    from research_workflow import ResearchWorkflow
    workflow=ResearchWorkflow.__new__(ResearchWorkflow)
    payload={'result':{'isError':True,'content':[{'type':'text','text':"Error calling tool 'get_company_info': 余额不足或配额已用完"}]}}
    monkeypatch.setattr(workflow,'_mcp_rpc',lambda *a,**k:(payload,None))
    result,_=workflow._mcp_call_tool('https://provider.test',{},'get_company_info',{})
    assert result['error']['code']=='tool_execution_error'
    assert '余额不足' in result['error']['message']


def test_mcp_successful_registration_result_is_unchanged(monkeypatch):
    from research_workflow import ResearchWorkflow
    workflow=ResearchWorkflow.__new__(ResearchWorkflow)
    payload={'result':{'content':[{'type':'text','text':'企业名称：目标科技股份有限公司'}]}}
    monkeypatch.setattr(workflow,'_mcp_rpc',lambda *a,**k:(payload,None))
    result,_=workflow._mcp_call_tool('https://provider.test',{},'get_company_info',{})
    assert result==payload


def test_xiniu_quota_failure_stops_repeated_aspect_calls(monkeypatch):
    from research_workflow import ResearchWorkflow
    workflow=ResearchWorkflow.__new__(ResearchWorkflow);calls=[]
    monkeypatch.setenv('XINIU_API_KEY','test-key')
    monkeypatch.setattr(workflow,'_mcp_initialize',lambda *a,**k:(None,True,''))
    def call(*a,**k):
        calls.append(1)
        return {'error':{'code':'tool_execution_error','message':'余额不足或配额已用完'}},None
    monkeypatch.setattr(workflow,'_mcp_call_tool',call)
    assert workflow._collect_xiniu_sources(None,project(),project().target_name,{})==0
    assert len(calls)==1
