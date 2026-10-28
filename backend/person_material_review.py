"""Read all admitted chapter material before producing a concise report.

Research input is batched without truncation. Final prose and illustrative
source excerpts have separate budgets. Delivery to a model is never called
independent verification, and unused cards are not counted as body citations.
"""
import json
import os
import re
import time
from person_prose_budget import analysis_budget, compact_draft


def writing_cards(facts):
    """One complete original per card; omit only redundant proof metadata."""
    from person_text import folded
    result=[]
    for f in facts:
        original=f['fact'];record=f.get('observation') or {}
        def compact_metadata(value):
            if isinstance(value,list):return [compact_metadata(v) for v in value]
            if not isinstance(value,dict):return value
            return {k:compact_metadata(v) for k,v in value.items() if not (
                k in {'source_quote','quote','original','evidence_quote'} and isinstance(v,str)
                and folded(v) in folded(original))}
        card={k:f.get(k,'') for k in ('evidence_id','fact','source_url','source_title','source_document_issuer',
            'source_document_kind','source_reporting_period_literal','attribution_boundary','subject','subject_scope',
            'source_grade','provider','published_at','retrieved_at','event_date','source_text_issue','opinion_only','temporal_conflict')}
        card.update(personal_analysis_allowed=bool(f.get('personal_analysis_allowed',f.get('analysis_allowed',False))),
            period=f.get('period',record.get('period','')),metrics=compact_metadata(f.get('metrics',record.get('metrics',[]))),
            role_dates=compact_metadata(f.get('role_dates',record.get('role_date_fields',[]))),
            source_events=compact_metadata(f.get('source_events',record.get('source_events',[]))),
            source_named_person=f.get('source_named_person',record.get('source_named_person','')),
            eligible_for_risk_scoring=False)
        if record.get('actor_context'):
            card['source_actor_context'] = compact_metadata(record['actor_context'])
        result.append(card)
    return result


def writing_input_for(package,facts):
    clues=package.get('identity_clues_not_facts',{})
    return {'chapter':package['chapter'],'title':package['title'],'task':package.get('task',''),
        **({'user_requirements': [{k:r[k] for k in ('requirement_id','question','expected_evidence')}
                                  for r in package['user_requirements']]}
           if package.get('user_requirements') else {}),
        'research_questions':[row['view'] for row in package.get('material_coverage',[])],
        'identity_clues_not_facts':{k:clues.get(k,[]) for k in ('aliases','known_affiliations','identity_anchors','roles','supplementary_context')},
        'facts':writing_cards(facts),
        **({'commission_questions':[{k:r[k] for k in ('question','questions') if k in r} for r in package['commission_coverage']]}
           if package.get('commission_coverage') else {})}


def material_batches(rows, max_chars=14000):
    batches, current, used = [], [], 0
    for row in rows:
        size = len(json.dumps(row, ensure_ascii=False))
        if current and used+size > max_chars:
            batches.append(current)
            current, used = [], 0
        current.append(row)
        used += size
    if current:
        batches.append(current)
    return batches


def _parsed(answer):
    try:
        result = json.loads(re.sub(r'^```(?:json)?\s*|\s*```$', '', str(answer).strip()))
        return result if isinstance(result, dict) and isinstance(result.get('claims'), list) else None
    except (ValueError, TypeError):
        return None


def read_then_write(role, prefix, writing_input, package, invoke, emit, validate):
    """Return a source-bound final draft plus auditable, complete input batches."""
    package['require_material_dispositions']=True
    writing_input={**writing_input,'facts':writing_cards(writing_input['facts'])}
    try:
        max_chars = max(4000, min(40000, int(os.getenv('PERSON_RESEARCH_BATCH_CHARS', '14000'))))
    except ValueError:
        max_chars = 14000
    batches = material_batches(writing_input['facts'], max_chars)
    audit = {'version': 'complete-material-review-v3', 'status': 'started',
             'input_evidence_ids': [r['evidence_id'] for r in writing_input['facts']],
             'batches': [], 'proposed_findings': [], 'omitted_for_input_budget': [],
             'boundary': 'model_input_delivery_and_validation_are_not_independent_truth_verification'}
    package['material_review'] = audit
    writing_note = (f'现在写本章正文，分析合计不超过{analysis_budget(writing_input.get("chapter"))}字符，'
                    '不含证据编号；不限制分析条数或来源数量。合并同类事项并引用实际支撑的各来源，保留时期、条件及相反材料。\n')
    if len(batches) <= 1:
        audit['batches'].append({'batch': 1, 'evidence_ids': audit['input_evidence_ids'], 'status': 'requested'})
        try:
            result = invoke(role, prefix+writing_note+json.dumps(writing_input, ensure_ascii=False), emit)
            audit['batches'][0]['status'] = 'returned' if _parsed(result) is not None else 'invalid_structured_response'
            audit['status'] = 'returned' if _parsed(result) is not None else 'invalid_structured_response'
            if _parsed(result) is not None and not any(f.get('analysis_allowed') for f in package['research_facts']):
                audit['context_only'] = True
                audit['ignored_interpretation_count'] = sum(bool(c.get('analysis')) for c in _parsed(result)['claims'] if isinstance(c, dict))
                audit['boundary'] += ';context_interpretations_never_adopted'
                return '{"claims":[]}', 1
            result, extra = compact_draft(result, role, prefix, writing_input, invoke, emit, audit)
            return result, 1+extra
        except Exception:
            audit['batches'][0]['status'] = audit['status'] = 'failed'
            raise
    proposals, recovery_material, requests = [], [], 0
    for i, batch in enumerate(batches, 1):
        event = {'batch': i, 'evidence_ids': [r['evidence_id'] for r in batch], 'status': 'requested'}
        audit['batches'].append(event)
        started = time.monotonic()
        batch_input = {**writing_input, 'facts': batch}
        batch_note = (f'这是完整研究材料的第{i}/{len(batches)}批。逐条考虑材料，合并同类证据，'
            '同时检查反例、相反陈述、不同任期与不同机构。先形成该批最有实质信息的研究判断，'
            '研读阶段不限制判断条数或分析总字数，不提前按成文篇幅舍弃不同事项、反例或矛盾；'
            '最终正文会在全部批次完成后综合压缩。没有判断可以返回空claims，不能编造信息补齐。\n')
        try:
            requests += 1
            answer = invoke(role+f'资料研读{i}/{len(batches)}', prefix+batch_note+json.dumps(batch_input,ensure_ascii=False), emit)
        except Exception:
            event['status'] = audit['status'] = 'failed'
            raise
        finally:
            event['elapsed_seconds'] = round(time.monotonic()-started,3)
        parsed = _parsed(answer)
        if parsed is None:
            event['status'] = audit['status'] = 'invalid_structured_response'
            # An unreadable batch cannot silently disappear behind a concise
            # final draft; the outer writer records a failed research stage.
            raise ValueError('invalid_research_batch_response')
        allowed = {r['evidence_id'] for r in batch}
        batch_package = {**package, 'facts': [f for f in package['research_facts']
            if f['evidence_id'] in allowed and f.get('analysis_allowed')]}
        accepted, rejected = validate(answer, batch_package)
        event.update(status='returned', validation_rejections=rejected,
                     valid_findings=sum(bool(c.get('analysis')) for c in accepted))
        for claim in accepted:
            audit['proposed_findings'].append({**claim, 'batch': i})
            if claim.get('analysis'):
                proposals.append({'evidence_ids':claim['evidence_ids'], 'analysis':claim['analysis']})
            elif claim.get('evidence_ids'):
                # A rejected interpretation does not erase admissible source
                # facts. Keep original cards available for final synthesis.
                recovery_material.append({'evidence_ids':claim['evidence_ids'],
                    'rejected_interpretation_reasons':list(rejected),
                    'status':'original_material_retained_interpretation_rejected'})
    audit['status'] = 'all_batches_returned'
    # Every source statement has now reached a research batch. Only this final
    # writing stage is concise; an earlier source count does not ration reading.
    if not any(f.get('analysis_allowed') for f in package['research_facts']):
        audit['synthesis'] = {'status':'no_valid_analysis_proposals','requests':0}
        return '{"claims":[]}', requests
    support_ids = {eid for p in [*proposals,*recovery_material] for eid in p['evidence_ids']}
    final_input = {**writing_input,
                   'research_findings':proposals,'material_with_rejected_interpretations':recovery_material}
    note = (writing_note+'全部批次的研究候选已完成。facts仍包含完整原始材料，不只包含候选判断选中的证据。'
            '研读候选未引用的材料仍须考虑，不能将未被选中视为没有价值或已经否定。合并重复，'
            '结合research_questions优先保留不同问题已有的具体事项；授权、组织变动与接班等不同事项不要全部压成单一主题。'
            'material_with_rejected_interpretations中的原始材料仍须考虑：被拒绝的是此前的解释，不能因解释错误就遗漏有效原文。'
            '根据拒绝原因重新读原文，出版年份不当作实施年份、辞职威胁不当作已辞职、指令不当作已执行；无需为每条材料强写推断。'
            '不要先总括学历履历再用两条分别重复，同一事项只说明一次；优先保留不同问题的实质信息，所用来源合并引用。'
            '保留有实质影响的不同机构、历史变化、反例及矛盾。候选判断尚未独立核实，'
            '必须重新依据facts原句检查，不可将多个候选拼成更强的结论。'
            '控制正文篇幅，不因来源多堆砌原文；来源内已有的限制、回应和不同主体行为必须保留。\n')
    audit['synthesis'] = {'status':'requested','requests':1,'proposal_count':len(proposals),
                          'retained_rejected_interpretation_material':recovery_material,
                          'support_evidence_ids':sorted(support_ids),
                          'input_evidence_ids':list(audit['input_evidence_ids']),
                          'omitted_original_evidence_ids':[]}
    try:
        requests += 1
        result = invoke(role+'综合写作', prefix+note+json.dumps(final_input,ensure_ascii=False), emit)
        audit['synthesis']['status'] = 'returned'
        result, extra = compact_draft(result, role, prefix, final_input, invoke, emit, audit)
        requests += extra
        return result, requests
    except Exception:
        audit['synthesis']['status'] = audit['status'] = 'failed'
        raise


def presentation_facts(package, claims, max_records=None, max_chars=1600):
    """Budget illustrative original quotations after complete research."""
    def quote_key(fact):
        # Ignore only edge quotation punctuation for duplicate detection;
        # displayed originals and their literal validation remain unchanged.
        return re.sub(r'\s+','',fact['fact']).strip('“”"‘’\'。')
    by_id={f['evidence_id']:f for f in package.get('research_facts', package['facts'])}
    required=[{**by_id[r['evidence_id']],'fact':r['quote'],'full_original_in_appendix':True}
              for r in package.get('required_source_displays',[]) if r['evidence_id'] in by_id
              and r['quote'] in by_id[r['evidence_id']]['fact']]
    ordered=[]
    # Prefer one support per distinct finding before filling with additional
    # cards. Three near-identical biographies must not crowd out a different
    # event merely because the first finding cites all three.
    active = [c for c in claims if c.get('analysis')]
    for claim in active:
        first = next((by_id[eid] for eid in claim['evidence_ids'] if eid in by_id and by_id[eid] not in ordered), None)
        if first is not None:
            ordered.append(first)
    for claim in active:
        if not claim.get('analysis'):
            continue
        for eid in claim['evidence_ids']:
            if eid in by_id and by_id[eid] not in ordered:
                ordered.append(by_id[eid])
    ordered += [f for f in package['facts'] if f not in ordered]
    required_ids={f['evidence_id'] for f in required}
    ordered=required+[f for f in ordered if f['evidence_id'] not in required_ids]
    # Display a complete containing excerpt once. Nested cards stay in the
    # research/claim ledger and keep their own citations, but do not consume a
    # second illustrative quotation slot merely for one extra closing mark.
    ordered = [fact for fact in ordered if fact in required or not any(
        other is not fact and (other['source_url']==fact['source_url'] or len(quote_key(fact))>=80)
        and len(other['fact'])<=max_chars
        and len(quote_key(other))>len(quote_key(fact))
        and quote_key(fact) in quote_key(other)
        for other in ordered)]
    chosen,used,originals=[],0,set()
    for fact in ordered:
        if max_records is not None and len(chosen)>=max_records:
            break
        size=len(fact['fact'])
        canonical = quote_key(fact)
        key = canonical if len(canonical)>=80 else (fact['source_url'], canonical)
        mandatory=fact in required
        if mandatory and any(g['evidence_id']==fact['evidence_id'] and fact['fact'] in g['fact'] for g in chosen):
            continue
        if not mandatory and key in originals:
            continue
        if used+size>max_chars:
            continue
        chosen.append(fact)
        originals.add(key)
        used+=size
    package['quotation_budget'] = {'max_chars': max_chars, 'max_records': max_records,
        'displayed_chars':used, 'displayed_evidence_ids':[f['evidence_id'] for f in chosen],
        'undisplayed_evidence_ids':[eid for eid in by_id if eid not in {f['evidence_id'] for f in chosen}],
        'boundary':'not_displayed_is_not_rejected_or_unused_as_analysis_support;complete_originals_remain_in_evidence_ledger'}
    package['quotation_budget']['required_undisplayed_evidence_ids']=sorted({f['evidence_id'] for f in required
        if not any(f['evidence_id']==g['evidence_id'] and f['fact'] in g['fact'] for g in chosen)})
    return chosen
