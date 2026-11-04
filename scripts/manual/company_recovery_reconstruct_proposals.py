"""Recover old model selections against same native bytes, then replay new guards."""
import argparse,hashlib,json,os,sqlite3,sys
from pathlib import Path
from types import SimpleNamespace as NS
parser=argparse.ArgumentParser();parser.add_argument('--legacy-root',required=True);parser.add_argument('--output',default='work/replay-native');args=parser.parse_args()
root=Path(args.legacy_root).resolve()
sys.dont_write_bytecode=True  # The legacy checkout is strictly read-only.
sys.path[:0]=[str(root/'backend'),str(root)]
from report_agents.company_corpus import prepare_corpus,source_input_fingerprint,disclosed_aliases
from report_agents.company_issuer_identity import build_issuer_identity
from report_agents.company_source_review import validate_selection
out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
for company in ('haitian','kingsoft'):
 db=sqlite3.connect((root/'work/company-phase1-20261028/native'/company/'acceptance.sqlite').as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
 project=dict(db.execute('SELECT * FROM research_projects WHERE id=1').fetchone())
 meta=json.loads(db.execute("SELECT artifact_metadata FROM research_artifacts WHERE artifact_type='desktop_report' ORDER BY id DESC LIMIT 1").fetchone()[0]);old=meta['company_source_review_evidence']
 sources=[]
 for r in db.execute('SELECT * FROM research_sources WHERE project_id=1 ORDER BY id'):
  value=dict(r);value['source_metadata']=json.loads(value['source_metadata'] or '{}');sources.append(NS(**value))
 db.close();p=NS(**project);p.sources=sources;p.company_research_intake={'as_of_date':old['research_as_of'],**old.get('research_context',{})}
 case_ids={sid for sid,state in old['source_review'].items() if not state.get('accepted_claims') and any(d.get('disposition')=='accepted' for d in state.get('review_decisions',[]))}
 context=(disclosed_aliases(p.target_name,sources),build_issuer_identity(sources,p.target_name))
 p.sources=[s for s in sources if str(s.id) in case_ids]
 docs,_,_=prepare_corpus(p,{'facts':[]},_context=context);lookup={d['evidence_id']:d for d in docs}
 by_id={str(s.id):s for s in sources};cases=[];missing=[]
 rejections={(r.get('evidence_id'),r.get('window_id'),str(r.get('proposed_chapter'))):r for r in old.get('rejected_selections',[])}
 for receipt in old['review_receipts']:
  for selection in receipt.get('response',{}).get('facts',[]):
   key=(selection.get('evidence_id'),selection.get('window_id'),str(selection.get('chapter')))
   doc=lookup.get(selection.get('evidence_id'))
   if doc is None:continue
   prior=old['source_review'][doc['source_id']]
   rejected={'reason':(prior.get('validation_rejections') or ['unknown'])[0]}
   doc=lookup.get(selection.get('evidence_id'));w=next((w for w in doc['windows'] if w['window_id']==selection.get('window_id')),None) if doc else None
   if not w:missing.append({'selection':selection,'reason':rejected.get('reason'),'reconstruction':'not_reconstructed'});continue
   source=by_id[doc['source_id']];prior=old['source_review'][doc['source_id']]
   checked,error=validate_selection(selection,{doc['evidence_id']:doc},p.target_name,old['research_as_of'])
   cases.append({'source_id':doc['source_id'],'source_url':doc['source_url'],'source_title':doc['source_title'],
    'old_selection':selection,'old_rejection':rejected.get('reason'),'reproduced_rejection':error,
    'same_original_bytes':prior.get('original_sha256')==hashlib.sha256(source.content.strip().encode()).hexdigest(),
    'same_source_input':prior.get('source_input_sha256')==source_input_fingerprint(source),
    'old_receipt_input_sha256':receipt.get('input_sha256'),'quote':w['quote'],'start':w['start'],
    'source_kind':doc['source_kind'],'subject_binding':doc['subject_binding'],'document_date_proof':doc['document_date_proof'],
    'target_name':p.target_name,'as_of_date':old['research_as_of'],'original_sha256':prior.get('original_sha256')})
 (out/(company+'-old-proposals.json')).write_text(json.dumps({'cases':cases,'not_reconstructed':missing},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'company':company,'reconstructed':len(cases),'not_reconstructed':len(missing),'reasons':list(set(c['old_rejection'] for c in cases))},ensure_ascii=False),flush=True)
