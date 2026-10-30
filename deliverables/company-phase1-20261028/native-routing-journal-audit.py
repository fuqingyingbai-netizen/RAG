"""Read-only verification of actual production-written routing receipts."""
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
import hashlib,json,sys

ROOT=Path(__file__).resolve().parents[2];RUN=ROOT/'work/company-phase1-20261028'
sys.path.insert(0,str(ROOT/'backend'))
from report_agents.company_information_journal import read_decisions,binding
from report_agents.company_checkpoint import scope
from report_agents.company_report_agent import COMPANY_REPORT_OUTLINE

objects=(RUN/'native/haitian/objects').resolve()
class ReadOnlyStore:
    def get_text(self,key):
        path=(objects/key).resolve();assert path.is_relative_to(objects)
        return path.read_text(encoding='utf-8')
store=ReadOnlyStore()
def sha(raw):return hashlib.sha256(raw).hexdigest()
prefix='projects/1/company_generation_checkpoint'
pointer=json.loads(store.get_text(prefix+'/current.json'))
text=store.get_text(pointer['key']);assert sha(text.encode())==pointer['sha256']
checkpoint=json.loads(text);usage=checkpoint['packages']['company_information_usage_cache']
assert not usage['diagnostic']['pending_information_ids'] and not usage['diagnostic']['unmapped_statements']
project=SimpleNamespace(id=checkpoint['project_id'],target_name=checkpoint['target_name'],
    industry=checkpoint['scope'].get('declared_industry',''),company_research_intake=checkpoint['scope'])
assert scope(project)==checkpoint['scope']
index=json.loads(store.get_text(prefix+'/information-routing-current.json'))
assert all(index.get(k)==v for k,v in binding(project,COMPANY_REPORT_OUTLINE).items())
recovered=read_decisions(project,usage['records'],COMPANY_REPORT_OUTLINE,store=store)
assert recovered and set(recovered)==set(index['entries'])
entries={}
for iid,item in index['entries'].items():
    body=store.get_text(prefix+'/information-routing/'+item['sha256']+'.json')
    assert sha(body.encode())==item['sha256']
    entries[iid]={'receipt_sha256':item['sha256'],'input_sha256':item['input_sha256'],
                  'revalidated_status':recovered[iid]['status']}
plan=RUN/'native/haitian/bounded-plan-20261030T135651080519.json'
native=json.loads(plan.read_text(encoding='utf-8'))
assert sorted((RUN/'native/haitian').glob('bounded-plan-*.json'))[-1]==plan, 'Do not attribute a later run to this pinned observation.'
assert all(sha((ROOT/name).read_bytes())==value for name,value in native['code_sha256'].items())
proof={'at':datetime.now(timezone.utc).isoformat(),'scope':'actual native per-batch routing journal readback',
    'generator_sha256':sha(Path(__file__).read_bytes()),
    'native_plan':plan.name,'native_code_commit':native['code_commit'],'runtime_source_unchanged':True,
    'whole_usage_checkpoint_sha256':pointer['sha256'],'whole_usage_records':len(usage['records']),
    'native_journal_index_sha256':sha(store.get_text(prefix+'/information-routing-current.json').encode()),
    'journal_version':index['version'],'revalidated_native_decisions':len(recovered),'entries':entries,
    'validation':'production read_decisions validates current text, context, provenance, evidence, scope, template and decision',
    'business_data_or_cache_written_by_this_verifier':False,'model_or_network_calls':0,
    'diagnostic_responses_transplanted':False,'full_report_accepted':False,'goal_complete':False}
(ROOT/'deliverables/company-phase1-20261028/native-routing-journal-proof-20261030.json').write_text(
    json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'actual_native_decisions_revalidated':len(recovered),'whole_usage_records':len(usage['records']),
                  'native_runtime_unchanged':True,'report_accepted':False}))
