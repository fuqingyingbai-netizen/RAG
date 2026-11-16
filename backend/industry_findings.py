"""Source-bound finding registry and deterministic cross-chapter diagnostics."""
import hashlib
import json
import re
from industry_research_workspace import evidence_record

VERSION='industry-findings-v1-shared-source-bindings'


def build_registry(plans, facts, scope=None):
    records={fact['evidence_id']:evidence_record(fact) for fact in facts if fact.get('evidence_id')}
    findings=[]
    for chapter,plan in plans.items():
        for claim in plan.get('analysis_claims',[]):
            refs=claim.get('evidence_ids') or []
            source_records=[records[e]['record_id'] for e in refs if e in records]
            identity={'chapter':str(chapter),'question':claim.get('question'),
                'text':claim.get('text'),'conclusion':claim.get('conclusion'),
                'claim_kind':claim.get('claim_kind'),'refs':source_records}
            findings.append({'finding_id':'F-'+hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:20],
                **identity,'conclusion':claim.get('conclusion'), 'evidence_ids':refs,
                'claim_kind':claim.get('claim_kind'), 'review_status':(claim.get('support_review') or {}).get('status','not_evaluated')})
    used={eid for f in findings for eid in f['evidence_ids']}
    return {'version':VERSION,'scope':scope or {},'evidence_records':{eid:records[eid] for eid in used if eid in records},
        'findings':findings,'certifies_semantic_truth':False}


def consistency_issues(registry, report=''):
    issues=[]
    by_evidence={}
    for finding in registry['findings']:
        for ref in finding['refs']:
            by_evidence.setdefault(ref,[]).append(finding)
    for ref, findings in by_evidence.items():
        def wording(finding):
            return str(finding.get('conclusion') or '')+'\n'+str(finding.get('text') or '')
        absent=[f for f in findings if re.search(r'(?:未|没有)(?:明确)?(?:规定|说明|指定|披露)?.{0,20}(?:义务(?:承担)?主体|承担主体)|义务(?:承担)?主体.{0,15}(?:未明确|未规定|未知)',wording(f))]
        specific=[f for f in findings if f not in absent and re.search(r'义务(?:承担)?(?:对象|主体)(?:是|为).{0,25}(?:提供|运营|开发|部署)|(?:提供者|运营者|开发者|服务商)(?:应当|必须|须)',wording(f))]
        if absent and specific and any(a['chapter']!=s['chapter'] for a in absent for s in specific):
            issues.append({'code':'shared_policy_actor_conflict','chapter':None,
                'message':'同一原文在不同章节的义务主体认定不一致，需核对明确条款与条件推论。',
                'record_id':ref,'finding_ids':[f['finding_id'] for f in absent+specific]})
    cutoff=str(registry['scope'].get('as_of_date',''))[:4]
    if cutoff.isdigit():
        pattern=rf'{cutoff}年[^。！？\n]{{0,45}}(?:预测|目标)[^。！？\n]{{0,45}}距[^。！？\n]{{0,20}}(?:截止日|截点)[^。！？\n]{{0,8}}(?:一|1)年'
        if re.search(pattern,report):
            issues.append({'code':'same_year_forecast_horizon','chapter':None,
                'message':'预测目标年与研究截止日同年，正文却写成相距一年，需统一时间口径。'})
    return issues
