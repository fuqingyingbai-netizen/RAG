"""Replay the production company writer and delivery contract on frozen sources.

No collection or deployment. Exact model receipts and failed attempts are kept.
Use --sources for native source snapshots, or --usage/--report/--state to
exercise the new editorial stage against a prior retained corpus in full.
Word export and page QA remain separate, explicit operations.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from report_agents.company_report_agent import CompanyReportAgent,COMPANY_REPORT_OUTLINE
from report_agents.company_editorial import build_editorial_package,digest_groups,apply_narrative_uses,render_conflicts
from report_agents.company_delivery_contract import split_sections,fill_evidence_gaps
from report_agents.company_corpus_writer import render_compact_chapters
from research_workflow import ResearchWorkflow


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--target',required=True)
    parser.add_argument('--sources',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--env-file',type=Path,required=True)
    parser.add_argument('--as-of',required=True)
    parser.add_argument('--usage',type=Path)
    parser.add_argument('--report',type=Path)
    parser.add_argument('--state',type=Path)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    receipts=args.output/'model-receipts';receipts.mkdir(exist_ok=True)
    read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
    def write(name,value):
        (args.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    code_root=Path(__file__).resolve().parents[1]
    proof_files=sorted([str(p.relative_to(code_root)).replace('\\','/')
        for p in (code_root/'backend/report_agents').glob('company*.py')]+[
        'backend/research_workflow.py','backend/research_schemas.py','backend/research_api.py',
        'backend/docx_exporter.py','diagnostics/replay_company_delivery.py'])
    write('replay-input.json',{'target':args.target,'as_of':args.as_of,
        'source_snapshots_sha256':hashlib.sha256(args.sources.read_bytes()).hexdigest(),
        'code_root':str(code_root),'code_sha256':{f:hashlib.sha256((code_root/f).read_bytes()).hexdigest() for f in proof_files}})
    from dotenv import load_dotenv
    from openai import OpenAI
    load_dotenv(args.env_file,override=True)
    client=OpenAI(api_key=os.environ['ARK_API_KEY'],base_url=os.environ['BASE_URL'],timeout=180,max_retries=0)
    model=os.environ['MODEL'];lock=threading.Lock();counts={'new_calls':0,'cached_calls':0,'failed_calls':0}
    def invoke(role,prompt,trace=None):
        key=hashlib.sha256((model+'\n'+role+'\n'+prompt).encode()).hexdigest();path=receipts/(key+'.json')
        if path.exists():
            old=read(path)
            if old.get('finish_reason')!='length' and old.get('response'):
                with lock:counts['cached_calls']+=1
                return old['response']
        with lock:counts['new_calls']+=1
        try:
            result=client.chat.completions.create(model=model,temperature=0.1,max_tokens=16000,
                messages=[{'role':'system','content':'你是严谨的公司研究编辑与核对员，只依据给定材料，保留来源和范围。返回指定格式。'},
                          {'role':'user','content':prompt}],extra_body={'enable_thinking':False})
            answer=result.choices[0].message.content or '';finish=result.choices[0].finish_reason
            path.write_text(json.dumps({'model':model,'role':role,'prompt_sha256':key,'prompt':prompt,
                'response':answer,'finish_reason':finish,'usage':result.usage.model_dump() if result.usage else None},ensure_ascii=False),encoding='utf-8')
            if finish=='length':raise ValueError('truncated_model_response')
            return answer
        except Exception:
            with lock:counts['failed_calls']+=1
            raise
    def emit(*parts,**data):
        event=parts[0] if len(parts)==1 and isinstance(parts[0],dict) else data
        with lock:
            write('progress.json',{'model_calls':dict(counts),'event':event})
        if event.get('label'):print(event['label'],flush=True)
    source_data=read(args.sources)
    if isinstance(source_data,dict):source_data=source_data['sources']
    sources=[SimpleNamespace(**{'id':i+1,'title':'','url':'','content':'','summary':'','source_type':'web',
        'source_metadata':{},'credibility_score':70,'created_at':None,**s}) for i,s in enumerate(source_data)]
    project=SimpleNamespace(id=1,target_type='company',target_name=args.target,title=args.target,
        industry='',description='',sources=sources,artifacts=[],
        company_research_intake={'as_of_date':args.as_of,'target_type':'company','target_name':args.target,
                                 'ai_search_enabled':False})
    for attr,filename in [('company_editorial_cache','company_editorial_package.json'),
                          ('company_corpus_analysis_cache','company_source_review_package.json')]:
        if (args.output/filename).exists():setattr(project,attr,read(args.output/filename))
    if args.state:
        for key,value in read(args.state).items():
            if key.startswith('company_'):setattr(project,key,value)
    workflow=ResearchWorkflow.__new__(ResearchWorkflow)
    workflow._invoke_company_report_editor=lambda role,prompt,emit=None:invoke(role,prompt,emit)
    if args.usage:
        if not args.report:parser.error('--usage requires --report')
        usage=read(args.usage);project.company_information_usage_package=usage
        editor=build_editorial_package(usage,COMPANY_REPORT_OUTLINE,args.target,invoke,
            previous=read(args.output/'company_editorial_package.json') if (args.output/'company_editorial_package.json').exists() else None,
            workers=6,emit=lambda *a,**kw:emit(**kw))
        project.company_editorial_package=editor
        digest={'statements':[],'groups':digest_groups(editor),'diagnostic':editor['diagnostic']}
        project.company_corpus_digest_package=digest
        sections=render_compact_chapters(project,digest,COMPANY_REPORT_OUTLINE,split_sections(args.report.read_text('utf-8')))
        sections=render_conflicts(editor,sections);sections=fill_evidence_gaps(sections,editor,COMPANY_REPORT_OUTLINE,usage=usage)
        apply_narrative_uses(usage,editor)
        sections[1]=CompanyReportAgent()._write_summary(project,'{}',sections,invoke,lambda *a,**kw:None)
        report='\n\n'.join(sections[n] for n in sorted(sections))
    else:
        report=CompanyReportAgent().generate(project,'{"facts":[]}','{}',invoke,lambda s,n:s[:n],lambda *a,**kw:emit(**kw))
    report=workflow._consolidate_report_verification_gaps(report,target_type='company')
    report=workflow._append_report_evidence_index(project,report,'{}')
    report,metadata=workflow._prepare_company_delivery(project,report)
    errors=[]
    try:workflow._validate_delivery_report(project,report)
    except RuntimeError as exc:errors=[str(exc)]
    (args.output/'report.md').write_text(report,encoding='utf-8')
    write('outline.json',COMPANY_REPORT_OUTLINE)
    write('source-snapshots.json',source_data)
    for key,value in vars(project).items():
        if key.startswith('company_'):write(key+'.json',value)
    write('verification.json',{'target':args.target,'as_of':args.as_of,'source_records':len(sources),
        'new_collection_calls':0,'model_calls':counts,'content_contract':project.company_delivery_contract,
        'legacy_gate_errors':errors,'metadata':metadata,'scope':'冻结原文的完整生成及成稿验收回放；非新增全网尽调。'})
    print(json.dumps({'target':args.target,'contract_status':project.company_delivery_contract['status'],
        'legacy_gate_errors':errors,'editorial':getattr(project,'company_editorial_package',{}).get('diagnostic',{}),
        'model_calls':counts},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
