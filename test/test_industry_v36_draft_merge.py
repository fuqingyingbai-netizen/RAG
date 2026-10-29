"""Current draft selection is independent from revision history and paid IO."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from industry_draft_policy import (consolidate_drafts, question_alignment_issue,
                                   current_revision_state)
from industry_conclusion_recovery import finding_issue,recovery_plan
from industry_question_generation import compile_jobs,parse_answers
from test_industry_chapter_batches import rich_package


def claim(text=None, **fields):
    body=text or '在样本企业范围内，技术层毛利率和研发投入最高，应用层现金流更平稳，因此评估盈利时应分别比较企业层次。'
    return {'question':'盈利及收入成本材料','conclusion':body,'text':body,
            'claim_kind':'conditional','evidence_ids':['E-000000000001'],**fields}


def supported(c, *, answered=True):
    return {**c,'support_review':{'status':'supported','answer_quality':'answered' if answered else 'scope_only'}}


def test_final_consolidation_removes_repeated_variant_and_preserves_inputs():
    first=supported(claim())
    second=claim('在样本企业范围内，技术层毛利率与研发投入最高，应用层现金流表现更平稳，因此评估盈利时应分别比较企业层次。')
    original=deepcopy([first,second])
    result=consolidate_drafts([],original,final=True)
    assert len(result)==1 and result[0]['text']==first['text']
    assert original==[first,second]


def test_pre_review_preserves_best_fallback_plus_one_revision_not_every_attempt():
    old=supported(claim(),answered=False)
    old['partial_parent_claim_id']='C-PARENT'
    prior=[old,deepcopy(old),claim('在样本企业范围内，技术层毛利率与研发投入最高，应用层现金流更平稳，因此评估盈利时应分别比较企业层次。')]
    new=claim('在样本企业范围内，技术层毛利率和研发投入最高，应用层现金流更平稳，因此盈利评估应分别比较企业层次。')
    assert len(consolidate_drafts(prior,[new]))==2


def test_reviewed_complete_revision_replaces_overlapping_supported_fragment():
    old=supported(claim(),answered=False)
    old['partial_parent_claim_id']='C-PARENT'
    new=supported(claim(old['text']+'技术层的高毛利仍可能伴随较大的研发投入，现金流平稳也不等于毛利更高。'))
    result=consolidate_drafts([old],[new],final=True)
    assert len(result)==1 and result[0]['text']==new['text']


@pytest.mark.parametrize('left,right',[
    ('2022年中国大陆甲公司毛利率为37.20%，其财务评价应按该企业当期收入成本口径进行。',
     '2023年中国大陆甲公司毛利率为37.20%，其财务评价应按该企业当期收入成本口径进行。'),
    ('2022年中国大陆甲公司毛利率为37.20%，其财务评价应按该企业当期收入成本口径进行。',
     '2022年中国大陆乙公司毛利率为37.20%，其财务评价应按该企业当期收入成本口径进行。'),
    ('2022年中国大陆甲公司毛利率为37.20%，其财务评价应按该企业当期收入成本口径进行。',
     '2022年全球甲公司毛利率为37.20%，其财务评价应按该企业当期收入成本口径进行。'),
    ('2022年中国大陆甲公司毛利率为37.20%，其财务评价应按该企业当期收入成本口径进行。',
     '2022年中国大陆甲公司毛利率为27.20%，其财务评价应按该企业当期收入成本口径进行。'),
    ('科大讯飞在该样本市场提供模型服务，方案部署应核对平台接口、算力配置与客户需求的衔接条件。',
     '商汤在该样本市场提供模型服务，方案部署应核对平台接口、算力配置与客户需求的衔接条件。'),
])
def test_similar_prose_with_different_period_subject_scope_or_value_is_never_merged(left,right):
    assert len(consolidate_drafts([], [claim(left),claim(right)],final=True))==2


def test_distinct_judgments_and_distinct_source_permissions_survive():
    first=claim()
    other=claim('按量收费使服务收入与客户调用量挂钩，单位推理成本和请求负载影响服务毛利，因此应分别记录收入与资源成本。')
    same_words_new_source={**first,'evidence_ids':['E-000000000002']}
    assert len(consolidate_drafts([], [first,other,same_words_new_source],final=True))==3


def test_same_sample_value_with_rephrased_boundary_is_one_current_judgment():
    first=claim('在样本口径下，2022年中国大陆人工智能代表企业平均毛利率为37.20%，但这只是企业样本均值，不能作为行业整体盈利的证据。')
    second=claim('2022年中国大陆人工智能代表企业样本平均毛利率为37.20%，仅反映该企业样本群体的毛利水平，不能外推行业整体盈利。')
    first=supported(first);second=supported(second)
    assert len(consolidate_drafts([], [first,second],final=True))==1


def test_exact_supported_old_judgment_survives_failed_or_pending_revision():
    old=supported(claim())
    bad={**old,'text':old['text'].replace('因此','所以'),'support_review':{'status':'unsupported'}}
    result=consolidate_drafts([old],[bad],final=True)
    assert len(result)==1 and result[0]['text']==old['text']


@pytest.mark.parametrize('text',[
    '2022年代表企业样本平均毛利率为37.20%，仅反映样本群体毛利水平，不能外推整个行业。',
    '材料仅提出基础订阅加按Token消耗收费可作为商业模式方向，未说明任何主体已实际采用、向谁收费或收费水平。',
])
def test_margin_or_pricing_idea_does_not_resolve_actual_payment_even_after_positive_review(text):
    c=supported(claim(text,question='实际收费与付费客户'))
    assert question_alignment_issue(c)=='actual_payment_not_answered'
    assert finding_issue(c)=='actual_payment_not_answered'


def test_partial_known_customer_transaction_stays_useful_without_price_disclosure():
    c=supported(claim('企业客户已经采购该服务，付费安排采用订阅方式，未披露具体收费金额。',question='实际收费与付费客户'))
    assert question_alignment_issue(c) is None and finding_issue(c) is None


@pytest.mark.parametrize('text',[
    '若企业已采用订阅收费，收入会随用户留存变化。',
    '如果企业已采用订阅收费，收入会随客户续费而变化。',
    '如果采用该模式，客户按调用量支付费用。',
    '若企业采用订阅服务，收费为199元每月。',
    '假设该企业已经采购模型服务，后续支出随调用量变化。',
    '该服务计划采用订阅方式，售价199元每月。',
    '该服务未来采用订阅方式，售价199元每月。',
    '建议该服务按月订阅，价格为199元每月。',
    '企业可以采用订阅服务，价格为199元每月。',
    '企业将采用订阅服务，收费为199元每月。',
    '在客户已经采用订阅服务的情况下，续费与留存会影响收入。',
    '在客户已付费的假设下，服务按调用量收费。',
    '以客户已付费为前提，服务售价为199元每月。',
    '客户已经付费这一假设尚待原始交易披露验证。',
    '企业未采用订阅收费，客户尚无实际交易记录。',
    '企业未曾购买该服务，当前只讨论可能的采购方式。',
    '若干客户未曾购买该服务，企业没有取得相关服务收入。',
    '如果未来科技公司已购买该服务，则该项费用属于其服务支出。',
])
def test_conditional_future_or_recommended_payment_is_readable_but_not_completed(text):
    c=supported(claim(text,question='实际收费与付费客户'));before=deepcopy(c)
    assert question_alignment_issue(c)=='actual_payment_not_answered'
    assert finding_issue(c)=='actual_payment_not_answered'
    plan={'analysis_claims':[c],'analysis_rejections':[],'question_ledger':{'questions':[{'question':c['question']}]}}
    current_revision_state(plan)
    assert plan['analysis_claims']==[before] and not plan['resolved_questions']
    assert plan['question_ledger']['questions'][0]['model_revision_complete'] is False


@pytest.mark.parametrize('text',[
    '企业客户已经采购该服务，若后续调用量增加，服务收入可能增加。',
    '企业客户已采购该服务，若需求增长则追加订阅。',
    '企业客户已经采购该服务，如果后续调用量增加，服务收入可能增加。',
    '若干客户已经购买该服务，采用现行订阅方案。',
    '若干企业客户已经采购该服务，未来的续费仍需跟踪。',
    '该服务已向企业客户收费，建议后续分别核对调用收入和服务成本。',
    '如果企业采用订阅方式，收入可能随留存变化。企业客户目前已经购买该服务，具体价格未披露。',
    '企业已经采购该服务后若继续续费，服务收入还会受到调用量影响。',
    '未来科技公司已购买该服务，当前采用现行订阅方案。',
    '未来智能集团已经采购该服务，未来追加用量的条件仍需观察。',
    '企业未采用订阅收费，但已有客户购买该服务。',
])
def test_actual_purchase_fact_survives_later_conditions_and_several_is_not_if(text):
    c=supported(claim(text,question='实际收费与付费客户'));before=deepcopy(c)
    assert question_alignment_issue(c) is None and finding_issue(c) is None
    plan={'analysis_claims':[c],'analysis_rejections':[],'question_ledger':{'questions':[{'question':c['question']}]}}
    current_revision_state(plan)
    assert c==before and plan['resolved_questions']==[c['question']]
    assert plan['question_ledger']['questions'][0]['model_revision_complete'] is True


def test_policy_dates_cannot_be_completed_demand_but_are_valid_event_nodes():
    body='生成式人工智能办法于2023年施行，另一办法于2026年公布并施行。'
    assert finding_issue(supported(claim(body,question='商业化里程碑与终端需求')))=='policy_dates_not_demand_evidence'
    assert question_alignment_issue(claim(body,question='有日期的主体事件')) is None


def test_every_missing_answer_retry_has_specific_feedback_and_no_search():
    p={4:{'analysis_claims':[],'analysis_rejections':[], 'generation_batches':{'questions':[{
        'question':'规模、期间和统计口径','status':'answer_missing'}]}}}
    task=recovery_plan(p,{4:{}})['tasks'][0]
    assert task['action']=='retry_generation' and task['issue_codes']==['answer_missing']
    assert '返回结果缺少本题' in task['feedback']


def test_misaligned_draft_is_retained_but_scheduled_for_targeted_revision():
    c=supported(claim('样本企业毛利率与研发投入存在差异，因此应按企业层次比较财务表现。',question='实际收费与付费客户'))
    p={10:{'analysis_claims':[c],'analysis_rejections':[], 'generation_batches':{'questions':[{
        'question':c['question'],'status':'draft_retained'}]}}}
    task=recovery_plan(p,{10:{}})['tasks'][0]
    assert task['action']=='rewrite_conclusion' and task['revision_draft']['text']==c['text']
    assert '实际收费与付费客户' in task['feedback'] and p[10]['analysis_claims']==[c]


def test_current_revision_marks_completed_question_and_keeps_history_for_audit():
    c=supported(claim())
    history={'question':c['question'],'issues':['claim_support_partial']}
    pending={'question':'实际收费与付费客户','issues':['answer_missing']}
    plan={'analysis_claims':[c],'analysis_rejections':[history,pending], 'question_ledger':{'questions':[
        {'question':c['question']},{'question':pending['question']}]}}
    current_revision_state(plan)
    assert plan['analysis_rejections']==[history,pending]
    assert plan['active_analysis_rejections']==[pending]
    assert plan['resolved_questions']==[c['question']]
    assert [r['model_revision_complete'] for r in plan['question_ledger']['questions']]==[True,False]


def test_parser_records_missing_question_as_concrete_retry_defect():
    packet=compile_jobs(rich_package(),2)[0][0]
    _,_,states=parse_answers('{"answers":[]}',packet)
    assert states and all(x['issue_codes']==['answer_missing'] and x['reason'] for x in states.values())


def test_old_aggregate_does_not_override_current_chapter_based_synthesis():
    from report_agents.industry_report_agent import IndustryReportAgent
    old=supported(claim('商业化材料显示计费已经转向按量收费，整个行业都已采用同一模式。',question='竞争与商业化判断'))
    current=claim('材料只提出订阅和按量计费方向，业务评估仍须核对实际客户和收入成本。',question='竞争与商业化判断')
    plan={'analysis_claims':[current]}
    p=SimpleNamespace(industry_statement_plans={14:plan})
    seed={'industry_statement_plans':{14:{'analysis_claims':[old]}}}
    IndustryReportAgent()._preserve_supported_synthesis(p,{}, {},{},seed)
    assert plan['analysis_claims']==[current] and plan['historical_synthesis_ignored']==1


@pytest.mark.parametrize('used_in_draft',[False,True])
def test_new_candidate_alone_is_not_content_progress_but_new_used_premise_is(used_in_draft):
    from industry_conclusion_recovery import recovery_limits,reserve_tasks,finish_tasks,task_key
    from test_industry_briefing import card
    package=rich_package();question='产业链主体和分层关系'
    plans={2:{'analysis_claims':[],'analysis_rejections':[], 'generation_batches':{'questions':[{
        'question':question,'status':'draft_retained'}]}}}
    task={'chapter':2,'question':question,'action':'collect_evidence','cause':'material_gap','issue_codes':[]}
    state={'attempts':0,'actions':{},'no_progress':0,'history':[],'seen_evidence':[]}
    record={'limits':recovery_limits(),'round':1,'questions':{task_key(task):state}}
    reserve_tasks([task],record,plans,{2:package})
    extra=card('机器人产业链上游提供传感器，中游承担整机集成，下游用于仓储场景。',
               'E-ABCDEF987654',module='细分赛道与产业链')
    package['facts'].append(extra)
    if used_in_draft:
        plans[2]['analysis_claims']=[claim('上游提供传感器，中游整机集成和下游仓储应用需要分别核对接口与场景条件。',
            question=question,evidence_ids=[extra['evidence_id']],partial_answer=True)]
    finish_tasks([task],record,plans,{2:package})
    row=state['history'][-1]
    assert row['new_applicable_evidence']==1 and row['new_used_evidence']==int(used_in_draft)
    assert row['progress']==used_in_draft and state['no_progress']==int(not used_in_draft)
