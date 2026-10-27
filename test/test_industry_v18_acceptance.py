"""Synthetic v18 holdouts: actual evidence is separate from system diagnostics."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from industry_delivery import verification_tasks, risk_status_section
from industry_fact_contracts import attach_contract, chapter_coverage, render_plan
from industry_passages import reader_proposition
from industry_research import numeric_mentions, normalize_risk, risk_repair_package
from industry_risk_input import model_evidence, risk_input
from test_industry_fact_contracts import card, SCOPE


def test_numbered_web_headings_are_removed_from_the_reader_view_only():
    quote = ('行业市场集中度1、中国机器人行业竞争派系根据《机器人发展报告(2022)》，'
             '我国机器人行业的市场参与者可以分为三个派系，分别是平台企业、融合企业和技术企业。')
    body = '研究正文。' + quote
    f = card(quote, module='竞争格局与代表企业')
    f['provenance']['locator'].update(body_sha256=hashlib.sha256(body.encode()).hexdigest(),
                                    start=len('研究正文。'),end=len(body))
    before = deepcopy(f)
    checked = attach_contract(f, SCOPE, body)
    assert checked['fact_contract']['statement'].startswith('根据《机器人发展报告')
    assert checked['provenance'] == before['provenance'] and f == before
    package = {'facts':[checked]}
    text = render_plan(package,6,'竞争格局',[checked['evidence_id']])
    assert '行业市场集中度1' not in text and '定性的玩家分层' in text
    assert '当前仅有来源判断或企业样本' not in text


@pytest.mark.parametrize('quote', [
    '第一条 机器人服务提供者应当保护用户权益。',
    '2024年中国机器人市场规模达到120亿元。',
    '机器人产业链上游包括芯片，中游负责整机，下游包括工业客户。',
])
def test_reader_projection_does_not_remove_real_article_subject_or_scope(quote):
    assert reader_proposition(quote) == quote


@pytest.mark.parametrize('quote,token', [
    ('机器人头部厂商占据八成以上市场份额。','八成'),
    ('机器人行业市场份额达到百分之八十。','百分之八十'),
    ('机器人代理市场有三成半采用该模式。','三成半'),
])
def test_written_ratios_cannot_bypass_the_typed_numeric_contract(quote,token):
    assert token in numeric_mentions(quote)
    checked = attach_contract(card(quote,module='竞争格局与代表企业'),SCOPE)
    assert not checked['fact_contract']['report_admitted']
    assert 'untyped_quantity' in checked['fact_contract']['issues']


def test_idioms_ids_and_urls_are_not_ratios():
    assert not numeric_mentions('机器人技术路线不是一成不变。参考E-ABCDEF123456及https://research.example/八成。')
    assert numeric_mentions('实际市场份额80%。') == ['80%']


def test_concentration_coverage_needs_an_actual_metric_and_keeps_qualitative_background_separate():
    q = attach_contract(card('机器人市场的供应集中度较高，参与者分为三个派系。',
        module='竞争格局与代表企业',evidence_id='E-111111111111'),SCOPE)
    measured = attach_contract(card('2024年中国机器人市场份额为80%。','市场份额','80','%',
        module='竞争格局与代表企业',evidence_id='E-222222222222'),SCOPE)
    def coverage(fs):
        return next(x for x in chapter_coverage({'facts':fs},6,[f['evidence_id'] for f in fs]) if x['question']=='份额及集中度')
    missing = coverage([q])
    assert not missing['evidence_ids'] and missing['background_evidence_ids']==[q['evidence_id']]
    assert missing['status']=='background_only'
    present = coverage([q,measured])
    assert present['evidence_ids']==[measured['evidence_id']]
    assert q['evidence_id'] in present['background_evidence_ids']


@pytest.mark.parametrize('reason,cause,name', [
    ('缺乏行业级盈利数据，盈利可持续性存疑。','evidence_gap_as_business_risk','商业化与盈利模式风险'),
    ('未提供盈利披露，说明盈利能力不足。','evidence_gap_as_business_risk','商业化与盈利模式风险'),
    ('所有数值均经numeric_validation passed，属中度口径复杂性风险。','internal_diagnostic_as_evidence','数据口径与证据可靠性风险'),
    ('引用校验通过，因此这些统计数据可靠。','internal_diagnostic_as_evidence','数据口径与证据可靠性风险'),
])
def test_scoring_rejects_missing_disclosure_inferences_and_validator_status(reason,cause,name):
    f = attach_contract(card('机器人软件采用按量计费，用户按实际调用量支付费用。',module='商业模式与盈利逻辑'),SCOPE)
    row = {'name':name,'score':60,'reason':reason,'evidence_ids':[f['evidence_id']]}
    checked = normalize_risk({'dimensions':[row]},[f],SCOPE)
    bad = next(d for d in checked['dimensions'] if d['name']==name)
    assert bad['score'] is None and bad['unknown_cause']==cause
    assert bad['validation_diagnostic']['original_reason']==reason
    repair = risk_repair_package({'facts':[f],'dimension_evidence_ids':{name:[f['evidence_id']]}},checked)
    assert len(repair['dimensions_to_repair'])==1
    tasks = verification_tasks({'facts':[f]},checked,[],SCOPE)
    task = next(t for t in tasks if t['topic']==name)
    assert task['validation_cause']==cause and task['task_type']=='assessment_validation'
    assert ('内部字段' if cause=='internal_diagnostic_as_evidence' else '实际经营结果') in task['action']+task['completion']


@pytest.mark.parametrize('reason', [
    '缺少行业盈利资料，不能据此认定盈利可持续性存疑。',
    '数值校验通过不等于原始数据真实可靠。',
    '引用校验通过不代表判断得到语义证明。',
])
def test_honest_limitations_remain_valid(reason):
    from industry_research import claim_semantic_issues
    assert not claim_semantic_issues(reason,[])


def test_model_view_omits_diagnostics_without_changing_retained_input_or_number_permissions():
    f = attach_contract(card('2024年中国机器人市场规模达到120亿元。','市场规模','120','亿元'),SCOPE)
    packet = risk_input([f],SCOPE)
    original = deepcopy(packet)
    view = json.loads(model_evidence(packet))
    assert 'input_selection' not in view
    assert 'numeric_validation' not in json.dumps(view)
    assert 'risk_admitted' not in json.dumps(view)
    assert view['dimension_evidence_ids']==packet['dimension_evidence_ids']
    assert view['facts'][0]['allowed_numbers']==['120亿元']
    assert packet==original and packet['facts'][0]['numeric_validation']['passed']


def test_live_workflow_prompt_does_not_expose_validator_flags_to_the_model():
    from research_workflow import ResearchWorkflow
    f = attach_contract(card('2024年中国机器人市场规模达到120亿元。','市场规模','120','亿元'),SCOPE)
    project = SimpleNamespace(title='机器人研究',target_name='机器人',target_type='industry',industry='机器人',industry_scope=SCOPE)
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    prompts = []
    def invoke(role,prompt,emit=None,repair=False):
        prompts.append(prompt)
        return json.dumps({'dimensions':[{'name':'市场增长与需求风险','score':35,'reason':f['fact_contract']['statement'],'evidence_ids':[f['evidence_id']]}]},ensure_ascii=False)
    workflow._invoke_industry_risk = invoke
    result = json.loads(workflow.assess_risk(project,json.dumps({'facts':[f],'industry_scope':SCOPE},ensure_ascii=False)))
    assert prompts and all('numeric_validation' not in p and 'input_selection' not in p for p in prompts)
    assert next(d for d in result['dimensions'] if d['name']=='市场增长与需求风险')['score']==35


def test_reader_unknown_reason_is_localized_and_punctuation_is_not_doubled():
    f = attach_contract(card('机器人软件采用按量计费，用户按实际调用量支付费用。',module='商业模式与盈利逻辑'),SCOPE)
    risk = normalize_risk({'dimensions':[{'name':'商业化与盈利模式风险','score':60,
        'reason':'无行业级盈利证据，盈利可持续性存疑。','evidence_ids':[f['evidence_id']]}]},[f],SCOPE)
    text = risk_status_section(risk,SCOPE)
    assert '。，' not in text and '原因代码' not in text and 'evidence_gap_as_business_risk' not in text
    assert next(d for d in risk['dimensions'] if d['name']=='商业化与盈利模式风险')['unknown_cause']=='evidence_gap_as_business_risk'
