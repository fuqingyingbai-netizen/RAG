"""Read all admitted chapter material before producing a concise report.

Research input is batched without truncation. Final prose and illustrative
source excerpts have separate budgets. Delivery to a model is never called
independent verification, and unused cards are not counted as body citations.
"""
import json
import os
import re
import time


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
    try:
        max_chars = max(4000, min(40000, int(os.getenv('PERSON_RESEARCH_BATCH_CHARS', '14000'))))
    except ValueError:
        max_chars = 14000
    batches = material_batches(writing_input['facts'], max_chars)
    audit = {'version': 'complete-material-review-v1', 'status': 'started',
             'input_evidence_ids': [r['evidence_id'] for r in writing_input['facts']],
             'batches': [], 'proposed_findings': [], 'omitted_for_input_budget': [],
             'boundary': 'model_input_delivery_and_validation_are_not_independent_truth_verification'}
    package['material_review'] = audit
    if len(batches) <= 1:
        audit['batches'].append({'batch': 1, 'evidence_ids': audit['input_evidence_ids'], 'status': 'requested'})
        try:
            result = invoke(role, prefix+json.dumps(writing_input, ensure_ascii=False), emit)
            audit['batches'][0]['status'] = 'returned' if _parsed(result) is not None else 'invalid_structured_response'
            audit['status'] = 'returned' if _parsed(result) is not None else 'invalid_structured_response'
            return result, 1
        except Exception:
            audit['batches'][0]['status'] = audit['status'] = 'failed'
            raise
    by_id = {r['evidence_id']:r for r in writing_input['facts']}
    proposals, requests = [], 0
    for i, batch in enumerate(batches, 1):
        event = {'batch': i, 'evidence_ids': [r['evidence_id'] for r in batch], 'status': 'requested'}
        audit['batches'].append(event)
        started = time.monotonic()
        batch_input = {**writing_input, 'facts': batch}
        batch_note = (f'这是完整研究材料的第{i}/{len(batches)}批。逐条考虑材料，合并同类证据，'
            '同时检查反例、相反陈述、不同任期与不同机构。先形成该批最有实质信息的研究判断，'
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
    audit['status'] = 'all_batches_returned'
    # Every source statement has now reached a research batch. Only this final
    # writing stage is concise; an earlier source count does not ration reading.
    if not proposals:
        audit['synthesis'] = {'status':'no_valid_analysis_proposals','requests':0}
        return '{"claims":[]}', requests
    support_ids = {eid for p in proposals for eid in p['evidence_ids']}
    final_input = {**writing_input, 'facts':[by_id[eid] for eid in by_id if eid in support_ids],
                   'research_findings':proposals}
    note = ('全部批次的研究候选已完成。现在综合压缩为最多3条简短判断，合并重复，'
            '保留有实质影响的不同机构、历史变化、反例及矛盾。候选判断尚未独立核实，'
            '必须重新依据facts原句检查，不可将多个候选拼成更强的结论。'
            '控制正文篇幅，不因来源多堆砌原文；来源内已有的限制、回应和不同主体行为必须保留。\n')
    audit['synthesis'] = {'status':'requested','requests':1,'proposal_count':len(proposals),
                          'support_evidence_ids':sorted(support_ids)}
    try:
        requests += 1
        result = invoke(role+'综合写作', prefix+note+json.dumps(final_input,ensure_ascii=False), emit)
        audit['synthesis']['status'] = 'returned'
        return result, requests
    except Exception:
        audit['synthesis']['status'] = audit['status'] = 'failed'
        raise


def presentation_facts(package, claims, max_records=4, max_chars=1600):
    """Budget illustrative original quotations after complete research."""
    by_id={f['evidence_id']:f for f in package.get('research_facts', package['facts'])}
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
    chosen,used=[],0
    for fact in ordered:
        if len(chosen)>=max_records:
            break
        size=len(fact['fact'])
        if chosen and used+size>max_chars:
            continue
        chosen.append(fact)
        used+=size
    return chosen
