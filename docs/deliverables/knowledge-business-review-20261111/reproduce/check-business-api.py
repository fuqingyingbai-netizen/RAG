from pathlib import Path
import io,json,time,uuid,zipfile
import httpx
from pypdf import PdfWriter
from openpyxl import Workbook,load_workbook
from docx import Document
from PIL import Image
root=Path(__file__).parent;results=[];samples={}
base='http://127.0.0.1:8912'
def record(name,passed,**actual):results.append({'id':name,'passed':passed,'actual':actual});(root/'api-business.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
with httpx.Client(base_url=base,headers={'Authorization':'Bearer audit-alice'},timeout=25,trust_env=False) as c:
 for role,expected in [('',401),('disabled',403)]:
  r=c.get('/company-knowledge/projects',headers={'Authorization':'Bearer audit-'+role} if role else {'Authorization':''});record('authentication-'+(role or 'anonymous'),r.status_code==expected,status=r.status_code)
 for role,manageable in [('alice',True),('bob',False),('audit-admin',True)]:
  r=c.get('/company-knowledge/projects',headers={'Authorization':'Bearer audit-'+role});p=next(x for x in r.json()['projects'] if x['id']=='owned');record('project-role-'+role,p['can_manage']==manageable,can_manage=p['can_manage'])
 for body,status in [({},422),({'project_ids':['empty']},409),({'project_ids':['private']},403),({'project_ids':['owned'],'scope':'experience'},403)]:
  r=c.post('/company-knowledge/selection',json=body);record('selection-denial-'+str(len(results)),r.status_code==status,status=r.status_code,request=body)
 r=c.post('/company-knowledge/selection',json={'folder_ids':['level-one']});ids=set(r.json()['document_ids']);record('parent-folder-subtree',len(ids)==21 and 'file-21' not in ids and 'file-20' in ids,count=len(ids))
 r=c.post('/company-knowledge/selection',json={'project_ids':['owned','other'],'folder_ids':['level-two'],'document_ids':['file-00']});ids=r.json()['document_ids'];record('multi-project-union-deduplicated',len(ids)==len(set(ids)) and 'file-24' in ids and 'file-27' not in ids,count=len(ids))
 r=c.post('/company-knowledge/projects/owned/folders',headers={'Authorization':'Bearer audit-bob'},json={'name':'forbidden'});record('member-direct-create-denied',r.status_code==403,status=r.status_code)
 r=c.post('/company-knowledge/uploads',headers={'Authorization':'Bearer audit-bob'},data={'project_id':'owned'},files={'file':('forbidden.txt',b'synthetic')});record('member-direct-upload-denied',r.status_code==403,status=r.status_code)
 # Dedicated synthetic project keeps generated mutation and reader samples apart.
 p=c.post('/company-knowledge/projects',json={'name':'API-BIZ-'+uuid.uuid4().hex[:8],'department':'market','category':'项目原件'}).json();pid=p['id']
 folder=c.post('/company-knowledge/projects/'+pid+'/folders',json={'name':'一级'}).json();fid=folder['id']
 child=c.post('/company-knowledge/projects/'+pid+'/folders',json={'name':'二级','parent_id':fid});record('nested-create-current-parent',child.status_code==201 or child.status_code==200,status=child.status_code)
 childid=child.json()['id']
 r=c.patch('/company-knowledge/projects/'+pid+'/folders/'+fid,json={'name':'一级','parent_id':childid});record('rename-cannot-reparent-folder',r.status_code==200 and r.json()['parent_id']=='',status=r.status_code,parent_id=r.json().get('parent_id'))
 def upload(name,data):
  r=c.post('/company-knowledge/uploads',data={'project_id':pid,'folder_id':childid},files={'file':(name,data)});assert r.status_code in (200,201,202),r.text
  row=r.json();samples[name]=row['id'];return row
 writer=PdfWriter();writer.add_blank_page(width=420,height=595);out=io.BytesIO();writer.write(out);pdf=upload('API-preview.pdf',out.getvalue())
 r=c.get('/company-knowledge/documents/'+pdf['id']+'/page');record('pdf-page-real-render',r.status_code==200 and r.headers.get('content-type','').startswith('image/') and len(r.content)>100,status=r.status_code,bytes=len(r.content))
 r=c.get('/company-knowledge/documents/'+pdf['id']+'/download');record('pdf-download-watermarked',r.status_code==200 and bool(r.headers.get('x-watermark-trace')) and 'no-store' in r.headers.get('cache-control',''),status=r.status_code)
 book=Workbook();book.active.title='收入';book.active['A1']='SYNTHETIC-REVENUE';book.active['B2']=120;book.active.merge_cells('A3:C3');book.active['A3']='MERGED';book.create_sheet('第二表')['A1']='SECOND-SHEET';out=io.BytesIO();book.save(out);sheet=upload('API-preview.xlsx',out.getvalue())
 for index in (0,1):
  r=c.get('/company-knowledge/documents/'+sheet['id']+'/sheet',params={'sheet':index});data=r.json();record('xlsx-native-sheet-'+str(index),r.status_code==200 and data.get('mode')=='workbook' and bool(data.get('watermark')),status=r.status_code,mode=data.get('mode'))
 r=c.get('/company-knowledge/documents/'+sheet['id']+'/sheet',params={'sheet':9});record('xlsx-invalid-sheet-rejected',r.status_code in (404,422),status=r.status_code)
 locked=PdfWriter();locked.add_blank_page(width=200,height=200);locked.encrypt('synthetic-only');out=io.BytesIO();locked.write(out);enc=upload('API-encrypted.pdf',out.getvalue())
 r=c.get('/company-knowledge/documents/'+enc['id']+'/page');record('encrypted-pdf-explicit-error',r.status_code==422 and r.headers.get('x-preview-error')=='pdf_encrypted',status=r.status_code,error=r.headers.get('x-preview-error'))
 doc=Document();doc.add_paragraph('SYNTHETIC-OFFICE-PREVIEW');out=io.BytesIO();doc.save(out);word=upload('API-preview.docx',out.getvalue())
 started=time.monotonic()
 try:
  r=c.get('/company-knowledge/documents/'+word['id']+'/page',timeout=12)
  record('docx-page-environment',r.status_code==200,status=r.status_code,seconds=round(time.monotonic()-started,2),classification='passed' if r.status_code==200 else 'blocked',error=r.json().get('detail') if r.status_code!=200 else '')
 except httpx.TimeoutException:record('docx-page-environment',False,classification='blocked',reason='12 second bounded request timed out')
 r=c.post('/company-knowledge/conversations',json={'document_ids':['audit-export-income']});assert r.status_code==201,r.text;sid=r.json()['session_id']
 r=c.post('/company-knowledge/chat/stream',json={'message':'请生成合成收入表','document_ids':['audit-export-income'],'session_id':sid,'request_id':str(uuid.uuid4())});record('saved-synthetic-stream',r.status_code==200,status=r.status_code)
 data=c.get('/company-knowledge/conversations/'+sid).json();messages=data.get('messages',[]);answer=next(x for x in reversed(messages) if x['role']=='assistant');mid=answer['id']
 (root/'export-session.json').write_text(json.dumps({'session_id':sid,'message_id':mid}));dest=root/'exports';dest.mkdir(exist_ok=True)
 for fmt in ('docx','xlsx','png'):
  r=c.post('/company-knowledge/conversations/'+sid+'/messages/'+str(mid)+'/export',json={'format':fmt});assert r.status_code==200,r.text
  (dest/('answer.'+fmt)).write_bytes(r.content)
  if fmt=='png':Image.open(io.BytesIO(r.content)).verify()
  elif fmt=='xlsx':
   b=load_workbook(io.BytesIO(r.content));assert any(cell.value==120 for row in b.active for cell in row)
  else:
   d=Document(io.BytesIO(r.content));assert '120' in ' '.join(cell.text for t in d.tables for row in t.rows for cell in row.cells)
  record('answer-export-'+fmt,bool(r.headers.get('x-watermark-trace')) and r.headers.get('cache-control')=='no-store',status=r.status_code,bytes=len(r.content))
 for field in ('table_index','value_column'):
  for value in (True,False,'0',1.0,-1,31):
   r=c.post('/company-knowledge/conversations/'+sid+'/messages/'+str(mid)+'/export',json={'format':'xlsx',field:value});record('strict-index-'+field+'-'+repr(value),r.status_code==422,status=r.status_code)
 r=c.get('/company-knowledge/conversations/'+sid,headers={'Authorization':'Bearer audit-bob'});record('conversation-not-readable-by-other-account',r.status_code==404,status=r.status_code)
(root/'reader-samples.json').write_text(json.dumps(samples,ensure_ascii=False,indent=2));print(json.dumps({'checks':len(results),'failed':[x for x in results if not x['passed']]},ensure_ascii=False,indent=2))
