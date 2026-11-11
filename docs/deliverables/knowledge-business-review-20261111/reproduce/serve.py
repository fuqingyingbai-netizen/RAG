from pathlib import Path
import argparse,hashlib,os,asyncio
parser=argparse.ArgumentParser();parser.add_argument('--data-dir',type=Path,required=True);parser.add_argument('--port',type=int,required=True);args=parser.parse_args()
from audit_app import build_app
app=build_app(args.data_dir)
from database import SessionLocal
from company_catalog import CompanyDocument,CompanyProject,CompanyFolder,document_store
from sqlalchemy import select
with SessionLocal() as db:
 for pid,department in [('owned','market'),('other','project'),('private','expert')]:
  db.get(CompanyProject,pid).department=department
  for doc in db.scalars(select(CompanyDocument).where(CompanyDocument.knowledge_project_id==pid)):doc.department=department
 for pid,name,department in [('empty','空项目','market'),('only-folders','仅目录项目','market')]:
  if not db.get(CompanyProject,pid):db.add(CompanyProject(id=pid,index_id='audit-index',name=name,department=department,owner='alice',owner_user_id=1,category='项目原件',visibility='members',confidentiality='internal',created_by='alice',modified_by='alice'))
 if not db.get(CompanyFolder,'empty-child'):db.add(CompanyFolder(id='empty-child',project_id='only-folders',parent_id='',name='空子目录'))
 for ident,title,state,folder in [('audit-export-income','TS-收入表.txt','ready',''),('failed-owned','失败样本.txt','failed',''),('processing-owned','处理中样本.txt','indexing','')]:
  if not db.get(CompanyDocument,ident):
   content='甲项目收入120万元，乙项目收入80万元。'.encode();key='audit/'+ident+'.txt';document_store().put_bytes(key,content,'text/plain')
   db.add(CompanyDocument(id=ident,index_id='audit-index',cloud_id='audit-income-cloud' if state=='ready' else None,title=title,format='TXT',size=len(content),sha256=hashlib.sha256(content+ident.encode()).hexdigest(),owner='alice',owner_user_id=1,uploaded_by='alice',knowledge_project_id='owned',folder_id=folder,project='验收项目甲',category='项目原件',industry='半导体',department='market',visibility='members',confidentiality='internal',state=state,status_message='合成失败样本' if state=='failed' else '',object_key=key,is_current=1))
 db.commit()
 with db.begin():
  processing=db.get(CompanyDocument,'processing-owned');processing.state='indexing';processing.cloud_id=None;processing.status_message='隔离样本：处理中，尚不可用于问答'
from fastapi import Request
from fastapi.responses import RedirectResponse,JSONResponse
@app.get('/audit/fault/{kind}',include_in_schema=False)
def arm_fault(kind:str):
 assert kind in ('documents-once','documents-until-cleared','projects-slow')
 response=RedirectResponse('/preview');response.set_cookie('audit_fault',kind,httponly=True,samesite='strict');return response
@app.get('/audit/clear-fault',include_in_schema=False)
def clear_fault():
 response=JSONResponse({'cleared':True});response.delete_cookie('audit_fault');return response
@app.middleware('http')
async def failures(request:Request,call_next):
 fault=request.cookies.get('audit_fault','')
 if fault in ('documents-once','documents-until-cleared') and request.url.path=='/company-knowledge/documents':
  response=JSONResponse({'detail':'隔离环境模拟资料请求失败，请重试'},status_code=503)
  if fault=='documents-once':response.delete_cookie('audit_fault')
  return response
 if fault=='projects-slow' and request.url.path=='/company-knowledge/projects':
  await asyncio.sleep(1.5);response=await call_next(request);response.delete_cookie('audit_fault');return response
 return await call_next(request)
# Put the audit-only fault endpoint before the catch-all static mount.
app.router.routes[:]=[r for r in app.router.routes if getattr(r,'path','').startswith('/audit/')]+[r for r in app.router.routes if not getattr(r,'path','').startswith('/audit/')]
if __name__=='__main__':
 import uvicorn
 uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False)
