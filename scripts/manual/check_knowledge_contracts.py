"""Schemathesis fuzzing + Hypothesis stateful checks against knowledge_audit_app only."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import schemathesis
from schemathesis import GenerationMode
from schemathesis.checks import not_a_server_error, response_schema_conformance, content_type_conformance
from hypothesis import given, settings, HealthCheck
from hypothesis.errors import Unsatisfiable
from hypothesis.stateful import RuleBasedStateMachine, initialize, rule, invariant, run_state_machine_as_test


def run(base_url, destination):
    if urlsplit(base_url).hostname not in ('127.0.0.1','localhost'):
        raise RuntimeError('Only the disposable loopback audit app is supported')
    with httpx.Client(base_url=base_url) as client:
        probe=client.get('/audit/evidence',headers={'Authorization':'Bearer audit-alice'})
        assert probe.status_code==200 and probe.json()['account']=='alice'
    schema=schemathesis.openapi.from_url(base_url+'/openapi.json')
    report={'tool':'schemathesis','version':schemathesis.__version__,'operations':[], 'failures':[],
        'requests':0,'business_checks':[],'stateful_requests':0,'schema_operations':len(list(schema.get_all_operations()))}
    auth={'Authorization':'Bearer audit-alice'}
    paths={
        '/company-knowledge/projects':['GET','POST'],
        '/company-knowledge/projects/{project_id}':['PATCH'],
        '/company-knowledge/projects/{project_id}/folders':['POST'],
        '/company-knowledge/projects/{project_id}/folders/{folder_id}':['PATCH','DELETE'],
        '/company-knowledge/documents':['GET'],
        '/company-knowledge/documents/{doc_id}':['PATCH'],
        '/company-knowledge/selection':['POST'],
        '/company-knowledge/conversations':['GET','POST'],
        '/company-knowledge/conversations/{session_id}':['GET','DELETE'],
        '/company-knowledge/notes':['GET','POST'],
        '/company-knowledge/notes/{note_id}':['GET','PATCH'],
        '/company-knowledge/my-projects':['GET'],
        '/company-knowledge/recycle-bin':['GET'],
        '/company-knowledge/recycle-bin/{item_id}/restore':['POST'],
        '/company-knowledge/access-requests/mine':['GET'],
        '/company-knowledge/documents/{doc_id}/access-requests':['POST'],
    }
    # Mutation fuzzing has its own project; named business invariants keep stable fixtures.
    with httpx.Client(base_url=base_url,headers=auth) as client:
        fuzz_project=client.post('/company-knowledge/projects',json={'name':'fuzz-'+uuid4().hex}).json()
        fuzz_folder=client.post('/company-knowledge/projects/'+fuzz_project['id']+'/folders',json={'name':'fuzz-folder'}).json()
        fuzz_doc=client.post('/company-knowledge/uploads',data={'project_id':fuzz_project['id']},
            files={'file':('fuzz.txt',b'isolated fuzz original','text/plain')}).json()
    path_values={'project_id':fuzz_project['id'],'folder_id':fuzz_folder['id'],'doc_id':fuzz_doc['id'],
        'session_id':'missing-session','note_id':'missing-note','item_id':'missing-item'}
    for path,methods in paths.items():
        if path not in schema.raw_schema['paths']:
            report['failures'].append({'kind':'harness','path':path,'message':'endpoint absent'});continue
        for method in methods:
            operation=schema[path][method]
            fixed={key:value for key,value in path_values.items() if '{'+key+'}' in path}
            for mode in (GenerationMode.POSITIVE,GenerationMode.NEGATIVE):
                row={'path':path,'method':method,'mode':mode.value,'requests':0,'status':'passed'}
                try:
                    @settings(max_examples=16,deadline=None,derandomize=True,database=None,
                        suppress_health_check=[HealthCheck.filter_too_much,HealthCheck.too_slow])
                    @given(case=operation.as_strategy(generation_mode=mode,path_parameters=fixed))
                    def exercise(case):
                        response=case.call(base_url=base_url,headers=auth)
                        row['requests']+=1;report['requests']+=1
                        case.validate_response(response,checks=[not_a_server_error,response_schema_conformance,content_type_conformance])
                    exercise()
                except Unsatisfiable:
                    if row['requests']:
                        raise
                    row.update(status='not_applicable',reason='No invalid inputs remain after fixing required identifiers')
                except Exception as error:
                    row['status']='failed';report['failures'].append({'kind':'generated','path':path,
                        'method':method,'mode':mode.value,'message':str(error)[:7000]})
                report['operations'].append(row)
                destination.parent.mkdir(parents=True,exist_ok=True)
                destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

    def api(path,method='GET',body=None,params=None,role='alice',expected=None):
        kwargs={'path_parameters':params or {}}
        if body is not None:kwargs.update(body=body,media_type='application/json')
        case=schema[path][method].Case(**kwargs)
        response=case.call(base_url=base_url,headers={'Authorization':'Bearer audit-'+role})
        report['stateful_requests']+=1
        case.validate_response(response,checks=[not_a_server_error,response_schema_conformance,content_type_conformance])
        if expected is not None:assert response.status_code==expected,(path,response.status_code,response.text)
        return response.json()

    try:
        # Named invariants supplement schema-based input checks.
        for role in ['alice','bob','audit-admin']:
            values=api('/company-knowledge/projects',role=role,expected=200)['projects']
            owned=next(p for p in values if p['id']=='owned')
            assert owned['can_manage']==(role in ['alice','audit-admin'])
        report['business_checks'].append('owner/admin management, member read-only')
        api('/company-knowledge/projects/{project_id}/folders','POST',{'name':'forbidden'},
            {'project_id':'owned'},role='bob',expected=403)
        with httpx.Client(base_url=base_url) as client:
            response=client.post('/company-knowledge/uploads',headers={'Authorization':'Bearer audit-bob'},
                data={'project_id':'owned','folder_id':'level-two'},files={'file':('forbidden.txt',b'isolated payload')})
            assert response.status_code==403
            assert client.get('/company-knowledge/projects').status_code==401
            assert client.get('/company-knowledge/projects',headers={'Authorization':'Bearer audit-disabled'}).status_code==403
        report['business_checks'].append('direct unauthorized upload/create, anonymous and inactive denied')
        api('/company-knowledge/selection','POST',{'folder_ids':['level-one']},expected=200)
        api('/company-knowledge/selection','POST',{'project_ids':['private']},expected=403)
        api('/company-knowledge/selection','POST',{'project_ids':['owned'],'scope':'experience'},expected=403)
        api('/company-knowledge/selection','POST',{},expected=422)
        report['business_checks'].append('recursive scope, denied private/cross-library/empty selections')
        session=api('/company-knowledge/conversations','POST',{'document_ids':['file-00']},expected=201)
        api('/company-knowledge/conversations/{session_id}',params={'session_id':session['session_id']},role='bob',expected=404)
        report['business_checks'].append('conversation IDs do not bypass account ownership')
    except Exception as error:
        report['failures'].append({'kind':'business','message':str(error)[:2500]})

    class Workflow(RuleBasedStateMachine):
        @initialize()
        def start(self):
            self.project=api('/company-knowledge/projects','POST',{'name':'stateful-'+uuid4().hex},expected=201)
            self.folders=[];self.files=[]
        @rule()
        def add_folder(self):
            parent=self.folders[-1]['id'] if self.folders and len(self.folders)<5 else ''
            folder=api('/company-knowledge/projects/{project_id}/folders','POST',
                {'name':'folder-'+uuid4().hex,'parent_id':parent},{'project_id':self.project['id']},expected=201)
            assert folder['parent_id']==parent;self.folders.append(folder)
        @rule()
        def upload(self):
            folder=self.folders[-1]['id'] if self.folders else ''
            with httpx.Client(base_url=base_url) as client:
                response=client.post('/company-knowledge/uploads',headers=auth,
                    data={'project_id':self.project['id'],'folder_id':folder},
                    files={'file':('flow-'+uuid4().hex+'.txt',b'isolated stateful evidence','text/plain')})
            report['stateful_requests']+=1
            response.request.read()
            schema['/company-knowledge/uploads']['POST'].Case().validate_response(response,checks=[not_a_server_error,response_schema_conformance,content_type_conformance])
            assert response.status_code==202,response.text
            doc=response.json();assert doc['folder_id']==folder;self.files.append(doc)
        @rule()
        def delete_and_restore(self):
            if not self.files:return
            doc=self.files[0]
            api('/company-knowledge/documents/{doc_id}','DELETE',params={'doc_id':doc['id']},expected=200)
            items=api('/company-knowledge/recycle-bin',expected=200)['items']
            item=next(x for x in items if x['title']==doc['title'])
            api('/company-knowledge/recycle-bin/{item_id}/restore','POST',params={'item_id':item['id']},expected=200)
            api('/company-knowledge/recycle-bin/{item_id}/restore','POST',params={'item_id':item['id']},expected=409)
        @invariant()
        def tree_and_scope_remain_consistent(self):
            catalogue=api('/company-knowledge/projects',expected=200)
            folders={x['id']:x for x in catalogue['folders']}
            assert all(f['id'] in folders and folders[f['id']]['parent_id']==f['parent_id'] for f in self.folders)
            selected=api('/company-knowledge/selection','POST',{'project_ids':[self.project['id']]},
                expected=200 if self.files else 409)
            if self.files:assert set(selected['document_ids'])=={d['id'] for d in self.files}
    try:
        run_state_machine_as_test(Workflow,settings=settings(max_examples=8,stateful_step_count=9,
            deadline=None,derandomize=True,database=None,suppress_health_check=[HealthCheck.too_slow]))
        report['business_checks'].append('generated create/nest/upload/delete/restore sequences preserve scope and tree')
    except Exception as error:
        report['failures'].append({'kind':'stateful','message':str(error)[:7000]})
    report['status']='passed' if not report['failures'] else 'failed'
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['status','version','requests','stateful_requests','business_checks','failures']},ensure_ascii=False))
    return not report['failures']


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8892')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    raise SystemExit(0 if run(args.url,args.output) else 1)
