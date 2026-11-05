"""Read-only public annual-report input; isolated real-model chapter experiment.

No writes to the input database, no collection/push, no credential output.
Default only inspects selection sizes. --run explicitly invokes the configured
company model and stores disposable checkpoints under this experiment folder.
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from types import SimpleNamespace as NS
from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-db',required=True)
    parser.add_argument('--source-id',type=int)
    parser.add_argument('--chapters',default='7')
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--directory',default='company-chapter-experiment-20261103')
    parser.add_argument('--model-calls',type=int,default=80)
    parser.add_argument('--seconds',type=int,default=3600)
    args=parser.parse_args()
    load_dotenv(ROOT/'.env',override=True)
    directory=(ROOT/'work'/args.directory).resolve()
    if not directory.is_relative_to((ROOT/'work').resolve()):raise ValueError('experiment_directory_outside_work')
    directory.mkdir(exist_ok=True)
    os.environ.update(RESEARCH_OBJECT_STORE='local',RESEARCH_LOCAL_STORE=str(directory/'objects'),
        COMPANY_FLOW_MAX_MODEL_CALLS=str(args.model_calls),COMPANY_FLOW_MAX_INPUT_CHARS='2400000',
        COMPANY_FLOW_MAX_SECONDS=str(args.seconds),LANGSMITH_TRACING='false',LANGCHAIN_TRACING_V2='false')
    sys.path[:0]=[str(ROOT/'backend'),str(ROOT)]
    from company_chapters import VERSION
    from company_chapter_flow import ChapterFlow
    from research_workflow import ResearchWorkflow
    db=sqlite3.connect(Path(args.input_db).resolve().as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    rows=db.execute('SELECT id,title,url,length(content) AS chars,project_id FROM research_sources '
        "WHERE length(content)>50000 AND (title LIKE '%报告%' OR url LIKE '%.pdf%') ORDER BY length(content) DESC LIMIT 6").fetchall()
    print(json.dumps({'candidates':[dict(r) for r in rows]},ensure_ascii=False),flush=True)
    source_id=args.source_id or (rows[0]['id'] if rows else None)
    if source_id is None:raise RuntimeError('no_retained_public_report')
    s=dict(db.execute('SELECT * FROM research_sources WHERE id=?',(source_id,)).fetchone())
    target=db.execute('SELECT target_name FROM research_projects WHERE id=?',(s['project_id'],)).fetchone()[0]
    db.close()
    # The body is copied in memory. Input object keys are deliberately omitted;
    # only this experiment owns and can remove its own temporary files.
    s['source_metadata']=json.loads(s['source_metadata'] or '{}');s['object_key']=''
    numbers=[int(n) for n in args.chapters.split(',')]
    intake=dict(target_name=target,target_type='company',industry='',focus_modules=[f'company.ch{n:02d}' for n in numbers],
        company_template_version=VERSION,as_of_date='2026-11-03',ai_search_enabled=False,
        search_queries=[],focus_questions=[],special_requirements='')
    p=NS(id=1,title=target+'逐章实验',target_name=target,target_type='company',industry='',description='',
        sources=[NS(**s)],artifacts=[],status='draft')
    fake_db=NS(commit=lambda:None,rollback=lambda:None,expire=lambda *a:None)
    events=[]
    def emit(event):
        events.append(event)
        print(json.dumps({k:event[k] for k in ('label','chapter','status','input_chars','output_chars') if k in event},ensure_ascii=False),flush=True)
    flow=ChapterFlow(ResearchWorkflow(),fake_db,p,intake,emit)
    if args.resume:flow.restore()
    result={'mode':'real_chapter_run' if args.run else 'selection_only','resumed':args.resume,'source_id':source_id,'target':target,
        'original_chars':len(s['content']),'selections':{},'embeddings_created':0}
    for n in numbers:
        selection=flow.reader.select(p,n)
        result['selections'][str(n)]=selection['diagnostic']
    print(json.dumps(result,ensure_ascii=False),flush=True)
    if args.run:
        start=time.monotonic()
        try:
            for n in numbers:flow.run_chapter(n,local_only=True)
        except Exception as exc:
            result['error_type']=type(exc).__name__
        finally:
            result['elapsed_seconds']=round(time.monotonic()-start,3)
            result['summary']=flow.summary()
            result['chapters']={str(n):{'body_chars':len(flow.sections.get(n,'')),
                'accepted_claims':len(flow.reads.get(n,{}).get('facts',[])),
                'coverage':flow.coverage.get(n,{}),
                'editorial_diagnostic':flow.editorials.get(n,{}).get('diagnostic',{})} for n in numbers}
            (directory/'chapter-draft.md').write_text('\n\n'.join(flow.sections.values()),encoding='utf-8')
    (directory/('result.json' if args.run else 'selection.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'result_path':str(directory),'summary':result.get('summary'),
        'error_type':result.get('error_type')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
