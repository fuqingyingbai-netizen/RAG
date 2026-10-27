import json
from types import SimpleNamespace

import pytest

from person_commission import requirements, assess, event_years
from person_evidence import build_packages, generate_person_report, split_sections, validate_model_claims, cited_ids
from person_retrieval import SearchSession, coverage
from research_strategies.person import PersonResearchStrategy
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE


def intake(name='林知远'):
    return {'target_name': name, 'target_type': 'person', 'affiliation': '恒川软件有限公司',
            'person_anchor': {'aliases': [name], 'known_affiliations': ['恒川软件有限公司']},
            'special_requirements': '核对历史持股及任职变化，区分本人行为与关联企业事项。'}


def fact(text='林知远于2021年在恒川软件有限公司任职，担任董事并负责产品战略。', **extra):
    return {'fact': text, 'source_url': 'structured://qcc_executive/positions',
            'identity_match': 'confirmed', 'identity_confidence': 'high', **extra}


def package():
    p = build_packages({'facts': [fact()]}, '林知远', PERSON_REPORT_OUTLINE, intake())['chapters'][2]
    p['writing_contract'] = 'evidence_selection_v1'
    return p


def test_commissioned_career_records_enter_special_chapter_without_generic_special_keywords():
    row = fact('林知远；历史记录；{"企业名称":"恒川软件有限公司","角色":["董事"],"成立日期":"2001-01-01"}',
               claim_type='person_platform_record', person_chapters=[2, 6, 9])
    contract = build_packages({'facts': [row]}, '林知远', PERSON_REPORT_OUTLINE, intake())
    special = contract['chapters'][10]
    assert special['facts']
    career = next(r for r in special['commission_coverage'] if '任职' in r['question'])
    assert career['state'] == 'partial'
    assert any('成立日' in gap for gap in career['gaps'])
    assert any('两个' in gap for gap in career['gaps'])
    holdings = next(r for r in special['commission_coverage'] if '持股' in r['question'])
    assert holdings['state'] == 'missing'
    assert not event_years('"成立日期":"2001-01-01"')


def test_question_labels_cannot_make_unrelated_company_material_relevant():
    rows = [fact('恒川软件有限公司的主营产品为工业软件。', module='专项调研',
                 person_affiliation={'person_name': '林知远', 'affiliation_name': '恒川软件有限公司'})]
    special = build_packages({'facts': rows}, '林知远', PERSON_REPORT_OUTLINE, intake())['chapters'][10]
    assert not special['facts']
    assert all(r['state'] == 'missing' for r in special['commission_coverage'])


def test_company_suffix_and_other_team_members_do_not_fill_target_special_questions():
    value = intake()
    value['special_requirements'] = '核对持股及任职变化、教育背景'
    context = {'person_name': '林知远', 'affiliation_name': '恒川股份有限公司'}
    rows = [fact('恒川股份有限公司的平台记录（团队成员）：姓名：陈雨安；职位：董事；教育：远山大学；介绍：2021年与林知远合作。',
                 person_affiliation=context, claim_type='person_company_record', person_chapters=[6]),
            fact('林知远的平台人员记录：{"企业名称":"恒川股份有限公司","角色":["董事"]}',
                 claim_type='person_platform_record', person_chapters=[2, 6, 9]),
            fact('陈先生于2019年担任其他公司董事，后于2021年与林知远合作。')]
    special = build_packages({'facts': rows}, '林知远', PERSON_REPORT_OUTLINE, value)['chapters'][10]
    assert len(special['facts']) == 1
    assert '平台人员记录' in special['facts'][0]['fact']
    assert next(r for r in special['commission_coverage'] if '持股' in r['question'])['state'] == 'missing'
    assert next(r for r in special['commission_coverage'] if '教育' in r['question'])['state'] == 'missing'


def test_compact_table_headers_do_not_count_as_a_different_person_name():
    value = intake()
    row = fact('序号 姓名 职务 任职日期 持股数 1 林知远 董事 2021-01-01 100股')
    special = build_packages({'facts': [row]}, '林知远', PERSON_REPORT_OUTLINE, value)['chapters'][10]
    assert special['facts']


def test_executive_director_is_not_a_judicial_execution_record():
    value = intake()
    value['special_requirements'] = '核对司法事项'
    row = fact('林知远担任恒川软件有限公司执行董事。')
    special = build_packages({'facts': [row]}, '林知远', PERSON_REPORT_OUTLINE, value)['chapters'][10]
    assert not special['facts']


@pytest.mark.parametrize('name', ['陈雨安', 'Amelia Hart', '山田太郎'])
def test_questions_are_generic_and_do_not_import_another_person(name):
    value = intake(name)
    value['special_requirements'] = '核对学历与专利，核对融资情况'
    rows = PersonResearchStrategy().expand_search_queries({}, value)
    commissioned = [r for r in rows if r.get('commission_id')]
    assert {r['topic'] for r in requirements(value)} == {'education', 'ipr', 'operations'}
    assert commissioned and all(name in r['query'] for r in commissioned)
    assert not any('林知远' in r['query'] for r in commissioned)


def test_search_initial_round_prioritizes_actual_special_questions_and_total_budget(monkeypatch):
    monkeypatch.setenv('PERSON_SEARCH_CALL_BUDGET', '18')
    value = intake()
    items = PersonResearchStrategy().expand_search_queries({}, value)
    session = SearchSession(value, ['bocha', 'exa', 'tavily'])
    chosen = session.choose(items, 1, [])
    special = [r for r in chosen if r['person_chapters'] == [10]]
    assert special and all(r.get('commission_id') for r in special)
    assert any('持股' in r['query'] for r in special)
    assert any('任职' in r['query'] for r in special)
    assert all('恒川软件有限公司' in r['query'] for r in special)
    session.record([(r, []) for r in chosen])
    session.choose(items, 2, [])
    session.choose(items, 3, [])
    assert len(session.rows) <= 18
    assert all(r.get('requirement_ids') for r in session.rows if r.get('commission_id'))


def test_coverage_uses_original_question_topics_not_static_special_words():
    value = intake()
    text = '林知远历史任职记录：企业名称为恒川软件有限公司，角色为董事。' * 8
    src = SimpleNamespace(id=1, content=text, url='structured://qcc/positions', source_type='business_database',
                          source_metadata={'identity_confidence': 'high'})
    special = coverage([src], value)['chapters'][9]
    career = next(r for r in special['requirements'] if '任职' in r['question'])
    assert career['candidates'] and career['state'] == 'partial'
    assert next(r for r in special['requirements'] if '持股' in r['question'])['state'] == 'missing'


def test_analysis_selection_uses_server_fact_and_exact_support_quote():
    p = package()
    f = p['facts'][0]
    answer = {'claims': [{'evidence_ids': [f['evidence_id']], 'analysis': '该来源披露了董事职责，实际履职情况仍需核验。',
                         'support_quotes': [{'evidence_id': f['evidence_id'], 'quote': f['fact']}]}]}
    accepted, errors = validate_model_claims(json.dumps(answer, ensure_ascii=False), p)
    assert not errors and accepted[0]['statement'] == f['fact']
    assert accepted[0]['analysis']
    answer['claims'][0]['support_quotes'][0]['quote'] = '另一公司发生严重舞弊问题。'
    accepted, errors = validate_model_claims(json.dumps(answer, ensure_ascii=False), p)
    assert 'missing_or_invalid_analysis_support_quote' in errors
    assert not accepted[0]['analysis']


@pytest.mark.parametrize('bad_id', ['E-NONEXISTENT', {}, ['E-NONEXISTENT']])
def test_unknown_or_malformed_evidence_reference_is_rejected(bad_id):
    accepted, errors = validate_model_claims(json.dumps({'claims': [{'evidence_ids': [bad_id], 'analysis': '无任何诉讼。'}]}), package())
    assert not accepted and errors == ['unknown_or_missing_evidence_id']


def test_new_protocol_does_not_allow_injected_statement_or_unfounded_numbers():
    p = package()
    f = p['facts'][0]
    row = {'evidence_ids': [f['evidence_id']], 'analysis': '诚信优秀，2035年没有任何风险。',
           'support_quotes': [{'evidence_id': f['evidence_id'], 'quote': f['fact']}]}
    accepted, errors = validate_model_claims(json.dumps({'claims': [row]}), p)
    assert not accepted[0]['analysis'] and 'unsupported_analysis' in errors
    row.update(statement='另一人物在2035年融资900亿元。', analysis='')
    assert validate_model_claims(json.dumps({'claims': [row]}), p)[1] == ['statement_not_in_cited_fact']


def test_indirect_company_record_is_never_personal_analysis_even_with_quote():
    data = fact('恒川软件有限公司于2021年发生合同争议。',
                person_affiliation={'person_name': '林知远', 'affiliation_name': '恒川软件有限公司'})
    p = build_packages({'facts': [data]}, '林知远', PERSON_REPORT_OUTLINE)['chapters'][12]
    p['writing_contract'] = 'evidence_selection_v1'
    f = p['facts'][0]
    answer = {'claims': [{'evidence_ids': [f['evidence_id']], 'analysis': '体现该人物的信用问题。',
                          'support_quotes': [{'evidence_id': f['evidence_id'], 'quote': f['fact']}]}]}
    accepted, errors = validate_model_claims(json.dumps(answer), p)
    assert not accepted[0]['analysis'] and 'indirect_or_conflicting_analysis' in errors


def test_report_keeps_facts_and_unanswered_questions_when_model_abstains():
    value = intake()
    p = SimpleNamespace(target_name='林知远', target_type='person', title='合成人物核验', sources=[], person_research_intake=value)
    calls = []
    def invoke(role, prompt, trace):
        if '材料采用诊断' in role:
            from person_model_fixture import material_response
            return material_response(json.loads(prompt.splitlines()[-1]))
        calls.append(prompt)
        assert '不要返回statement' in prompt
        return '{"claims":[]}'
    text = generate_person_report(p, json.dumps({'facts': [fact()]}), '{}', PERSON_REPORT_OUTLINE, invoke, lambda *a, **kw: None)
    sections = split_sections(text)
    assert len(sections) == 15 and calls
    assert '林知远于2021年在恒川软件有限公司任职' in sections[2]
    assert '同一原文已列第2章' in sections[10]
    assert cited_ids(sections[10]) & cited_ids(sections[2])
    assert '委托问题逐项核查' in sections[10] and '持股及权益' in sections[10]
    assert '委托问题“持股及权益”' in sections[15]
    assert p.person_delivery_diagnostic['section_diagnostics'][10]['accepted_analysis_count'] == 0
    assert p.person_delivery_diagnostic['errors'] == []
