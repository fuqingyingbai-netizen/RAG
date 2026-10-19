import json
from collections import Counter, defaultdict
from copy import deepcopy
from types import SimpleNamespace

import pytest

from report_agents.company_risk_register import (
    _judicial_entries, build_risk_register, dictionary, iso_date,
    recall_discovery_queries, recall_events, render_risk_register,
    risk_register_errors, source_anchor, subsidiary_relations,
)

ROOT = '青禾制造股份有限公司'
CHILD = '青禾汽车制造有限公司'
OTHER = '青禾汽车有限公司'


def report(child=CHILD, year=2025, half=False, pct='96.79 3.21', star=False):
    title = ROOT + str(year) + ('年半年度报告' if half else '年年度报告')
    pages = [{'page': 1, 'text': ROOT + '\n' + title},
             {'page': 10, 'text': '合并资产负债表\n' + str(year) + ('年6月30日' if half else '年12月31日') + '\n单位：人民币元'},
             {'page': 25, 'text': '在子公司中的权益\n企业集团的构成\n持股比例(%) 直接 间接\n'
              + child + ('*' if star else '') + ' 深圳 深圳 制造 人民币1,000,000元 ' + pct}]
    return {'title': title, 'url': f'https://www.hkexnews.hk/{year}/report{int(half)}.pdf',
            'content': '\n'.join(p['text'] for p in pages),
            'source_metadata': {'content_kind': 'pdf_text_extracted', 'document_pages': pages}}


def notice(owner=CHILD, index=1, publication='2026-09-18', body=None):
    if body is None:
        body = ('召回编号S2026M0116V：自即日起，召回2021年3月2日至2022年9月29日期间生产的甲型汽车，共计40辆。\n'
                '本次召回范围内部分车辆，因部件制造原因，可能引发短路，存在起火风险。\n'
                + owner + '将为召回范围内车辆免费更换改进后的部件，以消除安全隐患。')
    text = (owner + '召回部分汽车\n发布时间：' + publication + ' 15:01\n日前，' + owner
            + '根据《缺陷汽车产品召回管理条例》，向国家市场监督管理总局备案了召回计划。\n' + body)
    return {'title': owner + '召回部分汽车', 'url': f'https://www.samr.gov.cn/recall/{index}.html',
            'content': text, 'source_metadata': {'content_kind': 'html_text_extracted', 'fetch_status': 'done'}}


def card(s, eid='E-000000000001', fact='均为低风险，股权集中证明决策科学。'):
    return {'source_url': s['url'], 'source_title': s['title'], 'evidence_id': eid,
            'fact': fact, 'evidence_scope': 'target_direct', 'eligible_for_risk_scoring': True}


def build(*sources, target=ROOT, facts=None, **kwargs):
    return build_risk_register({'facts': facts or []}, target, sources, **kwargs)


def recalls(p):
    return [e['fact_record'] for e in p['entries'] if e['kind'] == 'recall']


def test_dictionary_exactly_preserves_75_template_questions_and_three_categories():
    d = dictionary()
    assert len(d['items']) == len({i['id'] for i in d['items']}) == 75
    assert Counter(i['category'] for i in d['items']) == {'组织与管理风险': 23, '业务与运营风险': 24, '行业特殊风险': 28}
    assert all(i['origin'] == 'template' for i in d['items'])
    assert 'B24' in d['template_reference']


@pytest.mark.parametrize('value, expected', [('2026-09-18', '2026-09-18'), ('2026年6月30日', '2026-06-30'),
                                          ('2025年2月30日', None), ('2025年', None)])
def test_date_parsing_rejects_incomplete_or_invalid_dates(value, expected):
    assert iso_date(value) == expected


def test_missing_cleaned_card_does_not_hide_original_recall_or_relation():
    p = build(report(), notice())
    assert len(recalls(p)) == 1
    assert all(e.startswith('E-') for e in recalls(p)[0]['evidence_ids'])
    assert len(recalls(p)[0]['evidence_ids']) == 2


def test_parent_name_prefix_does_not_prove_child_ownership():
    assert not recalls(build(notice()))
    assert build(notice())['diagnostic']['filters']['unproven_manufacturer_relationship'] == 1


def test_direct_manufacturer_needs_no_parent_relationship():
    p = build(notice(owner=ROOT))
    assert len(recalls(p)) == 1 and 'relationship' not in recalls(p)[0]


@pytest.mark.parametrize('star, half', [(False, False), (True, True)])
def test_subsidiary_grid_requires_owned_report_and_preserves_direct_indirect(star, half):
    s = report(half=half, star=star)
    rs = subsidiary_relations(ROOT, [s], defaultdict(list))
    assert len(rs) == 1 and rs[0]['direct_pct'] == '96.79' and rs[0]['indirect_pct'] == '3.21'
    assert rs[0]['as_of'] == ('2025-06-30' if half else '2025-12-31')


def test_blank_indirect_is_not_zero_and_invalid_percentage_not_admitted():
    rs = subsidiary_relations(ROOT, [report(pct='99.00 -')], defaultdict(list))
    assert rs[0]['indirect_pct'] == '-'
    assert not subsidiary_relations(ROOT, [report(pct='120.0 3.0')], defaultdict(list))


def test_fiscal_year_is_not_automatically_calendar_year_end():
    s = report(); s['source_metadata']['document_pages'][1]['text'] = '合并资产负债表\n2025年3月31日\n单位：人民币元'
    rs = subsidiary_relations(ROOT, [s], defaultdict(list))
    assert rs[0]['as_of'] == '2025-03-31'


def test_relationship_cutoff_not_invented_when_only_report_year_or_contents_available():
    s = report(); s['source_metadata']['document_pages'][1]['text'] = '目录\n合并资产负债表......10'
    assert not subsidiary_relations(ROOT, [s], defaultdict(list))


def test_wrong_issuer_and_generic_table_comention_are_not_relationship_proof():
    s = report(); s['source_metadata']['document_pages'][0]['text'] = '其他股份有限公司\n2025年年度报告'
    assert not recalls(build(s, notice()))
    s = report(); s['source_metadata']['document_pages'][2]['text'] = CHILD + ' 深圳 深圳 制造 人民币100元 96.79 3.21'
    assert not recalls(build(s, notice()))


def test_historical_recall_with_later_relationship_is_explicitly_retrospective():
    p = build(report(), notice(publication='2024-09-29', body='召回2021年3月2日至2022年9月29日期间生产的甲型汽车，共计40辆。\n本次召回范围内部分车辆可能发生短路，存在安全风险。\n' + CHILD + '将免费更换部件。'))
    assert len(recalls(p)) == 1
    assert '事后' in recalls(p)[0]['relationship_timing']
    assert '事件当日关系未证' in render_risk_register(p)


def test_research_cutoff_excludes_future_notice_and_future_relationship():
    assert not recalls(build(report(), notice(), intake={'as_of_date': '2026-09-17'}))
    assert not recalls(build(report(year=2027), notice(), intake={'as_of_date': '2026-10-14'}))


def test_future_financial_statement_and_later_exchange_release_do_not_leak_into_risk():
    s = report(year=2027)
    s['source_metadata']['document_pages'].append({'page': 30, 'text': '本公司截至2027年12月31日尚有余额为人民币1,000万元的应付票据到期未付。'})
    s['content'] += '\n' + s['source_metadata']['document_pages'][-1]['text']
    p = build(s, intake={'as_of_date': '2026-10-14'})
    assert not p['entries'] and p['diagnostic']['filters']['sources_after_research_cutoff'] == 1
    s = report(); s['url'] = 'https://www.hkexnews.hk/listedco/listconews/sehk/2026/0422/report.pdf'
    assert not subsidiary_relations(ROOT, [s], defaultdict(list), as_of='2026-01-01')


def test_recent_h1_relation_selected_without_claiming_event_date_unchanged():
    p = build(report(), report(year=2026, half=True, star=True), notice())
    assert recalls(p)[0]['relationship']['as_of'] == '2026-06-30'
    assert '公告日股权未变化' in render_risk_register(p)


@pytest.mark.parametrize('status', ['failed', 'blocked_or_challenge', 'wrong_page_or_homepage', 'fetch_timeout'])
def test_failed_or_wrong_page_never_becomes_no_recall_or_event(status):
    s = notice(owner=ROOT); s['source_metadata']['fetch_status'] = status
    p = build(s)
    assert not recalls(p) and p['overall_score'] is None
    assert p['coverage'][0]['state'] == 'not_usable_primary_notice'


def test_search_snippet_and_homepage_even_http200_are_not_original_notices():
    s = notice(owner=ROOT); s['source_metadata']['content_kind'] = 'search_summary'
    assert not recalls(build(s))
    s = notice(owner=ROOT); s['source_metadata']['target_article_matched'] = False
    assert not recalls(build(s))


def test_primary_web_reader_cache_is_distinguished_from_direct_403():
    s = notice(owner=ROOT)
    s['source_metadata'].update(acquisition_method='web_reader_primary_page_cache', direct_http_fetch_status=403)
    p = build(s)
    assert recalls(p)[0]['acquisition_method'] == 'web_reader_primary_page_cache'


def test_notice_date_wins_over_portal_index_and_quantity_not_annual_sales():
    s = notice(owner=ROOT); s['source_metadata']['publication_date'] = '2026-09-24'
    r = recalls(build(s))[0]
    assert r['publication_date'] == r['effective_date'] == '2026-09-18'
    assert r['scope_parts'][0]['reported_quantity'] == 40
    assert r['scope_parts'][0]['production_from'] == '2021-03-02'
    assert r['defect_quote'].endswith('起火风险。')
    assert '事故' not in r['fact']


def multi_notice():
    body = ('一、' + CHILD + '\n召回编号S2026M0116V：自2026年10月1日起，召回2021年3月2日至2022年9月29日生产的甲型，共计40辆；2022年10月1日至2023年1月2日生产的乙型，共计12辆。\n'
            '二、' + OTHER + '\n召回编号S2026M0117V：自2026年10月1日起，召回2021年1月1日至2022年1月1日期间生产的丙型，共计8辆。\n'
            '本次召回范围内的车辆，限位垫可能脱落，造成制动灯常亮，存在安全隐患。\n'
            + CHILD + '、' + OTHER + '将免费更换改善后的限位垫。')
    return notice(owner=CHILD + '、' + OTHER, body=body)


def test_multiple_manufacturers_shared_defect_and_three_model_rows_not_summed():
    p = build(report(), report(child=OTHER, year=2024), multi_notice())
    rs = recalls(p)
    assert len(rs) == 2 and len(rs[0]['scope_parts']) == 2
    assert all(r['effective_date'] == '2026-10-01' for r in rs)
    text = render_risk_register(p)
    assert text.count('潜在缺陷及后果（原文）') == 1
    assert '40辆' in text and '12辆' in text and '8辆' in text and '60辆' not in text
    assert '制动失效' not in text


def test_separate_campaigns_do_not_share_the_wrong_defect_or_investigation():
    a = '召回编号S2026M0116V：自即日起，召回2021年1月1日至2022年1月1日生产的甲型，共计40辆。\n本次召回范围内部分车辆存在起火风险。\n本次召回活动是在国家市场监督管理总局启动缺陷调查情况下开展的。' + CHILD + '将免费更新软件。'
    b = '召回编号S2026M0117V：自即日起，召回2022年1月1日至2023年1月1日生产的乙型，共计12辆。\n本次召回范围内部分车辆存在密封不足。\n' + CHILD + '将免费补强密封。'
    s = notice(body='一、' + a + '\n二、' + b)
    rs = recalls(build(report(), s))
    assert len(rs) == 2 and rs[0]['under_defect_investigation']
    assert not rs[1]['under_defect_investigation'] and '起火' not in rs[1]['defect_quote']


def test_unshown_recall_number_is_null_not_fabricated():
    s = notice(owner=ROOT); s['content'] = s['content'].replace('召回编号S2026M0116V：', '')
    assert recalls(build(s))[0]['recall_number'] is None


def test_impossible_future_production_period_not_admitted():
    s = notice(owner=ROOT); s['content'] = s['content'].replace('2022年9月29日', '2028年9月29日')
    assert not recalls(build(s))


def test_shared_total_across_two_production_periods_is_a_manual_gap_not_wrong_assignment():
    s = notice(owner=ROOT, body='召回2021年1月1日至2022年1月1日期间生产的甲型以及2022年2月1日至2023年2月1日期间生产的乙型，共计40辆。\n本次召回范围内部分车辆存在起火风险。\n' + ROOT + '将免费更换部件。')
    p = build(s)
    assert not recalls(p)
    assert p['coverage'][0]['state'] == 'recall_body_requires_manual_scope_review'


def test_unproven_shared_remedy_does_not_assign_defect_to_first_manufacturer():
    s = multi_notice(); s['content'] = s['content'].replace(CHILD + '、' + OTHER + '将免费', OTHER + '将免费')
    parsed, _ = recall_events(s, source_anchor(s, defaultdict(list)))
    assert len(parsed) == 1 and parsed[0]['entity'] == OTHER


def test_unknown_sector_not_clearance_and_verified_related_events_still_admitted():
    p = build(report(), notice(), industry='新能源汽车')
    assert p['active_template_sectors'] == ['新能源行业']
    assert len(recalls(p)) == 1
    consumer = next(i for i in p['checklist'] if i['id'] == 'CON-07')
    assert consumer['state'] == 'outside_declared_sector_scope'
    assert not consumer['entry_ids']


def test_consumer_quality_question_links_event_but_not_parameter_fraud():
    p = build(notice(owner=ROOT), industry='消费品家电')
    assert next(i for i in p['checklist'] if i['id'] == 'CON-07')['entry_ids']
    assert next(i for i in p['checklist'] if i['id'] == 'OPS-07')['state'] == 'requires_event_evidence'


def test_template_and_60_plus_model_claims_do_not_establish_events_or_score():
    n = notice(owner=ROOT)
    facts = [card(n, fact='权威来源确认管理失效、造假，风险95分。') for _ in range(80)]
    p = build(n, facts=facts)
    assert len(recalls(p)) == 1 and len(p['checklist']) == 75
    assert p['overall_score'] is None and all(d['score'] is None for d in p['dimensions'])
    assert '95分' not in render_risk_register(p)
    assert not any(e['kind'] == 'fraud' for e in p['entries'])


def test_company_workflow_uses_originals_without_model_or_old_normalizers():
    from research_workflow import ResearchWorkflow
    w = ResearchWorkflow.__new__(ResearchWorkflow)
    def forbidden(*a, **kw):
        raise AssertionError('legacy model scoring must not run')
    w._invoke = w._normalize_company_risk_evidence = w._normalize_risk_unknowns = forbidden
    s = notice(owner=ROOT)
    project = SimpleNamespace(target_type='company', target_name=ROOT, industry='制造', sources=[s])
    r = json.loads(w.assess_risk(project, json.dumps({'facts': []})))
    assert r['version'] == 'company-risk-register-v2-case-display-references' and len(r['entries']) == 1


def test_person_and_industry_risk_paths_keep_their_own_model_dispatch():
    from research_workflow import ResearchWorkflow
    for kind in ('person', 'industry'):
        calls = []
        w = ResearchWorkflow.__new__(ResearchWorkflow)
        w._invoke = lambda agent, prompt, **kw: calls.append('person') or json.dumps({'dimensions': [], 'overall_score': None})
        w._invoke_industry_risk = lambda agent, prompt, **kw: calls.append('industry') or json.dumps({'dimensions': [], 'overall_score': None})
        p = SimpleNamespace(target_type=kind, title='测试', target_name='独立对象', industry='测试', sources=[])
        w.assess_risk(p, '{}')
        assert calls == [kind] and not hasattr(p, 'company_risk_register_package')


def judicial_row(**kw):
    return {'kind': 'disclosed_case', 'evidence_id': 'E-000000000001', 'evidence_ids': ['E-000000000001'],
            'source_url': 'https://www.hkexnews.hk/case.pdf', 'source_title': '年报', 'case_description': '甲公司与乙公司合同纠纷',
            'amount': '100万元', 'stage': '执行中', 'result': '乙方向甲方赔偿', 'execution': '乙方暂无财产可供执行',
            'period': '2025年年度报告', 'fact': '原件具体案件及角色', **kw}


def test_recovery_obstacle_is_case_specific_and_latest_exact_case_preferred():
    rows = [judicial_row(case_description='1.甲公司与乙公司合同纠纷'),
            judicial_row(period='2026年半年度报告')]
    es = _judicial_entries(rows)
    assert len(es) == 1 and es[0]['kind'] == 'recovery_obstacle'
    assert es[0]['fact_record']['period'] == '2026年半年度报告'
    assert '追偿方不据此变成失信被执行人' in es[0]['assessment']


def test_different_claim_amounts_not_collapsed_and_scan_counts_not_adverse_judgments():
    es = _judicial_entries([judicial_row(), judicial_row(amount='200万元'), judicial_row(kind='scan')])
    assert len(es) == 2


def test_labour_notice_does_not_imply_illegal_employment_or_loss():
    es = _judicial_entries([judicial_row(kind='labour', case_number='测试仲案2025号')])
    assert es[0]['state'] == 'procedure_pending'
    assert '尚不能据公告认定违法用工' in es[0]['assessment']


def test_writer_and_audit_index_resolve_event_recovered_without_any_fact_card():
    from report_agents.company_report_agent import CompanyReportAgent
    from research_workflow import ResearchWorkflow
    p = build(notice(owner=ROOT))
    project = SimpleNamespace(target_type='company', target_name=ROOT, company_risk_register_package=p)
    t = CompanyReportAgent()._write_risk_register(project, p, lambda *a, **kw: None)
    assert not project.company_risk_register_diagnostic['degraded']
    indexed = ResearchWorkflow.__new__(ResearchWorkflow)._append_company_claim_evidence_index(
        project, t + '\n\n## 13. 信息来源\n\n## 14. 后续研究建议\n待核验。', [],
        total_traceable_sources=1, eligible_company_sources=1)
    assert '第十一章原文核对' in indexed and 'samr.gov.cn/recall/1.html' in indexed


def test_checked_risk_chapter_is_restored_after_unfounded_editor_rewrite(monkeypatch):
    from report_agents.company_report_agent import CompanyReportAgent
    s = notice(owner=ROOT)
    project = SimpleNamespace(target_name=ROOT, target_type='company', title=ROOT, industry='制造', description='', sources=[s])
    agent = CompanyReportAgent()
    monkeypatch.setattr(agent, '_write_section', lambda *a, **kw: '')
    monkeypatch.setattr(agent, '_write_summary', lambda *a, **kw: '## 1. 摘要\n摘要。')
    monkeypatch.setenv('COMPANY_REPORT_EDITOR_ENABLED', 'true')
    monkeypatch.setattr(agent, '_edit_batched', lambda *a, **kw: '\n'.join(
        f'## {i}. 标题\n' + ('无召回，已确认低风险。[E-FFFFFFFFFFFF]' if i == 11 else '待核验。') for i in range(1, 15)))
    text = agent.generate(project, '{"facts":[]}', '{}', lambda *a, **kw: '', lambda s, n: s[:n], lambda *a, **kw: None)
    chapter = text.split('## 11.')[1].split('## 12.')[0]
    assert '40辆' in chapter and '无召回，已确认低风险' not in chapter and 'FFFFFFFFFFFF' not in chapter


def test_empty_chapter_detail_survives_legacy_marker_pass():
    from report_agents.company_report_agent import CompanyReportAgent
    p = build()
    text = CompanyReportAgent._ensure_section_evidence_markers(render_risk_register(p), {11: []})
    assert '75个原始词条' in text and '当前召回/司法材料' in text


def test_empty_packet_is_degraded_and_unknown_does_not_masquerade_as_acceptance():
    p = build()
    assert risk_register_errors(render_risk_register(p), p)
    assert p['risk_level'] == 'unknown' and not p['entries']


def test_tampered_checklist_and_orphan_evidence_are_rejected():
    p = build(notice(owner=ROOT)); p['checklist'].pop()
    errors = risk_register_errors(render_risk_register(p) + '[E-FFFFFFFFFFFF]', p)
    assert len(errors) == 2


def test_discovery_is_bounded_and_only_uses_proven_manufacturers():
    seen = set(); ss = [report(), notice()]
    qs = recall_discovery_queries(ss, ROOT, seen)
    assert {q['recall_entity'] for q in qs} == {ROOT, CHILD}
    assert all(q['include_domains'] == ['samr.gov.cn', 'samrdprc.org.cn'] for q in qs)
    assert next(q for q in qs if q['recall_entity'] == CHILD)['recall_relationship_source'] == ss[0]['url']
    assert not recall_discovery_queries(ss, ROOT, seen)
    assert len(recall_discovery_queries([notice()], ROOT)) == 1


def test_discovery_does_not_search_a_co_mentioned_or_investment_vehicle_as_manufacturer():
    s = report(); s['source_metadata']['document_pages'][2]['text'] = s['source_metadata']['document_pages'][2]['text'].replace(' 制造 ', ' 投资控股 ')
    assert len(recall_discovery_queries([s], ROOT)) == 1
    # An actual primary recall notice independently identifies a manufacturer
    # (which may legally be an importer investment company).
    assert len(recall_discovery_queries([s, notice()], ROOT)) == 2


@pytest.mark.parametrize('name', ['星河精密股份有限公司', '青禾食品有限公司', 'Northstar Robotics Limited'])
def test_no_target_company_constant_in_generic_builder(name):
    p = build(notice(owner=name), target=name)
    text = render_risk_register(p)
    # The current Chinese primary parser handles legal Chinese manufacturers;
    # unparsed foreign notices remain a review gap rather than an invented event.
    if name.endswith('有限公司'):
        assert len(recalls(p)) == 1
    assert '比亚迪' not in text and '青禾制造股份有限公司' not in text
