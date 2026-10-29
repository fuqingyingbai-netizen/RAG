"""Developed findings and summaries reuse scoped evidence, with no service calls."""
from copy import deepcopy
import json

from industry_answer_quality import complete_finding
from industry_briefing import short_conclusion,refresh_conclusion_summary,chapter_judgments
from industry_conclusion_recovery import recovery_plan
from industry_fact_contracts import validate_analyses,render_plan
from industry_question_generation import compile_jobs,parse_answers,job_prompt
from industry_reader import analysis_paragraphs,question_writing_profile
from industry_research import summary_length
from test_industry_briefing import card,SCOPE,EID


FINDING='云端、端侧与边缘侧的部署选择应分别结合吞吐、能耗与延迟要求。业务选型应先明确场景，再比较对应架构。'
DETAIL='对于吞吐要求较高的云端场景，可以围绕吞吐量优化目标比较方案；端侧关注能耗，边缘侧关注低延迟。'


def packet():
    packets,_=compile_jobs({'facts':[card()],'industry_scope':SCOPE},7)
    return packets[0]


def answer(p,detail=DETAIL):
    q=p['questions'][0]
    return {'question_id':q['id'],'status':'answered','conclusion':FINDING,'analysis':detail,
            'kind':'conditional','refs':[q['allowed_refs'][0]]}


def test_multi_sentence_finding_is_preserved_once_with_separate_explanation():
    p=packet();before=deepcopy(p)
    accepted,rejected,_=parse_answers(json.dumps({'answers':[answer(p)]}),p)
    assert accepted and not rejected
    c=accepted[0]
    assert c['conclusion']==short_conclusion(c)==FINDING
    section=render_plan({'facts':[card()]},7,'技术路线对比',[EID],accepted)
    assert section.count(FINDING)==section.count(DETAIL)==1
    assert section.index(FINDING)<section.index(DETAIL)<section.index('### 关键依据')
    assert p==before


def test_multi_sentence_finding_does_not_authorize_wrong_numbers_or_incomplete_sentences():
    p=packet();a=answer(p);a['conclusion']+='该路线吞吐量已提高248%。'
    accepted,rejected,_=parse_answers(json.dumps({'answers':[a]}),p)
    assert not accepted and any('analysis_unauthorized_number' in e['issues'] for e in rejected)
    assert complete_finding(FINDING)
    assert not complete_finding(FINDING+'尚未结束')
    assert not complete_finding('完整且具体的判断与适用条件。'*4)


def test_long_analysis_no_longer_fails_because_it_was_duplicated_into_reasoning():
    p=packet();body=DETAIL*14
    assert 600<len(body)<2000
    accepted,rejected,_=parse_answers(json.dumps({'answers':[answer(p,body)]}),p)
    assert accepted and not rejected
    assert accepted[0]['text']==FINDING+body and 'reasoning' not in accepted[0]
    # Existing explicit reasoning-field checks remain independent.
    original={k:v for k,v in accepted[0].items() if k in {'question','conclusion','text','evidence_ids','claim_kind'}}
    original['reasoning']='过长的另写说明'*100
    assert 'invalid_claim_reasoning' in validate_analyses([original],{'facts':[card()]},7,[EID])[1][0]['issues']


def test_question_depth_uses_retained_unique_premises_and_stays_inside_real_prompt_budget():
    f=card();assert question_writing_profile([f]*20,'路线及适用场景')['distinct_premises']==1
    rows=[card(eid=f'E-{i+1:012X}',source_url=f'https://research.example/{i}',
               **{}) for i in range(4)]
    for i,f in enumerate(rows):
        f['fact_contract']['statement']+=f'所引部署场景分别为第{i}类。'
    p=packet();q=p['questions'][0]
    assert q['writing_profile']['distinct_premises']==len(q['allowed_refs'])==1
    assert q['writing_profile']['targets_are_guidance_not_permission_to_invent']
    assert len(job_prompt(p))<=10000 and '1至3个完整句子' in job_prompt(p)
    assert question_writing_profile(rows,'路线及适用场景')['material_tier']=='rich'


def test_finding_without_explanation_stays_visible_and_schedules_existing_material_rewrite():
    p=packet();accepted,rejected,states=parse_answers(json.dumps({'answers':[answer(p,FINDING)]}),p)
    assert accepted and not rejected and accepted[0]['development_warning']=='analysis_not_developed'
    assert states[p['questions'][0]['id']]['answer_status']=='needs_expansion'
    plan={'analysis_claims':accepted,'generation_batches':{'questions':[
        {'question':'路线及适用场景',**states[p['questions'][0]['id']]}]}}
    tasks=recovery_plan({7:plan},{7:{'facts':[card()]}})['tasks']
    assert tasks and tasks[0]['action']=='rewrite_conclusion'
    assert '已有原文' in tasks[0]['feedback'] and '不重新检索' in tasks[0]['feedback']
    section=render_plan({'facts':[card()]},7,'技术路线对比',[EID],accepted)
    assert section.count(FINDING)==1 and '### 研究分析' not in section


def test_long_prose_splits_only_at_whole_sentences_and_preserves_current_body_lineage():
    p=packet();body=(DETAIL+'该选择仍需结合实际应用负载，不能把部署方向解释为实测性能排名。')*5
    accepted,errors,_=parse_answers(json.dumps({'answers':[answer(p,body)]}),p)
    assert accepted and not errors
    paragraphs=analysis_paragraphs(body)
    assert len(paragraphs)>1 and ''.join(paragraphs)==body
    section=render_plan({'facts':[card()]},7,'技术路线对比',[EID],accepted)
    assert chapter_judgments({7:{'analysis_claims':accepted}},{'facts':[card()]},{7:section})
    quoted='《'+'很长的标题。'*60+'》'+DETAIL*5
    paragraphs=analysis_paragraphs(quoted)
    assert ''.join(paragraphs)==quoted and paragraphs[0].count('《')==paragraphs[0].count('》')==1


def checked(finding=FINDING,detail=DETAIL):
    c={'question':'路线及适用场景','conclusion':finding,'text':detail,'claim_kind':'conditional','evidence_ids':[EID]}
    claims,errors=validate_analyses([c],{'facts':[card()]},7,[EID])
    assert claims and not errors
    return claims[0]


def test_summary_leads_with_findings_keeps_whole_explanation_and_places_notice_last():
    c=checked();before=deepcopy(c)
    notice='评估与使用边界：未完成评估：技术迭代与替代风险；总分暂不计算。'
    report='## 1. 摘要\n\n'+notice+'\n\n旧摘要。\n\n## 2. 正文\n\n保持正文。'
    result=refresh_conclusion_summary(report,[c],SCOPE)
    summary=result.split('## 2.',1)[0]
    assert summary.index(FINDING)<summary.index(DETAIL)<summary.index(notice)
    assert '机器人' in summary and summary_length(summary)<=600
    assert c==before and result.split('## 2.',1)[1]==report.split('## 2.',1)[1]
    assert refresh_conclusion_summary(result,[c],SCOPE)==result


def test_summary_reserves_distinct_findings_before_filling_explanations():
    claims=[]
    for finding,detail in [
        ('云端方案应围绕吞吐要求比较，端侧方案应关注低功耗。',DETAIL*7),
        ('边缘部署应按低延迟场景比较，而非直接套用云端架构。',DETAIL),
        ('架构选择应先明确应用场景，再比较各自对应的约束。',DETAIL)]:
        claims.append(checked(finding,detail))
    report='## 1. 摘要\n\n旧摘要。\n\n## 2. 正文\n\n保持。'
    result=refresh_conclusion_summary(report,claims,SCOPE)
    assert all(c['conclusion'] in result for c in claims)
    assert summary_length(result.split('## 2.',1)[0])<=600
    assert DETAIL in result  # Spare room goes to explanation, not a status preamble.


def test_empty_updated_conclusions_remove_previous_generated_summary():
    report='## 1. 摘要\n\n旧摘要。\n\n## 2. 正文\n\n保持。'
    generated=refresh_conclusion_summary(report,[checked()],SCOPE)
    result=refresh_conclusion_summary(generated,[],SCOPE)
    assert FINDING not in result and '依据已变化' in result
