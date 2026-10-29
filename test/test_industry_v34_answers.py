"""v34 defects: question contribution, attribution, bounded growth and recovery.

No model, search, database or original-document mutations. Positive controls
keep scoped analysis available; these checks do not certify semantic truth.
"""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from industry_answer_quality import contribution_issue, search_outcome, writer_card
from industry_assertions import bounds_used_as_direction
from industry_question_generation import compile_jobs, job_prompt, parse_answers
from test_industry_chapter_batches import rich_package
from test_industry_question_jobs import answer
from test_industry_conclusion_recovery import make_workflow, run


@pytest.mark.parametrize('question,conclusion,issue', [
    ('盈利情况','该毛利率仅反映样本水平，不能据此判断新增或行业整体的盈利质量。','scope_only_answer'),
    ('路线及适用场景','AIPaaS弹性扩容、PIM加速卡和存算一体各有适用前提，不能仅凭性能主张判定优劣。','generic_comparison_without_criteria'),
    ('适用政策原文','仅能确认公布施行的程序性信息，不能据此识别具体法规。','scope_only_answer'),
    ('产业链主体和分层关系','所引材料仍需进一步人工复核。','only_review_notice'),
])
def test_known_nonanswers_do_not_resolve_a_question(question, conclusion, issue):
    assert contribution_issue({'question':question,'conclusion':conclusion})==issue


@pytest.mark.parametrize('question,conclusion', [
    ('盈利情况','按量收费将收入与实际调用量挂钩，规模增长对利润的影响取决于单位推理成本与收费的匹配。'),
    ('路线及适用场景','云端侧重吞吐、端侧侧重能效，选型应分别核对负载与部署条件，不能据此认定单一路线普遍领先。'),
    ('统计口径可比性','两份统计的地域和期间不同，不能据此计算同口径市场增长。'),
    ('适用政策原文','审查与复核职责需分别由不同服务主体承担，数据标注提供者则承担自身标注规则制定责任。'),
    ('产业链主体和分层关系','上游提供核心部件，中游负责整机集成，下游面向制造业场景提供应用服务。'),
])
def test_useful_conditional_and_specific_negative_answers_remain(question, conclusion):
    assert contribution_issue({'question':question,'conclusion':conclusion}) is None


def test_qualification_does_not_erase_a_real_allocation_answer():
    c={'question':'产业链主体和分层关系','conclusion':'上游提供核心部件，中游负责整机集成，下游服务应用，但不能据此认定各环节盈利水平。'}
    assert contribution_issue(c) is None


def test_writer_and_selector_receive_identity_without_licensing_extra_numbers():
    package=rich_package(); f=package['facts'][0]
    f.update(source_title='机器人产业研究',publisher='研究机构',evidence_quote=f['fact_contract']['statement']+'附注信息。',
             original_model_fact='PRIVATE_DIAGNOSTIC')
    before=deepcopy(package)
    row=writer_card('F1',f)
    assert row['identity']['document_title']=='机器人产业研究'
    assert row['statement']==f['fact_contract']['statement'] and row['authorized_metric'] is None
    assert row['original_context']==f['evidence_quote'] and 'not_extra_metrics' in row['context_use']
    assert 'PRIVATE_DIAGNOSTIC' not in json.dumps(row)
    jobs,_=compile_jobs(package,2)
    for job in jobs:
        assert len(job_prompt(job))<=10000
    assert package==before


def test_uncited_or_unlocated_context_is_not_added_to_authorization():
    f=rich_package()['facts'][0]
    f['evidence_quote']='页面上另一段与授权陈述不同的内容。'
    f['provenance']['locator']['status']='unlocated'
    assert 'original_context' not in writer_card('F1',f)
    assert writer_card('F1',f)['statement']==f['fact_contract']['statement']


def test_alias_is_rendered_as_real_document_only_when_cited():
    packet=compile_jobs(rich_package(),2)[0][0];q=packet['questions'][0]
    ref=q['allowed_refs'][0];a=answer(q['id'],ref)
    a['analysis']=ref+'说明上游供给、中游集成与下游应用分别承担不同职责，因此业务选型需要核对各环节的依赖条件与接口要求。'
    valid,errors,_=parse_answers(json.dumps({'answers':[a]}),packet)
    assert valid and not errors
    assert '《机器人技术研究》' in valid[0]['text'] and ref+'说明' not in valid[0]['text']
    a['analysis']='F999说明'+a['analysis']
    valid,errors,_=parse_answers(json.dumps({'answers':[a]}),packet)
    assert not valid and errors[0]['issues']==['uncited_alias_in_analysis']


def test_incomplete_answer_routes_to_rewrite_without_discarding_sources():
    from industry_conclusion_recovery import recovery_plan
    packet=compile_jobs(rich_package(),2)[0][0];q=packet['questions'][0]
    a=answer(q['id'],q['allowed_refs'][0]);a['conclusion']='所引材料只能确认产业链有分工，不能据此判断业务选择。'
    valid,errors,states=parse_answers(json.dumps({'answers':[a]}),packet)
    assert valid and valid[0]['answer_quality_warning']=='scope_only_answer'
    assert states[q['id']]['execution_status']=='completed' and states[q['id']]['answer_status']=='partial'
    assert errors[0]['severity']=='improvement'
    plan={2:{'analysis_claims':valid,'analysis_rejections':errors,
             'generation_batches':{'questions':[{'question':q['question'],**states[q['id']]}]}}}
    task=recovery_plan(plan,{2:rich_package()})['tasks'][0]
    assert task['action']=='rewrite_conclusion' and task['issue_codes']==['answer_quality_scope_only_answer']


@pytest.mark.parametrize('quality,expected', [('scope_only','supported'), ([], 'not_evaluated')])
def test_review_truth_and_question_quality_are_independent(quality,expected):
    from industry_reasoning import review_packet,validate_reviews
    from test_industry_reasoning import chain,review_claim,verdict,response
    f=chain();c=review_claim(f);packet,_=review_packet([c],[f])
    row=verdict(c,f,answer_quality=quality,answer_quality_reason='本条有引用，但未说明实际业务含义。')
    checked=validate_reviews(response(packet,[row]),packet)[c['claim_id']]
    assert checked['status']==expected
    if expected=='supported':assert checked['answer_quality']=='scope_only' and not checked['entailment_proven']


def metric(eid,value,unit,period,definition='我国人工智能核心产业规模',comparator='>',name='产业规模',forecast=False):
    return {'evidence_id':eid,'numeric_validation':{'passed':True},
        'numeric_context':{'metric':name,'definition':definition,'geography':'中国大陆','period':period,
            'value':value,'unit':unit,'comparator':comparator,'is_forecast':forecast}}


def test_v34_two_lower_bounds_not_growth_even_with_unrelated_exact_cards():
    rows=[metric('E-1',9000,'亿元','2024',definition='2024 年我国人工智能核 心产业规模'),
          metric('E-2',1.2,'万亿元','2025',name='核心产业规模'),
          metric('E-3',100,'亿元','2024',definition='人工智能芯片产业规模',comparator='='),
          metric('E-4',3,'万亿元','2030',forecast=True)]
    assert bounds_used_as_direction('2024年规模超过9000亿元、2025年超过1.2万亿元，规模水平扩大，但不能计算精确增速。',rows)
    assert not bounds_used_as_direction('两个来源只给出规模下限，不能据此认定规模扩大。',rows)
    rows[0]['numeric_context']['comparator']='='
    rows[1]['numeric_context']['comparator']='='
    assert not bounds_used_as_direction('同口径规模从9000亿元扩大至1.2万亿元。',rows)


def test_search_failure_is_distinct_from_real_empty_search_and_partial_success():
    blocked={'engine_states':{
        'tavily':{'status':'failed','reason':'quota_exceeded','http_status':429,'error':'SECRET'},
        'exa':{'status':'failed','reason':'quota_exceeded'},
        'bocha':{'status':'failed','reason':'access_denied','http_status':403},
        'serper':{'status':'failed','reason':'invalid_request','http_status':400}}}
    assert search_outcome(blocked,0)['status']=='provider_unavailable'
    assert 'SECRET' not in json.dumps(search_outcome(blocked,0))
    partial=deepcopy(blocked);partial['engine_states']['serper']={'status':'returned'}
    assert search_outcome(partial,0)['status']=='no_hits'
    assert search_outcome(blocked,1)['status']=='returned'
    assert search_outcome({},0)['status']=='empty_unverified'


def test_provider_outage_stops_collection_but_keeps_other_questions_and_one_finalization(monkeypatch):
    _,w,db,p,calls=make_workflow(monkeypatch)
    def collect(*a,**k):
        calls.append('collect')
        p.industry_search_outcomes=[{'status':'provider_unavailable','result_count':0}]
    def generate(*a,**k):
        if p.industry_recovery_plan.get('finalize_synthesis'):
            calls.append('finalize');return 'new draft'
        calls.append('generate')
        q=p.industry_statement_plans[2]['generation_batches']['questions'][0]['question']
        p.industry_statement_plans[2]['analysis_claims']=[{'question':q,'conclusion':'业务部署依赖供给与应用环节的衔接。'}]
        return 'new draft'
    w.collect_web_sources=collect;w.generate_report=generate
    result=run(w,db,p)
    assert result[0]=='new draft' and calls==['collect','generate','finalize']
    record=p.industry_conclusion_recovery
    blocked=[s for s in record['questions'].values() if s.get('stop_reason')=='collection_unavailable']
    assert record['collection_unavailable'] and len(blocked)==1
    assert blocked[0]['no_progress']==0 and blocked[0]['attempts']==1
    assert record['status']=='completed_with_gaps'


def test_no_new_premises_skips_entire_generation_and_synthesis(monkeypatch):
    _,w,db,p,calls=make_workflow(monkeypatch)
    p.industry_statement_plans[2]['generation_batches']['questions']=p.industry_statement_plans[2]['generation_batches']['questions'][1:]
    assert run(w,db,p)[0]=='original draft'
    assert calls==['collect','collect']
    assert all(s['generation_skipped']=='no_new_evidence' for s in p.industry_conclusion_recovery['passes'])


def test_final_review_updates_remaining_questions_instead_of_stale_success(monkeypatch):
    _,w,db,p,calls=make_workflow(monkeypatch)
    original=w.generate_report
    def generate(*a,**k):
        result=original(*a,**k)
        if p.industry_recovery_plan.get('finalize_synthesis'):
            p.industry_statement_plans[2]['analysis_claims']=[]
        return result
    w.generate_report=generate
    run(w,db,p)
    record=p.industry_conclusion_recovery
    assert record['status']=='completed_with_gaps' and len(record['remaining_tasks'])==2
    assert all(s['status']=='unresolved_after_final_review' for s in record['questions'].values())


def synthesis_fixture():
    from industry_reasoning import claim_id
    f=rich_package()['facts'][1]
    c={'question':'产业阶段与发展条件','conclusion':'业务部署依赖供给与应用环节的衔接。',
       'text':'业务部署依赖供给与应用环节的衔接。','evidence_ids':[f['evidence_id']],
       'support_review':{'status':'supported','human_review_required':True}}
    old={'industry_statement_plans':{14:{'analysis_claims':[c]}},
         'industry_section_packages':{14:json.dumps({'facts':[f]})}}
    p=SimpleNamespace(industry_statement_plans={14:{'analysis_claims':[],'analysis_rejections':[]}},
                      industry_claim_support_review={'reviews':{},'attempts':0},industry_report_degradations=[])
    return f,c,old,p


@pytest.mark.parametrize('changed',[False,True])
def test_historical_synthesis_is_not_revived_even_with_identical_premises(changed):
    from report_agents.industry_report_agent import IndustryReportAgent
    f,c,seed,p=synthesis_fixture();current=deepcopy(f)
    if changed:current['fact_contract']['statement']='已经改变的陈述。'
    packages={14:json.dumps({'facts':[current]})};sections={}
    IndustryReportAgent()._preserve_supported_synthesis(p,{'facts':[current]},packages,sections,seed)
    claims=p.industry_statement_plans[14]['analysis_claims']
    assert not claims
    assert p.industry_statement_plans[14]['historical_synthesis_ignored']==1
    assert not p.industry_claim_support_review['reviews']


def test_current_synthesis_keeps_reexport_lineage_without_old_seed_question():
    from industry_briefing import synthesis_package,current_conclusions,bind_plan
    from industry_fact_contracts import render_plan,validate_analyses
    from report_agents.industry_report_agent import IndustryReportAgent
    from test_industry_briefing import card
    package=rich_package();f=package['facts'][1];eid=f['evidence_id']
    proposed={'question':'总体判断及成立条件','conclusion':'业务部署依赖供给与应用环节的衔接。',
        'text':'上游负责核心部件供给，中游负责整机集成，下游面向应用，因此方案选择需要同时核对部件供给、集成能力和具体应用的接口要求。',
        'reasoning':'依据原文分工讨论业务衔接条件，不补充行业盈利或份额。',
        'claim_kind':'conditional','evidence_ids':[eid]}
    valid,errors=validate_analyses([proposed],package,14,[eid])
    assert valid and not errors
    c={**valid[0],'support_review':{'status':'supported','human_review_required':True}}
    source_section=render_plan(package,2,'行业基础定义与产业链全景',[eid])
    old_package=synthesis_package({2:package},{2:source_section},package['industry_scope'])
    seed={'industry_statement_plans':{14:{'analysis_claims':[c]}},
        'industry_section_packages':{14:json.dumps(old_package)}}
    tech=card(eid='E-ABCDEF123456')
    tech_section=render_plan({'facts':[tech]},7,'技术路线对比',[tech['evidence_id']])
    candidate=synthesis_package({7:{'facts':[tech]}},{7:tech_section},package['industry_scope'])
    new_claim={'question':'技术及落地条件','conclusion':'云端与端侧面向不同部署要求，方案选择应分别核对吞吐与功耗条件。',
        'text':'云端采用吞吐量优化架构，端侧采用低功耗架构，边缘侧面向低时延部署，因此可以按部署位置和应用负载分别比较适用条件，不能仅凭单项性能作统一排序。',
        'reasoning':'由材料中的不同部署要求讨论方案适用条件，不增加实际测试或性能排名。',
        'claim_kind':'conditional','evidence_ids':[tech['evidence_id']]}
    new_valid,new_errors=validate_analyses([new_claim],{'facts':[tech]},14,[tech['evidence_id']])
    assert new_valid and not new_errors
    new_claim={**new_valid[0],'support_review':{'status':'supported','human_review_required':True}}
    package['facts'].append(tech)
    p=SimpleNamespace(industry_statement_plans={14:{'analysis_claims':[new_claim],'analysis_rejections':[]}},
                      industry_claim_support_review={'reviews':{},'attempts':0},industry_report_degradations=[])
    p.industry_statement_plans[14]['evidence_ids']=[tech['evidence_id']]
    bind_plan(p.industry_statement_plans[14],candidate)
    packages={14:json.dumps(candidate)}
    sections={14:render_plan(candidate,14,'综合评估',[tech['evidence_id']],[new_claim])}
    IndustryReportAgent()._preserve_supported_synthesis(p,package,packages,sections,seed)
    assert p.industry_statement_plans[14]['analysis_claims']==[new_claim]
    report=source_section+'\n\n'+tech_section+'\n\n'+sections[14]
    exported=current_conclusions(report,package,p.industry_statement_plans,package['industry_scope'])
    assert len(exported)==1 and exported[0]['text']==new_claim['text']
