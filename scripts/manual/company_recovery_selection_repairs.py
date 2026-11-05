"""Real production-model scope repairs for byte-bound frozen proposals."""
import argparse,hashlib,json,os,sqlite3,sys,time
from pathlib import Path
from types import SimpleNamespace as NS
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parents[2]

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--cases-root',required=True);ap.add_argument('--company',default='haitian');ap.add_argument('--native-root',required=True);args=ap.parse_args()
 load_dotenv(ROOT/'.env',override=True);directory=ROOT/'work'/('selection-repairs-'+args.company);directory.mkdir(parents=True,exist_ok=True)
 os.environ.update(DATABASE_URL='sqlite://',RESEARCH_OBJECT_STORE='local',RESEARCH_LOCAL_STORE=str(directory/'objects'),LANGSMITH_TRACING='false',LANGCHAIN_TRACING_V2='false')
 sys.path[:0]=[str(ROOT/'backend'),str(ROOT)]
 from company_flow_state import fingerprint,FlowJournal
 from research_store import research_store
 from research_workflow import ResearchWorkflow
 from report_agents.company_transport import bounded_company_invoke
 from report_agents.company_source_review import validate_selection
 from report_agents.company_reading_recovery import repair_selection_records
 cases=json.loads((Path(args.cases_root)/(args.company+'-old-proposals.json')).read_text(encoding='utf-8'))['cases']
 db=sqlite3.connect((Path(args.native_root)/args.company/'acceptance.sqlite').resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
 docs={};sources={};facts=[];target=cases[0]['target_name']
 for c in cases:
  if not c['same_original_bytes'] or not c['same_source_input']:continue
  source_id=c['source_id'];eid=c['old_selection']['evidence_id']
  if source_id not in sources:
   raw=dict(db.execute('SELECT * FROM research_sources WHERE id=?',(source_id,)).fetchone());raw['source_metadata']=json.loads(raw['source_metadata'] or '{}');sources[source_id]=NS(**raw)
  raw=sources[source_id].content.strip();quote=c['quote'];start=c['start'];end=start+len(quote)
  assert raw[start:end]==quote and hashlib.sha256(raw.encode()).hexdigest()==c['original_sha256']
  doc=docs.setdefault(eid,{k:c[k] for k in ('source_id','source_url','source_title','source_kind','subject_binding','document_date_proof','original_sha256')})
  doc.update(evidence_id=eid,model_reading_mode='frozen-model-scope-repair-v1',windows=doc.get('windows',[]))
  left=max(0,start-2500);right=min(len(raw),end+2500)
  if not any(w['window_id']==c['old_selection']['window_id'] for w in doc['windows']):
   doc['windows'].append({'window_id':c['old_selection']['window_id'],'quote':quote,'start':start,'end':end,
    'context_quote':raw[left:right],'candidate_chapters':list(range(2,12)),
    'native_window_sha256':fingerprint([c['original_sha256'],start,end,quote])})
  facts.append(c['old_selection'])
 db.close();project=NS(id=1,target_name=target,sources=list(sources.values()),company_research_intake={'as_of_date':cases[0]['as_of_date']})
 j=FlowJournal(research_store,1,{'target':target,'purpose':'frozen-native-scope-repair','company':args.company})
 j.restore();project._company_flow_journal=j;w=ResearchWorkflow()
 invoke=bounded_company_invoke(lambda role,prompt,trace=None:j.invoke(lambda r,p,t:w._invoke_company_report_editor(r,p,usage_sink=j.usage),role,prompt,trace))
 result={'facts':facts,'decisions':[{'evidence_id':eid,'disposition':'accepted','reason':'历史模型判断；本轮只修引用与主体记录。'} for eid in docs]}
 before=[validate_selection(row,docs,target,cases[0]['as_of_date'])[1] for row in facts];start=time.monotonic()
 repaired=repair_selection_records(project,list(docs.values()),result,invoke)
 after=[validate_selection(row,docs,target,cases[0]['as_of_date'])[1] for row in repaired.get('facts',[])]
 outcome={'company':args.company,'scope':'same-native-bytes historical-proposal guard and model scope repair; not narrative/report acceptance',
  'native_sources':len(sources),'original_proposals':len(facts),'before_pending_scope':sum(bool(e) for e in before),
  'after_valid_selections':sum(not e for e in after),'pending_repairs':repaired.get('pending_selection_repairs',[]),
  'repairs':repaired.get('selection_repairs',[]),'error':repaired.get('selection_repair_error'),
  'metrics':j.data['metrics'],'seconds':round(time.monotonic()-start,3),'model':os.environ['MODEL'],'base_url':os.environ['BASE_URL']}
 (directory/'repaired-proposals.json').write_text(json.dumps(repaired,ensure_ascii=False,indent=2),encoding='utf-8')
 (ROOT/'docs/deliverables/company-recovery-20261104'/(args.company+'-real-selection-repairs.json')).write_text(json.dumps(outcome,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:outcome[k] for k in ('company','native_sources','original_proposals','before_pending_scope','after_valid_selections','metrics','seconds')},ensure_ascii=False))

if __name__=='__main__':main()
