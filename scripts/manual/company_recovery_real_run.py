"""Isolated real-model run through ResearchWorkflow, SQLite save and export."""
import argparse,hashlib,json,os,sqlite3,sys,time
from pathlib import Path
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parents[2]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input-db',required=True);ap.add_argument('--source-id',type=int,required=True)
    ap.add_argument('--directory',required=True);ap.add_argument('--resume',action='store_true');ap.add_argument('--calls',type=int,default=180);ap.add_argument('--seconds',type=int,default=3600);ap.add_argument('--input-chars',type=int,default=12000000)
    args=ap.parse_args();load_dotenv(ROOT/'.env',override=True)
    directory=(ROOT/'work'/args.directory).resolve();assert directory.is_relative_to((ROOT/'work').resolve())
    directory.mkdir(parents=True,exist_ok=True)
    os.environ.update(DATABASE_URL='sqlite:///'+str(directory/'research.sqlite').replace('\\','/'),
        RESEARCH_OBJECT_STORE='local',RESEARCH_LOCAL_STORE=str(directory/'objects'),
        RESEARCH_KNOWLEDGE_ARCHIVE_ENABLED='false',COMPANY_FLOW_MAX_MODEL_CALLS=str(args.calls),
        COMPANY_FLOW_MAX_SECONDS=str(args.seconds),COMPANY_FLOW_MAX_INPUT_CHARS=str(args.input_chars),
        COMPANY_MODEL_CONCURRENCY='1',COMPANY_CORPUS_REVIEW_WORKERS='1',COMPANY_EDITORIAL_WORKERS='1',COMPANY_INFORMATION_USAGE_WORKERS='1',
        COMPANY_DOCUMENT_REVIEW_WORKERS='1',LANGCHAIN_TRACING_V2='false',LANGSMITH_TRACING='false',
        DOCX_RENDER_QA_WORKDIR=str(ROOT/'work/loqa'))
    sys.path[:0]=[str(ROOT/'backend'),str(ROOT)]
    from database import Base,engine,SessionLocal
    from models import User,ResearchProject,ResearchSource,ResearchArtifact
    from research_workflow import ResearchWorkflow
    from research_store import research_store
    from company_chapters import VERSION
    from report_agents.company_transport import failure_diagnostic
    Base.metadata.create_all(engine)
    original=sqlite3.connect(Path(args.input_db).resolve().as_uri()+'?mode=ro',uri=True);original.row_factory=sqlite3.Row
    row=dict(original.execute('SELECT * FROM research_sources WHERE id=?',(args.source_id,)).fetchone())
    target=original.execute('SELECT target_name FROM research_projects WHERE id=?',(row['project_id'],)).fetchone()[0];original.close()
    with SessionLocal() as db:
        p=db.query(ResearchProject).filter(ResearchProject.id==1).first()
        if p is None:
            user=User(username='isolated-native-recovery',password_hash='local-unused');db.add(user);db.flush()
            p=ResearchProject(title=target+'真实原件恢复验证',target_type='company',target_name=target,created_by_id=user.id)
            db.add(p);db.flush()
            meta=json.loads(row['source_metadata'] or '{}');meta.pop('raw_response_key',None)
            meta.update(retention_policy='transient_web_body',original_fixture_source_id=args.source_id)
            key=research_store.put_text(f'projects/{p.id}/raw_web/frozen-native.txt',row['content'])
            db.add(ResearchSource(project_id=p.id,title=row['title'],url=row['url'],source_type=row['source_type'],
                content=row['content'],summary=row['summary'],object_key=key,source_metadata=meta,credibility_score=row['credibility_score']))
            db.commit()
        elif not args.resume:raise ValueError('existing_run_requires_resume')
        intake={'company_name':target,'target_name':target,'target_type':'company','focus_modules':[],
            'company_template_version':VERSION,'ai_search_enabled':False,'as_of_date':'2026-11-04',
            'search_queries':[],'focus_questions':[],'special_requirements':''}
        start=time.monotonic();events=[]
        def emit(event):
            safe={k:event[k] for k in ('type','stage','role','label','chapter','status','input_chars','output_chars') if k in event}
            events.append(safe)
            with (directory/'events.jsonl').open('a',encoding='utf-8') as log:log.write(json.dumps(safe,ensure_ascii=False)+'\n')
            if event.get('type')=='trace_step':print(json.dumps(safe,ensure_ascii=False),flush=True)
        outcome={'original_source_id':args.source_id,'source_url':row['url'],'original_chars':len(row['content']),
            'original_sha256':hashlib.sha256(row['content'].encode()).hexdigest(),
            'model':os.environ['MODEL'],'base_url':os.environ['BASE_URL'],'resumed':args.resume,'artifacts':[],
            'code_sha256':{str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in (ROOT/'backend').rglob('*.py')}}
        try:
            artifacts,added=ResearchWorkflow().run_project(db,p,[],[],intake=intake,emit=emit,pause_requested=lambda:(directory/'request-stop').exists())
            db.expire_all()
            for artifact in artifacts:
                meta=artifact.artifact_metadata or {};record={'id':artifact.id,'type':artifact.artifact_type,
                    'chars':len(artifact.content or ''),'sha256':hashlib.sha256((artifact.content or '').encode()).hexdigest(),
                    'delivery_status':meta.get('delivery_status'),'docx_integrity_status':meta.get('docx_integrity_status'),
                    'docx_render_status':meta.get('docx_render_status'),'docx_layout_status':meta.get('docx_layout_status')}
                outcome['artifacts'].append(record)
                (directory/(artifact.artifact_type+'-'+str(artifact.id)+'.txt')).write_text(artifact.content or '',encoding='utf-8')
                if artifact.artifact_type=='desktop_report':
                    outcome['report_summary']=meta.get('company_flow_summary');outcome['delivery_contract']=meta.get('company_delivery_contract')
                    for k in ('company_source_review_evidence','company_document_review','quality_warning'):
                        outcome[k]=meta.get(k)
            outcome['status']=p.status;outcome['added_sources']=added
        except Exception as exc:
            db.rollback();outcome['error']=failure_diagnostic(exc,stage='real_workflow_run');outcome['status']=p.status
        finally:
            outcome['seconds_this_invocation']=round(time.monotonic()-start,3)
            journal=getattr(p,'_company_flow_journal',None)
            if journal is not None:
                outcome['metrics']=journal.data['metrics'];outcome['transport_events']=[r for r in journal.data['events'] if r.get('error')]
                outcome['chapter_states']={k:v.get('status') for k,v in journal.data['chapters'].items()}
            (directory/'result.json').write_text(json.dumps(outcome,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            print(json.dumps({k:outcome[k] for k in ('status','seconds_this_invocation','metrics','error') if k in outcome},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
