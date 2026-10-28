"""Revalidate stored corpus proposals under current gates, without cache writes."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]


def digest(value):return hashlib.sha256(value).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case',choices=['haitian','kingsoft','holdout'])
    parser.add_argument('--checkpoint-sha',help='Revalidate a preserved payload in this case instead of the live pointer.')
    args=parser.parse_args()
    if args.checkpoint_sha and not re.fullmatch('[0-9a-f]{64}',args.checkpoint_sha):
        parser.error('checkpoint-sha must be a lowercase SHA256 digest')
    os.environ['PYTHON_DOTENV_DISABLED']='1'
    sys.path.insert(0,str(ROOT/'backend'))
    from report_agents.company_corpus import build_corpus_review,VERSION
    from report_agents.company_text import company_matching_cache
    native=ROOT/'work/company-phase1-20261028/native'/args.case
    store=native/'objects'
    directory=store/'projects/1/company_generation_checkpoint'
    pointer=(dict(key=(directory/(args.checkpoint_sha+'.json')).relative_to(store).as_posix(),sha256=args.checkpoint_sha)
             if args.checkpoint_sha else json.loads((directory/'current.json').read_text(encoding='utf-8')))
    path=(store/pointer['key']).resolve()
    assert path.is_relative_to(store.resolve())
    payload=path.read_bytes();assert digest(payload)==pointer['sha256']
    old=json.loads(payload)['packages']['company_corpus_analysis_cache']
    original_responses=digest(json.dumps(old['review_receipts'],ensure_ascii=False,sort_keys=True).encode())
    with sqlite3.connect((native/'acceptance.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        sources=[dict(r) for r in db.execute('SELECT * FROM research_sources WHERE project_id=1 ORDER BY id')]
        for source in sources:source['source_metadata']=json.loads(source['source_metadata'] or '{}')
        cleaned=json.loads(db.execute("SELECT content FROM research_artifacts WHERE artifact_type='cleaned_facts' ORDER BY id DESC LIMIT 1").fetchone()[0])
    intake=json.loads((native/'state/company_research_intake.json').read_text(encoding='utf-8'))
    project=SimpleNamespace(target_name=old['target_name'],sources=sources,company_research_intake=intake,
                            company_corpus_analysis_cache=old)
    def no_model(*args,**kwargs):raise BaseException('Offline revalidation refuses every new model request.')
    with company_matching_cache(max_chars=100_000_000,max_entries=30000):
        current=build_corpus_review(project,cleaned,{},no_model,lambda *a,**kw:None)
    assert original_responses==digest(json.dumps(old['review_receipts'],ensure_ascii=False,sort_keys=True).encode())
    assert current['diagnostic']['model_requests']==0
    previous_ids={f['statement_id'] for f in old['facts']}
    current_ids={f['statement_id'] for f in current['facts']}
    added=[f for f in current['facts'] if f['statement_id'] not in previous_ids]
    result={'case':args.case,'previous_version':old['version'],'current_version':VERSION,
        'checkpoint_sha256':pointer['sha256'],'previous_facts':len(old['facts']),'current_facts':len(current['facts']),
        'removed_statement_ids':sorted(previous_ids-current_ids),
        'new_statements':[{k:f.get(k) for k in ['statement_id','source_id','source_url','chapter','fact',
                          'original_offset','scope','boundary','selection_corrections']} for f in added],
        'diagnostic':current['diagnostic'],'old_receipts_sha256_before_and_after':original_responses,
        'raw_receipts_modified':False,'production_cache_modified':False,'new_model_calls':0,'new_search_calls':0,
        'full_report_accepted':False,'independent_full_report_semantic_review':'not_performed',
        'fact_count_definition':'Model-proposed literal records passing current selection guards, including corroborating copies; not a count of independently verified business conclusions or unique events.',
        'production_source_sha256':{p.relative_to(ROOT).as_posix():digest(p.read_bytes()) for p in
            [ROOT/'backend/report_agents/company_corpus.py',ROOT/'backend/report_agents/company_source_review.py']}}
    (native/'corpus-revalidation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['case','previous_facts','current_facts','removed_statement_ids',
        'new_model_calls','raw_receipts_modified','production_cache_modified','full_report_accepted']},ensure_ascii=False))


if __name__=='__main__':main()
