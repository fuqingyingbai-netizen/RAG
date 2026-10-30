"""Two bounded question batches, keeping validated successes independently."""
from copy import deepcopy
import json
import time

from industry_model_output import IndustryModelOutputError, request_deadline

FIELDS = {'question', 'conclusion', 'text', 'evidence_ids', 'claim_kind', 'reasoning', 'premises'}


def plan_batches(package, chapter):
    from industry_fact_contracts import chapter_coverage, bounded_writer_package
    facts = package.get('facts', [])
    if chapter not in {2, 3, 4, 13} or len(facts) <= 12:
        return []
    coverage = chapter_coverage(package, chapter, [f['evidence_id'] for f in facts])
    useful = [q for q in coverage if q['evidence_ids']]
    if len(useful) < 2:
        return []
    middle = (len(useful)+1)//2
    result = []
    for number, questions in enumerate((useful[:middle], useful[middle:]), 1):
        ids = {eid for q in questions for eid in q['evidence_ids'] + q.get('background_evidence_ids', [])}
        # Reserve one direct premise per question, then use the original order.
        order = list(dict.fromkeys([q['evidence_ids'][0] for q in questions]
            + [f['evidence_id'] for f in facts if f['evidence_id'] in ids]))[:12]
        by_id = {f['evidence_id']: f for f in facts}
        batch = {**package, 'facts': [by_id[eid] for eid in order], 'analysis_batch': {
            'index': number, 'total': 2, 'questions': [q['question'] for q in questions]}}
        result.append(json.loads(bounded_writer_package(batch, chapter, 12000)))
    return result


def generate_batches(batches, chapter, title, invoke, emit, trace_emit, *, clock=None):
    from industry_fact_contracts import plan_prompt, parse_chapter_response, validate_analyses
    clock = clock or time.monotonic
    deadline = clock()+90
    ids, claims, rejections, errors, rows, keys, origins = [], [], [], [], [], set(), []
    valid_responses, attempts = 0, 0
    for batch in batches:
        descriptor = batch['analysis_batch']
        row = {'index': descriptor['index'], 'questions': descriptor['questions'], 'status': 'pending'}
        rows.append(row)
        remaining = deadline-clock()
        if remaining < 2:
            row.update(status='skipped', code='chapter_generation_budget_exhausted')
            errors.append({'attempt': attempts, 'batch': descriptor['index'],
                           'code': row['code'], 'kind': 'generation_failure'})
            continue
        timeout = min(45.0, remaining)
        row.update(timeout_seconds=timeout, input_fact_count=len(batch['facts']))
        emit(trace_emit, 'report', 'industry_report_agent', '正在生成本章部分研究问题',
             f'chapter={chapter}; part={descriptor["index"]}/2', status='running')
        try:
            attempts += 1
            with request_deadline(time.monotonic()+timeout):
                raw = invoke(f'行业章节分段编排 Agent - {title} - {descriptor["index"]}/2',
                             plan_prompt(batch, chapter), trace_emit)
            selected, proposed = parse_chapter_response(raw, batch, chapter)
            valid_responses += 1
            allowed_questions = set(descriptor['questions'])
            scoped, foreign = [], []
            for original in proposed:
                if isinstance(original, dict) and original.get('question') in allowed_questions:
                    scoped.append(original)
                else:
                    foreign.append({'question': original.get('question') if isinstance(original, dict) else None,
                        'issues': ['analysis_outside_requested_batch'], 'original_analysis': deepcopy(original)})
            accepted, rejected = validate_analyses(scoped, batch, chapter, selected)
            for claim in accepted:
                key = json.dumps({k:claim.get(k) for k in ('question', 'text', 'evidence_ids')}, sort_keys=True, ensure_ascii=False)
                if key not in keys:
                    claims.append({k:v for k,v in claim.items() if k in FIELDS})
                    origins.append(descriptor['index'])
                    keys.add(key)
            rejections.extend({**r, 'batch':descriptor['index']} for r in rejected+foreign)
            ids.extend(eid for eid in selected if eid not in ids)
            row.update(status='completed', accepted=len(accepted), rejected=len(rejected)+len(foreign))
        except Exception as exc:
            code = exc.code if isinstance(exc, IndustryModelOutputError) else (
                str(exc) if type(exc) is ValueError and str(exc) in {'invalid_statement_plan',
                    'unauthorized_statement_plan', 'empty_statement_plan', 'invalid_analysis_plan'} else type(exc).__name__)
            row.update(status='failed', code=code)
            errors.append({'attempt': attempts, 'batch': descriptor['index'], 'code': code,
                'kind':'generation_failure' if isinstance(exc, IndustryModelOutputError) else 'format_failure'})
        emit(trace_emit, 'report', 'industry_report_agent', '本章部分研究问题处理完成',
             f'chapter={chapter}; part={descriptor["index"]}/2; status={row["status"]}',
             status='done' if row['status']=='completed' else 'warning')
    # An overlong response must not displace every later research question.
    selected, questions_seen = [], set()
    for i, claim in enumerate(claims):
        if claim['question'] not in questions_seen:
            selected.append(i)
            questions_seen.add(claim['question'])
    selected = (selected + [i for i in range(len(claims)) if i not in selected])[:6]
    omitted = [{'question':c['question'], 'evidence_ids':c['evidence_ids'], 'batch':origins[i]}
               for i,c in enumerate(claims) if i not in selected]
    claims = [claims[i] for i in selected]
    for row in rows:
        row['retained'] = sum(origins[i] == row['index'] for i in selected)
    for ordinal, rejected in enumerate(rejections, len(claims)):
        rejected['index'] = ordinal
    return {'ids': ids, 'analyses': claims, 'rejections': rejections, 'errors': errors,
        'attempts': attempts, 'valid': bool(valid_responses), 'diagnostic': {
            'mode':'two_question_batches', 'max_requests':2, 'shared_timeout_seconds':90,
            'max_output_tokens_per_request':3000, 'attempts':attempts, 'batches':rows,
            'omitted_valid_analyses': omitted,
            'partial_failure': bool(errors) and bool(claims),
            'elapsed_ms':max(0, int((clock()-(deadline-90))*1000))}}
