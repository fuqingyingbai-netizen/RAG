"""Conclusions are generated from scoped premises, never manufactured by rendering."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from industry_briefing import short_conclusion, refresh_conclusion_summary, synthesis_package, reuse_chapter_judgments
from industry_fact_contracts import (generation_targets, plan_prompt, render_plan,
                                     validate_analyses, normalize_analysis)
from industry_model_output import response_text, IndustryModelOutputError
from industry_reasoning import review_packet, validate_reviews, run_support_review
from test_industry_reasoning import chain, claim, review_claim, verdict, response, EID
from test_industry_claim_semantics import fact as numeric_fact


FINDING = '所引材料按上下游区分产品与集成分工，产业链分析宜分别考察不同环节。'
DETAIL = '上游提供部件，中游承担集成，下游面向应用；这种分工是研究各环节业务的起点，不能据此推定各环节利润高低。'


def checked_claim():
    f = chain()
    kept, errors = validate_analyses([{**claim(DETAIL), 'conclusion': FINDING}], {'facts': [f]}, 2, [EID])
    assert not errors and len(kept) == 1
    return f, kept[0]


def test_generation_packet_distinguishes_answerable_questions_before_prose():
    f = chain()
    target = {r['question']: r for r in generation_targets({'facts': [f]}, 2, [EID])}
    assert target['产业链主体和分层关系']['mode'] == 'bounded_judgment'
    assert target['产业链主体和分层关系']['direct_evidence_ids'] == [EID]
    assert target['核心瓶颈']['mode'] == 'gap_only'
    prompt = plan_prompt({'facts': [f]}, 2)
    data = json.loads(prompt.split('\n', 1)[1])
    assert 'generation_targets' in data and 'research_questions' not in data
    assert '先按generation_targets' in prompt and 'conclusion' in prompt
    assert '引用1至4条前提' in prompt and '不能只在后文补限制' in prompt


def test_conclusion_and_explanation_remain_one_bound_claim_with_exact_premises():
    f, c = checked_claim()
    assert c['text'] == FINDING + DETAIL
    assert short_conclusion(c) == FINDING
    assert c['premises'] == [{'evidence_id': EID, 'quote': f['fact_contract']['statement']}]
    body = render_plan({'facts': [f]}, 2, '产业链', [EID], [c])
    assert body.index('### 本章初步结论') < body.index('### 研究分析') < body.index('### 关键依据')
    assert body.count(FINDING) == body.count(DETAIL) == 1
    assert f['fact_contract']['statement'] in body
    assert normalize_analysis(c, {EID: f})[0]['text'] == c['text']


def test_one_rejected_inference_keeps_a_separate_supported_observation_and_source():
    from report_agents.industry_report_agent import IndustryReportAgent
    f, c = checked_claim()
    other = dict(c, conclusion='', text='不同环节的职能有所区分，但这种分工未必转化为利润优势，仍需核对各环节经营资料。')
    project = SimpleNamespace(industry_statement_plans={2: {'evidence_ids': [EID],
        'analysis_claims': [c, other], 'analysis_rejections': []}}, industry_report_degradations=[])
    def invoke(role, prompt, trace):
        packet = json.loads(prompt.split('\n', 1)[1])
        return response(packet, [verdict(row, f, 'supported' if row.get('conclusion') else 'unsupported')
                                  for row in packet['claims']])
    sections = {}
    IndustryReportAgent()._review_statement_claims(project, {'facts': [f]}, {2: json.dumps({'facts': [f]})},
        sections, invoke, lambda *a, **k: None, None)
    assert FINDING in sections[2] and other['text'] not in sections[2]
    assert f['fact_contract']['statement'] in sections[2]
    assert len(project.industry_statement_plans[2]['analysis_claims']) == 1


def test_short_conclusion_cannot_drop_a_sample_boundary_kept_only_in_explanation():
    f = chain()
    f['fact_contract']['sample_boundary'] = '所引企业样本'
    bad = {**claim('企业样本中可见上下游分工，这仅支持样本观察，不能代表整个行业的分工和盈利结构。'),
        'conclusion': '行业产业链已经形成统一的上下游业务分工。'}
    kept, errors = validate_analyses([bad], {'facts': [f]}, 2, [EID])
    assert not kept and 'analysis_sample_boundary_missing' in errors[0]['issues']


@pytest.mark.parametrize('finding', ['不完整的短语', '结论一。结论二。', '新市场规模达到999亿元。',
                                     '行业分工[E-111111111111]明显。', {}, None])
def test_invalid_or_invented_short_conclusion_never_gets_promoted(finding):
    f = chain()
    kept, errors = validate_analyses([{**claim(DETAIL), 'conclusion': finding}], {'facts': [f]}, 2, [EID])
    assert not kept and errors


def test_forecast_marker_must_be_in_short_conclusion_itself():
    from industry_fact_contracts import attach_contract
    f = numeric_fact()
    f.update(source_title='机器人市场规模预测', module='市场规模与增长',
        provenance={'locator': {'status': 'verified', 'quote': f['fact']}})
    f = attach_contract(f, {'industry_name': '机器人', 'capital_market': 'none'}, f['fact'])
    bad = {'question': '规模、期间和统计口径', 'conclusion': '机器人开发服务市场规模已达到6240亿元。',
        'text': '来源预计2026年机器人开发服务市场规模达到6240亿元，这只是预测点位，不能作为已经实现的经营业绩。',
        'evidence_ids': [f['evidence_id']], 'claim_kind': 'observation'}
    kept, errors = validate_analyses([bad], {'facts': [f]}, 4, [f['evidence_id']])
    assert not kept and 'forecast_presented_as_actual' in errors[0]['issues']


def test_summary_reuses_complete_short_findings_without_cutting_explanation():
    _, c = checked_claim()
    claims = [dict(c, conclusion='现有材料支持将产业链分层作为研究不同环节业务的起点。',
        text='现有材料支持将产业链分层作为研究不同环节业务的起点。'+DETAIL*3)]
    report = '## 1. 摘要\n\n原摘要。\n\n## 2. 产业链\n正文。'
    result = refresh_conclusion_summary(report, claims)
    assert claims[0]['conclusion'] in result and DETAIL not in result
    changed = dict(c, conclusion='独立的新结论，不能借旧正文授权。')
    assert not short_conclusion(changed)
    assert not short_conclusion(dict(c, support_review={'status': 'unsupported'}))
    assert not short_conclusion(dict(c, claim_kind='limitation'))


def test_complete_small_premises_leave_room_for_diverse_chapter_judgments():
    from test_industry_briefing import card, SCOPE
    examples = [
        (2, '产业链主体和分层关系', '机器人产业链上游提供控制器，中游完成整机集成，下游服务制造场景。', '细分赛道与产业链'),
        (7, '路线及适用场景', '机器人云端采用吞吐量优化架构，端侧采用低功耗架构，边缘侧面向低时延部署场景。', '技术路线对比'),
        (10, '实际收费与付费客户', '机器人服务采用订阅和按量计费，用户按实际调用支付费用。', '商业模式与盈利逻辑'),
    ]
    packages, sections, plans = {}, {}, {}
    for number, (chapter, question, quote, module) in enumerate(examples, 1):
        f = card(quote, f'E-{number:012X}', module=module)
        finding = {'question': question, 'text': quote+'该观察只适用于所引材料的业务范围，不据此判断盈利、市场排名或统一的性能优劣。',
                   'conclusion': quote, 'claim_kind': 'observation', 'evidence_ids': [f['evidence_id']]}
        package = {'facts': [f], 'industry_scope': SCOPE}
        accepted, errors = validate_analyses([finding], package, chapter, finding['evidence_ids'])
        assert accepted and not errors
        packages[chapter], plans[chapter] = package, {'analysis_claims': accepted}
        sections[chapter] = render_plan(package, chapter, '合成章节', finding['evidence_ids'], accepted)
    assembled = synthesis_package(packages, sections, SCOPE, plans)
    assert len(assembled['facts']) == 3 and len(assembled['completed_chapter_judgments']) == 3
    assert len(json.dumps(assembled, ensure_ascii=False)) <= 14000
    assert {c['reused_from_chapter'] for c in reuse_chapter_judgments(plans, assembled)} == {2, 7, 10}


@pytest.mark.parametrize('verb', ['明确', '规定', '要求'])
def test_unique_authorized_reference_alias_is_readable_but_product_codes_stay(verb):
    f = chain()
    normalized, _ = normalize_analysis(claim('E-11'+verb+'产业链分层。'+DETAIL), {EID: f})
    assert normalized['text'].startswith('所引材料'+verb)
    product = deepcopy(f)
    product['fact_contract']['statement'] = '产品E-11要求按照说明配置。'
    assert normalize_analysis(claim('E-11'+verb+'配置。'+DETAIL), {EID: product})[0]['text'].startswith('E-11')


def test_text_blocks_ignore_thinking_and_never_stringify_provider_objects():
    msg = SimpleNamespace(content=[{'type': 'reasoning', 'text': 'PRIVATE_THINKING'},
        {'type': 'text', 'text': '{"reviews":'}, {'type': 'text', 'text': '[]}'}],
        response_metadata={'finish_reason': 'stop', 'provider_secret': 'PRIVATE_KEY'},
        usage_metadata={'input_tokens': 50, 'output_tokens': 20, 'raw': 'PRIVATE'})
    text, diagnostic = response_text(msg)
    assert text == '{"reviews":[]}' and diagnostic['content_shape'] == 'text_blocks'
    assert 'PRIVATE' not in json.dumps(diagnostic) + text


@pytest.mark.parametrize('content,metadata,code', [
    ('{"complete":true}', {'finish_reason': 'length'}, 'truncated_model_output'),
    ('', {'finish_reason': 'content_filter'}, 'refused_model_output'),
    ([{'type': 'thinking', 'thinking': 'PRIVATE'}], {}, 'empty_model_output'),
    ([{'type': 'tool_call', 'args': 'PRIVATE'}], {}, 'non_text_model_output'),
])
def test_incomplete_or_nontext_response_remains_a_specific_pending_failure(content, metadata, code):
    f = chain(); c = review_claim(f)
    calls = []
    def invoke(prompt):
        calls.append(prompt)
        return response_text(SimpleNamespace(content=content, response_metadata=metadata))[0]
    result = run_support_review([c], [f], invoke)
    assert len(calls) == 1 and result['output_error_code'] == code
    assert result['reviews'][c['claim_id']]['diagnostic_code'] == 'review_request_failed'
    assert result['valid_review_count'] == 0 and 'PRIVATE' not in json.dumps(result)


def test_complete_review_presentation_is_accepted_but_cut_or_ambiguous_json_is_not():
    f = chain(); c = review_claim(f); packet, _ = review_packet([c], [f])
    raw = response(packet, [verdict(c, f)])
    good = validate_reviews('\ufeff```json\n'+raw+'\n```', packet)[c['claim_id']]
    assert good['status'] == 'supported' and not good['entailment_proven']
    for complete in ('说明：'+raw, raw+'\n额外文字'):
        assert validate_reviews(complete, packet)[c['claim_id']]['status'] == 'supported'
    for bad in (raw[:-3], raw+'\n'+raw):
        assert validate_reviews(bad, packet)[c['claim_id']]['status'] == 'not_evaluated'


def test_support_transport_requests_json_once_without_sdk_retry(monkeypatch):
    import research_workflow
    configured, invoked, events = [], [], []
    monkeypatch.setenv('ARK_API_KEY', 'synthetic')
    monkeypatch.setenv('MODEL', 'synthetic')
    def create(**kwargs):
        configured.append(kwargs)
        def invoke(messages):
            invoked.append(messages)
            return SimpleNamespace(content=[{'type': 'text', 'text': '{}'}], response_metadata={'finish_reason': 'stop'})
        return SimpleNamespace(invoke=invoke)
    monkeypatch.setattr(research_workflow, 'init_chat_model', create)
    w = research_workflow.ResearchWorkflow.__new__(research_workflow.ResearchWorkflow)
    assert w._invoke_industry_support_review('synthetic', events.append) == '{}'
    assert len(invoked) == 1 and configured[0]['max_retries'] == 0
    assert configured[0]['model_kwargs']['response_format'] == {'type': 'json_object'}
    assert any(e.get('output_diagnostic', {}).get('finish_reason') == 'stop' for e in events)
