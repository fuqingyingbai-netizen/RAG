"""Frozen v12 failure classes with independent correct and held-out controls.

All data are synthetic; real reports, snapshots and URLs remain under work/.
"""
import io
import json
import re
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from industry_assertions import bounded_conflict_unsupported
from industry_delivery import verification_tasks, verification_task_table
from industry_fact_contracts import attach_contract, chapter_admitted, render_plan
from industry_grounding import metric_period_region
from industry_research import normalize_risk, extract_industry_source_facts
from report_agents.industry_proposal import build_industry_proposal
from test_industry_fact_contracts import card, SCOPE


@pytest.mark.parametrize('year,amount', [('2032','2020'),('2036','2024'),('2020','2032')])
def test_money_digits_cannot_supply_a_statistical_year(year,amount):
    quote=f'预计{year}年中国机器人市场规模将达到{amount}亿美元。'
    assert metric_period_region(quote,'市场规模',amount,'亿美元') == (year,'中国大陆')
    f=card(quote,'市场规模',amount,'亿美元')
    f['numeric_context'].update(period=amount,is_forecast=True,definition='中国机器人市场规模')
    c=attach_contract(f,SCOPE)
    assert c['fact_contract']['report_admitted']
    assert c['numeric_context']['period']==year
    assert f['numeric_context']['period']==amount  # audit input remains untouched


@pytest.mark.parametrize('text',[
    '2030机器人行业研究.docx - 资料站 # 文档简介 报告目录123摘要 一、市场格局 二、技术路线',
    '机器人市场报告 Contact For more information Email: analyst@example.test Phone number: 123',
    '--- PDF page 1 --- TC999 机器人安全技术文件 摘要 本文件说明',
    '中国机器人产业结构包括上游驱动、中游集成以及',
    '3 全球竞争态势分析 3.1 企业收入 3.2 竞争格局 3.2.1 前三厂商份额 3.2.2 前五厂商份额',
    '（6）机器人行业产业链上游、中游及下游分析',
    '洞察2030：中国机器人行业竞争格局及市场份额（附市场集中度等）',
    '用户提问：机器人行业集中度不断提高，如何判断投资机会。',
])
def test_page_furniture_and_clipped_propositions_are_not_statements(text):
    assert attach_contract(card(text),SCOPE)['eligible_for_report'] is False


def test_same_document_body_is_recovered_without_blanket_source_rejection():
    source=SimpleNamespace(url='https://research.example/robot',title='机器人市场报告',
        content='# 机器人市场报告\nContact Email: staff@example.test\n2024年中国机器人市场规模达到150亿元。\n机器人软件采用按量计费，客户按实际调用支付费用。',
        source_type='web_search',source_metadata={'module':'市场规模与增长'},credibility_score=80,object_key='test.txt')
    facts=extract_industry_source_facts([source],SCOPE)
    assert any((f.get('numeric_context') or {}).get('value')=='150' for f in facts)
    assert any('按量计费' in f['evidence_quote'] for f in facts)
    assert not any('Email' in f['evidence_quote'] for f in facts)


def test_verified_offset_must_end_at_a_proposition_boundary():
    text='机器人服务应当遵守法律、行政法规，并建立安全管理制度。'
    quote='机器人服务应当遵守法律、行政'
    f=card(quote,provenance={'locator':{'status':'verified','quote':quote,'start':0,'end':len(quote)}})
    assert 'clipped_source_span' in attach_contract(f,SCOPE,text)['fact_contract']['issues']
    full=card(text,provenance={'locator':{'status':'verified','quote':text,'start':0,'end':len(text)}})
    assert attach_contract(full,SCOPE,text)['fact_contract']['report_admitted']
    fragment='本显著下滑，机器人需求吞吐量持续增长。'
    source='成'+fragment
    clipped=card(fragment,provenance={'locator':{'status':'verified','quote':fragment,'start':1,'end':len(source)}})
    assert 'clipped_source_span' in attach_contract(clipped,SCOPE,source)['fact_contract']['issues']


def test_named_subject_is_attributed_as_a_sample_and_not_a_summary_or_score():
    f=attach_contract(card('甲厂在机器人零部件领域的全球市场份额领先。',module='竞争格局与代表企业'),SCOPE)
    assert f['fact_contract']['report_admitted']
    assert f['fact_contract']['sample_boundary']
    assert '样本观察' in f['fact_contract']['statement']
    assert not f['fact_contract']['risk_admitted'] and not chapter_admitted(f,1)


def test_source_wording_cannot_bypass_the_existing_inference_guard():
    bad=attach_contract(card('企业数量分布显示机器人行业技术壁垒较低。',module='竞争格局与代表企业'),SCOPE)
    assert not bad['fact_contract']['report_admitted']
    assert any(code.startswith('claim_') for code in bad['fact_contract']['issues'])
    mechanism=attach_contract(card('厂商专用接口和迁移成本构成进入壁垒，限制替代竞争。',module='竞争格局与代表企业'),SCOPE)
    assert mechanism['fact_contract']['report_admitted']


def test_pdf_soft_wrap_retains_original_offsets_for_quote_and_scope_anchor():
    from industry_evidence import attach_provenance
    from industry_research import annotate_fact
    body='2024年中国机器人市场规模达到\n150亿元。\n\n机器人供应商迁移成本形成竞争压力。'
    src=SimpleNamespace(id=72,url='https://research.example/wrapped',title='机器人统计',content=body,
        source_type='web_search',source_metadata={'module':'市场规模与增长'},object_key='test.pdf',credibility_score=75)
    extracted=[annotate_fact(f,SCOPE) for f in extract_industry_source_facts([src],SCOPE)]
    numeric=next(f for f in attach_provenance(extracted,[src]) if f.get('numeric_context'))
    loc=numeric['provenance']['locator'];anchor=loc['scope_anchor']
    assert body[loc['start']:loc['end']]==loc['quote']
    assert body[anchor['start']:anchor['end']]==anchor['quote']
    assert attach_contract(numeric,SCOPE,body)['fact_contract']['report_admitted']


def amount(value, qualifier='', **updates):
    f=card(f'2024年中国机器人市场规模{qualifier}{value}亿元。','市场规模',value,'亿元',**updates)
    return attach_contract(f,SCOPE)


@pytest.mark.parametrize('word', ['突破','超','逾','超过'])
def test_lower_bound_survives_writer_and_risk_input(word):
    f=amount('100',word)
    assert f['numeric_context']['comparator']=='>'
    assert '超过100亿元' in f['fact_contract']['statement']


def test_compatible_bounds_do_not_become_point_conflicts_but_true_conflicts_remain():
    low=amount('100','突破')
    high=amount('150','超',evidence_id='E-AAAAAAAAAAAA')
    exact=amount('200','达到',evidence_id='E-BBBBBBBBBBBB')
    assert bounded_conflict_unsupported('三组不一致数值',[low,high,exact])
    below=amount('90','低于',evidence_id='E-CCCCCCCCCCCC')
    assert not bounded_conflict_unsupported('数值存在冲突',[low,below])
    equal=amount('100','达到',evidence_id='E-DDDDDDDDDDDD')
    assert not bounded_conflict_unsupported('口径冲突',[low,equal])
    assert not bounded_conflict_unsupported('多组不一致数值',[amount('100','达到'),exact])


def test_policy_permissions_and_revalidation_follow_the_proposition():
    f=amount('150','达到',module='政策与监管')
    assert not chapter_admitted(f,3)
    raw={'dimensions':[{'name':'政策与监管风险','score':30,'level':'low',
        'reason':'产业规模扩大，无证据表明存在实质性准入限制或处罚影响。','evidence_ids':[f['evidence_id']]}]}
    checked=normalize_risk(raw,[f],SCOPE)
    row=next(r for r in checked['dimensions'] if r['name']=='政策与监管风险')
    assert row['score'] is None and row['unknown_cause']=='no_applicable_evidence'
    good=attach_contract(card('第三条 机器人服务提供者应当建立安全管理制度，保障使用者合法权益。',
        module='政策与监管',source_title='机器人服务管理办法',source_url='https://www.cac.gov.cn/law'),SCOPE)
    assert chapter_admitted(good,3)
    assessed=normalize_risk({'dimensions':[{'name':'政策与监管风险','score':45,'level':'medium',
        'reason':'服务提供者应当建立安全管理制度，需核对履行情况。','evidence_ids':[good['evidence_id']]}]},[good],SCOPE)
    assert next(r for r in assessed['dimensions'] if r['name']=='政策与监管风险')['score']==45
    row={'name':'政策与监管风险','score':20,'level':'low','evidence_ids':[good['evidence_id']],
         'reason':'未见实质性准入限制或处罚影响，因此监管风险较低。'}
    result=normalize_risk({'dimensions':[row]},[good],SCOPE)
    rejected=next(r for r in result['dimensions'] if r['name']==row['name'])
    assert rejected['score'] is None and rejected['unknown_cause']=='absence_as_low_risk'


def test_analysis_review_is_distinct_from_generation_failure_in_delivery_reasons():
    from industry_research import delivery_review_reasons
    reasons=delivery_review_reasons(SCOPE,{},[
        {'chapter':4,'review_type':'statement_synthesis_review','message':'编排完成，分析待复核'},
        {'chapter':7,'message':'生成失败，保留摘录'}])
    assert reasons[0]['code']=='chapter_analysis_pending_review'
    assert reasons[1]['code']=='chapter_generation_degraded'


def test_opinion_and_unconditioned_performance_do_not_enter_summary():
    opinion=attach_contract(card('单位成本比能力分数更能决定最终份额，应该关注推理延迟。'),SCOPE)
    claim=attach_contract(card('机器人模型保持精度且吞吐量提升了数倍，商用普及率大幅提升。'),SCOPE)
    assert opinion['fact_contract']['source_role']=='opinion'
    assert claim['fact_contract']['source_role']=='performance_claim'
    assert all(not chapter_admitted(f,1) for f in [opinion,claim])


def test_macro_filler_does_not_answer_business_or_dated_events_and_gaps_are_explicit():
    f=amount('150','达到')
    assert not chapter_admitted(f,5) and not chapter_admitted(f,10)
    text=render_plan({'facts':[f]},7,'技术路线对比',[])
    assert '同条件测试配置' in text and '本轮未回答' in text
    assert '150亿元' not in text


def test_synthesis_review_is_grouped_linked_and_not_misreported_as_failure():
    f=amount('150','达到')
    notes=[{'chapter':n,'review_type':'statement_synthesis_review','message':'编排完成待复核',
            'evidence_ids':[f['evidence_id']]} for n in [2,4,7]]
    tasks=verification_tasks({'facts':[f]}, {}, notes, SCOPE)
    assert len(tasks)==1 and tasks[0]['task_type']=='synthesis_review'
    assert tasks[0]['priority']=='中' and tasks[0]['chapters']==[2,4,7]
    assert f['evidence_id'] in tasks[0]['review_evidence_ids']
    table=verification_task_table(tasks)
    assert f['source_url'] in table and f['source_title'] in table
    assert '重写失败章节' not in table
    dep={'report_version':17,'report_artifact_id':100,'report_sha256':'a'*64,
         'run_id':'synthetic-run','report_created_at':'2026-01-01 01:02:03','cleaned_artifact_id':98,'risk_artifact_id':99}
    proposal=build_industry_proposal(SimpleNamespace(title='合成研究',target_name='机器人',industry_scope=SCOPE,
        industry_verification_tasks=tasks,industry_report_dependency=dep))
    assert 'v17（产物 100）' in proposal and 'synthetic-run' in proposal
    assert 'a'*64 in proposal and '重写失败章节' not in proposal
    from docx_exporter import markdown_to_docx_bytes
    with ZipFile(io.BytesIO(markdown_to_docx_bytes(proposal,document_kind='industry_proposal'))) as z:
        assert f['source_url'] in z.read('word/_rels/document.xml.rels').decode()
    assert len(re.findall(r'^## \d+\.',proposal,re.M))==7
