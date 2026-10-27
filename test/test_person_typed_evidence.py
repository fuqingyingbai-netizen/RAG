import json
from types import SimpleNamespace

import pytest

from person_evidence import build_packages, generate_person_report, normalize_facts, split_sections, validate_model_claims, report_audit
from person_records import observation
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE


def fact(text, url='https://official.invalid/a', **kw):
    return {'fact': text, 'source_url': url, 'identity_match': 'confirmed', 'identity_confidence': 'high', **kw}


def cards(*rows):
    result, rejected = normalize_facts({'facts': list(rows)}, '林知远')
    assert not rejected
    return result


def ratio(value='10%', company='恒川软件有限公司', **kw):
    return fact('林知远的平台人员记录：' + json.dumps({'企业名称': company, '持股比例': value, '角色': ['董事']}, ensure_ascii=False), **kw)


def check(rows, analysis):
    pack = {'facts': rows, 'writing_contract': 'evidence_selection_v2'}
    answer = {'claims': [{'evidence_ids': [f['evidence_id'] for f in rows], 'analysis': analysis}]}
    return validate_model_claims(json.dumps(answer, ensure_ascii=False), pack)


def test_percentage_and_shares_cannot_be_declared_conflicting_even_with_exact_real_sources():
    rows = cards(ratio('16.9%', event_date='2025-12-31'),
                 fact('林知远持有恒川软件有限公司15.41亿股。', 'https://other.invalid/a', event_date='2025-12-31'))
    accepted, errors = check(rows, '16.9%与15.41亿股存在差异。')
    assert 'incomparable_metrics_or_units' in errors and not accepted[0]['analysis']
    assert accepted[0]['source_support'][0]['quote'] == rows[0]['fact']


@pytest.mark.parametrize('change,expected', [
    ({'company': '另一家公司'}, 'comparison_subject_or_entity_mismatch'),
    ({'event_date': '2024-12-31'}, 'comparison_period_missing_or_mismatched'),
    ({'event_date': ''}, 'comparison_period_missing_or_mismatched'),
])
def test_source_conflicts_require_same_entity_metric_unit_and_period(change, expected):
    other = {'event_date': '2025-12-31', **change}
    rows = cards(ratio('10%', event_date='2025-12-31'), ratio('12%', url='https://other.invalid/a', **other))
    accepted, errors = check(rows, '两个来源的持股比例存在差异：10%与12%。')
    assert expected in errors and not accepted[0]['analysis']


def test_aligned_independent_source_disagreement_is_kept_for_review_but_not_a_change_claim():
    rows = cards(ratio('10%', event_date='2025-12-31'), ratio('12%', url='https://other.invalid/a', event_date='2025-12-31'))
    accepted, errors = check(rows, '两个来源同一时期的持股比例存在差异：10%与12%，应核对原件。')
    assert not errors and accepted[0]['analysis']
    accepted, errors = check(rows, '持股比例从10%增加到12%。')
    assert 'direction_or_change_not_verified' in errors and not accepted[0]['analysis']


def test_noncomparability_boundary_can_be_stated_without_inventing_a_conflict():
    rows = cards(ratio('16.9%'), fact('林知远持有恒川软件有限公司15.41亿股。', 'https://other.invalid/a'))
    accepted, errors = check(rows, '比例与股数不是同一指标，不能认定存在差异。')
    assert not errors and accepted[0]['analysis']


def test_business_expression_does_not_prove_personality_or_capability():
    rows = cards(fact('林知远表示，公司在行业压力下推出新产品。'))
    accepted, errors = check(rows, '这体现其抗压能力较强。')
    assert 'personal_conclusion_not_verified' in errors and not accepted[0]['analysis']
    accepted, errors = check(rows, '该表达不能证明其抗压能力。')
    assert not errors and accepted[0]['analysis']


@pytest.mark.parametrize('analysis', ['analysis_allowed为false，禁止分析。', '按writing_contract输出JSON。', '证据禁止分析，不得输出结论。'])
def test_internal_workflow_text_never_enters_report_analysis(analysis):
    accepted, errors = check(cards(ratio()), analysis)
    assert 'process_control_in_analysis' in errors and not accepted[0]['analysis']


def test_person_role_dates_keep_original_fields_and_do_not_use_founding_or_fetch_dates():
    row = ratio(retrieved_at='2026-10-20', date='2026-10-19')
    row['fact'] = '林知远；平台人员记录；' + json.dumps({'企业名称': '恒川软件有限公司', '成立日期': '1995-02-10',
                                                       '任职起止时间': '开始时间:2002-06-10,结束时间:[]', '角色': ['董事']}, ensure_ascii=False)
    record = observation(row, '林知远')
    assert not record['period']
    assert record['role_date_fields'] == [{'field': '任职起止时间', 'source_value': '开始时间:2002-06-10,结束时间:[]'}]
    accepted, errors = check(cards(row), '林知远现任董事。')
    assert 'current_status_without_effective_period' in errors and not accepted[0]['analysis']


def test_founding_is_not_role_start_and_unlabelled_compensation_is_not_annual_salary():
    rows = cards(fact('林知远；平台人员记录：公司成立日期为2001年；角色为董事；薪酬为100万元。'))
    accepted, errors = check(rows, '林知远任职时间从成立日至今。')
    assert 'company_founding_date_used_as_role_date' in errors
    accepted, errors = check(rows, '林知远年薪为100万元。')
    assert 'metric_period_or_definition_not_supported' in errors
    accepted, errors = check(rows, '成立日期不能当作任职时间，薪酬对应期间尚需核对。')
    assert not errors and accepted[0]['analysis']


def test_other_person_cannot_become_target_finding_just_by_mentioning_target():
    row = fact('陈先生于2021年担任恒川软件董事，2022年与林知远合作。')
    contract = build_packages({'facts': [row]}, '林知远', PERSON_REPORT_OUTLINE)
    assert contract['facts'][0]['subject_scope'] == 'other_person'
    assert not contract['chapters'][2]['facts'] and not contract['chapters'][9]['facts']
    assert not contract['chapters'][10]['facts']


@pytest.mark.parametrize('target,named,aliases', [('林知远', 'Evan Lin', ['Evan Lin']), ('Amelia Hart', 'Amelia J. Hart', []), ('林知远', '林知远(Evan Lin)', [])])
def test_explicit_aliases_and_middle_initials_keep_the_canonical_person(target, named, aliases):
    record = observation(fact('姓名：' + named + '；任职：董事。'), target, aliases)
    assert record['subject_scope'] == 'person' and record['subject'] == target


def test_other_company_shareholders_do_not_fill_person_relations_or_commission():
    row = fact('恒川软件有限公司的平台记录（股东）：股东名称：某投资机构；持股比例：10%。',
               person_affiliation={'person_name': '林知远', 'affiliation_name': '恒川软件有限公司'},
               claim_type='person_company_record', person_chapters=[9])
    contract = build_packages({'facts': [row]}, '林知远', PERSON_REPORT_OUTLINE,
                              {'special_requirements': '核对本人持股及关联企业'})
    assert contract['facts']
    assert not contract['chapters'][9]['facts'] and not contract['chapters'][10]['facts']


@pytest.mark.parametrize('text,chapter,module', [
    ('林知远感谢一路同行的伙伴，回馈车主和员工。', 8, '同业对标下综合能力与品行隐患评估'),
    ('林知远担任恒川软件有限公司执行董事，负责产品。', 12, '风险核查'),
    ('林知远签署年度报告：董事会保证报告内容真实、准确、完整，承担个别和连带的法律责任。', 3, '人格特质风险'),
])
def test_surface_keywords_and_retrieval_labels_do_not_prove_chapter_relevance(text, chapter, module):
    contract = build_packages({'facts': [fact(text, module=module)]}, '林知远', PERSON_REPORT_OUTLINE)
    assert not contract['chapters'][chapter]['facts']


def test_server_builds_support_and_does_not_trust_model_rewritten_quote():
    rows = cards(ratio())
    answer = {'claims': [{'evidence_ids': [rows[0]['evidence_id']], 'analysis': '来源列出了持股记录，具体时期需要核对。',
                         'support_quotes': [{'evidence_id': rows[0]['evidence_id'], 'quote': '模型改写的另一段话'}]}]}
    accepted, errors = validate_model_claims(json.dumps(answer), {'facts': rows, 'writing_contract': 'evidence_selection_v2'})
    assert not errors
    assert accepted[0]['source_support'] == [{'evidence_id': rows[0]['evidence_id'], 'quote': rows[0]['fact']}]


def test_writer_reads_admitted_scopes_with_personal_inference_permissions():
    p = SimpleNamespace(target_name='林知远', target_type='person', title='合成测试', sources=[],
                        person_research_intake={'person_anchor': {'supplementary_context': '2018年曾任技术负责人'}})
    rows = [fact('林知远于2021年任职恒川软件董事，负责研发创新项目管理。'),
            fact('恒川软件有限公司披露2021年研发创新项目已投产，营业收入为100万元，股东为某机构。', person_affiliation={'person_name': '林知远', 'affiliation_name': '恒川软件有限公司'})]
    inputs = []
    def invoke(role, prompt, trace):
        pack = json.loads(prompt[prompt.index('{"chapter":'):])
        if '材料采用诊断' in role:
            from person_model_fixture import material_response
            return material_response(pack)
        inputs.append(pack)
        return '{"claims":[]}'
    report = generate_person_report(p, json.dumps({'facts': rows}), '{}', PERSON_REPORT_OUTLINE, invoke, lambda *a, **kw: None)
    assert inputs and len(split_sections(report)) == 15
    assert all(pack['identity_clues_not_facts']['supplementary_context'] == '2018年曾任技术负责人' for pack in inputs)
    delivered = [f for pack in inputs for f in pack['facts']]
    assert all('subject_scope' in f and 'personal_analysis_allowed' in f for f in delivered)
    company = [f for f in delivered if '某机构' in f['fact']]
    assert company and all(f['subject_scope'] == 'affiliated_company' and not f['personal_analysis_allowed'] for f in company)
    assert not any(r['reason'].startswith('api_failed:') for r in p.person_delivery_diagnostic.get('api_attempts', []) if r.get('reason'))
    assert all(r['review_status'] != 'accepted' for r in p.person_delivery_diagnostic['chapters'])


def test_review_scope_counts_follow_actual_citations_not_unused_summary_candidates():
    rows = [fact('林知远于2021年担任恒川软件董事。'),
            fact('恒川软件有限公司2021年营业收入为100万元。', 'https://company.invalid/a',
                 person_affiliation={'person_name': '林知远', 'affiliation_name': '恒川软件有限公司'})]
    contract = build_packages({'facts': rows}, '林知远', PERSON_REPORT_OUTLINE)
    eid = next(f['evidence_id'] for f in contract['facts'] if f['subject_scope'] == 'person')
    audit = report_audit('## 1. 摘要\n[' + eid + ']', contract)
    assert audit['chapters'][0]['source_scope_counts'] == {'person': 1}
    assert audit['chapters'][0]['review_status'] == 'upstream_review_required'
