from pathlib import Path
import json
import schemathesis
from schemathesis import GenerationMode
from schemathesis.core.failures import FailureGroup
from schemathesis.checks import not_a_server_error,response_schema_conformance,content_type_conformance,negative_data_rejection
from hypothesis import given,settings,HealthCheck
root=Path(__file__).parent;data=json.loads((root/'export-session.json').read_text());base='http://127.0.0.1:8912'
schema=schemathesis.openapi.from_url(base+'/openapi.json');path='/company-knowledge/conversations/{session_id}/messages/{message_id}/export';operation=schema[path]['POST']
report={'endpoint':path,'requests':0,'modes':[],'failures':[]}
for mode in (GenerationMode.POSITIVE,GenerationMode.NEGATIVE):
 row={'mode':mode.value,'requests':0}
 try:
  @settings(max_examples=16,deadline=None,derandomize=True,database=None,suppress_health_check=[HealthCheck.too_slow,HealthCheck.filter_too_much])
  @given(case=operation.as_strategy(generation_mode=mode,path_parameters=data))
  def exercise(case):
   response=case.call(base_url=base,headers={'Authorization':'Bearer audit-alice'},timeout=30);row['requests']+=1;report['requests']+=1
   case.validate_response(response,checks=[not_a_server_error,response_schema_conformance,content_type_conformance,negative_data_rejection])
  exercise();row['status']='passed'
 except (Exception,FailureGroup) as exc:row['status']='failed';report['failures'].append({'mode':mode.value,'error':str(exc)[:2200]})
 report['modes'].append(row)
report['status']='failed' if report['failures'] else 'passed';(root/'export-contract.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
