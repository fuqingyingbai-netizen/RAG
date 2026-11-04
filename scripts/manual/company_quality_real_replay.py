"""Replay retained real failure cases with current producer/reviewer code."""
import hashlib,json,os,sqlite3,sys,time
from pathlib import Path
from types import SimpleNamespace
from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parents[2]


def main():
    load_dotenv(ROOT/'.env',override=True)
    directory=ROOT/'work/quality-haitian-targeted';directory.mkdir(parents=True,exist_ok=True)
    os.environ.update(DATABASE_URL='sqlite:///'+str(directory/'research.sqlite').replace('\\','/'),
        RESEARCH_OBJECT_STORE='local',RESEARCH_LOCAL_STORE=str(directory/'objects'),
        LANGCHAIN_TRACING_V2='false',LANGSMITH_TRACING='false',COMPANY_EDITORIAL_WORKERS='1')
    sys.path[:0]=[str(ROOT/'backend'),str(ROOT)]
    from research_workflow import ResearchWorkflow
    from report_agents import company_editorial as ed
    from report_agents.company_report_agent import COMPANY_REPORT_OUTLINE as outline
    from report_agents.company_summary import fallback_company_summary
    from docx_exporter import markdown_to_docx_bytes
    fixture=ROOT/'work/recovery-haitian-source30/research.sqlite'
    db=sqlite3.connect(fixture.resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    def artifact(kind):return json.loads(db.execute('SELECT content FROM research_artifacts WHERE artifact_type=? ORDER BY id DESC LIMIT 1',(kind,)).fetchone()[0])
    usage=artifact('company_information_usage');previous=artifact('company_editorial')
    source=dict(db.execute('SELECT * FROM research_sources WHERE id=1').fetchone());source['source_metadata']=json.loads(source['source_metadata']);db.close()
    rows=[r for r in usage['records'] if r['information_id'] in {'I-6664f1735e6d3c38','I-57f34e709cfbbbcf'}]
    assert len(rows)==2
    target=rows[0]['context'].get('entity') or '佛山市海天调味食品股份有限公司'
    workflow=ResearchWorkflow();calls=[];usages=[]
    def invoke(role,prompt,trace=None):
        started=time.monotonic()
        answer=workflow._invoke_company_report_editor(role,prompt,usage_sink=usages.append)
        calls.append({'role':role,'input_sha256':ed.fingerprint(prompt),'input_chars':len(prompt),
                      'output_chars':len(answer),'seconds':round(time.monotonic()-started,3)})
        print(json.dumps(calls[-1],ensure_ascii=False),flush=True)
        return answer
    started=time.monotonic()
    package=ed.build_editorial_package({'records':rows},outline,target,invoke,workers=1,previous=previous,originals=[source])
    first_calls=len(calls)
    repeated=ed.build_editorial_package({'records':rows},outline,target,invoke,workers=1,previous=package,originals=[source])
    identical_calls=len(calls)-first_calls
    old=ed.audit_prompt
    ed.audit_prompt=lambda *a,**kw:'补充审稿要求：每段必须保留股东会会议材料的真实文类，不能写成年报披露。'+old(*a,**kw)
    changed=ed.build_editorial_package({'records':rows},outline,target,invoke,workers=1,previous=package,originals=[source])
    changed_calls=len(calls)-first_calls
    ed.audit_prompt=old
    report='## 6. 主营业务\n\n'+'\n\n'.join(f['text']+''.join('['+eid+']' for eid in f['evidence_ids']) for f in package['findings'])
    (directory/'report.md').write_text(report,encoding='utf-8')
    word=markdown_to_docx_bytes(report,title=target+'真实失败案例回放')
    (directory/'report.docx').write_bytes(word)
    risk={'fact':'公司公告提示半年度财务数据未经审计。','summary_topic':'risk','evidence_id':'E-123456ABCDEF'}
    literal=fallback_company_summary(SimpleNamespace(target_name=target),{'facts':[risk]})
    result={'scope':'Two real Haitian source30 failure records, current production writer/auditor; not complete-company acceptance',
        'model':os.environ['MODEL'],'base_url':os.environ['BASE_URL'],'original_sha256':hashlib.sha256(source['content'].encode()).hexdigest(),
        'initial_calls':first_calls,'unchanged_input_calls':identical_calls,'changed_actual_audit_prompt_calls':changed_calls,
        'policy_changed_without_manual_version_bump':package['policy_sha256']!=changed['policy_sha256'],
        'first_diagnostic':package['diagnostic'],'revised_diagnostic':changed['diagnostic'],
        'first_findings':package['findings'],'revised_findings':changed['findings'],
        'program_errors':[e for b in package['batches'] for e in b['errors']],
        'literal_summary':literal,'calls':calls,'usage':usages,'seconds':round(time.monotonic()-started,3),
        'report_sha256':hashlib.sha256(report.encode()).hexdigest(),'docx_sha256':hashlib.sha256(word).hexdigest(),
        'code_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'backend').rglob('*.py')}}
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (directory/'editorial.json').write_text(json.dumps(package,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('initial_calls','unchanged_input_calls','changed_actual_audit_prompt_calls','first_diagnostic')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
