"""Run real Ragas metrics over frozen private answers, with resumable audit files.

No production imports, deployments, business writes or external tracking. Supply
the existing approved model through RAG_EVAL_MODEL/BASE_URL/API_KEY environment.
Unanswerable cases are kept in the manifest but excluded from positive-fact
metrics; their refusal/citation regressions require separate business checks.
"""
import argparse
import asyncio
from contextvars import ContextVar
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import re
import time

os.environ['RAGAS_DO_NOT_TRACK']='true'
os.environ['LANGCHAIN_TRACING_V2']='false'
os.environ['LANGSMITH_TRACING']='false'


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def metric_inputs(row, name):
    contexts=[r['text'] for r in row['references']]
    if name=='context_recall':
        return {'user_input':row['question'],'retrieved_contexts':contexts,'reference':row['expected_answer']}
    if name=='factual_correctness':
        return {'response':row['answer'],'reference':row['expected_answer']}
    if name=='cited_faithfulness':
        cited=set(re.findall(r'\[id_([^\]]+)\]',row['answer']))
        if not cited and row.get('unanswerable'):return None
        known={str(r['id']) for r in row['references']}
        if not cited or not cited<=known:raise ValueError('Missing or unknown citation')
        contexts=[r['text'] for r in row['references'] if str(r['id']) in cited]
    return {'user_input':row['question'],'response':row['answer'],'retrieved_contexts':contexts}


async def run(args):
    import httpx
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.cache import DiskCacheBackend
    from ragas.metrics.collections import ContextRecall,Faithfulness,FactualCorrectness
    assert version('ragas')=='0.4.3','Use requirements-ragas.txt'
    rows=json.loads(args.answers.read_text(encoding='utf-8'))
    assert len({r['id'] for r in rows})==len(rows),'Duplicate case ID'
    assert all(r.get('answer') and not r.get('error') for r in rows),'Generation errors must be resolved first'
    args.output.mkdir(parents=True,exist_ok=True)
    identity=ContextVar('metric_identity',default=None)
    async def audit(response):
        await response.aread()
        target=identity.get()
        if target:
            record={'time':time.time(),'status':response.status_code,
                'request':json.loads(response.request.content),'response':response.text}
            with (args.output/(target+'-calls.jsonl')).open('a',encoding='utf-8') as f:
                f.write(json.dumps(record,ensure_ascii=False)+'\n')
    options={'temperature':0.0,'max_tokens':8192,'max_retries':2}
    options.update(json.loads(os.environ.get('RAG_EVAL_MODEL_OPTIONS','{}')))
    environment={p:version(p) for p in ('ragas','openai','instructor','langchain','langchain-core','langchain-community','langchain-openai')}
    config={'environment':environment,'model':os.environ['RAG_EVAL_MODEL'],
        'endpoint_sha256':digest(os.environ['RAG_EVAL_BASE_URL']),'model_options':options,
        'factual_correctness':{'mode':'f1','atomicity':'high','coverage':'high'},
        'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'unanswerable_policy':'not applicable to positive-fact metrics; retained for separate refusal checks'}
    manifest={'config':config,'answers_sha256':hashlib.sha256(args.answers.read_bytes()).hexdigest(),
        'case_ids':[r['id'] for r in rows],'excluded_unanswerable':[r['id'] for r in rows if r.get('unanswerable')],
        'citation_probe_ids':args.citation_ids,'metrics':['context_recall','faithfulness','factual_correctness']}
    path=args.output/'manifest.json'
    if path.exists():assert json.loads(path.read_text(encoding='utf-8'))==manifest,'Frozen run inputs changed'
    path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    semaphore=asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(timeout=180,trust_env=False,event_hooks={'response':[audit]}) as transport:
        client=AsyncOpenAI(api_key=os.environ['RAG_EVAL_API_KEY'],base_url=os.environ['RAG_EVAL_BASE_URL'],http_client=transport,max_retries=0)
        # Separate caches by complete judge configuration, including model options.
        cache=DiskCacheBackend(str(args.cache/digest(config)))
        llm=llm_factory(os.environ['RAG_EVAL_MODEL'],client=client,cache=cache,**options)
        metrics={'context_recall':ContextRecall(llm=llm),'faithfulness':Faithfulness(llm=llm),
            'factual_correctness':FactualCorrectness(llm=llm,mode='f1',atomicity='high',coverage='high'),
            'cited_faithfulness':Faithfulness(llm=llm)}
        factual_recall=FactualCorrectness(llm=llm,mode='recall',atomicity='high',coverage='high')
        async def score(row,name):
            payload=metric_inputs(row,name);fingerprint=digest({'config':config,'name':name,'input':payload})
            path=args.output/(row['id']+'-'+name+'.json');previous=None
            if path.exists():
                previous=json.loads(path.read_text(encoding='utf-8'))
                assert previous['fingerprint']==fingerprint,'Metric inputs changed'
                if previous['status'] in ('completed','not_applicable') or not args.retry_errors:return previous
            if payload is None:
                result={'id':row['id'],'metric':name,'fingerprint':fingerprint,'status':'not_applicable',
                    'value':None,'reason':'Unanswerable response has no citations; check refusal separately'}
                path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                return result
            async with semaphore:
                identity.set(row['id']+'-'+name);start=time.monotonic()
                result={'id':row['id'],'split':row['split'],'metric':name,'fingerprint':fingerprint,
                    'native_class':type(metrics[name]).__module__+'.'+type(metrics[name]).__name__}
                try:
                    outcome=await metrics[name].ascore(**payload);value=float(outcome.value)
                    if not math.isfinite(value):raise ValueError('Undefined metric value')
                    result.update(status='completed',value=value,reason=outcome.reason)
                    if name=='factual_correctness':
                        # Same native claim/NLI prompts; reuse cached judgments, change only aggregation.
                        result['factual_recall']=float((await factual_recall.ascore(**payload)).value)
                        if not math.isfinite(result['factual_recall']):raise ValueError('Undefined factual recall')
                except Exception as exc:
                    # Raw provider responses stay in private call audit files, never console output.
                    result.update(status='error',value=None,error=type(exc).__name__)
                result['seconds']=time.monotonic()-start
                if previous:
                    result['prior_attempts']=previous.get('prior_attempts',[])+[{k:v for k,v in previous.items() if k!='prior_attempts'}]
                path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps({k:result[k] for k in ('id','metric','status','value')},ensure_ascii=False),flush=True)
                return result
        tasks=[]
        for row in rows:
            if args.case_id and row['id'] not in args.case_id:continue
            if not row.get('unanswerable'):tasks.extend(score(row,name) for name in manifest['metrics'])
            if row['id'] in args.citation_ids:tasks.append(score(row,'cited_faithfulness'))
        await asyncio.gather(*tasks)
    summary={}
    for name in [*manifest['metrics'],'cited_faithfulness']:
        results=[json.loads(p.read_text(encoding='utf-8')) for p in args.output.glob('Q*-'+name+'.json')]
        complete=[r for r in results if r['status']=='completed']
        excluded=sum(r['status']=='not_applicable' for r in results)
        summary[name]={'completed':len(complete),'errors':sum(r['status']=='error' for r in results),'not_applicable':excluded,
            'mean':sum(r['value'] for r in complete)/len(complete) if complete else None,
            'mean_is_partial':len(complete)+excluded!=sum((r['id'] in args.citation_ids) if name=='cited_faithfulness' else not r.get('unanswerable') for r in rows)}
    factual=[json.loads(p.read_text(encoding='utf-8')) for p in args.output.glob('Q*-factual_correctness.json')]
    recall=[r['factual_recall'] for r in factual if r.get('status')=='completed' and 'factual_recall' in r]
    summary['factual_recall']={'completed':len(recall),'mean':sum(recall)/len(recall) if recall else None}
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--answers',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--cache',type=Path,required=True)
    p.add_argument('--concurrency',type=int,choices=range(1,5),default=3)
    p.add_argument('--case-id',nargs='+');p.add_argument('--retry-errors',action='store_true')
    p.add_argument('--citation-ids',nargs='+',default=['Q032','Q057','Q082','Q093'])
    asyncio.run(run(p.parse_args()))
