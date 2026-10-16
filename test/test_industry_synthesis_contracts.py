"""Round-nine review regressions, using synthetic public-style passages only."""
import json
import re
from types import SimpleNamespace

import pytest

from industry_claims import claim_contract_issues, table_completeness_issues, industry_gap_plan
from industry_delivery import finalize_synthesis, risk_status_section, verification_tasks
from industry_evidence import attach_provenance
from industry_grounding import complete_excerpt, source_metadata
from industry_research import (annotate_fact, normalize_risk, extract_industry_source_facts,
    select_chapter_evidence, bounded_package, risk_fact_applicable, append_evidence_index)
from report_agents.industry_report_agent import IndustryReportAgent

SCOPE={'industry_name':'机器人','geography':'中国大陆','capital_market':'none','named_companies':[],'as_of_date':'2026-10-16'}


def card(eid='E-111111111111',**changes):
    return {'evidence_id':eid,'fact':'2024年中国机器人市场规模100亿元。','evidence_quote':'2024年中国机器人市场规模100亿元。',
        'source_title':'机器人统计报告','source_url':'https://stats.example/report','module':'市场规模与增长',
        'scope_match':'in_scope','evidence_scope':'industry_level','eligible_for_report':True,
        'numeric_validation':{'passed':True}, 'numeric_context':{'metric':'市场规模','value':100,'unit':'亿元',
            'geography':'中国大陆','period':'2024','definition':'机器人市场规模','is_forecast':False}, **changes}


def source(body,**changes):
    return SimpleNamespace(id=7,title='机器人行业研究报告',content=body,url='https://stats.example/report',
        source_type='web_search',source_metadata={'module':'技术路线对比'},credibility_score=70,object_key='raw/7.txt',**changes)


def codes(text,facts=None):
    return {i['code'] for i in claim_contract_issues(text,facts or [])}


def test_risk_table_has_every_enabled_dimension_and_cannot_inherit_model_states():
    from industry_research import active_risk_dimensions
    rows=[{'name':name,'score':score,'level':'medium' if score is not None else 'unknown',
           'reason':'来源支持该风险判断。' if score is not None else '未取得可比口径。',
           'unknown_cause':'model_abstained','evidence_ids':['E-111111111111'] if score is not None else []}
          for name,score in zip(active_risk_dimensions(SCOPE),[45,38,None,42,50,None])]
    risk={'dimensions':rows,'overall_score':None}
    dirty='## 14. 综合评估\n技术风险未知，仅市场完成评估。\n## 15. 信息来源\n索引\n## 16. 后续研究点\n旧任务'
    once,tasks=finalize_synthesis(dirty,{},risk,[],SCOPE)
    twice,_=finalize_synthesis(once,{},risk,[],SCOPE)
    assert twice==once
    assert '技术风险未知' not in once and '6个启用风险维度中，4项已评估' in once
    assert '| 技术迭代与替代风险 | 已评估 | 50 | 中 |' in once
    assert '| 数据口径与证据可靠性风险 | 未完成评估 | 未评分 | 未知 |' in once
    assert '资本热度' not in once and '总分暂不计算' in once
    assert [t['topic'] for t in tasks]==['竞争格局与集中度风险','数据口径与证据可靠性风险']


def test_model_writer_never_rewrites_risk_status_or_invents_followup_tasks():
    project=SimpleNamespace(title='机器人研究',target_name='机器人',target_type='industry',industry_scope=SCOPE,industry='机器人',description='')
    roles=[]
    def invoke(role,prompt,trace):
        roles.append(role)
        return ''
    report=IndustryReportAgent().generate(project,json.dumps({'facts':[card()]}),json.dumps({}),invoke,lambda s,n:s[:n],lambda *a,**k:None)
    assert not any(r.endswith(' - 综合评估') or r.endswith(' - 后续研究点') for r in roles)
    assert re.findall(r'^## (\d+)\.',report,re.M)==[str(i) for i in range(1,17)]


def test_unknown_tasks_cannot_be_crowded_out_by_early_boilerplate_and_skip_disabled_modules():
    payload={'evidence_coverage':{'requirements':[{'requirement_id':str(i),'question':'行业统计'+str(i),'status':'candidate'} for i in range(20)]}}
    risk={'dimensions':[{'name':'竞争格局与集中度风险','score':None,'reason':'缺少份额分母','unknown_cause':'model_abstained'},
                        {'name':'资本热度与估值风险','score':None}]}
    tasks=verification_tasks(payload,risk,[{'chapter':7,'message':'技术章节修复失败'},{'chapter':8,'message':'关闭'}],SCOPE)
    assert tasks[0]['topic']=='竞争格局与集中度风险' and len(tasks)==22
    assert tasks[-1]['chapter']==7 and all(t['topic']!='资本热度与估值风险' for t in tasks)
    assert not any('已补搜' in t['action'] or '已访谈' in t['action'] for t in tasks)


@pytest.mark.parametrize('title',['机器人行业代表性上市企业毛利率','部分上市公司经营样本','机器人上市企业样本盈利质量'])
def test_author_saying_industry_average_does_not_remove_sample_boundary(title):
    f=card(source_title=title,module='商业模式与盈利逻辑',fact='2024年机器人行业平均毛利率37.2%。',
        evidence_quote='2024年机器人行业平均毛利率37.2%。', numeric_context={'metric':'毛利率','value':37.2,'unit':'%',
            'period':'2024','geography':'中国大陆','definition':'机器人毛利率'})
    checked=annotate_fact(f,SCOPE)
    assert checked['evidence_scope']=='representative_company' and checked['eligible_for_risk_scoring'] is False
    assert f['evidence_scope']=='industry_level'
    assert not risk_fact_applicable(f,'商业化与盈利模式风险')  # Legacy card is also excluded during replay.
    risk=normalize_risk({'dimensions':[{'name':'商业化与盈利模式风险','score':42,'level':'medium','evidence_ids':[f['evidence_id']]}]},[f],SCOPE)
    row=next(d for d in risk['dimensions'] if d['name']=='商业化与盈利模式风险')
    assert row['score'] is None and row['unknown_cause']=='no_applicable_evidence'
    assert 'sample_extrapolation_unsupported' in codes('唯一可验证的行业级盈利指标 E-111111111111',[f])
    assert 'sample_extrapolation_unsupported' not in codes('仅限代表企业样本，不能代表行业平均 E-111111111111',[f])


def test_industry_population_statistics_are_not_misclassified_merely_for_mentioning_companies():
    f=card(source_title='全国机器人行业统计年鉴',fact='全国机器人企业收入统计，涵盖行业总体。',numeric_context={})
    assert annotate_fact(f,SCOPE)['evidence_scope']=='industry_level'


@pytest.mark.parametrize('text,expected',[
    ('同业竞争呈高度分散化特征。','concentration_inference_unsupported'),
    ('应用层企业占比85%，表明准入门槛相对较低 E-111111111111','entry_barrier_inference_unsupported'),
    ('应用层主体聚集于低门槛市场。','entry_barrier_inference_unsupported'),
    ('未取得标准执行记录，政策执行效力存疑。','evidence_gap_as_policy_effect'),
    ('所有清洗事实均未定义产业链。','evidence_absence_overstated'),
    ('标准发布将缩短审批周期。','policy_causal_inference_unsupported'),
    ('情景假设增长22.5%，2027至2030年规模1.8万亿元至2.5万亿元，待核验。','derived_forecast_unvalidated'),
])
def test_unlicensed_inferences_and_new_forecasts_are_rejected(text,expected):
    assert expected in codes(text,[card()])


def test_supported_concentration_barrier_forecast_and_uncertainty_are_preserved():
    f=card(fact='机器人行业进入壁垒较低，迁移成本低。',evidence_quote='机器人行业进入壁垒较低，迁移成本低。',
           numeric_context={**card()['numeric_context'],'metric':'CR3集中度','value':15})
    assert not codes('行业高度分散，CR3为15% E-111111111111',[f])
    assert not codes('进入壁垒较低 E-111111111111',[f])
    assert not codes('不能据企业数量推断行业高度分散；执行效力是否不足仍需核验。',[f])
    assert not codes('来源预测2024年规模为100亿元 E-111111111111',[card()])
    assert not codes('本章保留的证据不足以形成技术路线比较，需核对候选测试。',[])


def test_partial_count_table_cannot_present_itself_as_a_complete_total():
    table='上海机器人企业按行政区如下（合计535家）：\n| 区域 | 企业数量 | 占比 |\n| --- | --- | --- |\n| 甲 | 145家 | 27% |\n| 乙 | 300家 | 56% |\n'
    assert table_completeness_issues(table)[0]['code']=='table_total_incomplete'
    assert not table_completeness_issues(table.replace('如下','部分列示如下'))
    assert not table_completeness_issues(table.replace('535','445'))


def test_rule_extraction_reserves_chain_and_vendor_conditions_after_macro_statistics():
    macro='\n'.join(f'2024年中国机器人市场规模达到{n}亿元。' for n in range(100,115))
    body=macro+'\n本平台自持集群。\n机器人产业链上游提供芯片，中游构建模型，下游开发应用。\n统一硬件测试条件为8卡集群，软件栈锁定INT4及指定模型。\n7B模型单卡吞吐量580 token/s，首token延迟34.7ms。'
    src=source(body);src.title='算力租赁实测横评'
    cards=extract_industry_source_facts([src],SCOPE)
    assert len(cards)<=10
    assert any('上游' in f['fact'] for f in cards)
    benchmarks=[f for f in cards if f.get('claim_type')=='vendor_benchmark']
    assert any('统一硬件' in f['fact'] for f in benchmarks) and any('580 token/s' in f['fact'] for f in benchmarks)
    assert all(f['evidence_scope']=='representative_company' for f in benchmarks)
    checked=[annotate_fact(f,SCOPE) for f in cards]
    assert all(f['scope_match']=='in_scope' for f in checked)
    package=select_chapter_evidence({'facts':checked},'技术路线对比',['技术路线'])
    assert package['selection_coverage']['task_selected']['技术测试条件']>=1
    assert package['selection_coverage']['task_selected']['技术性能']>=1


def test_task_reservations_survive_many_high_quality_macro_cards():
    macros=[card('E-'+f'{i:012X}',module='技术路线对比',quality_score=99) for i in range(20)]
    condition=card('E-AAAAAAAAAAAA',fact='机器人统一硬件测试环境为8卡，软件及模型版本固定。',evidence_quote='机器人统一硬件测试环境为8卡，软件及模型版本固定。',
        module='其他',numeric_context={},numeric_validation={},quality_score=20)
    selected=select_chapter_evidence({'facts':macros+[condition]},'技术路线对比',['吞吐量'])
    assert condition['evidence_id'] in {f['evidence_id'] for f in selected['facts']}


def test_report_cutoff_is_not_imputed_as_a_numeric_statistical_period():
    f=card(cleaning_method='llm',evidence_quote_verified=True,numeric_context={**card()['numeric_context'],'period':'截至2026年'})
    checked=annotate_fact(f,SCOPE)
    assert checked['numeric_context']['period']=='' and not checked['numeric_validation']['passed']
    assert 'period' in checked['numeric_validation']['missing_fields']


def test_numeric_geography_comes_from_the_target_block_not_later_global_ambition():
    f=card(cleaning_method='llm',evidence_quote_verified=True,
        fact='第一步到2020年我国机器人市场规模达到1500亿元，形成全球领先骨干企业。',
        evidence_quote='第一步到2020年我国机器人市场规模达到1500亿元，形成全球领先骨干企业。',
        numeric_context={**card()['numeric_context'],'geography':'全球','value':1500,'period':'2020'})
    checked=annotate_fact(f,SCOPE)
    assert checked['numeric_context']['geography']=='中国大陆' and checked['numeric_context']['period']=='2020'
    assert checked['numeric_context']['is_forecast'] is True


def test_raw_fallback_uses_complete_located_sentences_and_never_later_page_prose():
    src=source('# 机器人报道\n作者：某编辑\n机器人测试披露了统一硬件与模型条件。\n后续争议句尚未写完，')
    f=card(claim_type='source_excerpt',fact=src.content+'未定位的经营恶化结论。',evidence_quote='机器人测试披露了统一硬件与模型条件。',numeric_context={},numeric_validation={})
    located=attach_provenance([f],[src])[0]
    assert located['provenance']['locator']['body_version_id'].startswith('sha256:')
    assert located['provenance']['locator']['body_field']=='research_sources.content_snapshot'
    assert located['provenance']['locator']['archive_binding_status']=='not_verified'
    serialized=json.loads(bounded_package({'facts':[located]}))['facts'][0]
    assert serialized['fact']=='机器人测试披露了统一硬件与模型条件。'
    fallback=IndustryReportAgent()._fallback_section({'facts':[located]},13,'风险核查')
    assert '未定位' not in fallback and '某编辑' not in fallback and not fallback.endswith('，')
    assert complete_excerpt(src.content)=='机器人测试披露了统一硬件与模型条件。'


def test_publication_metadata_is_kept_separate_and_source_index_has_publisher_version():
    src=source('发布日期：2025年9月18日\n2024年中国机器人市场规模100亿元。')
    src.source_metadata.update(publisher='行业统计机构')
    f=attach_provenance([card()],[src])[0]
    assert f['published_date']=='2025-09-18' and f['numeric_context']['period']=='2024'
    md,diagnostic=append_evidence_index('## 2. 定义\nE-111111111111\n## 15. 信息来源\n## 16. 后续研究点',{'facts':[f]},[('章节',[])]*16,{2:{'facts':[f]}})
    assert '发布：2025-09-18' in md and '行业统计机构' in md and 'sha256:' in md
    assert diagnostic['referenced_sources']==1
    src.source_metadata={}
    src.content='2024年机器人市场规模100亿元。'
    assert source_metadata(src)['published_date']==''  # No invention from a statistic.


def test_chain_and_market_verification_methods_do_not_inherit_patent_or_hardware_boilerplate():
    chain=industry_gap_plan('产业链标准分层的定义待核验')
    market=industry_gap_plan('算力市场规模的统计口径待核验')
    assert '产业链图表' in chain[3] and '专利统计' not in chain[3]
    assert '原始统计表' in market[3] and '测试环境' not in market[3]


def test_locator_remains_resolvable_when_current_source_body_is_refreshed():
    import hashlib
    src=source('2024年中国机器人市场规模100亿元。')
    snapshots={}
    f=attach_provenance([card()],[src],snapshots)[0]
    locator=f['provenance']['locator']
    src.content='下一轮刷新后的网页正文。'
    saved=snapshots[locator['snapshot_key']]['content']
    assert hashlib.sha256(saved.encode()).hexdigest()==locator['body_sha256']
    assert saved[locator['start']:locator['end']]==locator['quote']
    assert locator['body_field'].startswith('cleaned_facts.source_body_snapshots.')
    assert src.content!=saved and len(snapshots)==1


def test_proposal_uses_exact_current_structured_task_list_without_truncating_late_items():
    from report_agents.industry_proposal import build_industry_proposal
    tasks=[{'topic':f'核验问题{i}','reason':'对应材料缺失','action':'核对原始报告','priority':'高','materials':'原始数据表'} for i in range(21)]
    project=SimpleNamespace(title='机器人研究',target_name='机器人',industry_scope=SCOPE,
                            industry_verification_tasks=tasks,industry_report_degradations=[])
    proposal=build_industry_proposal(project,report='旧正文技术路线缺少数据',risk_json='{}')
    assert '核验问题20' in proposal and '旧正文' not in proposal
    assert proposal.count('| 对应材料缺失 |')==21


def test_summary_only_content_never_becomes_a_rule_fact_and_independent_test_is_not_called_vendor():
    src=source('机器人测试报告采用统一硬件测试条件，吞吐量580 token/s。')
    src.title='机器人实测横评'
    src.source_metadata['content_kind']='summary_only'
    assert extract_industry_source_facts([src],SCOPE)==[]
    src.source_metadata.pop('content_kind')
    facts=extract_industry_source_facts([src],SCOPE)
    assert facts and all(f.get('claim_type')=='benchmark_sample' for f in facts)
    assert all(f['evidence_scope']=='representative_company' for f in facts)


def test_industry_evaluation_keeps_growth_inputs_but_never_uses_sample_profit_as_industry_average():
    from industry_delivery import evaluation_inputs
    growth=card(provenance={'locator':{'status':'verified'}})
    profit=card('E-AAAAAAAAAAAA',module='商业模式与盈利逻辑',source_title='机器人代表性上市企业毛利率',
                provenance={'locator':{'status':'verified'}})
    section=evaluation_inputs({'facts':[growth,profit]})
    assert growth['evidence_id'] in section and profit['evidence_id'] not in section
    assert '不代替行业整体盈利' in section and '吸引力不是风险分的倒数' in section


def test_new_industry_index_never_includes_unlocated_page_tail_or_extra_numeric_metrics(monkeypatch):
    import sys
    from research_workflow import ResearchWorkflow
    docs=[]
    monkeypatch.setitem(sys.modules,'milvus_writer',SimpleNamespace(MilvusWriter=lambda:SimpleNamespace(write_documents=lambda rows:docs.extend(rows))))
    raw=card(claim_type='source_excerpt',fact='机器人定位句。未定位的整页其他段落。',evidence_quote='机器人定位句。',
        numeric_context={},numeric_validation={},provenance={'locator':{'status':'verified','quote':'机器人定位句。'}})
    numeric=card('E-AAAAAAAAAAAA',fact='市场规模100亿元，另有毛利率20%。',evidence_quote='市场规模100亿元，另有毛利率20%。')
    p=SimpleNamespace(id=68,target_type='industry',target_name='机器人',industry='机器人')
    assert ResearchWorkflow.__new__(ResearchWorkflow)._index_cleaned_facts(p,json.dumps({'facts':[raw,numeric]}),9,'test-key')==2
    assert docs[0]['text']=='机器人定位句。' and '未定位' not in docs[0]['text']
    assert '100亿元' in docs[1]['text'] and '20%' not in docs[1]['text']
