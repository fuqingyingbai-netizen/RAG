"""Compare frozen financial fields through old and current parsers, without calls or DB writes."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,importlib.util,json,os,sqlite3,subprocess,sys

root=Path(__file__).resolve().parents[1];out=root/'work/company-phase1-20261028/financial-negative-field-review'
assert Path.cwd().resolve()==root
out.mkdir(parents=True,exist_ok=True)
os.environ['PYTHON_DOTENV_DISABLED']='1';sys.path.insert(0,str(root/'backend'))
from report_agents.company_diligence import disclosure_rows,VERSION
from report_agents.company_evidence import document_pages
old_code=subprocess.check_output(['git','show','d03e31f:backend/report_agents/company_diligence.py'])
old_file=out/'previous_diligence_d03e31f.py';old_file.write_bytes(old_code)
spec=importlib.util.spec_from_file_location('report_agents._previous_diligence',old_file)
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
db_path=root/'work/company-phase1-20261028/native/haitian/acceptance.sqlite'
records=[]
with sqlite3.connect(db_path.as_uri()+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    sources=[dict(row) for row in db.execute('SELECT * FROM research_sources WHERE id IN (25,34,46) OR content LIKE ?',('%1,124,166.67%',))]
for source in sources:
    source['source_metadata']=json.loads(source['source_metadata'] or '{}')
    for page in document_pages(source):
        if ((source['id']==25 and page['page']==156) or (source['id'] in (34,46) and page['page'] in (114,118)) or ('1,124,166.67' in page['text'])):
            base={'entity':'佛山市海天调味食品股份有限公司','source_url':source['url'],'source_title':source['title'],'period':''}
            def take(fn):return [{k:r[k] for k in ('kind','page','evidence_quote','mode')} for r in fn(source,[page],base) if r['kind'] in ('payment_pending','related_funding')]
            records.append({'source_id':source['id'],'source_url':source['url'],'physical_page':page['page'],
                'original_page_sha256':hashlib.sha256(page['text'].encode()).hexdigest(),
                'before':take(previous.disclosure_rows),'after':take(disclosure_rows)})
            (out/f"source{source['id']}-page{page['page']}.txt").write_bytes(page['text'].encode())
result={'observed_at':datetime.now(timezone.utc).isoformat(),'previous_commit':'d03e31f','current_version':VERSION,
    'model_calls':0,'http_calls':0,'database_mode':'read_only','originals_modified':False,'production_cache_modified':False,
    'full_report_accepted':False,'records':records}
destination=root/'deliverables/company-phase1-20261028/financial-boundary-real-replay.json'
destination.write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode())
print(json.dumps([{'source':r['source_id'],'page':r['physical_page'],'before':[x['kind'] for x in r['before']],'after':[x['kind'] for x in r['after']]} for r in records]))
