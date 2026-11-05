"""Trace a frozen rejected native range into saved usage and adopted prose."""
import argparse,hashlib,json,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]


def normalized(value):return ''.join(value.split())


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--directory',required=True);ap.add_argument('--cases',required=True)
    ap.add_argument('--original-source-id',required=True,type=int);ap.add_argument('--company',required=True);args=ap.parse_args()
    db=sqlite3.connect((ROOT/'work'/args.directory/'research.sqlite').resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    report=db.execute("SELECT * FROM research_artifacts WHERE artifact_type='desktop_report' ORDER BY id DESC LIMIT 1").fetchone()
    metadata=json.loads(report['artifact_metadata']);native=metadata['company_source_review_evidence']['facts']
    def package(kind):return json.loads(db.execute('SELECT content FROM research_artifacts WHERE artifact_type=? ORDER BY id DESC LIMIT 1',(kind,)).fetchone()[0])
    usage=package('company_information_usage');editorial=package('company_editorial');sources=[]
    for row in db.execute('SELECT * FROM research_sources'):
        s=dict(row);s['source_metadata']=json.loads(s['source_metadata'] or '{}')
        if s['source_metadata'].get('original_fixture_source_id')==args.original_source_id:sources.append(s)
    assert len(sources)==1;source=sources[0];raw=source['content'].strip();digest=hashlib.sha256(raw.encode()).hexdigest()
    cases=json.loads(Path(args.cases).read_text(encoding='utf-8'))['cases'];traces=[]
    for case in cases:
        if str(case['source_id'])!=str(args.original_source_id):continue
        assert case['same_original_bytes'] and case['same_source_input'] and case['original_sha256']==digest
        left=case['start'];right=left+len(case['quote']);assert raw[left:right]==case['quote']
        facts=[f for f in native if f['source_id']==str(source['id']) and f['original_sha256']==digest and f['original_offset']<right and f['original_end']>left]
        texts={normalized(f['fact']) for f in facts}
        records=[r for r in usage['records'] if normalized(r['text']) in texts and r.get('context',{}).get('original_sha256')==digest]
        ids={r['information_id'] for r in records}
        prose=[f for f in editorial['findings'] if ids & set(f.get('information_ids',[]))]
        assert all(f['text'] in report['content'] for f in prose)
        traces.append({'old_selection':case['old_selection'],'old_rejection':case['old_rejection'],
            'old_quote':case['quote'],'old_start':left,'old_end':right,
            'native_selections':[{'chapter':f['chapter'],'scope':f['scope'],'quote':f['fact'],'start':f['original_offset'],'end':f['original_end']} for f in facts],
            'information_ids':sorted(ids),'adopted_saved_prose':prose})
    result={'company':args.company,'original_source_id':args.original_source_id,'source_sha256':digest,
        'report_artifact_id':report['id'],'report_sha256':hashlib.sha256(report['content'].encode()).hexdigest(),
        'scope':'Exact native-range overlap and identical information text traced into saved adopted prose; semantic equivalence is for human review, not inferred from overlap.',
        'traces':traces}
    (ROOT/'docs/deliverables/company-recovery-20261104'/(args.company+'-legacy-statement-readback.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'company':args.company,'old_ranges':len(traces),'saved_adopted_passages':len({f['finding_id'] for t in traces for f in t['adopted_saved_prose']})}))
    db.close()


if __name__=='__main__':main()
