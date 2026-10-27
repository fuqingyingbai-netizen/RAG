"""Review frozen information and write an auditable chapter-detail replay.

No search, download, scoring, or full-report rewriting is performed.
Run with --help for explicit input/output paths. Exact model receipts survive
interruptions; credentials are never written into the output.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from report_agents.company_information_usage import build_information_usage, render_information_sections
from report_agents.company_report_agent import COMPANY_REPORT_OUTLINE


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--digest',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--target',required=True)
    p.add_argument('--env-file',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--workers',type=int,default=6)
    args=p.parse_args();args.output.mkdir(exist_ok=True,parents=True)
    receipts=args.output/'model-receipts';receipts.mkdir(exist_ok=True)
    from dotenv import load_dotenv
    from openai import OpenAI
    load_dotenv(args.env_file,override=True)
    client=OpenAI(api_key=os.environ['ARK_API_KEY'],base_url=os.environ['BASE_URL'],timeout=180,max_retries=0)
    model=os.environ['MODEL'];lock=threading.Lock();counts={'new_calls':0,'cached_calls':0,'failed_calls':0,'completed_batches':0}
    start=time.time()
    def write(name,value):
        (args.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    def invoke(role,prompt,trace):
        key=hashlib.sha256((model+'\n'+role+'\n'+prompt).encode()).hexdigest();path=receipts/(key+'.json')
        if path.exists():
            raw=json.loads(path.read_text('utf-8'))
            if raw.get('response'):
                with lock:counts['cached_calls']+=1
                return raw['response']
        try:
            with lock:counts['new_calls']+=1
            response=client.chat.completions.create(model=model,temperature=0.1,
                messages=[{'role':'system','content':'你是严谨的公司材料核对员，仅审核给定原文，不搜索、不编造。输出JSON。'},
                          {'role':'user','content':prompt}],max_tokens=14000,extra_body={'enable_thinking':False})
            answer=response.choices[0].message.content or ''
            record={'model':model,'role':role,'prompt_sha256':key,'prompt':prompt,'response':answer,
                    'usage':response.usage.model_dump() if response.usage else None,
                    'finish_reason':response.choices[0].finish_reason,'enable_thinking':False}
            path.write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8')
            if response.choices[0].finish_reason=='length':raise ValueError('truncated_model_response')
            return answer
        except Exception as exc:
            with lock:
                counts['failed_calls']+=1
                write('progress.json',{**counts,'seconds':round(time.time()-start,1),'last_failure_type':type(exc).__name__})
            raise
    def callback(receipt):
        key=hashlib.sha256('\n'.join(receipt['information_ids']).encode()).hexdigest()
        (receipts/('batch-'+key+'.json')).write_text(json.dumps(receipt,ensure_ascii=False),encoding='utf-8')
        with lock:
            counts['completed_batches']+=1
            write('progress.json',{**counts,'seconds':round(time.time()-start,1)})
            print(json.dumps({**counts,'seconds':round(time.time()-start,1)},ensure_ascii=False),flush=True)
    digest=json.loads(args.digest.read_text('utf-8'));report=args.report.read_text('utf-8')
    sections={int(m[1]):m[0] for m in re.finditer(r'(?ms)^## (\d+)\..*?(?=^## \d+\.|\Z)',report)}
    package=build_information_usage(digest,sections,COMPANY_REPORT_OUTLINE,args.target,invoke,
        receipt_callback=callback,workers=args.workers)
    package['input_files']={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [args.digest,args.report]}
    package['diagnostic']['runtime']={**counts,'seconds':round(time.time()-start,1)}
    write('information-usage.json',package)
    write('chapter-details.json',render_information_sections(package,COMPANY_REPORT_OUTLINE))
    print(json.dumps(package['diagnostic'],ensure_ascii=False),flush=True)


if __name__=='__main__':main()
