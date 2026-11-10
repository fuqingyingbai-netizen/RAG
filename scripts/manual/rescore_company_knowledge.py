"""Recompute deterministic evidence metrics from recorded IDs and original chunks.

No new retrieval or model calls. Preserve prior metrics for audit. This repairs
presentation-only matching issues without changing the generated answers/judgments.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from company_retrieval import evidence_id, select_evidence
from company_quality import retrieval_metrics


def rescore(corpus_path,dataset_path,results):
    docs=json.loads(corpus_path.read_text(encoding='utf-8'));corpus={d['id']:d for d in docs}
    chunks={}
    for doc in docs:
        for node in doc['chunks']:
            meta=node.get('metadata') or {};text=str(meta.get('content') or node.get('text') or '').strip()
            chunks[evidence_id(doc['cloud_id'],text)]=(doc['cloud_id'],meta,text)
    cases=json.loads(dataset_path.read_text(encoding='utf-8'));count=0
    for case in cases:
        path=results/(case['id']+'-optimized.json')
        if not path.exists():continue
        row=json.loads(path.read_text(encoding='utf-8'));trace=row.get('trace')
        if not trace:continue
        ids=trace['candidate_ids']
        missing=[key for key in ids if key not in chunks]
        if missing:raise ValueError('Recorded candidate cannot be reconstructed: '+case['id'])
        nodes=[{'score':len(ids)-i,'metadata':{**chunks[key][1],'doc_id':chunks[key][0],'content':chunks[key][2]},'text':chunks[key][2]}
            for i,key in enumerate(ids)]
        allowed={corpus[k]['cloud_id']:{} for k in case['scope_ids']}
        candidates=[{'document_id':chunks[key][0],'text':chunks[key][2]} for key in ids]
        source_case={**case,'answer':row.get('answer',''),'evidence':[{**e,'document_id':corpus[e['document_id']]['cloud_id']} for e in case.get('evidence',[])]}
        metrics=retrieval_metrics(source_case,candidates,row.get('references',[]))
        if 'automated_context_precision' in row.get('metrics',{}):metrics['automated_context_precision']=row['metrics']['automated_context_precision']
        old,_=select_evidence(nodes,allowed,corpus[case['scope_ids'][0]]['index_id'],case['question'],legacy=True)
        baseline=[{'id':str(i),'document_id':doc_id,'text':text} for i,(doc_id,_,text) in enumerate(old,1)]
        row.setdefault('metrics_before_rescore',deepcopy(row.get('metrics')))
        row['metrics']=metrics;row['baseline_evidence_metrics']=retrieval_metrics({**source_case,'answer':''},candidates,baseline)
        row['metric_version']='gold-quote-br-normalization-v2'
        row['original_candidate_ids_verified']=True
        path.write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8');count+=1
    return count


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',type=Path,required=True);p.add_argument('--dataset',type=Path,required=True);p.add_argument('--results',type=Path,required=True)
    a=p.parse_args();print(json.dumps({'rescored':rescore(a.corpus,a.dataset,a.results),'new_model_calls':0}))
