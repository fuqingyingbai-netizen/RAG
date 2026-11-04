"""Read-only frozen-source census; no model calls or original database writes."""
import argparse,hashlib,json,sqlite3,sys
from pathlib import Path
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'backend'),str(ROOT)]
from report_agents.company_model_reading import prepare_model_corpus
from report_agents.company_reading_recovery import uncovered_ranges


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--native-root',required=True);args=parser.parse_args()
    output=ROOT/'docs/deliverables/company-recovery-20261104';output.mkdir(parents=True,exist_ok=True)
    summaries={}
    for company in ('haitian','kingsoft'):
        path=Path(args.native_root)/company/'acceptance.sqlite'
        db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
        project=dict(db.execute('SELECT * FROM research_projects WHERE id=1').fetchone())
        report=db.execute("SELECT id,artifact_metadata FROM research_artifacts WHERE artifact_type='desktop_report' ORDER BY id DESC LIMIT 1").fetchone()
        metadata=json.loads(report['artifact_metadata']);old=metadata.get('company_source_review_evidence',{})
        sources=[]
        for row in db.execute('SELECT * FROM research_sources WHERE project_id=1 ORDER BY id'):
            value=dict(row);value['source_metadata']=json.loads(value['source_metadata'] or '{}');sources.append(NS(**value))
        db.close()
        p=NS(**project);p.sources=sources;p.company_research_intake={'as_of_date':old.get('research_as_of','')}
        # Stream originals: the census needs ranges, not hundreds of MB of
        # duplicated neighboring context resident at the same time.
        by_id={};states={};candidate_sources=0;candidate_windows=0
        for source in sources:
            p.sources=[source];docs,local_states,_=prepare_model_corpus(p)
            states.update(local_states);candidate_sources+=len(docs)
            candidate_windows+=sum(len(d['windows']) for d in docs)
            for d in docs:
                by_id[d['source_id']]={'ranges':[[w['start'],w['end']] for w in d['windows']]}
        records=[]
        for sid,prior in old.get('source_review',{}).items():
            current=states.get(sid,{});doc=by_id.get(sid);coverage=[] if not doc else doc['ranges']
            records.append({'source_id':sid,'before_state':prior.get('state'),'before_windows':prior.get('review_windows',0),
                'before_original_sha256':prior.get('original_sha256'),'current_original_sha256':current.get('original_sha256'),
                'same_native_bytes':prior.get('original_sha256')==current.get('original_sha256'),
                'after_state':current.get('state'),'after_candidate_windows':len(coverage),
                'original_chars':current.get('scanned_chars',0),'planned_ranges':coverage,
                'planned_uncovered_ranges':uncovered_ranges(current.get('scanned_chars',0),coverage),
                'model_read_in_this_census':False,'admitted_to_model_reading_plan':bool(doc),
                'post_cutoff_disclosure':current.get('post_cutoff_disclosure',False)})
        categories={}
        for row in records:
            state=row['before_state'];value=categories.setdefault(state,{'sources':0,'now_planned':0,'same_bytes':0})
            value['sources']+=1;value['now_planned']+=int(row['admitted_to_model_reading_plan']);value['same_bytes']+=int(row['same_native_bytes'])
        summaries[company]={'input_report_artifact_id':report['id'],'source_count':len(sources),'old_review_sources':len(records),
            'candidate_sources':candidate_sources,'candidate_windows':candidate_windows,
            'categories':categories,'model_calls':0,'boundary':'Coverage planning only. No model relevance judgment, report acceptance or new interface collection is asserted.'}
        (output/(company+'-frozen-admission-ledger.json')).write_text('[\n'+',\n'.join(
            json.dumps(r,ensure_ascii=False,separators=(',',':')) for r in records)+'\n]\n',encoding='utf-8')
        print(json.dumps({company:summaries[company]},ensure_ascii=False),flush=True)
    (output/'frozen-admission-summary.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
