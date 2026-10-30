"""Reproduce native standard-role routing and unchanged-receipt counts offline."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case',choices=['haitian','kingsoft','holdout'])
    args=parser.parse_args()
    os.environ['PYTHON_DOTENV_DISABLED']='1'
    sys.path.insert(0,str(ROOT/'backend'))
    from report_agents.company_corpus import prepare_corpus,_batches,research_context,VERSION
    from report_agents.company_text import company_matching_cache
    native=ROOT/'work/company-phase1-20261028/native'/args.case
    store=native/'objects'
    pointer=json.loads((store/'projects/1/company_generation_checkpoint/current.json').read_text(encoding='utf-8'))
    path=(store/pointer['key']).resolve()
    assert path.is_relative_to(store.resolve())
    payload=path.read_bytes()
    assert hashlib.sha256(payload).hexdigest()==pointer['sha256']
    old=json.loads(payload)['packages']['company_corpus_analysis_cache']
    with sqlite3.connect((native/'acceptance.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        sources=[dict(r) for r in db.execute('SELECT * FROM research_sources WHERE project_id=1 ORDER BY id')]
        for source in sources:source['source_metadata']=json.loads(source['source_metadata'] or '{}')
        cleaned=json.loads(db.execute("SELECT content FROM research_artifacts WHERE artifact_type='cleaned_facts' ORDER BY id DESC LIMIT 1").fetchone()[0])
    intake=json.loads((native/'state/company_research_intake.json').read_text(encoding='utf-8'))
    project=SimpleNamespace(target_name=old['target_name'],sources=sources,company_research_intake=intake)
    started=time.monotonic()
    with company_matching_cache(max_chars=100_000_000,max_entries=30000):
        documents,states,_=prepare_corpus(project,cleaned)
    old_keys={r['input_sha256'] for r in old['review_receipts'] if not r.get('error')}
    context=research_context(project)
    scope='\ncontext:'+json.dumps(context,ensure_ascii=False,sort_keys=True) if context else ''
    batches=list(_batches(documents));hits=[]
    for i,batch in enumerate(batches):
        key=hashlib.sha256((old['version']+'\n'+project.target_name+'\n'+old['research_as_of']+scope+'\n'+
            json.dumps(batch,ensure_ascii=False,sort_keys=True)).encode()).hexdigest()
        if key in old_keys:hits.append(i)
    by_id={str(s['id']):s for s in sources}
    formerly_structural=[]
    for sid,prior in old['source_review'].items():
        if prior['state']!='native_windows_require_structural_or_scope_review':continue
        source=by_id[sid]
        formerly_structural.append({**states[sid],'source_id':sid,'source_url':source['url'],'source_title':source['title']})
    result={'case':args.case,'version':VERSION,'checkpoint_sha256':pointer['sha256'],
        'old_review_batches':len(old_keys),'current_review_batches':len(batches),
        'unchanged_old_batches':len(hits),'new_model_batches':len(batches)-len(hits),
        'new_role_documents':[d for d in documents if states[d['source_id']].get('native_scope_recovery')],
        'formerly_structural_states':formerly_structural,'new_model_calls':0,'report_accepted':False,
        'elapsed_seconds':round(time.monotonic()-started,3),
        'production_source_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [ROOT/'backend/report_agents/company_corpus.py',ROOT/'backend/report_agents/company_source_review.py']}}
    (native/'standard-route-offline-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'new_role_documents','formerly_structural_states'}},ensure_ascii=False))
    print('Recovered source IDs:',[d['source_id'] for d in result['new_role_documents']])
    return 0


if __name__=='__main__':raise SystemExit(main())
