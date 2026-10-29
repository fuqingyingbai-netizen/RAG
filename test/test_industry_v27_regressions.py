"""Synthetic report-v27 regressions; no external services or historical labels."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from industry_analysis_repair import repair_analyses
from industry_briefing import synthesis_package, reuse_chapter_judgments
from industry_delivery import finalize_synthesis, verification_tasks
from industry_fact_contracts import attach_contract, chapter_coverage, normalize_analysis, render_plan, validate_analyses
from industry_reasoning import review_packet, validate_reviews
from industry_research import claim_semantic_issues
from report_agents.industry_report_agent import IndustryReportAgent
from test_industry_analysis_repair import run_repair, response as repair_response
from test_industry_reasoning import review_claim, verdict, response as review_response
from test_industry_template_analysis import fact, chain, claim, EID, SCOPE


def numeric(value=120,year=2030,*,eid=EID,forecast=False,comparator='='):
    lead='预计' if forecast else ''
    symbol={'>':'超过','>=':'不少于','<':'低于','<=':'不超过','=':''}[comparator]
    quote=f'{lead}{year}年中国机器人核心产业规模为{symbol}{value}亿元。'
    f,body=fact(quote,evidence_id=eid,module='市场规模与增长',
        numeric_context={'metric':'核心产业规模','value':value,'unit':'亿元','period':str(year),
            'geography':'中国大陆','definition':'中国机器人核心产业规模','is_forecast':forecast,
            'comparator':comparator},numeric_validation={'passed':True})
    return attach_contract(f,SCOPE,body)


def test_repair_response_can_omit_premises_as_promised_without_weakening_quotes():
    def invoke(role,prompt,trace):
        result=json.loads(repair_response(prompt))
        result['repairs'][0]['analysis'].pop('premises')
        return json.dumps(result)
    (accepted,rejected,diagnostic),passed,_=run_repair(invoke)
    assert not rejected and diagnostic['repaired']==[1]
    assert accepted==passed  # Duplicate content is omitted; the passed paragraph is intact.
    def wrong_quote(role,prompt,trace):
        result=json.loads(repair_response(prompt))
        result['repairs'][0]['analysis']['premises'][0]['quote']='伪造原文。'
        return json.dumps(result)
    (_,rejected,diagnostic),_,_=run_repair(wrong_quote)
    assert rejected and not diagnostic['repaired']


def test_missing_repair_reasoning_records_a_safe_specific_validation_code():
    def invoke(role,prompt,trace):
        result=json.loads(repair_response(prompt))
        result['repairs'][0]['analysis'].pop('reasoning')
        return json.dumps(result)
    (_,rejected,diagnostic),_,_=run_repair(invoke)
    assert rejected and diagnostic['validation_code']=='missing_repair_reasoning'


@pytest.mark.parametrize('text',[
    '来源预计2035年规模为500亿元；不能把500亿元当作已实现的市场规模。',
    '不得将500亿元视为当前规模，只可作为待核对的来源预测。',
])
def test_a_forecast_in_an_explicit_denied_comparison_is_not_an_actual_claim(text):
    f=numeric(500,2035,forecast=True)
    assert not any(x['code']=='forecast_presented_as_actual' for x in claim_semantic_issues(text,[f]))


@pytest.mark.parametrize('text',[
    '该市场已经达到500亿元。',
    '不能把500亿元当作统一口径，但该市场已达到500亿元。',
    '不能把500亿元当作统一口径且该市场已实现500亿元。',
    '两项数据不能比较；该市场规模为500亿元。',
])
def test_denial_cannot_hide_a_later_affirmative_forecast_misstatement(text):
    f=numeric(500,2035,forecast=True)
    assert any(x['code']=='forecast_presented_as_actual' for x in claim_semantic_issues(text,[f]))


@pytest.mark.parametrize('text',[
    '这两个规模下限可支持规模水平上升的方向性判断。',
    '无法计算CAGR，但规模水平上升。',
    '两项记录证明规模扩大。',
])
def test_two_lower_bounds_do_not_order_the_underlying_market_levels(text):
    fs=[numeric(90,2029,comparator='>'),numeric(120,2030,eid='E-222222222222',comparator='>')]
    assert any(x['code']=='bounded_levels_as_growth' for x in claim_semantic_issues(text,fs))


@pytest.mark.parametrize('text',[
    '两个下限不能证明规模水平上升。',
    '各期下限分别列示，不从下限变化认定实际增长。',
])
def test_a_correct_bound_limitation_is_retained(text):
    fs=[numeric(90,2029,comparator='>'),numeric(120,2030,eid='E-222222222222',comparator='>')]
    assert not any(x['code']=='bounded_levels_as_growth' for x in claim_semantic_issues(text,fs))


def test_exact_observations_are_not_rejected_by_the_lower_bound_guard():
    fs=[numeric(90,2029),numeric(120,2030,eid='E-222222222222')]
    assert not any(x['code']=='bounded_levels_as_growth' for x in claim_semantic_issues('两个精确规模点表明规模水平上升。',fs))


def test_policy_promotion_purpose_can_supply_local_policy_context_but_not_business_results():
    quote='第一条为了促进机器人产业高质量发展，结合本市实际制定本条例。'
    f,body=fact(quote,module='政策与监管',source_title='某市机器人产业促进条例',source_type='government',source_url='https://city.gov.cn/policy')
    f=attach_contract(f,SCOPE,body)
    rows={q['question']:q for q in chapter_coverage({'facts':[f]},3,[EID])}
    assert EID in rows['国家规划与地方支持']['evidence_ids']
    assert EID not in rows['实际执行材料']['evidence_ids']
    assert f['fact_contract']['risk_admitted'] is False


def test_historical_levels_are_comparison_background_not_verified_growth_series():
    f=numeric(90,2029,comparator='>')
    rows={q['question']:q for q in chapter_coverage({'facts':[f]},4,[EID])}
    q=rows['同口径增长趋势']
    assert not q['evidence_ids'] and q['background_evidence_ids']==[EID]
    assert rows['近三至五年历史序列与CAGR']['status']!='verified'


def test_test_entry_is_maturity_background_while_demand_opinion_is_not():
    f,body=fact('机器人专用加速器开始进入云服务商测试环境。',module='技术路线对比')
    f=attach_contract(f,SCOPE,body)
    q=next(q for q in chapter_coverage({'facts':[f]},7,[EID]) if q['question']=='落地难度与迭代成熟度')
    assert q['background_evidence_ids']==[EID] and not q['evidence_ids']
    assert q['status']=='background_only'


def test_citation_subject_is_preserved_before_recording_verb():
    f=chain()
    original=claim(EID+'记录：机器人产业链存在分层关系，所引材料仅说明环节分工，缺少成本与利润资料，不能据此评价行业整体盈利。')
    checked,_=normalize_analysis(original,{EID:f})
    assert checked['text'].startswith('所引材料记录：') and f==chain()


def test_missing_support_results_keep_specific_diagnostics_and_never_become_supported():
    f=chain(); c=review_claim(f); packet,_=review_packet([c],[f])
    cases=[('not JSON','invalid_review_json'),
        (json.dumps({'packet_fingerprint':'stale','reviews':[]}),'stale_packet_fingerprint'),
        (review_response(packet,[]),'missing_review_result'),
        (review_response(packet,[verdict(c,f),verdict(c,f)]),'duplicate_claim_id'),
        (review_response(packet,[verdict(c,f,quotes=[{'evidence_id':EID,'quote':'这是一条足够长但没有出现在来源里的伪造引文。'}])]),'invalid_review_quote')]
    for raw,code in cases:
        result=validate_reviews(raw,packet)[c['claim_id']]
        assert result['status']=='not_evaluated' and result['diagnostic_code']==code
        assert not result['entailment_proven']


def test_quality_diagnostic_explains_review_failure_without_reprinting_claims():
    from industry_reasoning import reasoning_markdown
    f=chain(); c=review_claim(f); packet,_=review_packet([c],[f])
    status=validate_reviews('invalid response',packet)[c['claim_id']]
    project=SimpleNamespace(industry_statement_plans={2:{'analysis_claims':[{**c,'support_review':status}]}})
    text=reasoning_markdown(project)
    assert '支持复核未完成的原因' in text and '不是有效JSON' in text
    assert c['text'] not in text


def test_synthesis_density_uses_its_own_short_judgment_contract():
    from industry_reader import writing_profile
    profile=writing_profile({'facts':[numeric()]},14)
    assert profile['target_analysis_characters']==[240,640]
    assert profile['suggested_paragraphs']=='3至4'


def test_support_failure_tasks_keep_distinct_dimension_criteria_and_audit_reason():
    names=['政策与监管风险','竞争格局与集中度风险','商业化与盈利模式风险','技术迭代与替代风险','数据口径与证据可靠性风险']
    f=chain(); risk={'dimensions':[{'name':n,'score':None,'level':'unknown','unknown_cause':'claim_support_rejected',
        'validation_diagnostic':{'original_score':45,'admissible_evidence_ids':[EID],
            'support_review':{'status':'partial','reason':'只支持部分原文，推理范围需要收窄。'}}} for n in names]}
    before=deepcopy(risk)
    tasks=verification_tasks({'facts':[f]},risk,[],SCOPE)
    assert len(tasks)==len(names) and len({t['completion'] for t in tasks})==len(names)
    assert all(t['support_review_diagnostic']['status']=='partial' for t in tasks)
    assert '义务' in tasks[0]['completion'] and '集中度' in tasks[1]['completion']
    assert risk==before and all(d['score'] is None for d in risk['dimensions'])


def test_synthesis_reserves_complete_existing_judgment_under_the_actual_writer_budget():
    market=numeric(120,2030,eid='E-333333333333')
    a,body=fact('机器人云端技术路线追求吞吐量，适用于集中部署场景。',module='技术路线对比')
    a=attach_contract(a,SCOPE,body)
    b,body=fact('机器人端侧技术路线采用低功耗架构，服务于本地部署场景。',evidence_id='E-222222222222',module='技术路线对比')
    b=attach_contract(b,SCOPE,body)
    for f in (market,a,b): f['source_title']='机器人研究'+'背景标题'*1100
    package={'facts':[a,b],'industry_scope':SCOPE}
    text='云端与端侧材料列出的优化方向不同，可以按部署位置和业务条件分别比较。现有材料并没有提供同条件测试的性能与成本，因此不能据此认定某一种路线在所有场景都占优。'
    cs,errors=validate_analyses([claim(text,question='路线及适用场景',evidence_ids=[EID,b['evidence_id']],claim_kind='comparison')],package,7,[EID,b['evidence_id']])
    assert cs and not errors
    plans={7:{'analysis_claims':cs}}
    sections={4:render_plan({'facts':[market]},4,'市场规模',[market['evidence_id']]),
        7:render_plan(package,7,'技术路线对比',[EID,b['evidence_id']],cs)}
    packages={4:{'facts':[market]},7:package}
    chosen=synthesis_package(packages,sections,SCOPE,plans)
    # Full internal archive titles are not sent to the writer. Charge the
    # complete actual prompt while keeping every source and premise in audit.
    from industry_fact_contracts import plan_prompt
    assert len(plan_prompt(chosen,14))<=14000 and len(chosen['facts'])<=8
    assert '背景标题'*20 not in plan_prompt(chosen,14)
    assert {EID,b['evidence_id']}<={f['evidence_id'] for f in chosen['facts']}
    assert reuse_chapter_judgments(plans,chosen)[0]['text']==text
    project=SimpleNamespace(industry_statement_plans=plans,industry_report_degradations=[])
    calls=[]
    def timeout(*args):
        calls.append(args); raise TimeoutError('synthetic timeout')
    IndustryReportAgent()._write_synthesis(project,{'facts':[market,a,b]},packages,sections,SCOPE,timeout,lambda *a,**k:None,None)
    p=project.industry_statement_plans[14]
    assert len(calls)==1 and p['analysis_method']=='chapter_analysis_reuse'
    assert p['reused_existing_analyses']
    assert '已复用' in project.industry_report_degradations[-1]['message']
    assert p['error_type']=='TimeoutError' and p['analysis_claims'][0]['reused_from_chapter']==7
    report='## 1. 摘要\n\n原摘要。\n\n'+'\n\n'.join(sections.values())+'\n\n## 16. 后续研究点\n待复核。'
    result,_=finalize_synthesis(report,{'facts':[market,a,b]},{},[],SCOPE,project.industry_statement_plans)
    assert result.count(text)>=2 and '阶段性综合结论' in result
    assert a['provenance']['locator']['quote'] in a['evidence_quote']
