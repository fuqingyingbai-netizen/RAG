"""One small, real request to the configured company editor; prints no key."""
from pathlib import Path
import json
import sys
import time
from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parents[2]
load_dotenv(ROOT/'.env',override=True)
sys.path[:0]=[str(ROOT/'backend'),str(ROOT)]
from research_workflow import ResearchWorkflow

if __name__=='__main__':
    report={'kind':'company_flow_editor_preflight','request_count':1,'credentials_printed':False}
    start=time.monotonic();usage=[]
    workflow=ResearchWorkflow()
    text=workflow._invoke_company_report_editor('公司链路实验连通性核对',
        '仅返回严格JSON：{"ready":true}。不要解释或添加其他内容。',usage_sink=usage.append)
    report.update(seconds=round(time.monotonic()-start,3),response_received=bool(text),usage=usage)
    try:report['ready']=json.loads(text).get('ready') is True
    except Exception:report['ready']=False
    path=ROOT/'work/company-template-plan-20261103/flow-preflight.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    raise SystemExit(0 if report['ready'] else 2)
