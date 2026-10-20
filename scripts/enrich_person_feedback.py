"""One paid source-extraction call on retained originals; no new searches."""
import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline', type=Path)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if not args.live:
        parser.error('--live required for the bounded model request')
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    from research_workflow import ResearchWorkflow
    from person_chapter_research import extract_personal_feedback
    baseline = args.baseline.resolve()
    out = ROOT / 'work/person-optimization' / ('feedback-enriched-' + datetime.now().strftime('%Y%m%dT%H%M%S'))
    out.mkdir(parents=True)
    for name in ('intake.json', 'person_retrieval_audit.json', 'summary.json'):
        shutil.copyfile(baseline / name, out / name)
    shutil.copytree(baseline / 'objects-before-cleanup', out / 'objects-before-cleanup')
    rows = json.loads((baseline / 'source-snapshots.json').read_text(encoding='utf-8'))
    sources = [SimpleNamespace(**row) for row in rows]
    intake = json.loads((baseline / 'intake.json').read_text(encoding='utf-8'))
    intake['target_name'] = intake.get('target_name') or intake.get('company_name')
    workflow = ResearchWorkflow()
    intake['person_anchor'] = workflow._build_person_anchor(intake)
    original_invoke = workflow._invoke_person_report_section
    def invoke(role, prompt, emit=None):
        answer = original_invoke(role, prompt, emit)
        (out / 'source-extraction-response.json').write_text(answer, encoding='utf-8')
        return answer
    workflow._invoke_person_report_section = invoke
    records, rejected, calls = extract_personal_feedback(workflow, sources, intake)
    for record in records:
        source = next(s for s in sources if s.url == record['source_url'])
        source.source_metadata = {**source.source_metadata, 'person_feedback_records':
                                  [*source.source_metadata.get('person_feedback_records', []), record]}
    rows = [vars(s) for s in sources]
    (out / 'source-snapshots.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    audit = json.loads((out / 'person_retrieval_audit.json').read_text(encoding='utf-8'))
    audit['chapter_7_feedback_extraction'] = {'records': records, 'rejections': rejected, 'actual_model_requests': calls,
                                             'new_search_requests': 0, 'new_fetch_requests': 0}
    (out / 'person_retrieval_audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = json.loads((out / 'summary.json').read_text(encoding='utf-8'))
    summary.update(scope='retained_originals_feedback_extraction_no_new_search', baseline=str(baseline),
                   actual_extraction_model_requests=calls, new_search_calls=0, new_fetch_calls=0,
                   feedback_extraction=audit['chapter_7_feedback_extraction'])
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'corpus': str(out), 'feedback_records': len(records), 'rejections': rejected}, ensure_ascii=False))


if __name__ == '__main__':
    main()
