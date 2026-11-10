import argparse,json,sqlite3
from pathlib import Path
import schemathesis
from schemathesis import GenerationMode
from schemathesis.core.failures import FailureGroup
from schemathesis.checks import not_a_server_error,response_schema_conformance,content_type_conformance,negative_data_rejection
from hypothesis import given,settings,HealthCheck

root=Path(__file__).parent
parser=argparse.ArgumentParser()
parser.add_argument('--url',choices=['http://127.0.0.1:8903','http://127.0.0.1:8906'],default='http://127.0.0.1:8903')
parser.add_argument('--output',default='export-contract.json')
args=parser.parse_args()
con=sqlite3.connect(root/'ui-data/audit.sqlite')
row=con.execute("SELECT thread_id,id FROM company_chat_messages WHERE role='assistant' AND content LIKE '%甲项目%' AND status='completed' ORDER BY id DESC LIMIT 1").fetchone()
assert row
schema=schemathesis.openapi.from_url(args.url+'/openapi.json')
path='/company-knowledge/conversations/{session_id}/messages/{message_id}/export'
operation=schema[path]['POST']
report={'endpoint':path,'requests':0,'modes':[],'failures':[]}
for mode in [GenerationMode.POSITIVE,GenerationMode.NEGATIVE]:
    tested={'mode':mode.value,'requests':0}
    try:
        @settings(max_examples=16,deadline=None,derandomize=True,database=None,suppress_health_check=[HealthCheck.too_slow,HealthCheck.filter_too_much])
        @given(case=operation.as_strategy(generation_mode=mode,path_parameters={'session_id':row[0],'message_id':row[1]}))
        def exercise(case):
            response=case.call(base_url=args.url,headers={'Authorization':'Bearer audit-alice'},timeout=30)
            tested['requests']+=1;report['requests']+=1
            case.validate_response(response,checks=[not_a_server_error,response_schema_conformance,content_type_conformance,negative_data_rejection])
        exercise()
        tested['status']='passed'
    except (Exception,FailureGroup) as exc:
        tested['status']='failed';report['failures'].append({'mode':mode.value,'error':str(exc)[:2200]})
    report['modes'].append(tested)
report['status']='failed' if report['failures'] else 'passed'
(root/args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
