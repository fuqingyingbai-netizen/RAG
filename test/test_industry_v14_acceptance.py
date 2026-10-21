"""Subject, local-growth and reader-output controls from the v14 review.

Examples are synthetic and offline. Positive controls prevent rejection of all
industry evidence from satisfying sample/conditional-boundary requirements.
"""
import io
import json
import re
from types import SimpleNamespace
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import pytest

from industry_analysis import complete_plan, observed_business
from industry_fact_contracts import attach_contract, render_plan, chapter_admitted
from industry_grounding import growth_definition, sample_boundary, source_markdown_link
from industry_research import extract_industry_source_facts, annotate_fact, normalize_risk
from test_industry_fact_contracts import card, SCOPE


@pytest.mark.parametrize('quote', [
    'Nova因模型发布后算力逼近极限暂停个人用户订阅。',
    '公司拥有成熟的用户增长和付费转化运营体系。',
    '两家公司体量相近，但收入结构分别为私有交付与平台订阅。',
    '作为一家订阅制软件公司，公司已经实现规模化盈利。',
    '三是其过往技术论文提出自研芯片是自身技术路线的延伸。',
    '卓远计算机系统股份有限公司则以整机能力见长，位居中国服务器市场第一阵营。',
    '中国方面，星海科技推出了旗下的生成式机器人平台，其竞争对手也已推出类似工具。',
    '全球市占率第一的隐形冠军，成立以来，卓越智能始终将科技创新视为发展生命线。',
])
def test_company_or_product_subject_cannot_be_promoted_by_industry_collection_title(quote):
    f = attach_contract(card(quote, module='商业模式与盈利逻辑', source_title='机器人行业报告合集'), SCOPE)
    assert sample_boundary(f)
    assert f['fact_contract']['report_admitted']
    assert not f['fact_contract']['risk_admitted']
    assert '样本观察' in f['fact_contract']['statement']
    risk = normalize_risk({'dimensions':[{'name':'商业化与盈利模式风险', 'score':68,
        'reason':quote+' '+f['evidence_id'], 'evidence_ids':[f['evidence_id']]}]}, [f], SCOPE)
    assert next(d for d in risk['dimensions'] if d['name']=='商业化与盈利模式风险')['score'] is None


@pytest.mark.parametrize('quote', [
    '机器人软件采用按量计费，用户按实际调用量支付费用。',
    '机器人行业企业采用统一订阅计费，用户按月支付服务费用。',
    '2024年中国机器人市场规模达到120亿元。',
])
def test_generic_business_and_aggregate_industry_subjects_are_not_company_samples(quote):
    assert not sample_boundary(card(quote))
    f = card(quote, '市场规模','120','亿元') if '120亿元' in quote else card(quote, module='商业模式与盈利逻辑')
    assert attach_contract(f, SCOPE)['fact_contract']['risk_admitted']


def source(quote):
    return SimpleNamespace(url='https://research.example/robot', title='机器人产业报告', content=quote,
        source_type='web_search', source_metadata={'module':'市场规模与增长'}, credibility_score=80, object_key='saved.txt')


@pytest.mark.parametrize('rate', ['24', '-3', '0'])
def test_explicit_local_growth_has_independent_definition_and_number(rate):
    quote=f'2024年中国机器人核心产业规模突破9000亿元，同比增长{rate}%。'
    from industry_evidence import attach_provenance
    rows=attach_provenance([annotate_fact(x,SCOPE) for x in extract_industry_source_facts([source(quote)],SCOPE)], [source(quote)])
    growth=next(x for x in rows if x['numeric_context']['unit']=='%')
    assert growth['numeric_context']['definition']=='中国机器人核心产业规模同比增长'
    assert growth['numeric_context']['period']=='2024' and growth['numeric_context']['value']==rate
    assert growth['numeric_validation']['passed']
    assert attach_contract(growth,SCOPE)['fact_contract']['risk_admitted']
    amount=next(x for x in rows if x['numeric_context']['unit']=='亿元')
    assert growth['evidence_id'] != amount['evidence_id']


@pytest.mark.parametrize('quote', [
    '2024年中国机器人市场规模达到120亿元；另一指标同比增长24%。',
    '2024年中国机器人市场规模达到120亿元，客户满意度同比增长24%。',
    '2024年中国机器人市场规模达到120亿元。同比增长24%。',
    '2024年中国机器人同比增长24%。',
])
def test_local_growth_does_not_inherit_a_remote_or_new_subject(quote):
    assert not growth_definition(quote,'同比增长','24','%')


def test_total_rate_never_licenses_an_adjacent_submetric():
    quote='2024年中国机器人数据总量达到199.48EB，同比增长42.86%，其中推理量达到101.34EB。'
    assert growth_definition(quote,'同比增长','42.86','%')=='中国机器人数据总量同比增长'
    assert not growth_definition(quote,'推理量','42.86','%')
    bad=card(quote,'推理量','42.86','%')
    assert not attach_contract(bad,SCOPE)['fact_contract']['report_admitted']


@pytest.mark.parametrize('quote,role', [
    ('如果强行使用通用模型，缺少行业数据微调，误判率无法满足工业安全要求。','conditional_statement'),
    ('对服务商，推动商业模式由项目制转向订阅制。','recommendation'),
    ('经过产业沉淀，机器人已经从炒概念走到上游硬件兑现利润的阶段。','commentary'),
])
def test_conditions_and_recommendations_remain_attributed_background(quote, role):
    f=attach_contract(card(quote,module='商业模式与盈利逻辑'),SCOPE)
    assert f['fact_contract']['report_admitted']
    assert f['fact_contract']['source_role']==role
    assert not f['fact_contract']['risk_admitted'] and not chapter_admitted(f,1)
    assert not observed_business(f)
    if role=='conditional_statement':
        assert '如果' in f['fact_contract']['statement'] and '条件性陈述' in f['fact_contract']['statement']


def test_question_selection_adds_a_real_duty_even_when_model_picks_only_purpose():
    fs=[]
    for i,text in enumerate(['第一条 为了促进机器人产业健康发展，保护使用者合法权益，制定本办法。',
                              '第三条 机器人服务提供者应当建立安全管理制度，保障使用者合法权益。']):
        fs.append(attach_contract(card(text,module='政策与监管',source_title='机器人服务管理办法',
            source_url='https://www.cac.gov.cn/robot',evidence_id=f'E-{i+1:012X}'),SCOPE))
    ids=complete_plan({'facts':fs},3,[fs[0]['evidence_id']])
    assert fs[1]['evidence_id'] in ids
    body=render_plan({'facts':fs},3,'政策',ids)
    assert '义务对象及要求' in body and '服务提供者应当建立安全管理制度' in body


def test_same_regulation_approval_and_publication_entries_are_one_version():
    texts=['2026年4月10日公布《机器人服务办法》，自2026年7月15日起施行。',
           '《机器人服务办法》已经2026年2月2日会议审议通过，现予公布，自2026年7月15日起施行。',
           '2027年4月10日公布《机器人服务办法》，自2027年7月15日起施行。']
    fs=[attach_contract(card(t,module='政策与监管',source_title='机器人服务办法',source_url='https://www.cac.gov.cn/robot',evidence_id=f'E-{i+1:012X}'),SCOPE) for i,t in enumerate(texts)]
    chosen=complete_plan({'facts':fs},5,[f['evidence_id'] for f in fs])
    assert len(chosen)==2 and fs[2]['evidence_id'] in chosen
    interpretation=attach_contract(card('2026年4月10日公布《机器人服务办法》，将自今年7月15日起施行。',
        module='政策与监管',source_title='机器人服务办法解读',source_url='https://www.cac.gov.cn/robot',
        published_date='2026-06-03',evidence_id='E-000000000004'),SCOPE)
    assert len(complete_plan({'facts':fs+[interpretation]},5,[f['evidence_id'] for f in fs]+[interpretation['evidence_id']]))==2


def test_author_timestamp_and_unmeasured_precision_claims_cannot_enter_summary():
    furniture=attach_contract(card('作者：来源：研究平台发布时间：2026年08月04日。',module='政策与监管'),SCOPE)
    assert not furniture['fact_contract']['report_admitted']
    performance=attach_contract(card('机器人模型的压缩技术可以在不牺牲模型精度的前提下，显著提升推理吞吐量，降低计算成本。',module='技术路线对比'),SCOPE)
    assert performance['fact_contract']['report_admitted']
    assert performance['fact_contract']['source_role']=='performance_claim'
    assert not chapter_admitted(performance,1) and not performance['fact_contract']['risk_admitted']


def test_identical_observation_is_one_row_with_both_sources_and_no_growth_calculation():
    fs=[]
    for i in range(2):
        f=card('2024年中国机器人核心产业规模超过9000亿元。','核心产业规模','9000','亿元',evidence_id=f'E-{i+1:012X}')
        f['numeric_context']['definition']='2024年中国机器人核心产业规模'
        fs.append(attach_contract(f,SCOPE))
    body=render_plan({'facts':fs},4,'市场',[f['evidence_id'] for f in fs])
    assert body.count('超过9000亿元')==1
    assert all(f['evidence_id'] in body for f in fs)
    assert '合列不表示口径已经统一或来源相互独立' in body
    assert '33%' not in body
    from industry_research import summary_package
    package={'facts':fs}
    assert summary_package({4:package},{4:body},SCOPE)['facts']
    # A citation to a fabricated table row is insufficient to infect a summary.
    modified=body.replace('超过9000亿元','超过9999亿元')
    assert not summary_package({4:package},{4:modified},SCOPE)['facts']


def test_display_cleanup_does_not_change_original_locator_or_title_metadata():
    quote='机器人服务提供者应当保护个人信 息，建立安全管理制 度。'
    f=card(quote,module='政策与监管',source_title='机器人服务管理办法',source_url='https://www.cac.gov.cn/robot')
    checked=attach_contract(f,SCOPE)
    assert checked['provenance']['locator']['quote']==quote
    assert '个人信息' in checked['fact_contract']['statement'] and '管理制度' in checked['fact_contract']['statement']
    title='机器人 / 全产业链梳理: 甲、乙、丙、丁、戊、己，后面还有截断文字'
    link=source_markdown_link(title,'https://research.example/report')
    assert '甲、乙' not in link and '全产业链梳理' in link


def test_nested_brackets_export_as_real_link_without_visible_markdown():
    from docx_exporter import markdown_to_docx_bytes
    w='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    markdown='## 15. 来源\n[机器人市场规模[2032]](https://research.example/report)'
    with ZipFile(io.BytesIO(markdown_to_docx_bytes(markdown,document_kind='industry_report'))) as z:
        root=ET.fromstring(z.read('word/document.xml'))
        visible=''.join(n.text or '' for n in root.iter(w+'t'))
        assert '[机器人市场规模' not in visible and '](https' not in visible
        assert '机器人市场规模[2032]' in visible
        assert root.find('.//'+w+'hyperlink') is not None
        assert 'https://research.example/report' in z.read('word/_rels/document.xml.rels').decode()


def test_proposal_keeps_questions_in_body_and_full_task_audit_in_appendices():
    from industry_delivery import verification_tasks
    from report_agents.industry_proposal import build_industry_proposal
    risk={'dimensions':[{'name':'技术迭代与替代风险','score':None,'unknown_cause':'no_applicable_evidence','reason':'缺可比测试材料'}]}
    tasks=verification_tasks({},risk,[],SCOPE)
    project=SimpleNamespace(title='机器人研究',target_name='机器人',industry_scope=SCOPE,industry_verification_tasks=tasks)
    proposal=build_industry_proposal(project,risk_json=json.dumps(risk,ensure_ascii=False))
    chapter2=re.search(r'(?s)## 2\..*?(?=## 3\.)',proposal)[0]
    assert '技术迭代与替代风险' in chapter2 and '优先级' in chapter2
    assert '指纹前缀' not in chapter2 and '核验动作及材料' not in chapter2
    assert '## 附录A 核验任务明细' in proposal and '## 附录B 候选来源索引' in proposal
    assert all(t['task_id'] in proposal and t['action'] in proposal for t in tasks)
    assert re.findall(r'^## (\d+)\.',proposal,re.M)==[str(i) for i in range(1,8)]
