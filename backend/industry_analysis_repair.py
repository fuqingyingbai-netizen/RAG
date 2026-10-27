"""One bounded repair of rejected analysis; approved prose and evidence stay fixed."""
from copy import deepcopy
import json
import os
from threading import Lock

from industry_reasoning import fingerprint

MAX_INPUT_CHARS = 18000
_BUDGET_LOCK = Lock()


def _max_calls():
    try:
        return max(0, min(3, int(os.getenv('INDUSTRY_ANALYSIS_REPAIR_MAX_CALLS', '2'))))
    except ValueError:
        return 2


def repair_packet(package, chapter, ids, rejections):
    from industry_fact_contracts import chapter_admitted, chapter_coverage
    facts = {f['evidence_id']: f for f in package.get('facts', [])
             if f.get('evidence_id') in ids and chapter_admitted(f, chapter)}
    questions = {q['question']: q for q in chapter_coverage(package, chapter, ids)}
    packet = {'chapter': chapter, 'failed_analyses_not_evidence': [], 'cards': {}}
    requested = []
    for rejected in rejections:
        original = rejected.get('original_analysis')
        if len(requested) >= 3 or not isinstance(original, dict) or original.get('question') not in questions:
            continue
        q = questions[original['question']]
        refs = original.get('evidence_ids')
        refs = [eid for eid in refs if isinstance(eid, str)] if isinstance(refs, list) else []
        order = list(dict.fromkeys(q['evidence_ids'] + q['background_evidence_ids'] + refs))
        # A repair sees licensed statements only, never source tails, original
        # model facts or diagnostics as writing evidence.
        cards = dict(packet['cards'])
        for eid in order[:4]:
            if eid not in facts:
                continue
            f = facts[eid]; c = f['fact_contract']
            cards[eid] = {'statement': c['statement'], 'sample_boundary': c.get('sample_boundary'),
                'source_role': c.get('source_role'), 'material_kind': c.get('material_kind'),
                'numeric_context': f.get('numeric_context') or {}}
        record = {'index': rejected['index'], 'question': original['question'],
            'failed_analysis': original, 'issues': rejected.get('issues', []),
            'details': rejected.get('details', []),
            'direct_ids': q['evidence_ids'], 'background_ids': q['background_evidence_ids']}
        candidate = {**packet, 'cards': cards,
            'failed_analyses_not_evidence': packet['failed_analyses_not_evidence'] + [record]}
        if len(json.dumps(candidate, ensure_ascii=False)) + 150 > MAX_INPUT_CHARS:
            continue
        packet = candidate
        requested.append(rejected['index'])
    packet['request_fingerprint'] = fingerprint(packet)
    return packet, requested


def repair_analyses(project, package, chapter, ids, accepted, rejected, invoke, emit, trace_emit, role):
    """The whole report defaults to two requests; each chapter gets at most one."""
    diagnostic = {'attempted': False, 'attempts': 0, 'requested': [], 'repaired': [],
        'remaining': [r['index'] for r in rejected], 'status': 'not_needed',
        'initial_rejections': deepcopy(rejected)}
    if not rejected:
        return accepted, rejected, diagnostic
    packet, requested = repair_packet(package, chapter, ids, rejected)
    if not requested or not packet['cards']:
        diagnostic['status'] = 'no_repairable_packet'
        return accepted, rejected, diagnostic
    with _BUDGET_LOCK:
        budget = getattr(project, 'industry_analysis_repair_budget', None)
        if budget is None:
            budget = {'requests_used': 0, 'chapters': []}
            project.industry_analysis_repair_budget = budget
        if chapter in budget['chapters'] or budget['requests_used'] >= _max_calls():
            diagnostic['status'] = 'request_budget_exhausted'
            return accepted, rejected, diagnostic
        budget['requests_used'] += 1
        budget['chapters'].append(chapter)
    diagnostic.update(attempted=True, attempts=1, requested=requested,
        input_chars=len(json.dumps(packet, ensure_ascii=False)), request_fingerprint=packet['request_fingerprint'])
    prompt = ('只修复列出的失败段落，不改章节、研究问题或已通过段落。失败原文仅作修改对象，不能作为事实依据。'
        '仅引用cards中实际保留的编号、完整statement及其已授权数值；不新增资料、数值或法律义务。'
        '可改正格式、引用和适用范围；证据不够时仅说明本章所引材料的缺口，claim_kind用limitation，'
        '不能把样本写成行业结论，不能把预测写成实际。每段60至180字，不输出标题、换行、网址或正文引用标记。'
        '返回严格JSON：{"request_fingerprint":"原样回传", "repairs":[{"index":原索引,'
        '"analysis":{"question":"原问题", "text":"修正分析", "evidence_ids":["卡片编号"],'
        '"claim_kind":"comparison或inference或conditional或limitation",'
        '"reasoning":"从前提到判断及限制"}}]}。逐字前提由程序按编号绑定，不必返回premises。不能修复的段落不返回；至多一次请求。\n'
        + json.dumps(packet, ensure_ascii=False))
    emit(trace_emit, 'report', 'industry_report_agent', '正在修正未通过校验的分析段落',
        f'chapter={chapter}; analyses={len(requested)}', status='running')
    try:
        raw = invoke(role, prompt, trace_emit)
        from industry_fact_contracts import validate_analyses
        import re
        response = json.loads(re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip(), flags=re.I))
        if (not isinstance(response, dict) or set(response) != {'request_fingerprint', 'repairs'}
                or response['request_fingerprint'] != packet['request_fingerprint']
                or not isinstance(response['repairs'], list) or len(response['repairs']) > len(requested)):
            raise ValueError('invalid_repair_response')
        originals = {r['index']: r['original_analysis'] for r in rejected}
        seen, repaired, failures = set(), {}, []
        for record in response['repairs']:
            if (not isinstance(record, dict) or set(record) != {'index', 'analysis'}
                    or type(record['index']) is not int or record['index'] not in requested
                    or record['index'] in seen):
                raise ValueError('invalid_repair_index')
            ordinal = record['index']; seen.add(ordinal); claim = record['analysis']
            if not isinstance(claim, dict) or claim.get('question') != originals[ordinal]['question']:
                raise ValueError('changed_repair_question')
            if not {'premises', 'claim_kind', 'reasoning'} <= set(claim):
                raise ValueError('missing_repair_premises')
            # Validate against the actually retained packet, not wider chapter IDs.
            valid, errors = validate_analyses([claim], package, chapter, list(packet['cards']))
            if valid:
                repaired[ordinal] = {**valid[0], 'analysis_index': ordinal, 'repair_of_index': ordinal}
            else:
                failures.extend({**error, 'index': ordinal} for error in errors)
        remaining = [r for r in rejected if r['index'] not in repaired]
        def content_key(claim):
            return fingerprint({k: claim.get(k) for k in ('question', 'text', 'evidence_ids')})
        keys = {content_key(c) for c in accepted}
        additions, duplicates = [], []
        for ordinal, claim in repaired.items():
            key = content_key(claim)
            if key in keys:
                duplicates.append(ordinal)
            else:
                additions.append(claim)
                keys.add(key)
        merged = sorted(accepted + additions, key=lambda c: c.get('analysis_index', -1))
        diagnostic.update(repaired=list(repaired), remaining=[r['index'] for r in remaining],
            duplicate_repairs_omitted=duplicates, validation_rejections=failures,
            status='complete' if not remaining else 'partial' if repaired else 'rejected')
        emit(trace_emit, 'report', 'industry_report_agent', '分析段落局部修复已结束',
            f'chapter={chapter}; repaired={len(repaired)}; remaining={len(remaining)}', status='done')
        return merged, remaining, diagnostic
    except Exception as exc:
        diagnostic.update(status='failed', error_type=type(exc).__name__)
        emit(trace_emit, 'report', 'industry_report_agent', '分析段落未能修复，保留有效材料待人工复核',
            f'chapter={chapter}; error={type(exc).__name__}', status='warning')
        return accepted, rejected, diagnostic
