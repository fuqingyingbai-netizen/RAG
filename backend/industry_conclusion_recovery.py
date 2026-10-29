"""Progress-aware per-question recovery. Never search generated assertions.

Execution failures retry existing evidence; genuine research gaps collect new
sources through the normal admission pipeline. All helpers are offline-testable.
"""
from copy import deepcopy
import hashlib
import json
import os
import re

VERSION = 'industry-conclusion-recovery-v6-analysis-development'
MAX_QUERIES = 4
MAX_NEW_SOURCES = 12


def recovery_limits():
    defaults = {'collect_evidence': 3, 'rewrite_conclusion': 3, 'narrow_conclusion': 2,
                'retry_generation': 2, 'total': 6, 'no_progress': 2}
    limits = {}
    for key, default in defaults.items():
        try:
            value = int(os.getenv('INDUSTRY_RECOVERY_' + key.upper(), str(default)))
        except ValueError:
            value = default
        limits[key] = max(1, min(value, 12))
    return limits


def task_key(task):
    return str(task['chapter']) + ':' + task['question']


def finding_issue(claim):
    """Detect only explicit non-answers, not semantic adequacy in general.

    Positive matches schedule a rewrite, never authorize a claim or discard a
    source. Substantive conditional findings remain available for human review.
    """
    from industry_answer_quality import contribution_issue
    if claim.get('source_observation_only'):
        return 'source_observation_needs_analysis'
    from industry_draft_policy import question_alignment_issue
    alignment = question_alignment_issue(claim)
    if alignment:
        return alignment
    if claim.get('development_warning'):
        return claim['development_warning']
    if claim.get('partial_parent_claim_id'):
        return 'partial_support_remains'
    verdict=claim.get('support_review',{})
    if verdict.get('answer_quality')=='scope_only' or claim.get('answer_quality_warning'):
        if not (verdict.get('status')=='supported' and verdict.get('answer_quality')=='answered'):
            return claim.get('answer_quality_warning') or 'scope_only_answer'
    if verdict.get('status')=='supported' and verdict.get('answer_quality')=='answered':
        return None
    if claim.get('partial_answer'):
        return 'partial_support_remains'
    quality = contribution_issue(claim)
    if quality:
        return quality
    finding = str(claim.get('conclusion') or '').strip()
    if not finding:
        return 'missing_finding'
    if re.fullmatch(r'(?:本章|所引|现有|上述|这些)(?:材料|资料|证据|条款|内容|来源)?.{0,100}'
                    r'(?:尚待|仍需|需要)(?:进一步)?(?:人工)?(?:核验|复核|研究|分析)[。！]?', finding):
        if not re.search(r'因此|意味着|取决于|依赖|需要区分|应优先|适用于|在.{1,30}条件下', finding):
            return 'only_review_notice'
    if finding in {'本章列示已准入陈述及材料支持的比较和边界分析。',
                   '本章初步判断及其依据如下，适用条件和推理仍需人工复核。'}:
        return 'only_review_notice'
    return None


def recovery_plan(plans, packages, scope=None):
    from industry_question_generation import CHAPTERS, compile_jobs
    from industry_fact_contracts import CHAPTER_QUESTIONS
    tasks = []
    for chapter in sorted(CHAPTERS):
        if chapter not in plans and str(chapter) not in plans and chapter not in packages and str(chapter) not in packages:
            continue
        plan = plans.get(chapter, plans.get(str(chapter), {}))
        canonical = {q for q, _ in CHAPTER_QUESTIONS.get(chapter, [])}
        claims = plan.get('analysis_claims', [])
        answered = {c.get('question') for c in claims if not finding_issue(c)}
        nonanswers = {c.get('question'):finding_issue(c) for c in claims if finding_issue(c)}
        generation = plan.get('generation_batches', {})
        decisions = generation.get('questions', [])
        if not decisions:
            package = packages.get(chapter, packages.get(str(chapter), {}))
            if isinstance(package, str):
                package = json.loads(package)
            _, diagnostic = compile_jobs(package or {}, chapter)
            decisions = diagnostic['questions']
        rejected = {r.get('question'): r for r in plan.get('active_analysis_rejections', plan.get('analysis_rejections', []))}
        for d in decisions:
            question, state = d.get('question'), d.get('status')
            if question not in canonical or question in answered:
                continue
            # API/format/budget failures never masquerade as missing sources.
            collect = state in {'material_gap', 'model_abstained'}
            # An overclaim must be narrowed to its existing premises, not
            # searched for until a supporting webpage happens to be found.
            issue_codes=list(dict.fromkeys(rejected.get(question,{}).get('issues',[])+d.get('issue_codes',[])))
            if d.get('quality_issue'):issue_codes.append('answer_quality_'+d['quality_issue'])
            if nonanswers.get(question):
                issue_codes.append('answer_quality_'+nonanswers[question])
            support_rejected = any(code.startswith('claim_support_') for code in issue_codes) or nonanswers.get(question)=='partial_support_remains'
            evidence_revision = any(code.startswith(('analysis_unauthorized_','analysis_sample_')) or code in {
                'invalid_analysis_citations','invalid_question_answer_or_references','analysis_question_evidence_mismatch',
                'sample_extrapolation_unsupported','bounded_levels_as_growth','business_screening_rule_unsupported',
                'invalid_claim_premises'} for code in issue_codes)
            shallow = bool(re.search(r'只复述|只罗列|未回答|没有回答|缺少.*(?:比较|业务含义)',
                rejected.get(question, {}).get('support_review', {}).get('reason', ''))) or any(
                    code.startswith('answer_quality_') for code in issue_codes)
            if question in rejected or (question in nonanswers and nonanswers[question]!='source_observation_needs_analysis'):
                collect = False
            if state == 'model_abstained' and nonanswers.get(question) in {'actual_payment_not_answered','policy_dates_not_demand_evidence'}:
                collect = True
            action = ('collect_evidence' if collect else 'retry_generation' if state=='generation_failed' else 'narrow_conclusion' if support_rejected or evidence_revision else
                      'rewrite_conclusion' if shallow or question in nonanswers else 'retry_generation')
            detail = rejected.get(question,{})
            support=detail.get('support_review',{})
            feedback='；'.join(str(x) for x in (support.get('reason'),support.get('answer_quality_reason'),
                detail.get('quality_reason'),d.get('reason'),d.get('code')) if x)
            from industry_draft_policy import alignment_feedback
            alignment_reason = alignment_feedback(nonanswers.get(question))
            if alignment_reason:
                feedback = alignment_reason + ('；' + feedback if feedback else '')
            if not feedback and issue_codes:
                feedback='请逐项修正：'+ '、'.join(issue_codes)
            if not feedback:
                issue_codes.append(state or 'missing_analysis')
                feedback = {
                    'answer_missing': '上次请求已结束，但返回结果缺少本题。请使用本题已给原文单独返回完整回答或具体缺失前提，不重新选择其他问题。',
                    'duplicate_answer': '上次返回重复问题编号，未取得本题唯一可用回答。请仅返回本题一次，保持问题编号与引用在本题授权范围内。',
                    'invalid_answer': '上次本题返回结构不完整。请按本题给定格式返回完整正文与引用，不能用空答案或其他题的编号替代。',
                    'deferred_request_budget': '本题尚未获得独立写作请求，优先使用已有原文作答；不要把等待写作误判为资料缺失。',
                    'material_gap': '本题尚无可用前提。请按问题所需的主体、指标和适用条件补充原始资料，不检索上一稿未经支持的推断。',
                }.get(state, '本题尚未形成可用判断。请对照已有原文回答当前问题，若仍无法作答，明确列出缺失的具体前提。')
            if detail.get('details'):
                feedback+='；具体校验项：'+json.dumps(detail['details'],ensure_ascii=False)[:200]
            revision = detail.get('original_analysis')
            if not isinstance(revision,dict):
                revision=next((c for c in claims if c.get('question')==question and finding_issue(c)),None)
            tasks.append({'chapter': chapter, 'question': question,
                          'action': action,
                          'issue_codes': list(dict.fromkeys(issue_codes)),
                          'feedback': feedback[:500],
                          **({'revision_draft':{k:v for k,v in revision.items()
                              if k in {'conclusion','text','evidence_ids','claim_kind'}}} if isinstance(revision,dict) else {}),
                          'cause': nonanswers.get(question) or ('support_rejected' if support_rejected else
                                   'validation_rejected' if question in rejected else state or 'missing_analysis')})
    return {'version': VERSION, 'limits': recovery_limits(), 'tasks': tasks,
            'chapters': sorted({t['chapter'] for t in tasks}), 'max_queries': MAX_QUERIES,
            'max_new_sources': MAX_NEW_SOURCES, 'generation_deadline_seconds': None}


def targeted_queries(plan, target, previous=()):
    """Only fixed template questions enter search, never a rejected model claim."""
    from industry_fact_contracts import CHAPTER_QUESTIONS
    from report_agents.industry_template import INDUSTRY_REPORT_OUTLINE
    from industry_research import CHAPTER_MODULES
    seen = {' '.join(str(q).lower().split()) for q in previous}
    rows = []
    # Round-robin across chapters so a single chapter cannot take every query.
    groups = {}
    for t in plan['tasks']:
        if t['action'] == 'collect_evidence' and t['question'] in dict(CHAPTER_QUESTIONS.get(t['chapter'], [])):
            groups.setdefault(t['chapter'], []).append(t)
    while groups and len(rows) < MAX_QUERIES:
        for chapter in list(groups):
            t = groups[chapter].pop(0)
            if not groups[chapter]:
                del groups[chapter]
            # Try distinct, fixed research angles; never search the rejected assertion.
            for angle in ('原始数据 研究报告', '原文 统计口径 适用条件', '实测 对比 研究方法'):
                query = f'{str(target)[:120]} {t["question"]} {angle}'
                key = ' '.join(query.lower().split())
                if key in seen:
                    continue
                seen.add(key)
                title = INDUSTRY_REPORT_OUTLINE[chapter-1][0]
                rows.append({'query': query, 'module': next(iter(CHAPTER_MODULES.get(title, (title,)))),
                             'chapter': chapter, 'question': t['question'], 'recovery_round': plan.get('round', 1)})
                break
            if len(rows) == MAX_QUERIES:
                break
    return rows


def merge_evidence(original, addition):
    """Append new admitted facts; old E-IDs and original body snapshots are immutable."""
    from industry_evidence import fact_coverage
    from industry_reasoning import question_ledger
    from industry_fact_contracts import CHAPTER_QUESTIONS
    merged = deepcopy(original)
    seen = {f.get('evidence_id') for f in merged.get('facts', [])}
    snapshots = addition.get('source_body_snapshots', {})
    old_snapshots = original.get('source_body_snapshots', {})
    conflicting_snapshots = {k for k,v in snapshots.items() if k in old_snapshots and v != old_snapshots[k]}
    added = [f for f in addition.get('facts', []) if f.get('evidence_id') and f['evidence_id'] not in seen
             and f.get('eligible_for_report') is not False
             and f.get('fact_contract', {}).get('report_admitted') is True
             and (f.get('provenance', {}).get('locator', {}).get('status') == 'verified')
             and f.get('provenance', {}).get('locator', {}).get('snapshot_key') not in conflicting_snapshots]
    for f in added:
        if f['evidence_id'] not in seen:
            merged.setdefault('facts', []).append(deepcopy(f))
            seen.add(f['evidence_id'])
    for key, body in addition.get('source_body_snapshots', {}).items():
        merged.setdefault('source_body_snapshots', {}).setdefault(key, deepcopy(body))
    facts = merged.get('facts', [])
    merged['provenance_summary'] = {
        'total_fact_count': len(facts),
        'located_fact_count': sum(f.get('provenance', {}).get('locator', {}).get('status') == 'verified' for f in facts),
        'quarantined_fact_count': sum(f.get('provenance', {}).get('locator', {}).get('status') != 'verified' for f in facts),
        'index_eligible_fact_count': sum(f.get('eligible_for_report') is not False for f in facts)}
    merged['evidence_coverage'] = fact_coverage(facts, merged.get('evidence_requirements', []))
    merged['fact_contract_summary'] = {
        'report_admitted': sum(bool(f.get('fact_contract', {}).get('report_admitted')) for f in facts),
        'risk_admitted': sum(bool(f.get('fact_contract', {}).get('risk_admitted')) for f in facts),
        'held_for_review': sum(not f.get('fact_contract', {}).get('report_admitted') for f in facts),
        'semantic_status': 'not_evaluated'}
    merged['research_questions'] = {str(i): question_ledger(merged, i, [f['evidence_id'] for f in facts]) for i in CHAPTER_QUESTIONS}
    merged['conclusion_recovery'] = {'version': VERSION, 'added_fact_count': len(facts)-len(original.get('facts', [])),
        'incremental_cleaning_diagnostic': addition.get('cleaning_diagnostic', {})}
    return merged


def snapshot(project):
    return deepcopy({name: getattr(project, name, {}) for name in (
        'industry_statement_plans', 'industry_section_packages', 'industry_generated_sections',
        'industry_report_degradations', 'industry_claim_support_review', 'industry_question_order',
        'industry_question_planning', 'industry_verification_tasks', 'industry_risk_transparency',
        'industry_independent_review')})


def vague_rejection(review):
    if review.get('status') not in {'partial', 'unsupported', 'contradicted'}:
        return False
    reason = re.sub(r'[\s，。；、：,.!！]', '', review.get('reason', ''))
    return reason in {'证据不足无法支持该结论', '材料不足无法支持该判断', '所引证据不足以支持结论',
                      '结论缺少充分依据需要进一步核验', '证据不足结论不成立'}


def refresh_review_counts(review, claims):
    from collections import Counter, defaultdict
    from industry_reasoning import REVIEW_STATES
    coverage = defaultdict(lambda: {'total':0, 'submitted':0, 'valid':0, 'supported':0})
    submitted = set(review.get('submitted_claim_ids', [])) | set(review.get('reused_supported_claim_ids', [])) | set(review.get('reused_review_claim_ids', []))
    for c in claims:
        row = coverage[str(c['chapter'])]
        status = review.get('reviews', {}).get(c['claim_id'], {}).get('status','not_evaluated')
        row['total'] += 1
        row['submitted'] += c['claim_id'] in submitted
        row['valid'] += status in REVIEW_STATES
        row['supported'] += status=='supported'
    review.update(coverage_by_chapter=dict(coverage), total_claim_count=len(claims),
        valid_review_count=sum(r['valid'] for r in coverage.values()),
        supported_claim_count=sum(r['supported'] for r in coverage.values()),
        pending_claim_count=sum(r['total']-r['valid'] for r in coverage.values()),
        submitted_claim_count=sum(r['submitted'] for r in coverage.values()),
        excluded_claim_ids=[c['claim_id'] for c in claims if c['claim_id'] not in submitted],
        review_state_counts=dict(Counter(review.get('reviews',{}).get(c['claim_id'],{}).get('status','not_evaluated') for c in claims)))


def question_progress(task, plans, packages):
    """Only question-applicable, deduplicated licensed statements count as new evidence."""
    from industry_fact_contracts import chapter_admitted, chapter_coverage
    chapter = task['chapter']
    package = packages.get(chapter, packages.get(str(chapter), {}))
    if isinstance(package, str):
        package = json.loads(package)
    cards = {f['evidence_id']: f for f in package.get('facts', []) if chapter_admitted(f, chapter)}
    coverage = next((r for r in chapter_coverage(package, chapter, list(cards)) if r['question'] == task['question']), {})
    signatures = set()
    by_id = {}
    for eid in coverage.get('evidence_ids', []):
        f = cards[eid]
        contract = f['fact_contract']
        signature=digest(json.dumps({
            'statement': re.sub(r'\s+', '', contract['statement']),
            'boundary': contract.get('sample_boundary'), 'kind': contract.get('material_kind'),
            'metric': f.get('numeric_context') if (f.get('numeric_validation') or {}).get('passed') else None,
        }, ensure_ascii=False, sort_keys=True))
        signatures.add(signature)
        by_id[eid]=signature
    plan = plans.get(chapter, plans.get(str(chapter), {}))
    used={eid for c in plan.get('analysis_claims',[]) if c.get('question')==task['question']
          for eid in c.get('evidence_ids',[])}
    claims = [c for c in plan.get('analysis_claims', []) if c.get('question') == task['question'] and not finding_issue(c)]
    return {'evidence_signatures': sorted(signatures),
            'used_evidence_signatures':sorted({by_id[eid] for eid in used if eid in by_id}), 'has_finding': bool(claims),
            'supported': any(c.get('support_review', {}).get('status') == 'supported' for c in claims)}


def schedule_tasks(plan, record):
    """At most two independent questions per chapter; no deferred task is charged."""
    limits = record['limits']
    selected, per_chapter, collected = [], {}, 0
    states = record.setdefault('questions', {})
    for task in sorted(plan['tasks'], key=lambda t: states.get(task_key(t), {}).get('attempts', 0)):
        state = states.setdefault(task_key(task), {'chapter': task['chapter'], 'question': task['question'],
            'attempts': 0, 'actions': {}, 'no_progress': 0, 'history': [], 'seen_evidence': []})
        if task['action']=='collect_evidence' and record.get('collection_unavailable'):
            state.update(stop_reason='collection_unavailable',status='execution_blocked')
            continue
        reason = ('total_limit' if state['attempts'] >= limits['total'] else
                  'no_progress' if state['no_progress'] >= limits['no_progress'] else
                  ('execution_limit' if task['action']=='retry_generation' and state.get('execution_failures') else 'action_limit')
                  if state['actions'].get(task['action'], 0) >= limits[task['action']] else '')
        if state.get('stop_reason') or reason:
            state['stop_reason'] = state.get('stop_reason') or reason
            continue
        if per_chapter.get(task['chapter'], 0) >= 2 or (task['action'] == 'collect_evidence' and collected >= MAX_QUERIES):
            continue
        selected.append(task)
        per_chapter[task['chapter']] = per_chapter.get(task['chapter'], 0) + 1
        collected += task['action'] == 'collect_evidence'
    return selected


def reserve_tasks(tasks, record, plans, packages):
    for task in tasks:
        state = record['questions'][task_key(task)]
        before = question_progress(task, plans, packages)
        state['seen_evidence'] = sorted(set(state['seen_evidence']) | set(before['evidence_signatures']))
        state['seen_used_evidence'] = sorted(set(state.get('seen_used_evidence',[])) | set(before['used_evidence_signatures']))
        state['attempts'] += 1
        state['actions'][task['action']] = state['actions'].get(task['action'], 0) + 1
        state['history'].append({'round': record['round'], 'action': task['action'], 'cause': task['cause'],
            'before': before, 'status': 'reserved'})


def finish_tasks(tasks, record, plans, packages, *, failed=False, collection_unavailable=False):
    remaining = {task_key(t): t for t in recovery_plan(plans, packages)['tasks']}
    for task in tasks:
        state = record['questions'][task_key(task)]
        row = state['history'][-1]
        after = question_progress(task, plans, packages)
        new_evidence = set(after['evidence_signatures']) - set(state['seen_evidence'])
        used_evidence = set(after['used_evidence_signatures']) - set(state.get('seen_used_evidence',[]))
        resolved = task_key(task) not in remaining and after['has_finding'] and not failed
        next_task = remaining.get(task_key(task), {})
        old_issues, new_issues = set(task.get('issue_codes', [])), set(next_task.get('issue_codes', []))
        fixed = ((old_issues-new_issues)-set(state.get('resolved_issues', []))
                 if next_task.get('action') == task['action'] and new_issues and new_issues < old_issues else set())
        # A source found but never used for this question is a candidate, not an
        # improved answer. Keep its count in audit without resetting stagnation.
        progressed = not failed and (resolved or bool(used_evidence) or bool(fixed)
                                     or (after['supported'] and not row['before']['supported']))
        state['resolved_issues'] = sorted(set(state.get('resolved_issues', [])) | fixed)
        state['seen_evidence'] = sorted(set(state['seen_evidence']) | set(after['evidence_signatures']))
        state['seen_used_evidence'] = sorted(set(state.get('seen_used_evidence',[])) | set(after['used_evidence_signatures']))
        execution_failed = failed or next_task.get('cause')=='generation_failed' or (
            task['action']=='collect_evidence' and collection_unavailable)
        state['execution_failures'] = state.get('execution_failures',0) + int(execution_failed)
        if not execution_failed:
            state['no_progress'] = 0 if progressed else state['no_progress'] + 1
        state['status'] = 'resolved' if resolved else 'execution_blocked' if execution_failed else 'unresolved'
        row.update(status='failed' if failed else 'completed', progress=progressed,
                   execution_failed=execution_failed,new_applicable_evidence=len(new_evidence),
                   new_used_evidence=len(used_evidence),resolved_issue_codes=sorted(fixed), resolved=resolved, after=after)
        if resolved:
            state.pop('stop_reason', None)
    return list(remaining.values())


def recovery_markdown(record):
    if not record:
        return ''
    def cell(value):
        return re.sub(r'\s+', ' ', str(value)).replace('|', '/')
    rows = []
    labels = {'no_progress':'连续无内容进展', 'action_limit':'本类修复达到上限', 'total_limit':'问题总修复达到上限',
              'execution_limit':'执行失败重试达到上限','collection_unavailable':'检索服务不可用，需处理配置或额度'}
    for state in record.get('questions', {}).values():
        status = '已形成初步判断' if state.get('status') == 'resolved' else labels.get(state.get('stop_reason'), '待人工处理')
        rows.append(f'| {state["chapter"]} | {cell(state["question"])} | {state["attempts"]} | {status} |')
    return ('## 逐题修复记录\n\n状态：' + cell(record.get('status')) +
            '。修复次数为问题处理轮次；检索、清洗、写作及复核调用分别记录，不等于一次API调用。初步判断仍须人工复核。\n\n'
            '| 章节 | 问题 | 修复次数 | 结果 |\n| --- | --- | --- | --- |\n' + '\n'.join(rows) + '\n\n')


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()
