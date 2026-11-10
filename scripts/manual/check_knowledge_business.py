"""Schemathesis business sequences against knowledge_audit_app.py only.

Use a separate disposable API database from the browser scenarios. Providers are
stubbed by that app; routes, permissions, persistence and recovery are real.
"""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
from uuid import uuid4


def run(base, report, tool_libs):
    if urlsplit(base).hostname != '127.0.0.1':
        raise RuntimeError('This destructive test runner only accepts the loopback audit app')
    sys.path.insert(0, str(tool_libs.resolve()))
    import requests
    import schemathesis
    from schemathesis.checks import not_a_server_error, response_schema_conformance
    schema = schemathesis.openapi.from_url(base+'/openapi.json')
    if schema.raw_schema.get('info', {}).get('title') != 'Disposable knowledge business audit':
        raise RuntimeError('Expected the disposable audit app')
    results = []

    def call(name, path, method='GET', *, status=200, user='alice', body=None, params=None, **kwargs):
        operation = schema[path][method]
        values = {'path_parameters': params or {}, 'headers': {'Authorization':'Bearer audit-'+user}}
        if body is not None:
            values.update(body=body, media_type='application/json')
        case = operation.Case(**values)
        response = case.call(base_url=base, timeout=10, **kwargs)
        assert response.status_code == status, f'{name}: {response.status_code}, expected {status}: {response.text[:250]}'
        case.validate_response(response, checks=[not_a_server_error, response_schema_conformance])
        results.append({'rule':name, 'status':'passed', 'http_status':response.status_code})
        return response.json()

    suffix = uuid4().hex[:8]
    p = call('创建项目记录真实归属', '/company-knowledge/projects', 'POST', status=201, body={'name':'接口验收-'+suffix})
    assert p['owner']=='alice' and p['can_manage']
    pid={'project_id':p['id']}
    call('重复项目名称明确冲突', '/company-knowledge/projects','POST',status=409,body={'name':p['name']})
    call('空白项目名称被拒绝', '/company-knowledge/projects','POST',status=422,body={'name':'  '})
    f = call('项目根目录下建目录', '/company-knowledge/projects/{project_id}/folders','POST',status=201,params=pid,body={'name':'一级'})
    g = call('在选中的目录下继续建子目录', '/company-knowledge/projects/{project_id}/folders','POST',status=201,params=pid,body={'name':'二级','parent_id':f['id']})
    call('不存在的上级目录不能创建', '/company-knowledge/projects/{project_id}/folders','POST',status=404,params=pid,body={'name':'无效','parent_id':'missing'})
    call('只读成员直接调创建接口仍被拒绝', '/company-knowledge/projects/{project_id}/folders','POST',status=403,user='bob',params=pid,body={'name':'越权'})
    payload={'files':{'file':('audit-'+suffix+'.txt',b'Isolated business evidence','text/plain')}, 'data':{'project_id':p['id'],'folder_id':g['id']}}
    call('只读成员直接调上传接口仍被拒绝', '/company-knowledge/uploads','POST',status=403,user='bob',**payload)
    uploaded=call('上传到当前子目录', '/company-knowledge/uploads','POST',status=202,**payload)
    docid=uploaded['id'];assert uploaded['folder_id']==g['id'] and uploaded['knowledge_project_id']==p['id']
    call('同目录相同内容重复上传明确拒绝', '/company-knowledge/uploads','POST',status=409,**payload)
    selected=call('父目录提问递归包含下级资料并去重', '/company-knowledge/selection','POST',body={'folder_ids':[f['id'],g['id']],'document_ids':[docid]})
    assert selected['document_ids']==[docid] and selected['document_count']==1
    call('空提问范围不能自动变成全库', '/company-knowledge/selection','POST',status=422,body={})
    call('普通资料不能进入经验问答范围', '/company-knowledge/selection','POST',status=403,body={'project_ids':[p['id']],'scope':'experience'})
    thread=call('创建会话保留明确资料范围','/company-knowledge/conversations','POST',status=201,body={'document_ids':[docid],'scope':'accessible'})
    assert thread['document_ids']==[docid]
    call('其他成员不能读取本人研究会话','/company-knowledge/conversations/{session_id}',status=404,user='bob',params={'session_id':thread['session_id']})
    call('非空目录不能直接删除','/company-knowledge/projects/{project_id}/folders/{folder_id}','DELETE',status=409,params=pid|{'folder_id':g['id']})
    xp=call('创建经验强制成员可读','/company-knowledge/projects','POST',status=201,body={'name':'经验验收-'+suffix,'category':'项目经验','visibility':'restricted'})
    assert xp['visibility']=='members'
    note=call('经验草稿创建','/company-knowledge/notes','POST',status=201,body={'project_id':xp['id'],'title':'未发布草稿'})
    call('未发布草稿仍仅本人可读','/company-knowledge/notes/{note_id}',status=404,user='bob',params={'note_id':note['id']})
    call('删除文件进入回收站','/company-knowledge/documents/{doc_id}','DELETE',params={'doc_id':docid})
    call('已删除文件不能作为提问依据','/company-knowledge/selection','POST',status=403,body={'document_ids':[docid]})
    recycle=call('创建者可查看自己的回收记录','/company-knowledge/recycle-bin')
    item=next(row for row in recycle['items'] if row['title']=='audit-'+suffix+'.txt')
    call('只读成员不能恢复别人的删除记录','/company-knowledge/recycle-bin/{item_id}/restore','POST',status=404,user='bob',params={'item_id':item['id']})
    call('创建者恢复自己的文件','/company-knowledge/recycle-bin/{item_id}/restore','POST',params={'item_id':item['id']})
    restored=call('恢复后文件重新可选','/company-knowledge/selection','POST',body={'document_ids':[docid]})
    assert restored['document_ids']==[docid]
    call('停用账号不能使用知识库','/company-knowledge/projects',status=403,user='disabled')
    response=requests.get(base+'/company-knowledge/projects',timeout=10)
    assert response.status_code==401
    results.append({'rule':'匿名账号被拒绝','status':'passed','http_status':401})
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({'tool':'Schemathesis '+schemathesis.__version__, 'status':'passed', 'checks':results}, ensure_ascii=False, indent=2),encoding='utf-8')
    print(json.dumps({'status':'passed','business_checks':len(results),'report':str(report)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8892')
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--tool-libs',type=Path,required=True)
    args=parser.parse_args();run(args.url,args.report,args.tool_libs)
