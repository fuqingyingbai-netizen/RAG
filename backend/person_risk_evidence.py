"""Person risk review register: evidence, reliability and severity stay separate."""
from person_provenance import stable_id

VERSION = 'person-risk-evidence-v1-no-automatic-score'


def build_register(facts, conflicts=(), platform_attempts=()):
    rows = []
    for f in facts:
        obs = f.get('observation') or {}
        scope = f.get('subject_scope') or obs.get('subject_scope') or 'unresolved'
        if scope in {'other_person', 'comparison_person'}:
            continue
        kinds = []
        relations = obs.get('relations') or []
        if 'legal' in relations:
            kinds.append('judicial_credit_source_lead')
        if set(relations) & {'holding', 'appointment'}:
            kinds.append('interest_relationship_not_conflict_finding')
        feedback = f.get('feedback_record') or {}
        if f.get('opinion_only') or feedback.get('kind') == 'attributed_opinion':
            kinds.append('named_or_attributed_evaluation_not_fact')
        if f.get('claim_type') == 'person_management_event':
            kinds.append('specific_reported_behavior')
        for kind in kinds:
            rows.append({'item_id': stable_id('RISK-REVIEW', [f['evidence_id'], kind]),
                'domain': kind, 'subject': f.get('subject'), 'subject_scope': scope,
                'evidence_ids': [f['evidence_id']], 'source_urls': [f.get('source_url')],
                'evidence_presence': 'admitted_source_statement',
                'evidence_reliability': {'source_grade': f.get('source_grade') or 'unrated',
                    'literal_match': f.get('original_excerpt_match'),
                    'independent_verification': 'pending'},
                'risk_severity': 'not_assessed', 'risk_score': None,
                'responsibility': 'not_determined',
                'attribution_boundary': f.get('attribution_boundary') or '',
                'event_period': obs.get('period') or '',
                'source_role_dates': obs.get('role_date_fields') or [],
                'review_status': 'pending',
                'boundary': ('仅为关联企业背景，不转移个人责任。' if scope == 'affiliated_company' else
                    '来源线索不等于事件成立、责任认定或个人失信。')})
    known = {f['evidence_id'] for f in facts}
    for conflict in conflicts:
        ids = [eid for eid in conflict.get('evidence_ids', []) if eid in known]
        if not ids:
            continue
        rows.append({'item_id': stable_id('CONFLICT-REVIEW', [ids, conflict.get('claim_key')]),
            'domain': 'identity_period_or_value_conflict_requires_review', 'evidence_ids': ids,
            'source_conflict': conflict, 'evidence_presence': 'conflicting_source_statements',
            'evidence_reliability': {'independent_verification': 'pending'},
            'risk_severity': 'not_assessed', 'risk_score': None, 'responsibility': 'not_determined',
            'review_status': 'pending', 'boundary': '先核对主体、时期、单位和来源；文本冲突不是个人失信。'})
    collection = [{k: attempt.get(k) for k in ('provider', 'tool', 'subject', 'status', 'reason', 'error_code', 'retrieved_at')}
                  for attempt in platform_attempts]
    return {'version': VERSION, 'overall_score': None, 'overall_severity': 'not_assessed',
        'items': rows, 'collection_outcomes': collection,
        'policy': {'weights': None, 'score_formula': None,
            'no_result_interpretation': '限定查询范围内没有取得可引用材料，不等于安全或无风险。',
            'provider_failure_interpretation': '采集能力缺口，不进入个人风险、信用或责任判断。',
            'company_boundary': '关联公司的事项、诉讼或处罚不直接归给个人。',
            'opinion_boundary': '评价者观点、当事人陈述与已经证明的事实分开。'}}
