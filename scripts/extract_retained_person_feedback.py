"""One bounded extraction request over archived originals; no retrieval calls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'scripts')]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('baseline',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    raw=(args.baseline/'source-snapshots.json').read_bytes()
    sources=[SimpleNamespace(**s) for s in json.loads(raw)]
    intake=json.loads((args.baseline/'intake.json').read_text(encoding='utf-8'))
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
    os.environ.update(PERSON_REPORT_SECTION_TIMEOUT_SECONDS='90',PERSON_REPORT_SECTION_MAX_RETRIES='0')
    from research_workflow import ResearchWorkflow
    from person_chapter_research import extract_personal_feedback
    from person_iteration import ChapterInvoker
    workflow=ResearchWorkflow.__new__(ResearchWorkflow)
    workflow._person_report_section_model=None
    invoke=ChapterInvoker(workflow._invoke_person_report_section,args.output)
    workflow._invoke_person_report_section=invoke
    start=time.monotonic()
    records,rejected,calls=extract_personal_feedback(workflow,sources,intake)
    result={'sources_sha256':hashlib.sha256(raw).hexdigest(),'records':records,'rejected':rejected,
        'actual_model_requests':calls,'new_search_calls':0,'new_fetch_calls':0,'new_professional_calls':0,
        'elapsed_seconds':round(time.monotonic()-start,3)}
    (args.output/'feedback.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
