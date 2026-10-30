"""Industry regressions and saved-run audit. No model, search or database calls.

Run with the project Python. A replay reports findings with exit 2; this does not
mean the historical run failed. It never regenerates or edits stored artifacts.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def audit_saved_run(folder: Path) -> dict:
    from industry_research import (normalize_risk, delivery_errors,
        summary_length, numeric_mentions, INDUSTRY_RISK_VERSION)
    cleaned = json.loads((folder / 'cleaned_facts.json').read_text(encoding='utf-8-sig'))
    risk = json.loads((folder / 'risk_assessment.json').read_text(encoding='utf-8-sig'))
    report = (folder / 'desktop_report.md').read_text(encoding='utf-8-sig')
    facts = cleaned.get('facts') or []
    scope = cleaned.get('industry_scope') or {}
    checked = normalize_risk(risk, facts, scope)
    original_dimensions = {row['name']:row for row in risk.get('dimensions', [])}
    newly_rejected = [{'dimension':new['name'], 'cause':new.get('unknown_cause'),
                       'issues':new.get('validation_diagnostic', {}).get('semantic_issues', [])}
                      for new in checked['dimensions']
                      for old in [original_dimensions.get(new['name'], {})]
                      if old.get('score') is not None and new.get('score') is None]
    summary_file = folder / 'monitor-evidence-summary.json'
    saved_summary=json.loads(summary_file.read_text(encoding='utf-8-sig')) if summary_file.exists() else {}
    meta=saved_summary.get('desktop_report',{}).get('metadata',{})
    diagnostic = meta.get('industry_evidence_diagnostic')
    if diagnostic is not None:
        by_id = {f.get('evidence_id'): f for f in facts}
        for eid, card in diagnostic.get('numeric_evidence', {}).items():
            for field in ('source_url','source_title','evidence_quote','claim_type','module','fact','evidence_scope'):
                card[field]=by_id.get(eid, {}).get(field,card.get(field,''))
        report_issues = delivery_errors(report, diagnostic, scope)
    else:
        report_issues = ['缺少原章节证据包诊断，无法完整回放章节归属闸门。']
    match = re.search(r'(?ms)^##\s*1[.、．][^\n]*\n(.*?)(?=^##\s*2[.、．]|\Z)', report)
    # summary_length expects the heading too; passing stripped prose drops its first paragraph.
    summary_chars = summary_length(match[0]) if match else None
    proposal_path = folder / 'proposal.md'
    proposal = proposal_path.read_text(encoding='utf-8-sig') if proposal_path.exists() else ''
    chapters = [int(n) for n in re.findall(r'^##\s*(\d+)[.、．]', report, re.M)]
    unknown = [row['name'] for row in checked['dimensions'] if row.get('score') is None]
    required_status = ('review_draft' if unknown or report_issues or meta.get('generation_degradations') else 'final_candidate')
    proposal_chapters = [int(n) for n in re.findall(r'^##\s*(\d+)[.、．]', proposal, re.M)]
    contract_issues = []
    from industry_delivery import risk_state_issues
    contract_issues.extend(risk_state_issues(report,checked,scope))
    if summary_chars is None or summary_chars > 600:
        contract_issues.append('摘要缺失或正文超过600字。')
    if chapters != list(range(1, 17)):
        contract_issues.append('行业报告未满足16章目录契约。')
    if proposal_chapters != list(range(1, 8)):
        contract_issues.append('建议书缺失或未满足7章目录契约。')
    if required_status == 'review_draft' and meta.get('delivery_status') != 'review_draft':
        contract_issues.append('当前规则要求待复核，但历史交付状态不是待复核稿。')
    ledger_path=folder/'industry_claim_ledger.json'
    ledger_summary=None
    if ledger_path.exists():
        ledger=json.loads(ledger_path.read_text(encoding='utf-8-sig'))
        ledger_summary=ledger.get('summary')
        deps=ledger.get('dependencies') or {}
        for kind,filename in [('report','desktop_report.md'),('cleaned','cleaned_facts.json'),('risk','risk_assessment.json')]:
            digest=hashlib.sha256((folder/filename).read_text(encoding='utf-8-sig').encode()).hexdigest()
            if deps.get(kind+'_sha256')!=digest:
                contract_issues.append(f'结论证据台账与{kind}正文指纹不一致或缺失。')
        for kind,key in [('desktop_report','report_artifact_id'),('cleaned_facts','cleaned_artifact_id'),('risk_assessment','risk_artifact_id')]:
            expected=saved_summary.get(kind,{}).get('id')
            if expected is not None and deps.get(key)!=expected:
                contract_issues.append(f'结论证据台账的{kind}产物版本关联不一致。')
    elif meta.get('claim_ledger_artifact_id'):
        contract_issues.append('新报告声明有结论证据台账，但回放目录缺少对应产物。')
    findings = bool(newly_rejected or report_issues or contract_issues)
    return {'mode':'offline_saved_output_audit', 'model_calls':0, 'search_calls':0, 'database_writes':0,
        'risk_rule_version':INDUSTRY_RISK_VERSION, 'fact_count':len(facts),
        'evidence_id_numeric_false_hits':sum(bool(numeric_mentions(f.get('evidence_id', ''))) for f in facts),
        'original_assessed_dimensions':risk.get('assessed_dimension_count'),
        'validated_assessed_dimensions':checked['assessed_dimension_count'], 'newly_rejected_risks':newly_rejected,
        'unknown_dimensions':unknown, 'report_chapters':chapters,
        'proposal_chapters':proposal_chapters,
        'summary_visible_chars':summary_chars, 'report_issues':report_issues, 'contract_issues':contract_issues,
        'claim_reference_summary':ledger_summary,
        'risk_support_under_current_rules':checked.get('risk_transparency'),
        'stored_delivery_status':meta.get('delivery_status'),
        'required_delivery_status':required_status,
        'has_new_findings':findings,
        'limitations':['Audits saved output only; does not simulate new model responses or Word rendering.',
                      'Different publishers satisfy a minimum count, not proof of independent original research.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full', action='store_true', help='Run all industry regression modules.')
    parser.add_argument('--replay', type=Path, help='Saved run folder with facts, risk, report and optional original diagnostics.')
    parser.add_argument('--replay-only', action='store_true', help='Audit only; requires --replay.')
    parser.add_argument('--output', type=Path, help='Save the local replay audit JSON; never alters source artifacts.')
    parser.add_argument('--acceptance', action='store_true', help='Also evaluate the frozen candidate acceptance set.')
    parser.add_argument('--acceptance-only', action='store_true', help='Evaluate candidate labels without running pytest or historical replay.')
    parser.add_argument('--acceptance-output', type=Path, help='New private JSON result for candidate acceptance.')
    args = parser.parse_args(argv)
    if args.replay_only and not args.replay:
        parser.error('--replay-only requires --replay')
    if args.output and not args.replay:
        parser.error('--output requires --replay')
    if args.acceptance_only and (args.full or args.replay or args.replay_only):
        parser.error('--acceptance-only cannot combine with --full or historical replay')
    if args.acceptance_output and not (args.acceptance or args.acceptance_only):
        parser.error('--acceptance-output requires --acceptance or --acceptance-only')
    if args.output and args.output.resolve() in {args.replay.resolve() / name for name in
            ['cleaned_facts.json', 'risk_assessment.json', 'desktop_report.md', 'proposal.md', 'monitor-evidence-summary.json','industry_claim_ledger.json']}:
        parser.error('--output must not overwrite saved source artifacts')
    if not args.replay_only and not args.acceptance_only:
        files = (sorted((ROOT / 'test').glob('test_industry_*.py')) + [ROOT / 'test/test_runtime_version.py'] if args.full else
                 [ROOT / 'test' / name for name in ['test_runtime_version.py','test_industry_template_analysis.py','test_industry_fact_contracts.py','test_industry_decision_readiness.py','test_industry_observed_inputs.py','test_industry_v12_acceptance.py','test_industry_v13_acceptance.py','test_industry_v14_acceptance.py','test_industry_evidence_contract.py','test_industry_runs.py','test_industry_delivery_contracts.py','test_industry_synthesis_contracts.py','test_industry_verification_tasks.py','test_industry_assertion_boundaries.py','test_industry_fallback.py','test_industry_risk_support.py','test_industry_claim_semantics.py', 'test_industry_risk_repair.py']])
        if not args.full:
            files.append(ROOT / 'test/test_industry_proposal_contract.py')
            files += [ROOT / 'test/test_industry_question_jobs.py', ROOT / 'test/test_industry_conclusion_recovery.py']
            files.append(ROOT / 'test/test_industry_v35_revision.py')
            files += [ROOT / 'test' / name for name in ['test_industry_v36_review.py',
                'test_industry_v36_draft_merge.py', 'test_industry_v36_briefing.py', 'test_industry_v36_tasks.py']]
            files.append(ROOT / 'test/test_industry_v37_recovery.py')
            files.append(ROOT / 'test/test_industry_developed_writing.py')
            files += [ROOT / 'test' / name for name in ['test_industry_reasoning.py', 'test_industry_cleaning_retrieval.py', 'test_industry_analysis_repair.py', 'test_industry_briefing.py', 'test_industry_analysis_selection.py', 'test_industry_reader.py', 'test_industry_v27_regressions.py', 'test_industry_balanced_review.py', 'test_industry_v28_failure.py', 'test_industry_stage_cache.py', 'test_industry_conclusion_generation.py', 'test_industry_v30_inputs.py', 'test_industry_v31_generation.py', 'test_industry_chapter_batches.py']]
        env = {**os.environ, 'PYTHONUTF8':'1', 'PYTHONPATH':str(ROOT / 'backend')}
        code = subprocess.run([sys.executable, '-m', 'pytest', *map(str, files), '-q', '--tb=short'], cwd=ROOT, env=env).returncode
        if code:
            return code
    if args.acceptance or args.acceptance_only:
        command = [sys.executable, str(ROOT / 'scripts/industry_acceptance.py')]
        if args.acceptance_output:
            command += ['--output', str(args.acceptance_output)]
        code = subprocess.run(command, cwd=ROOT, env={**os.environ, 'PYTHONUTF8':'1'}).returncode
        if code:
            return code
    if args.replay:
        result = audit_saved_run(args.replay.resolve())
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding='utf-8')
        print(rendered)
        return 2 if result['has_new_findings'] else 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
