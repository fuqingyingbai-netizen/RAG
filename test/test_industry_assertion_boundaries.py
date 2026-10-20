"""v10 review regressions: synthetic excerpts, no network/model/business DB."""
import json
from types import SimpleNamespace

import pytest

from industry_assertions import reader_evidence_excerpt
from industry_claims import industry_gap_plan
from industry_grounding import sample_boundary, source_metadata
from industry_evidence import attach_provenance, source_fingerprint
from industry_research import (claim_semantic_issues, annotate_fact, append_evidence_index,
    bounded_package, normalize_risk, risk_repair_package)
from report_agents.industry_report_agent import IndustryReportAgent

SCOPE={'industry_name':'机器人','geography':'中国大陆','as_of_date':'2026-10-14','capital_market':'none'}


def card(eid='E-111111111111', **kwargs):
    return {'evidence_id':eid,'fact':'预计2026年中国机器人需求同比增长37%。',
            'evidence_quote':'预计2026年中国机器人需求同比增长37%。',
            'source_url':'https://research.example/report','source_title':'机器人报告',
            'evidence_scope':'industry_level','scope_match':'in_scope','module':'市场规模与增长',
            'numeric_context':{'metric':'同比增长','value':37,'unit':'%','period':'2026',
                               'definition':'中国机器人需求同比增长','geography':'中国大陆','is_forecast':True},
            'numeric_validation':{'passed':True}, **kwargs}


def codes(text, facts):
    return {i['code'] for i in claim_semantic_issues(text,facts)}


@pytest.mark.parametrize('text',[
    '标的须具备以词元为单位的调用和计费能力 E-111111111111',
    '提供按需调用服务是投资的硬性门槛 E-111111111111',
    '明确排除：\n- 仅提供离线SDK且无token化演进的标的 E-111111111111',
    '按需调用是投资的硬性门槛 E-111111111111（待核验）',
])
def test_expert_billing_opinion_cannot_become_an_investment_exclusion(text):
    f=card(fact='词元推动软件由授权订阅向按需调用发展。',evidence_quote='词元推动软件由授权订阅向按需调用发展。',numeric_context={},numeric_validation={})
    assert 'business_screening_rule_unsupported' in codes(text,[f])


@pytest.mark.parametrize('text',[
    '按需调用可作为一种商业模式观察，不代表所有标的必须按token计费。',
    '不能将token计费变成全行业投资硬门槛。',
    '是否必须采用token计费，需要按业务范围核验。',
])
def test_bounded_business_observations_and_questions_are_preserved(text):
    assert 'business_screening_rule_unsupported' not in codes(text,[card()])


def test_direct_scoped_rule_is_distinct_from_commentary():
    f=card(evidence_quote='本接口规范要求机器人API必须提供token计费选项。',numeric_context={},numeric_validation={})
    assert 'business_screening_rule_unsupported' not in codes('本规范接口必须提供token计费选项 E-111111111111',[f])


@pytest.mark.parametrize('label',['CAGR','复合年增长率','年均增长率','环比'])
def test_same_percent_does_not_authorize_a_different_growth_metric(label):
    assert 'growth_rate_kind_conflict' in codes(f'预计2024–2026年{label}为37% E-111111111111',[card()])
    assert 'growth_rate_kind_conflict' not in codes('预计2026年同比增长37% E-111111111111',[card()])


def test_actual_cagr_card_and_negated_comparison_are_not_rejected():
    f=card(numeric_context={**card()['numeric_context'],'metric':'复合年增长率','definition':'机器人需求复合年增长率','period':'2024–2026'})
    assert 'growth_rate_kind_conflict' not in codes('预计2024–2026年CAGR为37% E-111111111111',[f])
    assert 'growth_rate_kind_conflict' not in codes('不能把预计同比37%写成CAGR E-111111111111',[card()])


def test_borrowed_quote_rate_is_not_authorized_but_its_wrong_label_is_detected():
    f=card(evidence_quote='预计2026年中国机器人规模515亿美元，同比增长37%。',
           numeric_context={**card()['numeric_context'],'metric':'市场规模','value':515,'unit':'亿美元','definition':'机器人市场规模'})
    assert 'growth_rate_kind_conflict' in codes('预计2024–2026年CAGR37%（待核验） E-111111111111',[f])


def test_gdp_comparison_requires_a_comparable_reference_card():
    line='预计机器人增速37%远高于同期GDP增速 E-111111111111'
    assert 'growth_benchmark_missing' in codes(line,[card()])
    gdp=card('E-222222222222',numeric_context={**card()['numeric_context'],'metric':'GDP增长率','value':5,'definition':'中国国内生产总值同比增长率'})
    assert 'growth_benchmark_missing' not in codes(line+' E-222222222222',[card(),gdp])
    gdp['numeric_context']['period']='2024'
    assert 'growth_benchmark_missing' in codes(line+' E-222222222222',[card(),gdp])


@pytest.mark.parametrize('text,code',[
    ('企业数量占比反映投入错配风险。','allocation_inference_unsupported'),
    ('基础层企业少，产业链结构显著失衡。（待核验）','allocation_inference_unsupported'),
    ('市场规模持续增长，产业整合正在发生。','integration_inference_unsupported'),
    ('规模增长说明行业已越过小批量验证阶段。','commercial_certainty_unsupported'),
    ('高增长构成最坚实投资前提并降低赛道选择风险。（待核验）','commercial_certainty_unsupported'),
])
def test_macro_observations_do_not_prove_allocation_mergers_or_commercial_certainty(text,code):
    assert code in codes(text,[card()])
    assert code not in codes('不能据此声称'+text,[card()])


def test_actual_transaction_evidence_can_support_a_bounded_integration_statement():
    f=card(evidence_quote='已披露甲乙双方完成机器人业务合资整合案例。',numeric_context={},numeric_validation={})
    assert 'integration_inference_unsupported' not in codes('该合资整合正在发生 E-111111111111',[f])


def test_old_counts_cannot_be_rebased_to_research_cutoff():
    f=card(fact='机器人国家标准已发布30项，84项在编。',evidence_quote='机器人国家标准已发布30项，84项在编。',
           published_date='2025-09-18',numeric_context={},numeric_validation={})
    assert 'statistic_asof_rebased' in codes('截至2026年10月14日已发布机器人标准30项 E-111111111111',[f])
    assert 'statistic_asof_rebased' in codes('| 已发布标准 | 30项 | E-111111111111 | 2026-10-14（as_of_date） |',[f])
    assert 'statistic_asof_rebased' not in codes('2025年9月报道已发布机器人标准30项 E-111111111111',[f])


def test_growth_and_amount_units_are_separate():
    assert 'rate_unit_conflict' in codes('| 同比增速；单位：亿元 | E-111111111111 |',[card()])
    assert 'rate_unit_conflict' not in codes('| 收入规模单位：亿元；同比增速单位：% |',[card()])


def test_survey_footnote_is_preserved_and_does_not_invent_december_31():
    f=card(fact='图表：受访中国机器人企业的份额在2024年为36%，注：2024年为预估值。',
           evidence_quote='图表：受访中国机器人企业的份额在2024年为36%，注：2024年为预估值。',
           cleaning_method='llm',evidence_quote_verified=True,
           numeric_context={**card()['numeric_context'],'metric':'份额','value':36,'period':'2024-12-31','is_forecast':False})
    result=annotate_fact(f,SCOPE)
    assert result['numeric_context']['is_forecast'] is True
    assert result['numeric_context']['period']=='2024'
    assert sample_boundary(result) and result['eligible_for_risk_scoring'] is False


def test_publication_header_timestamp_is_distinct_from_a_statistic():
    src=SimpleNamespace(content='2025年09月18日 10:30 来源：行业报\n机器人标准已发布30项。',source_metadata={},source_type='web_search',url='https://example.org/report',object_key='')
    assert source_metadata(src)['published_date']=='2025-09-18'
    src.content='2024年中国机器人收入增长，2025年09月18日完成测算。'
    assert source_metadata(src)['published_date']==''


def test_bound_source_metadata_cannot_be_forged_by_a_model():
    f=card(publisher='证监会',published_date='2026-10-14',original_source_url='https://fake.example/original')
    src=SimpleNamespace(id=1,title=f['source_title'],url=f['source_url'],content=f['evidence_quote'],object_key='',
                        source_type='web_search',source_metadata={},credibility_score=70)
    bound=attach_provenance([f],[src])[0]
    assert bound['publisher']==bound['published_date']==bound['original_source_url']==''
    before=source_fingerprint([src])
    src.source_metadata['original_publisher']='已保存的原始发布机构'
    assert source_fingerprint([src])!=before


def test_pdf_host_and_roadmap_wording_do_not_authorize_publisher_or_current_state_claims():
    f=card(source_title='机器人发展规划',source_url='https://pdf.example/file.pdf',
           evidence_quote='到2020年初步建成产业生态链，培育若干骨干企业。',numeric_context={},numeric_validation={})
    assert 'publisher_attribution_unsupported' in codes('证监会旗下报告 E-111111111111',[f])
    assert 'roadmap_as_current_state' in codes('规划称培育企业，暗示龙头企业尚未成型 E-111111111111',[f])
    assert 'roadmap_as_current_state' not in codes('不能据历史规划措辞说明龙头企业尚未成型 E-111111111111',[f])


def test_verbatim_republications_and_explicit_common_original_are_not_independent():
    first=card();other=card('E-222222222222',source_url='https://second.example/report')
    assert 'source_corroboration_overstated' in codes('多源交叉验证。',[first,other])
    first.update(original_source_url='https://original.example/report')
    other.update(original_source_url='https://original.example/report',evidence_quote='另一网站转载机器人统计。')
    assert 'source_corroboration_overstated' in codes('多源数据一致。',[first,other])
    kept=json.loads(bounded_package({'facts':[first]}))['facts'][0]
    assert kept['original_source_url']==first['original_source_url']


def test_numerical_source_count_must_match_the_claim():
    fs=[card(),card('E-222222222222',source_url='https://second.example/report',evidence_quote='另一个报告预计2026年机器人需求同比增长37%。')]
    assert 'source_corroboration_overstated' in codes('5源一致。',fs)
    assert 'source_corroboration_overstated' not in codes('2源一致。',fs)


def test_blocked_legal_claim_is_not_republished_in_reader_index():
    quote='欧盟人工智能法案AI Act对高风险AI违规最高处营业额7%罚款。'
    f=card(fact=quote,evidence_quote=quote,numeric_context={},numeric_validation={})
    report='## 3. 政策\n该来源需复核 E-111111111111\n## 15. 信息来源\n## 16. 后续研究点'
    indexed,diagnostic=append_evidence_index(report,{'facts':[f]},[('章节',[])]*16,{3:{'facts':[f]}})
    assert '7%' not in indexed and '暂不转述' in indexed
    assert f['source_url'] in indexed and diagnostic['referenced_sources']==1


def test_index_only_exposes_authorized_metric_or_complete_located_sentence():
    f=card(fact='预计机器人同比37%，毛利率20%。',evidence_quote='预计机器人同比37%，毛利率20%。')
    excerpt=reader_evidence_excerpt(f)
    assert '37%' in excerpt and '20%' not in excerpt
    raw=card(claim_type='source_excerpt',fact='作者导航。未定位的其他结论。',evidence_quote='已定位机器人采用指定软件框架进行测试。',numeric_context={},numeric_validation={})
    assert reader_evidence_excerpt(raw)=='已定位机器人采用指定软件框架进行测试。'
    raw['evidence_quote']='尚未完成的例子，'
    assert '完整信息点' in reader_evidence_excerpt(raw)


def test_technical_fallback_does_not_fill_space_with_market_or_internet_counts():
    section=IndustryReportAgent()._fallback_section({'facts':[card()]},7,'技术路线对比')
    assert '37%' not in section and '尚未形成同条件' in section
    assert '第16章' in section


def test_new_metric_rejection_remains_auditable_and_one_repair_is_budgeted():
    f=card();name='市场增长与需求风险'
    risk=normalize_risk({'dimensions':[{'name':name,'score':30,'reason':'预计2024–2026年CAGR为37%。','evidence_ids':[f['evidence_id']]}]},[f],SCOPE)
    row=next(r for r in risk['dimensions'] if r['name']==name)
    assert row['score'] is None and row['unknown_cause']=='growth_rate_kind_conflict'
    repair=risk_repair_package({'facts':[f],'dimension_evidence_ids':{name:[f['evidence_id']]}},risk)
    assert len(repair['dimensions_to_repair'])==1


def test_failed_investment_rule_gets_one_repair_then_safe_fallback():
    f=card(fact='词元推动软件由授权订阅向按需调用发展。',evidence_quote='词元推动软件由授权订阅向按需调用发展。',numeric_context={},numeric_validation={})
    unsafe='## 10. 投资机会\n标的须具备token计费能力 E-111111111111'
    calls=[];degradations=[]
    def invoke(*args):calls.append(args);return unsafe
    result=IndustryReportAgent()._validate_section(unsafe,{'facts':[f]},10,'投资机会',invoke,lambda *a,**k:None,None,degradations)
    assert len(calls)==1 and '须具备' not in result
    assert 'business_screening_rule_unsupported' in degradations[0]['initial_validation_reasons']
    assert '投资筛选门槛缺证' in degradations[0]['message']


def test_legal_gap_dispatch_does_not_request_hardware_benchmarks():
    plan=industry_gap_plan('标识办法适用主体范围、标识技术方式与违规处罚条款')
    assert '发布机关原文' in plan[1] and '测试环境' not in plan[3]
