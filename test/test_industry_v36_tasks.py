"""Current follow-up work must not expand with every discarded draft."""
from copy import deepcopy
import re
from types import SimpleNamespace

from industry_delivery import (consolidate_verification_tasks, verification_tasks,
                               verification_task_table, tasks_section)
from report_agents.industry_proposal import build_industry_proposal
from report_agents.industry_proposal_contract import proposal_tables, validate_proposal

SCOPE = {'industry_name':'人工智能', 'capital_market':'none', 'named_companies':[]}


def note(coverage=None, rejected=None, **extra):
    return {'chapter':10, 'review_type':'statement_synthesis_review',
            'content_coverage':coverage or [], 'analysis_rejections':rejected or [], **extra}


def coverage(topic, **extra):
    return {'question':topic, 'status':'source_material_pending_review',
            'evidence_state':'source_material_pending_review', 'evidence_ids':[],
            'criteria':['实际交易与经营披露','统计期间及收入成本口径'], **extra}


def rejected(topic, reason='本题只给样本毛利，没有回答实际付费客户。', **extra):
    return {'question':topic, 'issues':['answer_question_mismatch'],
            'support_review':{'status':'partial','reason':reason}, **extra}


def test_many_failed_attempts_create_one_current_task_per_question_with_diagnostics():
    topics = ['盈利及收入成本材料','实际收费与付费客户']
    rejections = [rejected(topics[0]) for _ in range(34)] + [rejected(topics[1]) for _ in range(16)]
    notes = [note([coverage(t) for t in topics], rejections)]
    original = deepcopy(notes)
    tasks = verification_tasks({}, {}, notes, SCOPE)
    assert len(tasks) == 1 and len(tasks[0]['subtasks']) == 2
    rows = tasks[0]['subtasks']
    assert {s['topic'] for s in rows} == set(topics)
    assert sum(len(s['audit_merged_task_ids']) for s in rows) == 52
    assert all(s['support_review_required'] for s in rows)
    assert rows[0]['issue_codes'] == ['answer_question_mismatch']
    table = verification_task_table(tasks)
    assert table.count('本题只给样本毛利，没有回答实际付费客户。') == 2
    assert '实际交易与经营披露' in table and '实际回款或付费客户记录' in table
    assert notes == original


def test_different_outstanding_defects_merge_without_losing_actions_or_reasons():
    notes = [note([coverage('实际收费与付费客户')], [
        rejected('实际收费与付费客户','样本毛利不能回答客户身份。'),
        rejected('实际收费与付费客户','收费金额归属的统计期间未明确。',issues=['analysis_unauthorized_number'])])]
    tasks = verification_tasks({}, {}, notes, SCOPE)
    sub, = tasks[0]['subtasks']
    assert set(sub['issue_codes']) == {'answer_question_mismatch','analysis_unauthorized_number'}
    table = verification_task_table(tasks)
    assert '客户身份' in table and '统计期间未明确' in table
    assert len(sub['audit_revision_history']) == 2


def test_resolved_question_keeps_one_human_confirmation_without_old_rejection():
    tasks = verification_tasks({}, {}, [note([
        coverage('实际收费与付费客户', model_revision_complete=True)],
        [rejected('实际收费与付费客户', '旧失败不能进入当前工作。')])], SCOPE)
    sub, = tasks[0]['subtasks']
    assert sub['model_revision_complete'] and not sub.get('support_review_required')
    assert '旧失败' not in verification_task_table(tasks)
    assert '当前判断已完成模型修订' in verification_task_table(tasks)


def test_latest_chapter_note_supersedes_history_and_question_ids_are_stable():
    old = note([coverage('旧版待解决问题')], [rejected('旧版待解决问题')])
    latest = note([coverage('实际收费与付费客户'),coverage('盈利及收入成本材料')])
    current = verification_tasks({}, {}, [old,latest], SCOPE)
    assert '旧版待解决问题' not in verification_task_table(current)
    reverse = verification_tasks({}, {}, [note(list(reversed(latest['content_coverage'])))], SCOPE)
    ids = lambda tasks: {s['topic']:s['task_id'] for s in tasks[0]['subtasks']}
    assert ids(current) == ids(reverse)


def test_legacy_saved_task_reexport_is_idempotent_and_does_not_mutate_inputs():
    legacy = [{'task_id':'V-11111111','topic':'章节分析复核','task_type':'synthesis_review',
        'completion':'核验通过后形成当前结论。','subtasks':[
            {'task_id':'Q-1','chapter':10,'topic':'实际收费与付费客户','status':'missing',
             'completion':'取得实际交易披露。'},
            {'task_id':'R-1','chapter':10,'topic':'结论支持复核：实际收费与付费客户','status':'partial',
             'completion':'修正样本外推。'},
            {'task_id':'R-2','chapter':10,'topic':'结论支持复核：实际收费与付费客户','status':'partial',
             'completion':'修正样本外推。'}]}]
    before = deepcopy(legacy)
    once = consolidate_verification_tasks(legacy)
    assert len(once[0]['subtasks']) == 1
    assert consolidate_verification_tasks(once) == once
    table = verification_task_table(legacy)
    assert table.count('实际收费与付费客户') == 1
    assert '取得实际交易披露' in table and '修正样本外推' in table
    assert legacy == before
    assert '实际收费与付费客户' in tasks_section(legacy)


def test_metric_without_chapter_binds_technical_work_package_by_requirement():
    tasks = verification_tasks({'evidence_coverage':{'requirements':[
        {'requirement_id':'technology_cost', 'question':'可比技术成本及测试条件',
         'module':'技术路线对比','status':'missing'}]}}, {}, [], SCOPE)
    task, = tasks
    assert task['chapters'] == [7]
    p = SimpleNamespace(title='行业测试',target_name='人工智能',industry_scope=SCOPE,
                        industry_verification_tasks=tasks)
    body = build_industry_proposal(p)
    schedule = proposal_tables(SCOPE,tasks)
    schedule_table = next(t for t in schedule if t['key']=='schedule')
    technical = next(row for row in schedule_table['rows'] if row[0]=='产品与技术')
    assert task['task_id'] in technical[1]
    assert not any(row[0]=='其他专项及来源复核' and task['task_id'] in row[1] for row in schedule_table['rows'])
    assert validate_proposal(body,SCOPE,tasks)['passed']
    assert re.findall(r'^## (\d+)\.',body,re.M) == list(map(str,range(1,8)))


def test_active_rejections_contract_takes_precedence_over_legacy_history():
    n = note([coverage('实际收费与付费客户')], [rejected('实际收费与付费客户','旧历史。')],
             active_analysis_rejections=[])
    tasks = verification_tasks({}, {}, [n], SCOPE)
    assert '旧历史' not in verification_task_table(tasks)


def test_merged_question_keeps_its_own_candidate_title_link_and_locator_in_index():
    eid='E-123456789ABC'
    fact={'evidence_id':eid,'source_title':'实际收费原始披露','source_url':'https://source.example/pricing',
          'scope_match':'in_scope','eligible_for_report':True,
          'provenance':{'locator':{'status':'verified','start':120,'end':180,'body_sha256':'a'*64}}}
    tasks=verification_tasks({'facts':[fact]}, {}, [note([
        coverage('实际收费与付费客户',evidence_ids=[eid])], [rejected('实际收费与付费客户')])], SCOPE)
    sub,=tasks[0]['subtasks']
    assert sub['evidence_ids']==[eid] and sub['review_references'][0]['start']==120
    index=verification_task_table(tasks,reference_index_only=True)
    assert '实际收费原始披露' in index and 'https://source.example/pricing' in index
    assert '120–180' in index and sub['task_id'] in index
