"""Plan actual native cache reuse with read-only source data and current gates."""
from pathlib import Path
from types import SimpleNamespace as NS
from datetime import datetime,timezone
import hashlib,json,sqlite3,sys

ROOT=Path(__file__).resolve().parents[2];RUN=ROOT/'work/company-phase1-20261028'
sys.path.insert(0,str(ROOT/'backend'))
from report_agents.company_checkpoint import source_fingerprint
from report_agents.company_presentation import (read_journal,presentation_scope,usable_records,
    receipt_aware_jobs,batch_input,validate_batch)

native=RUN/'native/haitian';objects=(native/'objects').resolve()
class ReadOnlyStore:
    def get_text(self,key):
        path=(objects/key).resolve();assert path.is_relative_to(objects)
        return path.read_text(encoding='utf-8')
store=ReadOnlyStore();folder='projects/1/company_generation_checkpoint'
pointer=json.loads(store.get_text(folder+'/current.json'));text=store.get_text(pointer['key'])
assert hashlib.sha256(text.encode()).hexdigest()==pointer['sha256'];cp=json.loads(text)
with sqlite3.connect((native/'acceptance.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    sources=[]
    for row in db.execute('SELECT * FROM research_sources WHERE project_id=? ORDER BY id',(cp['project_id'],)):
        values=dict(row);values['source_metadata']=json.loads(values['source_metadata']) if isinstance(values.get('source_metadata'),str) else values.get('source_metadata')
        sources.append(NS(**values))
assert source_fingerprint(sources)==cp['source_fingerprint']
project=NS(id=cp['project_id'],target_name=cp['target_name'],industry=cp['scope'].get('declared_industry',''),
    company_research_intake=cp['scope'],sources=sources)
records=usable_records(cp['packages']['company_information_usage_cache']);scope=presentation_scope(project)
batches=read_journal(project,store);prior={b['input_sha256']:b for b in batches}
jobs=receipt_aware_jobs(records,prior,project.target_name,scope)
fresh=receipt_aware_jobs(records,{},project.target_name,scope);reused=[];new=[]
for rows in jobs:
    key=batch_input(rows,project.target_name,scope);candidate=prior.get(key)
    if candidate and not validate_batch(rows,candidate)[1]:
        reused.append({'input_sha256':key,'information_ids':[r['information_id'] for r in rows]})
    else:new.append(rows)
ids=[r['information_id'] for rows in jobs for r in rows]
assert len(ids)==len(set(ids))==len(records) and set(ids)=={r['information_id'] for r in records}
assert len(reused)==76
result={'at':datetime.now(timezone.utc).isoformat(),'scope':'current production loader and planner over the full native input',
    'checkpoint_sha256':pointer['sha256'],'source_records':len(sources),'information_records':len(records),
    'candidate_receipts_loaded':len(batches),'revalidated_cached_jobs':len(reused),
    'revalidated_cached_information_records':sum(len(r['information_ids']) for r in reused),
    'baseline_fresh_review_jobs':len(fresh),'after_fix_new_review_jobs':len(new),
    'all_current_information_covered_exactly_once':True,'reused_batches':reused,
    'native_cache_or_business_data_modified':False,'model_or_network_calls':0,
    'diagnostic_responses_transplanted':False,'full_report_accepted':False,'goal_complete':False}
dest=RUN/'presentation-cache-audit-20261030/after-fix-production-readback.json'
dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in ['reused_batches','at','scope']}))
