"""One actual configured tool per provider; failures remain collection gaps."""
import json,os,sys,time
from pathlib import Path
from types import SimpleNamespace as NS
from urllib.parse import urlencode
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parents[2];load_dotenv(ROOT/'.env',override=True)
os.environ.update(RESEARCH_OBJECT_STORE='local',RESEARCH_LOCAL_STORE=str(ROOT/'work/platform-smoke/objects'),DATABASE_URL='sqlite://')
sys.path[:0]=[str(ROOT/'backend'),str(ROOT)]
from research_workflow import ResearchWorkflow
from company_platform import CompanyPlatformAudit,redact_provider_payload,failure_kind
from report_agents.company_transport import failure_diagnostic
w=ResearchWorkflow();p=NS(id=1,target_type='company',company_professional_platform_attempts=[])
target='佛山市海天调味食品股份有限公司';records=[]
providers=[('qcc',os.getenv('QCC_API_KEY',''),os.getenv('QCC_MCP_COMPANY_URL','https://agent.qcc.com/mcp/company/stream'),'get_company_registration_info',{'searchKey':target}),
    ('tyc',os.getenv('TYC_API_KEY') or os.getenv('TENC_API_KEY',''),os.getenv('TYC_MCP_URL','https://mcp.tianyancha.com/v1'),'search_companies',{'query':target,'page':1,'page_size':1}),
    ('xiniu',os.getenv('XINIU_API_KEY',''),os.getenv('XINIU_MCP_URL','https://vip.xiniudata.com/mcp'),'get_company_info',{'firm_name':target,'aspect':'企业基本信息'})]
out=ROOT/'docs/deliverables/company-recovery-20261104';work=ROOT/'work/platform-smoke';work.mkdir(parents=True,exist_ok=True)
for provider,key,url,tool,args in providers:
    row={'provider':provider,'tool':tool,'arguments':args,'tool_calls':0,'initialization_attempts':0};start=time.monotonic()
    if not key:row.update(status='not_configured',collection_gap=True);records.append(row);continue
    headers={'Authorization':('Bearer '+key if provider=='qcc' else key)} if provider!='xiniu' else {}
    if provider=='xiniu' and 'api_key=' not in url:url+=('?' if '?' not in url else '&')+urlencode({'api_key':key})
    audit=CompanyPlatformAudit(p,provider,key,{},subject=target)
    try:
        row['initialization_attempts']=1
        session,ok,error=audit.initialize(w._mcp_initialize,url,headers,timeout=15)
        if not ok:
            # Raw errors stay in private runtime; public evidence has categories only.
            audit.result('initialize',{}, {'error':error});row.update(status='initialization_failed',collection_gap=True,failure_kind=failure_kind({'error':error}))
        else:
            row['tool_calls']=1
            payload,_=audit.call(w._mcp_call_tool,url,headers,tool,args,session=session,timeout=15)
            audit.result(tool,args,payload)
            payload=redact_provider_payload(payload);raw=json.dumps(payload,ensure_ascii=False,indent=2)
            (work/(provider+'-raw.json')).write_text(raw,encoding='utf-8')
            import hashlib
            row.update(status='failed' if failure_kind(payload) else 'returned',collection_gap=bool(failure_kind(payload)),
                failure_kind=failure_kind(payload),raw_sha256=hashlib.sha256(raw.encode()).hexdigest(),raw_chars=len(raw),
                boundary='Returned platform assertions are not independently verified legal or financial facts.')
    except Exception as exc:row.update(status='transport_failed',collection_gap=True,error=failure_diagnostic(exc,stage='platform_'+provider))
    row['seconds']=round(time.monotonic()-start,3);records.append(row)
    (out/'platform-real-smoke.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(row,ensure_ascii=False),flush=True)
