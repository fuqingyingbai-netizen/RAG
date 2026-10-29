"""Hand-labelled acceptance examples: expected labels never call a second validator.

The first group mirrors failure categories; holdouts change vocabulary/word order.
Correct controls prevent a reject-all implementation from satisfying acceptance.
These synthetic examples contain no private reports, URLs or business data.
"""
import json
from types import SimpleNamespace

import pytest

from industry_fact_contracts import (attach_contract, build_contract, chapter_admitted,
    parse_plan, render_plan, risk_admitted, VERSION)
from industry_research import bounded_package, risk_fact_text, summary_package, summary_length
from report_agents.industry_report_agent import IndustryReportAgent

SCOPE = {'industry_name': '机器人', 'segments': ['机器人'], 'geography': '中国大陆', 'capital_market': 'none'}


def card(quote, metric='', value='', unit='', **updates):
    result = {'evidence_id': 'E-123456789ABC', 'fact': quote, 'evidence_quote': quote,
        'source_url': 'https://research.example/report', 'source_title': '机器人研究',
        'scope_match': 'in_scope', 'evidence_scope': 'industry_level', 'module': '市场规模与增长',
        'provenance': {'locator': {'status': 'verified', 'quote': quote}}, 'claim_type': 'fact'}
    if metric:
        result.update(numeric_context={'metric': metric, 'value': value, 'unit': unit, 'period': '2024',
                      'geography': '中国大陆', 'definition': '机器人' + metric, 'is_forecast': False},
                      numeric_validation={'passed': True})
    result.update(updates)
    return result


# Frozen decisions, including held-out phrasing. Booleans are reviewer labels,
# not values derived by production validators or replay normalization.
ACCEPTANCE = [
    ('size_percent', '2024年机器人产业规模增长速度维持在12%以上。', '产业规模', '12', '%', False),
    ('amount_rate_holdout', '2024年机器人收入规模的同比增幅达到8%。', '收入规模', '8', '%', False),
    ('growth_money', '2024年机器人增长率为20亿元。', '增长率', '20', '亿元', False),
    ('count_percent', '2024年机器人企业数量为15%。', '企业数量', '15', '%', False),
    ('ratio_money_holdout', '2024年机器人渗透率为40亿元。', '渗透率', '40', '亿元', False),
    ('fragment', '，单位制造成本降低29%”', '', '', '', False),
    ('orphan_percent', '98%，单位制造成本降低29%”', '', '', '', False),
    ('heading', '二、横评评测标准与统一测试环境', '', '', '', False),
    ('size_amount', '2024年中国机器人市场规模达到120亿元。', '市场规模', '120', '亿元', True),
    ('growth_percent', '2024年中国机器人增长率达到12%。', '增长率', '12', '%', True),
    ('ratio_percent', '2024年中国机器人渗透率达到15%。', '渗透率', '15', '%', True),
    ('count_units', '2024年中国机器人企业数量达到120家。', '企业数量', '120', '家', True),
    ('bound', '2024年中国机器人增长率维持在12%以上。', '增长率', '12', '%', True),
    ('negative_holdout', '2024年中国机器人同比增长率为-3%。', '同比增长率', '-3', '%', True),
    ('zero_control', '2024年中国机器人增长率为0%。', '增长率', 0, '%', True),
    ('chain', '机器人产业链上游提供控制器，中游完成整机集成，下游服务制造场景。', '', '', '', True),
    ('business', '机器人软件采用按量计费模式，用户按实际调用量支付费用。', '', '', '', True),
    ('tech_holdout', '机器人采用统一硬件进行测试，测试条件限定为相同模型和量化精度。', '', '', '', True),
]


@pytest.mark.parametrize('name,quote,metric,value,unit,admitted', ACCEPTANCE, ids=[c[0] for c in ACCEPTANCE])
def test_frozen_admission_labels(name, quote, metric, value, unit, admitted):
    assert build_contract(card(quote, metric, value, unit), SCOPE)['report_admitted'] is admitted


def test_bounds_and_period_are_preserved_without_mutating_audit_input():
    original = card('2019—2024年中国机器人增长率维持在12%以上。', '增长率', '12', '%')
    checked = attach_contract(original, SCOPE)
    text = risk_fact_text(checked)
    assert '2019—2024' in text and '不少于12%' in text
    assert original['numeric_context']['period'] == '2024'


def test_source_role_not_host_controls_law_permission_and_local_subject():
    quote = '机器人安全管理办法提出平台建设要求，违反规定最高可按营业额罚款。'
    commentary = card(quote, module='政策与监管', source_title='机器人管理办法解读',
        source_url='https://www.cac.gov.cn/commentary')
    assert 'legal_original_required' in build_contract(commentary, SCOPE)['issues']
    primary = card('第三条 机器人服务提供者应当建立安全管理制度，保障使用者合法权益。',
        module='政策与监管', source_title='机器人服务管理办法', source_url='https://www.cac.gov.cn/law')
    c = attach_contract(primary, SCOPE)
    assert c['fact_contract']['source_role'] == 'policy_primary'
    assert chapter_admitted(c, 13) and risk_admitted(c, '政策与监管风险')
    labor = card('劳务派遣用工必须符合临时性、辅助性和替代性的岗位要求。',
                 module='政策与监管', source_title='机器人法规汇总')
    assert build_contract(labor, SCOPE)['report_admitted'] is False


def test_opinions_are_attributed_and_never_promoted_into_summary_or_scores():
    f = attach_contract(card('机器人产业链上游控制器业绩确定性最高，中游整机弹性最大。', module='细分赛道与产业链'), SCOPE)
    assert f['fact_contract']['report_admitted']
    assert '来源观点' in risk_fact_text(f)
    assert not chapter_admitted(f, 1) and not risk_admitted(f, '市场增长与需求风险')


def test_module_labels_do_not_override_task_admission():
    macro = attach_contract(card('2024年中国机器人市场规模达到120亿元。', '市场规模', '120', '亿元', module='技术路线对比'), SCOPE)
    assert not chapter_admitted(macro, 7) and not risk_admitted(macro, '技术迭代与替代风险')
    assert not chapter_admitted(macro, 6)
    mechanism = attach_contract(card('机器人供应商迁移成本限制替代竞争，新进入者面临接口切换障碍。', module='竞争格局与代表企业'), SCOPE)
    assert chapter_admitted(mechanism, 6) and risk_admitted(mechanism, '竞争格局与集中度风险')


def test_plan_rejects_free_prose_ids_duplicates_and_empty_plan():
    f = attach_contract(card('2024年中国机器人市场规模达到120亿元。', '市场规模', '120', '亿元'), SCOPE)
    package = {'facts': [f]}
    for raw in ['{"evidence_ids":[],"analysis":"规模等于增速"}', '{"evidence_ids":["E-BADBADBADBAD"]}',
                '{"evidence_ids":[]}', '{"evidence_ids":[1]}', json.dumps({'evidence_ids':[f['evidence_id']]*2})]:
        with pytest.raises(ValueError): parse_plan(raw, package, 4)
    text = render_plan(package, 4, '市场', parse_plan(json.dumps({'evidence_ids':[f['evidence_id']]}), package, 4))
    assert '市场规模：120亿元' in text and '增长率' not in text


def test_rejected_body_statement_cannot_reinfect_summary_via_citation():
    f = attach_contract(card('2024年中国机器人市场规模达到120亿元。', '市场规模', '120', '亿元'), SCOPE)
    packages = {4: {'facts': [f]}}
    rejected = f'该来源需复核，暂不转述。 [{f["evidence_id"]}]'
    assert summary_package(packages, {4:rejected}, SCOPE)['facts'] == []
    assert '120亿元' not in IndustryReportAgent()._fallback_section(packages[4], 1, '摘要')
    accepted = render_plan(packages[4], 4, '市场', [f['evidence_id']])
    summary = summary_package(packages, {4:accepted}, SCOPE)
    assert summary['facts'][0]['summary_lineage']['chapter'] == 4
    assert '120亿元' in render_plan(summary, 1, '摘要', [f['evidence_id']])
    assert summary_length(render_plan(summary, 1, '摘要', [f['evidence_id']])) <= 600


def test_bounded_writer_packet_does_not_expose_raw_other_numbers():
    f = attach_contract(card('2024年中国机器人市场规模达到120亿元，同比增长13%。', '市场规模', '120', '亿元'), SCOPE)
    projected = json.loads(bounded_package({'facts':[f]}))['facts'][0]
    assert '13%' not in projected['fact'] and '13%' not in projected['evidence_quote']


def test_live_writer_compiles_plan_and_summary_never_calls_model():
    f = attach_contract(card('2024年中国机器人市场规模达到120亿元。', '市场规模', '120', '亿元'), SCOPE)
    project = SimpleNamespace(industry_statement_mode=True, industry_statement_plans={}, industry_report_degradations=[])
    calls = []
    def invoke(*args):
        calls.append(args)
        return json.dumps({'evidence_ids':[f['evidence_id']]})
    writer = IndustryReportAgent()
    text = writer._write_section(project, json.dumps({'facts':[f]}), '{}', 4, '市场', [], 1, invoke, lambda s,n:s, lambda *a,**k:None, None)
    summary = summary_package({4:{'facts':[f]}}, {4:text}, SCOPE)
    writer._write_section(project, json.dumps(summary), '{}', 1, '摘要', [], 1, invoke, lambda s,n:s, lambda *a,**k:None, None)
    assert len(calls) == 1
    assert project.industry_statement_plans[1]['model_attempts'] == 0


def test_bad_plan_has_one_repair_then_safe_statements_and_review_status():
    f = attach_contract(card('2024年中国机器人市场规模达到120亿元。', '市场规模', '120', '亿元'), SCOPE)
    project = SimpleNamespace(industry_statement_plans={}, industry_report_degradations=[])
    calls = []
    def invoke(*args):
        calls.append(args)
        return '机器人市场规模为12%，情况十分乐观。'
    result = IndustryReportAgent()._write_statement_section(project, {'facts':[f]}, 4, '市场', invoke, lambda *a,**k:None, None)
    assert len(calls) == 2 and '12%' not in result and '120亿元' in result
    assert '修复' in calls[1][0]
    assert project.industry_report_degradations


def test_real_outline_and_writer_preserve_16_chapters_and_seven_proposal_chapters():
    import re
    from industry_research import unknown_risk
    from report_agents.industry_proposal import build_industry_proposal
    chain = attach_contract(card('机器人产业链上游提供控制器，中游完成整机集成，下游服务制造场景。',
        module='细分赛道与产业链', evidence_id='E-AAAAAAAAAAAA'), SCOPE)
    market = attach_contract(card('2024年中国机器人市场规模达到120亿元。', '市场规模', '120', '亿元'), SCOPE)
    policy = attach_contract(card('第三条 机器人服务提供者应当建立安全管理制度，保障使用者合法权益。',
        module='政策与监管', source_title='机器人服务管理办法', source_url='https://www.cac.gov.cn/law',
        evidence_id='E-BBBBBBBBBBBB'), SCOPE)
    project = SimpleNamespace(title='合成行业验收', target_name='机器人', target_type='industry', industry='机器人',
                              industry_scope=SCOPE, description='')
    packets = []
    def invoke(role, prompt, trace):
        data = json.loads(prompt.split('\n', 1)[1])
        packets.append(data)
        if 'chapters' in data:
            return json.dumps({'priorities':[]})
        if 'questions' in data:
            return json.dumps({'answers':[]})
        return json.dumps({'evidence_ids':[f['id'] for f in data['cards']][:8]})
    payload = {'facts':[chain, market, policy], 'fact_contract_version':VERSION, 'industry_scope':SCOPE}
    risk = unknown_risk(scope=SCOPE)
    report = IndustryReportAgent().generate(project, json.dumps(payload), json.dumps(risk), invoke,
                                            lambda s,n:s[:n], lambda *a,**k:None)
    proposal = build_industry_proposal(project, report, risk)
    assert re.findall(r'^## (\d+)\.', report, re.M) == [str(i) for i in range(1,17)]
    assert re.findall(r'^## (\d+)\.', proposal, re.M) == [str(i) for i in range(1,8)]
    policy_chapter = report.split('## 3. ')[1].split('## 4. ')[0]
    assert policy['evidence_id'] in policy_chapter and market['evidence_id'] not in policy_chapter
    for chapter in (6,7):
        body = report.split(f'## {chapter}. ')[1].split(f'## {chapter+1}. ')[0]
        assert '120亿元' not in body
    assert packets and all('cards' in p or 'chapters' in p for p in packets)
    assert project.industry_question_jobs_enabled
    assert project.industry_question_planning['attempts'] == 1
    assert project.industry_statement_plans[1]['model_attempts'] == 0


def test_preparation_binds_source_snapshots_before_new_permissions_and_index_counts():
    from research_workflow import ResearchWorkflow
    good = card('2024年中国机器人市场规模达到120亿元。', '市场规模', '120', '亿元')
    bad = card('2024年中国机器人产业规模增长速度维持在12%以上。', '产业规模', '12', '%', evidence_id='E-BBBBBBBBBBBB')
    src = SimpleNamespace(id=55, url=good['source_url'], title='机器人统计材料',
        content=good['evidence_quote']+'\n'+bad['evidence_quote'], source_metadata={'module':'市场规模与增长'},
        object_key='synthetic.txt', source_type='web_search', summary='', credibility_score=70)
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    workflow._active_industry_sources = lambda project:[src]
    prepared = json.loads(workflow._prepare_industry_evidence(SimpleNamespace(industry_scope=SCOPE),
                          json.dumps({'facts':[good,bad],'industry_scope':SCOPE}), {'evidence_requirements':[]}))
    assert prepared['fact_contract_version'] == VERSION
    assert len(prepared['facts']) == 2 and prepared['source_body_snapshots']
    assert prepared['provenance_summary']['located_fact_count'] == 2
    assert prepared['provenance_summary']['index_eligible_fact_count'] == 1
    assert prepared['fact_contract_summary']['held_for_review'] == 1
    assert good.get('fact_contract') is None


def test_compact_index_keeps_real_links_and_full_locator_in_audit_not_repeated_prose():
    from industry_research import append_evidence_index, validate_docx_package
    from docx_exporter import markdown_to_docx_bytes
    from io import BytesIO
    from zipfile import ZipFile
    quote = '2024年中国机器人市场规模达到120亿元。'
    f = attach_contract(card(quote, '市场规模', '120', '亿元'), SCOPE)
    payload = {'facts':[f], 'fact_contract_version':VERSION}
    report = render_plan(payload,4,'市场',[f['evidence_id']])+'\n\n## 15. 信息来源\n\n## 16. 后续研究点\n'
    result, audit = append_evidence_index(report,payload,[(str(i),[]) for i in range(1,17)],{4:payload})
    index = result.split('## 15. ')[1].split('## 16. ')[0]
    assert '120亿元' not in index and f']({f["source_url"]})' in index
    assert '定位识别' in index and audit['numeric_evidence'][f['evidence_id']]['context']['value'] == '120'
    data = markdown_to_docx_bytes(result)
    assert validate_docx_package(data)['docx_integrity_status'] == 'passed'
    with ZipFile(BytesIO(data)) as archive:
        assert f['source_url'] in archive.read('word/_rels/document.xml.rels').decode()
