"""Round-seven regressions from small synthetic examples, not private snapshots."""
from types import SimpleNamespace

import pytest

from industry_research import (annotate_fact, extract_industry_source_facts, local_forecast_attribute,
    claim_semantic_issues, numeric_mentions, risk_fact_text, balanced_risk_facts, summary_length)
from report_agents.industry_report_agent import IndustryReportAgent

SCOPE = {'industry_name':'机器人','geography':'中国大陆','as_of_date':'2026-10-15','capital_market':'none'}


def fact(eid='E-123456789ABC', **updates):
    return {'evidence_id':eid,'module':'市场规模与增长','fact':'2024年中国机器人市场规模为216.3亿元，预计次年将继续增长。',
        'evidence_quote':'2024年中国机器人市场规模为216.3亿元，预计次年将继续增长。',
        'source_url':'https://stats.example/robot','claim_type':'fact','scope_match':'in_scope',
        'evidence_scope':'industry_level', 'quality_score':80,
        'provenance':{'locator':{'status':'verified'}},
        'numeric_context':{'metric':'市场规模','value':'216.3','unit':'亿元','period':'2024',
            'geography':'中国大陆','definition':'中国机器人市场规模','is_forecast':True},
        'numeric_validation':{'passed':True}, **updates}


@pytest.mark.parametrize('quote,expected', [
    ('2024年中国机器人市场规模为216.3亿元，预计次年增长。', False),
    ('2024年中国机器人市场规模已达到216.3亿元，预计到2030年翻番。', False),
    ('预计2026年中国机器人市场规模达到216.3亿元。', True),
    ('中国机器人市场规模216.3亿元（预测值）。', True),
    ('中国机器人市场规模目标达到216.3亿元。', True),
    ('据机构预测，中国机器人市场规模将达到216.3亿元。', True),
])
def test_prediction_labels_belong_to_the_paired_value(quote, expected):
    assert local_forecast_attribute(quote,'市场规模',216.3,'亿元') is expected


def test_conflicting_pairs_and_unpaired_values_do_not_get_guessed():
    assert local_forecast_attribute('市场规模216.3亿元，预计市场规模216.3亿元','市场规模',216.3,'亿元') is None
    assert local_forecast_attribute('市场规模100亿元，盈利216.3亿元','市场规模',216.3,'亿元') is None


def test_rule_extraction_does_not_apply_a_later_forecast_to_history():
    src=SimpleNamespace(content=fact()['fact'],url='https://stats.example/robot',title='机器人统计',
        source_type='government',source_metadata={'module':'市场规模与增长'},credibility_score=90)
    cards=extract_industry_source_facts([src],SCOPE)
    assert cards[0]['numeric_context']['is_forecast'] is False


def test_grounded_model_flag_is_corrected_before_identity_without_mutating_input():
    original=fact(cleaning_method='llm',evidence_quote_verified=True)
    checked=annotate_fact(original,SCOPE)
    assert checked['numeric_context']['is_forecast'] is False
    assert original['numeric_context']['is_forecast'] is True
    forecast=fact(cleaning_method='llm',evidence_quote_verified=True,
                  evidence_quote='预计2026年中国机器人市场规模达到216.3亿元。')
    assert annotate_fact(forecast,SCOPE)['numeric_context']['is_forecast'] is True


@pytest.mark.parametrize('index',[1,4,11,14])
def test_every_fallback_keeps_forecast_label_local_and_only_one_authorized_metric(index):
    f=fact(fact='市场规模216.3亿元，同比增长32.5%，未来预计增长。')
    section=IndustryReportAgent()._fallback_section({'facts':[f]},index,'章节')
    assert '预测/目标值' in section
    assert numeric_mentions(section)==['216.3亿元']
    assert not claim_semantic_issues(section,[f])
    if index==1:assert summary_length(section)<=600


def test_heat_and_next_steps_do_not_reuse_the_market_summary():
    f=fact()
    agent=IndustryReportAgent()
    heat=agent._fallback_section({'facts':[f]},5,'行业热度形成')
    outlook=agent._fallback_section({'facts':[f]},11,'前景展望')
    next_steps=agent._fallback_section({'facts':[f]},16,'后续研究点')
    assert '热度成因' in heat and '216.3' not in heat
    assert '情景对照' in outlook and '预测/目标值' in outlook
    assert '核对市场规模' in next_steps and '216.3' not in next_steps
    assert f['evidence_id'] in next_steps


def test_fallback_rechecks_source_claims_and_keeps_unsafe_prose_out():
    f=fact(numeric_validation={},numeric_context={},fact='多源数据一致表明行业已经成熟。')
    section=IndustryReportAgent()._fallback_section({'facts':[f]},4,'章节')
    assert '多源数据一致' not in section and '需复核' in section
    assert f['evidence_id'] in section
    assert not claim_semantic_issues(section,[f])


def test_fallback_keeps_distinct_metrics_from_same_raw_quote():
    quote='机器人市场规模216.3亿元，增长率5%。'
    a=fact(fact=quote,evidence_quote=quote);b=fact('E-AAAAAAAAAAAA',fact=quote,evidence_quote=quote,
        numeric_context={**a['numeric_context'],'metric':'增长率','value':'5','unit':'%'})
    section=IndustryReportAgent()._fallback_section({'facts':[a,b]},4,'章节')
    assert a['evidence_id'] in section and b['evidence_id'] in section


def test_long_summary_drops_whole_cards_instead_of_cutting_value_or_prediction():
    cards=[fact(f'E-{i:012X}',numeric_context={**fact()['numeric_context'],'definition':'机器人行业口径'*20}) for i in range(10)]
    section=IndustryReportAgent()._fallback_section({'facts':cards},1,'摘要')
    assert summary_length(section)<=600
    assert not claim_semantic_issues(section,cards)


def test_scoring_fact_text_itself_passes_forecast_clause_check():
    f=fact()
    assert not claim_semantic_issues(risk_fact_text(f),[f])


@pytest.mark.parametrize('prefix',['不构成','不代表','不等于','并非'])
def test_repair_abstention_is_not_misread_as_positive_corroboration(prefix):
    assert not claim_semantic_issues(prefix+'多源印证，证据仍不足。',[fact()])


def test_risk_selection_uses_actual_growth_and_different_documents_before_duplicates():
    first=fact()
    copies=[fact(f'E-{i:012X}') for i in range(1,6)]
    growth=fact('E-AAAAAAAAAAAA',source_url='https://survey.example/growth',fact='中国机器人行业同比增长率为5%。',
        numeric_context={**first['numeric_context'],'metric':'同比增长率','value':'5','unit':'%','is_forecast':False})
    other=fact('E-BBBBBBBBBBBB',source_url='https://other.example/size',
        numeric_context={**first['numeric_context'],'is_forecast':False})
    result=balanced_risk_facts([first,*copies,growth,other],3)
    assert growth in result and other in result


def test_quarantined_fact_never_reenters_fallback():
    f=fact(eligible_for_report=False)
    assert f['evidence_id'] not in IndustryReportAgent()._fallback_section({'facts':[f]},4,'章节')
