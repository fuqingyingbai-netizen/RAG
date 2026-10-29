"""Cross-chapter summaries follow current judgments, including after a retry."""
from copy import deepcopy
import json

from industry_briefing import (bind_plan, chapter_judgments, current_conclusions,
    reuse_chapter_judgments, synthesis_package, synthesis_source_issues)
from industry_fact_contracts import attach_contract, render_plan, validate_analyses, plan_prompt
from test_industry_briefing import card, SCOPE, EID, TEXT


PRICING_EID = 'E-B99FEA3B0462'
SOURCE = '取而代之的是“基础订阅+按Token消耗收费”或“AI增值模块独立收费”的全新商业模型。'
CURRENT = ('材料仅提出“基础订阅+按Token消耗收费”或“AI增值模块独立收费”可作为商业模型方向，'
           '未说明任何主体已实际采用、向谁收费或实际收费水平。'
           '它可用于讨论收费方式的设计选项，但不能据此判断收入是否已经取得。')
OLD = '商业化材料显示计费转向基础订阅加Token消耗或增值模块独立收费。'


def pricing_setup():
    scope = {**SCOPE, 'industry_name':'人工智能', 'segments':['人工智能']}
    fact = card(SOURCE, PRICING_EID, module='商业模式与盈利逻辑', industry_name='人工智能')
    fact = attach_contract(fact, scope, SOURCE)
    package = {'facts':[fact], 'industry_scope':scope}
    claim = {'question':'实际收费与付费客户', 'text':CURRENT,
        'evidence_ids':[PRICING_EID], 'claim_kind':'observation',
        'reasoning':'区分来源描述的模式与实际采用披露，不将模式存在升级为经营结果。'}
    claims, errors = validate_analyses([claim],package,10,[PRICING_EID])
    assert claims and not errors, errors
    plans = {10:{'analysis_claims':claims}}
    section = render_plan(package,10,'投资机会',[PRICING_EID],claims)
    selected = synthesis_package({10:package},{10:section},scope,plans)
    assert selected['source_judgments']
    return scope, fact, package, plans, section, selected


def test_v36_mode_direction_cannot_become_actual_adoption_in_the_summary():
    scope, fact, package, plans, section, selected = pricing_setup()
    old = {'question':'竞争与商业化判断','text':OLD,
        'evidence_ids':[PRICING_EID],'claim_kind':'observation'}
    valid, errors = validate_analyses([old],selected,14,[PRICING_EID])
    assert valid and not errors  # The old card-only check accepts this fluent upgrade.
    assert synthesis_source_issues(valid[0],selected)==['synthesis_statement_nature_changed']
    plan = {'evidence_ids':[PRICING_EID],'analysis_claims':valid}
    bind_plan(plan,selected)
    assert plan['analysis_claims'] is valid
    assert CURRENT in [c['text'] for c in valid] and OLD not in [c['text'] for c in valid]
    assert plan['analysis_rejections'][0]['issues']==['synthesis_statement_nature_changed']
    assert plan['synthesis_alignment']['revised_claims']==1
    assert 'pricing_design_not_actual_adoption' in json.dumps(selected['completed_chapter_judgments'])
    assert '不能绕过当前正文判断重新升级事实' in plan_prompt(selected,14)


def test_bounded_business_implication_is_still_allowed():
    *_, selected = pricing_setup()
    claim = {'text':'订阅与按调用量计费提供了不同的定价设计选项，可据客户的负载波动选择收费结构。',
        'evidence_ids':[PRICING_EID]}
    assert not synthesis_source_issues(claim, selected)


def test_valid_positive_adoption_is_not_silenced_without_an_opposite_chapter_judgment():
    *_, selected = pricing_setup()
    selected['source_judgments'][0]['text']='所列企业已采用订阅和按调用量收费，客户按实际使用量支付费用。'
    assert not synthesis_source_issues({'text':OLD,'evidence_ids':[PRICING_EID]},selected)


def test_unrelated_subject_does_not_inherit_a_pricing_constraint():
    *_, selected = pricing_setup()
    assert not synthesis_source_issues({'text':'算力服务已实现按请求量自动扩容，适用于负载波动的云端场景。',
        'evidence_ids':['E-111111111111']},selected)


def test_reexport_does_not_reuse_a_replaced_chapter_judgment_on_the_same_eid():
    scope, fact, package, plans, section, selected = pricing_setup()
    source = plans[10]['analysis_claims'][0]
    kept = reuse_chapter_judgments(plans, selected)
    plan = {'evidence_ids':[PRICING_EID],'analysis_claims':kept}
    bind_plan(plan, selected)
    plans[14]=plan
    report = '## 1. 摘要\n\n旧摘要。\n\n'+section+'\n\n## 14. 综合评估\n\n旧综合。'
    assert current_conclusions(report,package,plans,scope)
    amended = {k:v for k,v in source.items() if k in {'question','text','conclusion','evidence_ids','premises','claim_kind','reasoning'}}
    amended['text']='订阅和按调用量收费是两种不同的定价设计方向，企业可按自身应用负载选择适合的收费结构，不能据此确认实际采用。'
    valid, errors = validate_analyses([amended],package,10,[PRICING_EID])
    assert valid and not errors
    plans[10]['analysis_claims']=valid
    amended_section = render_plan(package,10,'投资机会',[PRICING_EID],valid)
    report = report.replace(section,amended_section)
    result = current_conclusions(report,package,plans,scope)
    assert result and result[0]['text']==valid[0]['text']
    assert all(c['text']!=CURRENT for c in result)


def test_current_plan_text_must_also_be_visible_in_the_current_body():
    scope, fact, package, plans, section, selected = pricing_setup()
    plan={'evidence_ids':[PRICING_EID],'analysis_claims':reuse_chapter_judgments(plans,selected)}
    bind_plan(plan,selected);plans[14]=plan
    report='## 10. 投资机会\n\n'+SOURCE+' ['+PRICING_EID+']\n\n## 14. 综合评估\n\n旧综合。'
    assert not current_conclusions(report,package,plans,scope)


def test_usable_independent_chapter_judgments_survive_one_bad_aggregate():
    scope,fact,package,plans,section,selected=pricing_setup()
    technical=card()
    technical_claim={'question':'路线及适用场景','text':TEXT,'evidence_ids':[EID],
        'claim_kind':'inference','reasoning':'根据部署条件分别比较路线，不推定统一优胜方案。'}
    tclaims,_=validate_analyses([technical_claim],{'facts':[technical]},7,[EID])
    plans[7]={'analysis_claims':tclaims}
    tsection=render_plan({'facts':[technical]},7,'技术路线对比',[EID],tclaims)
    selected=synthesis_package({10:package,7:{'facts':[technical]}},{10:section,7:tsection},scope,plans)
    good=reuse_chapter_judgments({7:plans[7]},selected)[0]
    bad={'question':'竞争与商业化判断','text':OLD,'evidence_ids':[PRICING_EID],'claim_kind':'observation'}
    bclaims,_=validate_analyses([bad],selected,14,[PRICING_EID])
    plan={'evidence_ids':[f['evidence_id'] for f in selected['facts']], 'analysis_claims':[good]+bclaims}
    bind_plan(plan,selected)
    assert TEXT in [c['text'] for c in plan['analysis_claims']]
    assert CURRENT in [c['text'] for c in plan['analysis_claims']]
    assert OLD not in [c['text'] for c in plan['analysis_claims']]


def test_finding_and_detail_remain_visible_when_renderer_places_them_in_separate_blocks():
    fact=card()
    finding='按部署场景分别比较技术路线，云端、端侧和边缘侧的选择目标不同。'
    detail='该选择应结合业务负载、吞吐量与能耗约束，不据此认定统一优胜路线。'
    claim={'question':'路线及适用场景','conclusion':finding,'text':finding+detail,
        'evidence_ids':[EID],'claim_kind':'inference'}
    accepted,errors=validate_analyses([claim],{'facts':[fact]},7,[EID])
    assert accepted and not errors
    section=render_plan({'facts':[fact]},7,'技术路线对比',[EID],accepted)
    # Reader-facing layout avoids repeating the finding verbatim in the detail.
    assert finding+detail not in section
    plans={7:{'analysis_claims':accepted}}
    assembled=synthesis_package({7:{'facts':[fact]}},{7:section},SCOPE,plans)
    assert len(assembled['source_judgments'])==len(assembled['completed_chapter_judgments'])==1
    # Removing either rendered half must invalidate that current judgment.
    assert not chapter_judgments(plans,assembled,{7:section.replace(detail,'原分析已移除。')})
    assert not chapter_judgments(plans,assembled,{7:section.replace('> '+finding,'> 当前小结已改写。')})
