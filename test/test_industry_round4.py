import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from industry_research import (annotate_fact, number_key, risk_fact_text, normalize_risk,
    risk_fact_applicable, append_evidence_index, mark_unverified_numbers, summary_length,
    bounded_package, company_filing_source)
from report_agents.industry_report_agent import IndustryReportAgent
from research_workflow import ResearchWorkflow


SCOPE = {'industry_name': '人工智能', 'segments': [], 'geography': '中国大陆',
         'as_of_date': '2026-10-14', 'capital_market': 'none'}
QUOTE = ('同一调查还显示，2025年用于人工智能训练和推理的数据总量达199.48 EB，同比增长42.86%；'
         '其中推理数据量101.34 EB，首次超过训练数据量。')
WRONG = '2025年中国人工智能推理数据量为101.34 EB，首次超过训练数据量，同比增长42.86%。'


def numeric_card(value='101.34', unit='EB', metric='人工智能推理数据量'):
    return annotate_fact({'fact': WRONG, 'evidence_quote': QUOTE, 'evidence_quote_verified': True,
        'cleaning_method': 'llm', 'source_url': 'https://example.org/industry.pdf',
        'source_title': '人工智能行业报告', 'module': '技术路线对比', 'claim_type': 'fact',
        'scope_match': 'in_scope', 'evidence_scope': 'industry_level',
        'numeric_context': {'metric': metric, 'value': value, 'unit': unit,
            'geography': '中国大陆', 'period': '2025', 'definition': '用于人工智能推理的数据量',
            'is_forecast': False}}, SCOPE)


def qualitative(eid='E-0123456789AB', text='人工智能行业竞争集中度较高。', module='竞争格局与代表企业'):
    return {'evidence_id': eid, 'fact': text, 'module': module,
            'evidence_scope': 'industry_level', 'scope_match': 'in_scope', 'source_url': 'https://example.org/a'}


def test_wrong_growth_paraphrase_is_replaced_by_native_quote_and_metric_only_score_text():
    card = numeric_card()
    assert card['fact'] == QUOTE and card['original_model_fact'] == WRONG
    assert card['numeric_validation']['passed']
    assert '101.34EB' in risk_fact_text(card)
    assert '42.86' not in risk_fact_text(card) and '199.48' not in risk_fact_text(card)


@pytest.mark.parametrize('value,metric', [('199.48', '人工智能推理数据量'),
                                        ('101.34', '人工智能数据总量')])
def test_same_quote_cannot_authorize_swapped_metric_and_value(value, metric):
    card = numeric_card(value=value, metric=metric)
    assert not card['numeric_validation']['passed']
    assert 'metric_value_not_paired' in card['numeric_validation']['missing_fields']
    assert card['eligible_for_risk_scoring'] is False


def test_distinct_metrics_using_same_native_quote_keep_distinct_stable_ids():
    inference = numeric_card()
    total = numeric_card(value='199.48', metric='人工智能训练和推理的数据总量')
    assert total['numeric_validation']['passed']
    assert inference['evidence_id'] != total['evidence_id']
    assert annotate_fact(inference, SCOPE)['evidence_id'] == inference['evidence_id']
    assert len(ResearchWorkflow.__new__(ResearchWorkflow)._dedupe_facts([inference,total]))==2


@pytest.mark.parametrize('a,b', [('1 EB', '1000pb'), ('1 EFLOPS','1000 PFLOPS'),
                               ('1000 GB','1 TB'), ('1万美元','10000美元')])
def test_units_compare_equivalent_values_without_currency_or_metric_mix(a, b):
    assert number_key(a) == number_key(b)
    assert number_key(a)[0] > Decimal(0)


def test_unsupported_numeric_unit_fails_closed():
    card = numeric_card(unit='倍')
    assert 'unsupported_numeric_unit' in card['numeric_validation']['missing_fields']


def test_original_model_prose_is_diagnostic_only_and_never_writer_evidence():
    card=numeric_card()
    sent=json.loads(bounded_package({'facts':[card]}))['facts'][0]
    assert sent['fact']==QUOTE and 'original_model_fact' not in sent


def test_industry_annual_report_is_not_a_company_filing():
    assert not company_filing_source(SimpleNamespace(title='人工智能产业年度报告',source_type='government'))
    assert company_filing_source(SimpleNamespace(title='某某科技股份有限公司2019年度报告',source_type='website'))


def test_nonmetric_growth_in_risk_reason_cannot_receive_score():
    card = numeric_card()
    result = normalize_risk({'dimensions': [{'name':'技术迭代与替代风险', 'score':58,
        'evidence_ids':[card['evidence_id']], 'reason': WRONG}]}, [card], SCOPE)
    row = next(d for d in result['dimensions'] if d['name']=='技术迭代与替代风险')
    assert row['score'] is None and row['unknown_cause']=='unverified_reason_numbers'


def test_index_uses_native_quote_even_for_legacy_model_card():
    card = numeric_card(); card['fact'] = WRONG
    report = f'## 1. 技术路线对比\n推理量101.34 EB [{card["evidence_id"]}]'
    result, _ = append_evidence_index(report, {'facts':[card]}, [('技术路线对比', [])], {1:{'facts':[card]}})
    assert WRONG not in result and QUOTE in result


def test_lowercase_eb_also_requires_metric_validation_in_chapter():
    card = numeric_card()
    text = f'数据量199.48 eb [{card["evidence_id"]}]'
    assert '待核验' in mark_unverified_numbers(text, [card])


def test_company_filing_cannot_inherit_macro_query_scope():
    src = SimpleNamespace(id=1, url='https://example.org/a', title='某科技股份有限公司年度报告',
        source_type='filing', source_metadata={'evidence_scope':'industry_level', 'module':'竞争格局与代表企业'},
        credibility_score=80)
    w = ResearchWorkflow.__new__(ResearchWorkflow)
    w._active_industry_sources = lambda p: [src]
    w._source_grade = lambda *a: 'B'
    p = SimpleNamespace(id=68, target_type='industry', target_name='人工智能', industry_scope=SCOPE)
    result = w._annotate_evidence_facts(p, [qualitative()])[0]
    assert result['evidence_scope']=='representative_company'
    assert result['eligible_for_risk_scoring'] is False


@pytest.mark.parametrize('text', ['人工智能广东核心产业260亿元。', '人工智能政策拟培育生态主导型企业。'])
def test_size_and_policy_target_are_not_competition_measurements(text):
    assert not risk_fact_applicable(qualitative(text=text), '竞争格局与集中度风险')


@pytest.mark.parametrize('supplied,cause', [([], 'missing_model_citations'),
    (['E-AAAAAAAAAAAA'], 'invalid_citations')])
def test_unknown_distinguishes_missing_model_ids_from_absent_evidence(supplied, cause):
    result = normalize_risk({'dimensions':[{'name':'竞争格局与集中度风险', 'score':40,
        'evidence_ids':supplied}]}, [qualitative()], SCOPE)
    row = next(d for d in result['dimensions'] if d['name']=='竞争格局与集中度风险')
    assert row['unknown_cause']==cause and row['candidate_evidence_count']==1


def test_reason_cannot_reference_other_dimensions_or_ids_outside_score():
    fact = qualitative()
    result = normalize_risk({'dimensions':[{'name':'竞争格局与集中度风险', 'score':40,
        'evidence_ids':[fact['evidence_id']], 'reason':'见E-AAAAAAAAAAAA'}]}, [fact], SCOPE)
    row = next(d for d in result['dimensions'] if d['name']=='竞争格局与集中度风险')
    assert row['unknown_cause']=='invalid_reason_citations' and row['score'] is None


def test_budgeted_risk_payload_maps_only_retained_applicable_ids():
    w = ResearchWorkflow.__new__(ResearchWorkflow)
    facts = [qualitative(eid=f'E-{i:012X}', text='人工智能行业竞争集中度较高。'*150) for i in range(70)]
    facts += [qualitative(eid='E-AAAAAAAAAAAA', text='人工智能广东产业规模260亿元。')]
    encoded = w._risk_evidence_payload(json.dumps({'facts':facts, 'industry_scope':SCOPE}), 'industry')
    payload = json.loads(encoded)
    ids = {f['evidence_id'] for f in payload['facts']}
    assert len(encoded)<=28000 and 0<len(ids)<70
    assert set(payload['dimension_evidence_ids']['竞争格局与集中度风险'])==ids
    assert 'E-AAAAAAAAAAAA' not in ids
    assert '资本热度与估值风险' not in payload['dimension_evidence_ids']


def test_industry_risk_schema_requires_ids_for_every_enabled_dimension():
    w = ResearchWorkflow.__new__(ResearchWorkflow); prompts=[]
    w._invoke = lambda role,prompt,**kw: (prompts.append(prompt) or '{"dimensions":[]}')
    p=SimpleNamespace(title='测试', target_name='人工智能', industry='人工智能', target_type='industry', industry_scope=SCOPE)
    w.assess_risk(p, '{"facts":[]}')
    schema=json.loads(prompts[0].split('请只输出 JSON，结构为：')[1])
    assert len(schema['dimensions'])==6
    assert all('evidence_ids' in d for d in schema['dimensions'])
    assert all(d['name']!='资本热度与估值风险' for d in schema['dimensions'])


def test_fenced_summary_is_accepted_without_model_repair():
    agent=IndustryReportAgent(); f=qualitative(); calls=[]
    result=agent._validate_section(f'```markdown\n# 1. 摘要\n行业竞争 [{f["evidence_id"]}]\n```',
        {'facts':[f]},1,'摘要', lambda *a: calls.append(a),lambda *a,**kw: None,None,[])
    assert result.startswith('## 1. 摘要') and not calls


def test_degradation_records_short_repair_invalid_citation_instead_of_length():
    agent=IndustryReportAgent(); f=qualitative(); notes=[]
    result=agent._validate_section('## 1. 摘要\n'+'行业判断。'*150+f['evidence_id'],{'facts':[f]},1,'摘要',
        lambda *a:'## 1. 摘要\n短摘要[E-AAAAAAAAAAAA]',lambda *a,**kw: None,None,notes)
    assert notes[0]['initial_validation_reasons']==['summary_too_long']
    assert 'invalid_citation' in notes[0]['repair_validation_reasons']
    assert 'summary_too_long' not in notes[0]['repair_validation_reasons']
    assert summary_length(result)<=600


def test_repair_cannot_cite_cards_dropped_by_its_own_budget():
    agent=IndustryReportAgent(); notes=[]
    facts=[qualitative(eid=f'E-{i:012X}', text='人工智能竞争事实。'*100) for i in range(40)]
    prompts=[]
    def repair(role,prompt,trace):
        prompts.append(prompt)
        package=json.loads(prompt.split('\n证据：')[1].split('\n待修复章节：')[0])
        retained={f['evidence_id'] for f in package['facts']}
        dropped=next(f['evidence_id'] for f in facts if f['evidence_id'] not in retained)
        return f'## 6. 竞争格局\n行业判断 [{dropped}]'
    result=agent._validate_section('目录错误',{'facts':facts},6,'竞争格局',repair,
        lambda *a,**kw: None,None,notes)
    assert len(prompts)==1 and 'invalid_citation' in notes[0]['repair_validation_reasons']
    assert '行业判断' not in result
