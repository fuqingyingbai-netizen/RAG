"""Budget industry scoring input by applicable dimension, never by a page prefix."""
import json


def model_evidence(payload):
    """Expose observations and licensed numbers, never validator success flags.

    The bounded audit package remains unchanged for selection diagnostics and
    backend validation against the original retained facts.
    """
    visible = {k:v for k,v in payload.items() if k not in {'input_selection', 'facts'}}
    visible['facts'] = []
    for original in payload.get('facts', []):
        row = {k:v for k,v in original.items() if k in {
            'evidence_id','fact','module','claim_type','evidence_scope','source_url','source_title',
            'source_document_key','numeric_context','allowed_numbers'}}
        if original.get('fact_contract'):
            row['source_boundaries'] = {k:v for k,v in original['fact_contract'].items()
                                        if k in {'source_role','sample_boundary','quantity_type'}}
        visible['facts'].append(row)
    return json.dumps(visible, ensure_ascii=False)


def risk_input(facts, scope, limit=28000):
    from industry_research import active_risk_dimensions, risk_fact_applicable, risk_fact_text, source_document_key
    from industry_evidence import evidence_requirements, fact_requirement_ids

    dimensions = active_risk_dimensions(scope)
    unique = {f['evidence_id']: f for f in facts if isinstance(f, dict) and f.get('evidence_id')}
    unique = {eid: f for eid, f in unique.items() if f.get('module') != '竞争格局与代表企业'
              or risk_fact_applicable(f, '竞争格局与集中度风险')}
    # Facts and dimensions are immutable during this selection. Reuse their
    # applicability while trying budget combinations, not across runs/users.
    applicable = {eid: {name for name in dimensions if risk_fact_applicable(f, name)}
                  for eid, f in unique.items()}
    document_keys = {eid: source_document_key(f.get('source_url', '')) for eid, f in unique.items()}
    pools = {name: [f for eid, f in unique.items() if name in applicable[eid]] for name in dimensions}
    requirements = evidence_requirements(sorted({f.get('module', '') for f in unique.values()}))
    metrics = {eid: set(fact_requirement_ids(f, requirements, True)) for eid, f in unique.items()}
    selected, rows, covered, documents = {}, [], set(), set()

    def package():
        ids = {name: [eid for eid in selected if name in applicable[eid]] for name in dimensions}
        return {'facts': rows, 'dimension_evidence_ids': ids,
                'input_selection': {name: {'available_applicable_count': len(pools[name]),
                    'retained_applicable_count': len(ids[name]),
                    'selection_status': 'retained' if ids[name] else 'budget_excluded' if pools[name] else 'no_applicable_evidence'}
                    for name in dimensions},
                'gap_interpretation': '全库候选、包内适用材料与足以评分分别判断；预算遗漏不等于资料不存在。'}

    def rank(f):
        c = f.get('fact_contract') or {}
        return (f.get('claim_type') != 'source_excerpt', bool(metrics[f['evidence_id']] - covered),
                document_keys[f['evidence_id']] not in documents,
                c.get('source_role') == 'policy_primary', (f.get('numeric_validation') or {}).get('passed') is True,
                float(f.get('quality_score') or 0))

    # The broad reliability dimension runs last; it must not consume the slots
    # reserved for policy, business or technical propositions.
    while len(rows) < 60:
        added = False
        for name in dimensions:
            candidates = sorted((f for f in pools[name] if f['evidence_id'] not in selected), key=rank, reverse=True)
            for f in candidates:
                eid = f['evidence_id']
                c = f.get('fact_contract') or {}
                ctx = {k: v for k, v in (f.get('numeric_context') or {}).items() if k in {
                    'metric', 'value', 'unit', 'period', 'geography', 'definition', 'is_forecast', 'value_nature', 'comparator'}}
                row = {k: f.get(k) for k in ('evidence_id', 'module', 'claim_type', 'evidence_scope', 'source_url')}
                row.update(fact=risk_fact_text(f), source_title=str(f.get('source_title') or '')[:120],
                           source_document_key=document_keys[eid],
                           fact_contract={k: c[k] for k in ('version', 'tasks', 'source_role', 'quantity_type', 'sample_boundary', 'risk_admitted') if k in c},
                           numeric_context=ctx, numeric_validation={'passed': (f.get('numeric_validation') or {}).get('passed') is True},
                           allowed_numbers=[str(ctx.get('value')) + str(ctx.get('unit'))] if (f.get('numeric_validation') or {}).get('passed') is True else [])
                selected[eid] = f
                rows.append(row)
                if len(json.dumps(package(), ensure_ascii=False)) <= limit:
                    covered.update(metrics[eid])
                    documents.add(document_keys[eid])
                    added = True
                    break
                rows.pop()
                del selected[eid]
            if len(rows) >= 60:
                break
        if not added:
            break
    result = package()
    if len(json.dumps(result, ensure_ascii=False)) > limit:
        raise ValueError('risk_input_budget_too_small_for_dimension_inventory')
    return result


def attach_selection(risk, selection):
    """Explain missing input separately from genuine absence and model abstention."""
    risk.setdefault('validation_diagnostics', {})['input_selection'] = selection
    for row in risk.get('dimensions', []):
        counts = selection.get(row.get('name'), {})
        row['input_selection'] = counts
        if row.get('score') is None and counts.get('selection_status') == 'budget_excluded':
            old = row.get('reason', '')
            row.update(unknown_cause='evidence_budget_excluded', reason='全库有适用候选，但评分预算未保留；先复核选材，暂不评分。')
            risk['unknowns'] = [note for note in risk.get('unknowns', []) if note != row['name'] + '：' + old]
            risk.setdefault('unknowns', []).append(row['name'] + '：' + row['reason'])
    return risk
