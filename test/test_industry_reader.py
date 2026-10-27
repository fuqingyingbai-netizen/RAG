"""Body-first writing and compact audit views retain evidence and unknowns."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from industry_reader import writing_profile, analysis_balance, task_brief, balance_markdown
from industry_fact_contracts import attach_contract, plan_prompt, normalize_analysis, render_plan, validate_analyses
from industry_analysis import statement_lineage_present
from industry_briefing import comparison_table, synthesis_package
from industry_delivery import verification_task_table, tasks_section
from report_agents.industry_proposal import build_industry_proposal
from test_industry_template_analysis import EID, SCOPE, ANALYSIS, chain, claim, fact


def market_material():
    rows = []
    for i, (quote, metric, value, unit, period, forecast) in enumerate([
        ('2028年中国机器人市场规模达到120亿元。', '市场规模', 120, '亿元', '2028', False),
        ('2028年中国机器人行业需求同比增长24%。', '同比增长', 24, '%', '2028', False),
        ('来源预测2036年中国机器人市场规模将达到900亿元。', '市场规模', 900, '亿元', '2036', True),
    ]):
        f, body = fact(quote, evidence_id='E-'+f'{i+1:012X}', module='市场规模与增长',
            source_url=f'https://research-{i}.example/report', numeric_context={'metric': metric, 'value':value,
                'unit':unit, 'period':period, 'geography':'中国大陆', 'definition':'中国机器人'+metric, 'is_forecast':forecast},
            numeric_validation={'passed':True})
        rows.append(attach_contract(f, SCOPE, body))
    f, body = fact('机器人市场需求增长的驱动因素包括制造场景部署，产业统计采用明确的地域和期间。',
        evidence_id='E-000000000004', module='市场规模与增长', source_url='https://research-extra.example/report')
    rows.append(attach_contract(f, SCOPE, body))
    return {'facts': rows, 'industry_scope': SCOPE}


def test_rich_evidence_gets_more_body_space_without_more_calls_or_sources():
    package = market_material(); original = deepcopy(package)
    rich = writing_profile(package, 4)
    sparse = writing_profile({'facts':[package['facts'][0]], 'industry_scope':SCOPE}, 4)
    assert rich['tier'] == 'rich' and sparse['tier'] == 'sparse'
    assert rich['target_analysis_characters'][0] > sparse['target_analysis_characters'][1]
    prompt = plan_prompt(package, 4)
    assert '先直接回答能得出什么判断' in prompt and '不能反复' in prompt
    assert '最多8条来源、6段分析' in prompt
    data = json.loads(prompt.split('\n', 1)[1])
    assert data['writing_profile']['targets_are_guidance_not_permission_to_invent']
    assert package == original


def test_writer_spends_response_on_analysis_and_program_binds_exact_premises():
    f = chain(); before = deepcopy(f)
    accepted, rejected = validate_analyses([claim()], {'facts':[f]}, 2, [EID])
    assert accepted and not rejected
    assert accepted[0]['premise_binding'] == 'program_exact'
    assert accepted[0]['premises'] == [{'evidence_id':EID, 'quote':f['fact_contract']['statement']}]
    assert accepted[0]['entailment_status'] == 'not_evaluated' and f == before
    bad = claim(premises=[{'evidence_id':EID, 'quote':'伪造原文。'}])
    assert not validate_analyses([bad], {'facts':[f]}, 2, [EID])[0]
    unsupported = claim('产业分工导致行业盈利能力必然增强，足以证明各个环节均能实现更高收益，因而可以直接作为经营改善的证据。')
    checked, rejected = validate_analyses([unsupported], {'facts':[f]}, 2, [EID])
    assert not checked and 'causal_link_not_supported' in rejected[0]['issues']
    assert '不必返回premises' in plan_prompt({'facts':[f]}, 2)


def test_repeated_cards_from_one_document_do_not_become_rich_research():
    package = market_material()
    for f in package['facts']:
        f['source_url'] = 'https://one.example/report'
    assert writing_profile(package, 4)['tier'] != 'rich'


def test_short_body_is_a_review_signal_and_not_an_excuse_to_fill_or_score():
    package = market_material()
    ids = [f['evidence_id'] for f in package['facts']]
    claims = [{'text':'材料说明存在规模记录，但未覆盖连续历史序列。', 'claim_kind':'comparison'}]
    d = analysis_balance(package, 4, ids, claims)
    assert d['expansion_review_needed'] and d['substantive_analysis_paragraphs'] == 1
    assert d['metric_is_not_semantic_or_quality_proof']
    assert '正文展开偏少' in balance_markdown({4: {'reader_balance':d}})
    assert 'score' not in d


def test_standard_material_also_flags_underused_body_without_filling_missing_questions():
    package = market_material()
    package['facts'] = package['facts'][:2]
    d = analysis_balance(package,4,[f['evidence_id'] for f in package['facts']],[])
    assert d['tier'] == 'standard' and d['expansion_review_needed']
    assert len(d['questions_with_direct_material']) == 2


@pytest.mark.parametrize('template', [
    EID+'指出，'+ANALYSIS,
    EID+'的陈述可作为分析起点。'+ANALYSIS,
    '根据'+EID+'，'+ANALYSIS,
    '['+EID+']显示产业链存在分层。'+ANALYSIS,
    'E-11以产业链分工为对象。'+ANALYSIS,
])
def test_citation_subjects_are_labelled_instead_of_deleted(template):
    f = chain(); original = deepcopy(f)
    checked, changes = normalize_analysis(claim(template), {EID:f})
    assert '所引材料' in checked['text']
    assert not checked['text'].startswith(('指出', '的陈述', '根据，', '显示'))
    assert any('labelled' in c for c in changes)
    assert f == original
    accepted, rejected = validate_analyses([claim(template)], {'facts':[f]}, 2, [EID])
    assert accepted and not rejected


def test_short_alias_is_not_guessed_when_ambiguous_or_an_original_product_code():
    a = chain(); b = deepcopy(a); b['evidence_id']='E-11FFFFFFFFFF'
    original = 'E-11显示相关信息。'+ANALYSIS
    result, _ = normalize_analysis(claim(original, evidence_ids=[EID,b['evidence_id']]), {EID:a,b['evidence_id']:b})
    assert 'E-11显示' in result['text']
    a['fact_contract']['statement'] = 'E-11是产品代码。'+a['fact_contract']['statement']
    result, _ = normalize_analysis(claim(original), {EID:a})
    assert 'E-11显示' in result['text']


def test_marker_after_a_noun_does_not_insert_a_second_subject():
    text = '该陈述['+EID+']显示分工关系。'+ANALYSIS
    result, _ = normalize_analysis(claim(text), {EID:chain()})
    assert result['text'].startswith('该陈述显示')


def test_route_table_transposes_only_explicit_targets_and_preserves_lineage():
    quote = '应用场景细分对应机器人技术路线的分层：云端追求吞吐量，端侧追求能效比与成本，边缘侧追求可靠性与低延迟。'
    f, body = fact(quote, module='技术路线对比')
    f = attach_contract(f, SCOPE, body)
    section = render_plan({'facts':[f], 'industry_scope':SCOPE}, 7, '技术路线对比', [EID])
    assert '| 部署位置 | 原文明确侧重点 |' in section
    assert all(v in section for v in ['| 云端 | 追求吞吐量 |', '| 端侧 | 追求能效比与成本 |', '| 边缘侧 | 追求可靠性与低延迟 |'])
    assert statement_lineage_present(f, section, {'facts':[f]}, 7)
    changed = section.replace('追求吞吐量', '性能必然领先')
    assert not statement_lineage_present(f, changed, {'facts':[f]}, 7)
    assert synthesis_package({7:{'facts':[f]}}, {7:section}, SCOPE)['facts']
    assert f['evidence_quote'] == quote


def test_chain_diagram_carries_its_subsegment_scope():
    quote = '具身智能产业链上游提供控制器，中游完成整机集成，下游服务制造场景。'
    f, body = fact(quote, module='细分赛道与产业链')
    f = attach_contract(f, SCOPE, body)
    table, _ = comparison_table([f], 2)
    assert '具身智能来源口径' in table


def tasks():
    return [{'task_id':'V-11111111', 'topic':'章节分析复核', 'priority':'高', 'task_type':'synthesis_review',
        'reason':'逐章核对所引材料与结论。', 'action':'先核对本轮已有原文与判断。再考虑是否补采。',
        'materials':'原始文件与版本、定位和统计方法。', 'completion':'引用、范围及结论对应原文。未通过时保持未知。',
        'subtasks':[{'task_id':f'V-11111111-C7-Q{i}', 'chapter':7, 'topic':'技术问题'+str(i),
            'status':'missing', 'completion':'保留完整的测试环境、版本、负载和测量方法，并逐项核对原文。'*4} for i in range(12)]}]


def test_compact_report_does_not_duplicate_full_appendix_or_drop_tasks():
    source = tasks(); before = deepcopy(source)
    full = verification_task_table(source)
    brief = task_brief(source)
    assert len(brief) < len(full)*0.6
    assert all(t['topic'] in brief for t in source[0]['subtasks'])
    assert source[0]['task_id'] in brief and '报告质量诊断' in brief
    proposal = build_industry_proposal(SimpleNamespace(title='机器人研究', target_name='机器人',
        industry_scope=SCOPE, industry_verification_tasks=source))
    chapter2 = proposal.split('## 2.',1)[1].split('## 3.',1)[0]
    appendix = proposal.split('### 附录A',1)[1] if '### 附录A' in proposal else proposal.split('附录A 核验任务明细',1)[1]
    assert source[0]['subtasks'][0]['completion'] not in chapter2
    assert source[0]['subtasks'][0]['completion'] in appendix
    assert task_brief(source) in tasks_section(source)
    assert source == before


def test_supported_limitation_is_not_labelled_as_a_completed_answer():
    f = chain()
    limitation = claim('本章所引材料未提供价值分配和利润统计，不能据此回答各环节盈利状况，需要另行核验。',
        question='各环节价值分配及毛利率', claim_kind='limitation')
    accepted, rejected = validate_analyses([limitation], {'facts':[f]}, 2, [EID])
    assert accepted and not rejected
    accepted[0]['support_review'] = {'status':'supported'}
    result = render_plan({'facts':[f]}, 2, '产业链', [EID], accepted)
    assert '仅缺口说明接受复核，研究问题仍未解决' in result


def test_reexport_keeps_candidate_priority_but_removes_absent_body_ids(monkeypatch):
    import industry_delivery
    captured = []
    def tasks(payload,risk,notes,scope):
        captured.extend(notes)
        return []
    monkeypatch.setattr(industry_delivery,'verification_tasks',tasks)
    first, second, absent = 'E-000000000001','E-000000000002','E-000000000003'
    body = f'## 2. 产业链\n\n表格在前 [{second}]，分析在后 [{first}]。\n\n## 14. 综合评估\n\n待复核。\n\n## 16. 后续研究点\n\n待复核。'
    notes = [{'chapter':2,'evidence_ids':[first,absent,second]}]
    before = deepcopy(notes)
    industry_delivery.finalize_synthesis(body,{'facts':[]},{},notes,SCOPE)
    assert captured[0]['evidence_ids'] == [first,second]
    assert notes == before
