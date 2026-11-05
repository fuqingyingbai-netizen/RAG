"""Compare staged governance extraction with current code on frozen real data."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,importlib.util,json,sqlite3,sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from report_agents import company_governance as current
spec=importlib.util.spec_from_file_location('report_agents.company_governance_candidate',HERE/'company_governance.py')
candidate=importlib.util.module_from_spec(spec);spec.loader.exec_module(candidate)
metadata=json.loads((HERE/'candidate.json').read_text(encoding='utf-8'))
assert hashlib.sha256((HERE/'company_governance.py').read_bytes()).hexdigest()==metadata['candidate_utf8_sha256']
assert hashlib.sha256((ROOT/'backend/report_agents/company_governance.py').read_bytes()).hexdigest()==metadata['base_utf8_sha256']


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()


path=ROOT/'work/company-phase1-20261028/baseline/kingsoft/acceptance.sqlite'
with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    row=db.execute("SELECT id,content FROM research_artifacts WHERE artifact_type='cleaned_facts' ORDER BY version DESC,id DESC LIMIT 1").fetchone()
    artifact_id=row['id'];cleaned=json.loads(row['content'])
    target=db.execute('SELECT target_name FROM research_projects WHERE id=1').fetchone()[0]
    sources=[]
    for row in db.execute('SELECT * FROM research_sources WHERE project_id=1 ORDER BY id'):
        values=dict(row)
        if isinstance(values.get('source_metadata'),str):values['source_metadata']=json.loads(values['source_metadata'])
        sources.append(values)
before=digest({'cleaned':cleaned,'sources':sources})
old=current.build_governance_package(cleaned,target,sources,as_of_date='2026-10-24')
new=candidate.build_governance_package(cleaned,target,sources,as_of_date='2026-10-24')
assert before==digest({'cleaned':cleaned,'sources':sources})
fixed={'成立日期','统一社会信用代码'}
old_conflicts={r['field']:r for r in old['conflicts']};new_conflicts={r['field']:r for r in new['conflicts']}
assert fixed<=set(old_conflicts) and not fixed&set(new_conflicts)
assert new_conflicts['注册资本']==old_conflicts['注册资本']
old_dates=[r for r in old['facts'] if r.get('field')=='成立日期']
new_dates=[r for r in new['facts'] if r.get('field')=='成立日期']
assert old_dates==new_dates
codes=[r for r in new['facts'] if r.get('field')=='统一社会信用代码']
assert codes and all(r['value']=='91110108587665983J' for r in codes)
assert set(e for r in old['facts'] if r.get('field')=='统一社会信用代码' for e in r['evidence_ids'])==set(e for r in codes for e in r['evidence_ids'])
result={'at':datetime.now(timezone.utc).isoformat(),'case':'kingsoft','scope':'isolated staged builder over complete frozen baseline inputs',
    'baseline_cleaned_artifact_id':artifact_id,'source_records':len(sources),'input_digest':before,
    'candidate':metadata,'current_governance_version':current.VERSION,'candidate_governance_version':candidate.VERSION,
    'current_fact_count':len(old['facts']),'candidate_fact_count':len(new['facts']),
    'removed_format_or_boundary_conflicts':sorted(fixed),'all_original_date_records_preserved':True,
    'all_credit_code_evidence_ids_preserved':True,'real_capital_conflict_preserved':new_conflicts['注册资本'],
    'input_objects_unchanged':True,'model_or_network_calls':0,'business_data_or_cache_writes':0,
    'runtime_backend_modified':False,'promoted':False,'final_report_accepted':False}
(HERE/'replay-proof.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:result[k] for k in ['source_records','current_fact_count','candidate_fact_count','removed_format_or_boundary_conflicts','input_objects_unchanged','promoted','final_report_accepted']},ensure_ascii=True))
