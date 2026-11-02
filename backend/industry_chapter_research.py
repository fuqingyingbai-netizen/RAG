"""Research chapters against shared evidence before assembling a deliverable.

Uses the established bounded, journaled recovery pipeline. Proposal generation
only consumes the final report and retains its own workflow and dependencies.
"""
import json

VERSION = 'industry-chapter-research-v1-before-synthesis'


def prepare_chapter_packages(payload, packages, project):
    """Diagnose each fixed question against the whole admitted library first."""
    from industry_question_generation import CHAPTERS, compile_jobs
    from industry_fact_contracts import chapter_admitted, chapter_coverage
    rows = {}
    for chapter in sorted(CHAPTERS):
        package = json.loads(packages.get(chapter, '{"facts":[]}'))
        library = [f for f in payload.get('facts', []) if chapter_admitted(f, chapter)]
        coverage = chapter_coverage({**package, 'facts': library}, chapter,
                                    [f['evidence_id'] for f in library])
        by_id = {f['evidence_id']: f for f in library}
        ids = {f['evidence_id'] for f in package.get('facts', [])}
        reused = []
        # Preserve current premises, then add up to four whole cards per question.
        for question in coverage:
            applicable = question['evidence_ids'] or question.get('background_evidence_ids', [])
            if not any(eid in ids for eid in applicable):
                for eid in applicable[:4]:
                    if eid not in ids:
                        package.setdefault('facts', []).append(by_id[eid])
                        ids.add(eid)
                        reused.append(eid)
        packages[chapter] = json.dumps(package, ensure_ascii=False)
        _, diagnostic = compile_jobs(package, chapter)
        rows[str(chapter)] = {'questions': diagnostic['questions'], 'reused_evidence_ids': reused,
            'completion_rule': 'retain_supported_analysis_or_explicit_bounded_gap'}
    project.industry_chapter_research_plan = {'version': VERSION, 'chapters': rows,
        'phase': 'chapter_analysis', 'synthesis_started': False}


def run_chapter_research(workflow, db, project, cleaned, risk, cleaned_artifact,
                         risk_artifact, plan, intake, emit, pause_requested, checkpoint):
    from industry_conclusion_recovery import snapshot
    current = ('', cleaned, risk, cleaned_artifact, risk_artifact)
    audit = None
    project.industry_chapter_research_done = False
    project.industry_chapter_phase = True
    try:
        chapters = workflow.generate_report(project, cleaned, risk, emit=emit, intake=intake)
        audit = workflow.save_artifact(db, project, 'industry_chapter_research',
            project.title + '：章节研究计划与证据缺口',
            json.dumps(project.industry_chapter_research_plan, ensure_ascii=False),
            {'run_id': getattr(project, 'industry_run_id', None), 'pipeline_version': VERSION})
        current = workflow._recover_industry_conclusions(db, project, chapters, cleaned, risk,
            cleaned_artifact, risk_artifact, plan, intake, emit, pause_requested, checkpoint)
        state = project.industry_chapter_research_plan
        state.update(phase='chapters_completed', remaining_tasks=(getattr(project,
            'industry_conclusion_recovery', {}) or {}).get('remaining_tasks', []))
        audit = workflow.save_artifact(db, project, 'industry_chapter_research',
            project.title + '：章节研究完成状态', json.dumps(state, ensure_ascii=False),
            {'run_id': getattr(project, 'industry_run_id', None), 'pipeline_version': VERSION})
    finally:
        project.industry_chapter_phase = False
    checkpoint('report')
    seed = snapshot(project)
    try:
        project.industry_recovery_seed = seed
        project.industry_recovery_plan = {'chapters': [], 'tasks': [], 'finalize_synthesis': True}
        report = workflow.generate_report(project, current[1], current[2], emit=emit, intake=intake)
        project.industry_chapter_research_done = True
        project.industry_chapter_research_plan.update(phase='assembled', synthesis_started=True)
        workflow.save_artifact(db, project, 'industry_chapter_research',
            project.title + '：章节研究与汇总完成状态',
            json.dumps(project.industry_chapter_research_plan, ensure_ascii=False),
            {'run_id': getattr(project, 'industry_run_id', None), 'pipeline_version': VERSION})
        return (report, *current[1:])
    finally:
        for name in ('industry_recovery_seed', 'industry_recovery_plan'):
            if hasattr(project, name):
                delattr(project, name)
