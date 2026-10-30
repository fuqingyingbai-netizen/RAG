"""Writer input capacity and analyst reasoning differ from source admission."""
from copy import deepcopy
import json

import pytest

from industry_fact_contracts import (attach_contract, bounded_writer_package, chapter_admitted,
    chapter_coverage, plan_prompt, validate_analyses, parse_chapter_response)
from industry_reasoning import review_prompt, review_packet
from industry_research import bounded_package, claim_semantic_issues
from test_industry_briefing import card, SCOPE
from test_industry_reasoning import chain, EID
from test_industry_v27_regressions import numeric


def test_audit_metadata_cannot_crowd_out_the_actual_writer_evidence():
    facts = []
    for i in range(12):
        f = card('机器人产业链上游提供控制器，中游完成整机集成，下游服务制造场景。',
                 f'E-{i+1:012X}', module='细分赛道与产业链')
        f['provenance']['private_audit_only'] = 'AUDIT_ONLY_NOT_WRITING_EVIDENCE' * 250
        facts.append(f)
    before = deepcopy(facts)
    old = json.loads(bounded_package({'facts': facts}))
    selected = json.loads(bounded_writer_package({'facts': facts, 'industry_scope': SCOPE}, 2))
    assert len(old['facts']) < 3 and len(selected['facts']) == 12
    actual = plan_prompt(selected, 2)
    assert len(actual) <= 20000 and 'AUDIT_ONLY' not in actual
    assert selected['writer_input_budget']['actual_prompt_chars'] == len(actual)
    assert facts == before
    assert selected['facts'][0]['provenance']['private_audit_only']


def test_budget_never_truncates_a_statement_or_drops_its_licensed_metric():
    first = chain()
    second = deepcopy(first); second['evidence_id'] = 'E-222222222222'
    second['fact_contract']['statement'] += '原文限定：' + '只适用于所述分工范围。' * 70
    package = {'facts': [first, second]}
    limit = len(plan_prompt({'facts': [first]}, 2)) + 20
    selected = json.loads(bounded_writer_package(package, 2, limit))
    assert len(plan_prompt(selected, 2)) <= limit
    assert [f['evidence_id'] for f in selected['facts']] == [EID]
    assert selected['facts'][0]['fact_contract']['statement'] == first['fact_contract']['statement']
    assert selected['writer_input_budget']['omitted_evidence_ids'] == [second['evidence_id']]
    with pytest.raises(ValueError, match='writer_prompt_base_exceeds_budget'):
        bounded_writer_package(package, 2, 1)


@pytest.mark.parametrize('quote', [
    '机器人产业是指机器人技术研发和应用涉及的硬件产品生产、系统应用和集成服务。',
    '机器人上游零部件面临核心部件依赖，供应瓶颈主要集中于所述关键部件。',
    '机器人各环节价值分配取决于产品、系统集成和应用服务等不同业务。',
])
def test_definition_and_bottleneck_material_do_not_require_a_full_chain_list(quote):
    f = card(quote, module='行业定义与边界')
    assert f['fact_contract']['report_admitted'] and chapter_admitted(f, 2)
    assert 'chain' not in f['fact_contract']['tasks']
    invalid = deepcopy(f); invalid['fact_contract']['report_admitted'] = False
    assert not chapter_admitted(invalid, 2)


def test_player_layering_can_support_synthesis_without_literal_competition_word():
    quote = '机器人参与者分为硬件供应商、平台企业和应用开发商，各类参与者分别积累技术、渠道或场景优势。'
    f = card(quote, module='竞争格局与代表企业')
    assert 'competition' in f['fact_contract']['tasks']
    question = '竞争与商业化判断'
    rows = {q['question']: q for q in chapter_coverage({'facts': [f]}, 14, [f['evidence_id']])}
    assert rows[question]['evidence_ids'] == [f['evidence_id']]
    a = {'question': question, 'conclusion': '机器人参与者分层提示不同类型企业的优势来源存在差别。',
        'text': '如果评价其业务竞争力，可以分别观察硬件、平台和应用对应的能力，而不是仅以参与者数量判断集中度。',
        'evidence_ids': [f['evidence_id']], 'claim_kind': 'inference',
        'reasoning': '从参与者分工和各类优势出发提出比较角度；不推定市场份额或哪类企业已经胜出。'}
    kept, rejected = validate_analyses([a], {'facts': [f]}, 14, [f['evidence_id']])
    assert kept and not rejected
    assert 'not_evaluated' == kept[0]['entailment_status']


def test_single_period_rate_comparison_is_not_misread_as_a_growth_assertion():
    f = numeric(24, 2030)
    f['numeric_context'].update(metric='产业规模同比增长', unit='%')
    f['fact_contract']['quantity_type'] = 'growth'
    text = '来源报告同比增长24%，支持的是单年增速观察，而非持续增长趋势判断。'
    assert not any(r['code'] == 'growth_trend_not_comparable' for r in claim_semantic_issues(text, [f]))
    bad = text + '该行业随后保持增长态势。'
    assert any(r['code'] == 'growth_trend_not_comparable' for r in claim_semantic_issues(bad, [f]))


def test_reasoning_contract_allows_an_inference_but_does_not_grant_new_facts():
    f = chain()
    prompt = plan_prompt({'facts': [f]}, 2)
    assert '分析不要求原文已经写出同一句结论' in prompt
    assert '额外假设和其他可能解释' in prompt
    assert 'gap_only问题由程序显示缺口' in prompt
    c = {'claim_id': 'C-SYNTHETIC', 'question': '产业链主体和分层关系',
         'text': '如果不同环节存在分工，可按业务职责考察协作；不推定哪一环节的利润更高。',
         'evidence_ids': [EID], 'claim_kind': 'conditional', 'reasoning': '明确限定条件的业务机制解释。'}
    packet, _ = review_packet([c], [f])
    rubric = review_prompt(packet)
    assert '不要求原文已写出同一句分析结论' in rubric
    assert '凭空断言已实现结果或新增事实' in rubric
    assert '行业评分或对企业样本的行业外推' in rubric


def test_writer_parses_a_whole_bom_wrapper_without_requesting_a_format_repair():
    f = chain()
    raw = json.dumps({'evidence_ids': [EID], 'analyses': []})
    ids, analyses = parse_chapter_response('\ufeff```json\n'+raw+'\n```', {'facts': [f]}, 2)
    assert ids == [EID] and analyses == []
    with pytest.raises(ValueError):
        parse_chapter_response('说明如下：'+raw, {'facts': [f]}, 2)


def test_statement_writer_requests_json_without_changing_legacy_output(monkeypatch):
    from types import SimpleNamespace
    import research_workflow
    monkeypatch.setenv('ARK_API_KEY', 'synthetic')
    monkeypatch.setenv('MODEL', 'synthetic')
    calls = []
    def model(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(invoke=lambda messages: SimpleNamespace(content='{}'))
    monkeypatch.setattr(research_workflow, 'init_chat_model', model)
    w = research_workflow.ResearchWorkflow.__new__(research_workflow.ResearchWorkflow)
    w._invoke_industry_report('CDD目标行业桌面研究报告章节编排 Agent - 合成章', 'synthetic')
    w._invoke_industry_report('CDD目标行业桌面研究报告传统写作 Agent', 'synthetic')
    assert calls[0]['model_kwargs']['response_format'] == {'type': 'json_object'}
    assert 'model_kwargs' not in calls[1]
    assert all(c['max_retries'] == 0 for c in calls)


def test_repeated_records_do_not_consume_distinct_writer_slots_or_destroy_sources():
    from industry_research import select_chapter_evidence
    from report_agents.industry_template import INDUSTRY_REPORT_OUTLINE
    repeated = [card('机器人产业链上游提供控制器，中游完成整机集成，下游服务制造场景。',
                     f'E-{i+1:012X}', module='细分赛道与产业链') for i in range(10)]
    definition = card('机器人行业是指机器人技术研发和应用涉及的硬件产品及系统集成服务。',
        'E-AAAAAAAAAAAA', module='行业定义与边界')
    payload = {'facts': repeated+[definition], 'industry_scope': SCOPE}
    original = deepcopy(payload)
    package = select_chapter_evidence(payload, *INDUSTRY_REPORT_OUTLINE[1], max_facts=24, deduplicate_statements=True)
    assert len(package['facts']) == 2
    assert sum(len(g['duplicate_ids']) for g in package['duplicate_statement_groups']) == 9
    assert payload == original


@pytest.mark.parametrize('difference', ['document_url', 'body_version'])
def test_same_policy_words_in_different_documents_do_not_silently_merge(difference):
    from industry_research import select_chapter_evidence
    from report_agents.industry_template import INDUSTRY_REPORT_OUTLINE
    quote = '第三条机器人服务提供者应当建立安全管理制度，保障使用者合法权益。'
    a = card(quote, module='政策与监管', source_url='https://www.gov.cn/rule-one',
             source_title='机器人服务管理条例')
    b = deepcopy(a); b['evidence_id'] = 'E-222222222222'
    if difference == 'document_url':
        b['source_url'] = 'https://www.gov.cn/rule-two'
    else:
        b['provenance']['locator']['body_sha256'] = 'another_archived_version'
    package = select_chapter_evidence({'facts': [a,b]}, *INDUSTRY_REPORT_OUTLINE[2], max_facts=24, deduplicate_statements=True)
    assert len(package['facts']) == 2 and not package['duplicate_statement_groups']
