from pathlib import Path
import hashlib,json,sys

root=Path(__file__).parent
repo=Path('E:/projects/RAG/work/knowledge-update-audit-code-20261110b')
sys.path.insert(0,str(repo))
from scripts.manual.knowledge_audit_app import build_app
app=build_app(root/'ui-data')
from database import SessionLocal
from company_catalog import CompanyDocument,CompanyProject,document_store
from sqlalchemy import select
with SessionLocal() as db:
    for pid,department in [('owned','market'),('other','project'),('private','expert')]:
        db.get(CompanyProject,pid).department=department
        for doc in db.scalars(select(CompanyDocument).where(CompanyDocument.knowledge_project_id==pid)):
            doc.department=department
    if not db.get(CompanyDocument,'audit-export-income'):
        content='甲项目收入120万元，乙项目收入80万元。'.encode('utf-8')
        key='audit/income.txt';document_store().put_bytes(key,content,'text/plain')
        db.add(CompanyDocument(id='audit-export-income',index_id='audit-index',cloud_id='audit-income-cloud',
            title='TS-收入表.txt',format='TXT',size=len(content),sha256=hashlib.sha256(content).hexdigest(),
            owner='alice',owner_user_id=1,uploaded_by='alice',knowledge_project_id='owned',folder_id='',
            project='验收项目甲',category='项目原件',industry='半导体',department='market',
            visibility='members',confidentiality='internal',state='ready',object_key=key,is_current=1))
    db.commit()
(root/'fixture-rules.json').write_text(json.dumps({'owned_department':'market','other_department':'project',
    'export_document_id':'audit-export-income','export_question':'请生成合成收入表','model':'explicit synthetic provider only',
    'source_text':'甲项目收入120万元，乙项目收入80万元。'},ensure_ascii=False,indent=2),encoding='utf-8')
print('Seeded separate departments and a synthetic export source; no verdict assigned')
