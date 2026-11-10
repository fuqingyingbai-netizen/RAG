import io
import sys
import time
from datetime import datetime

import pytest
from openpyxl import Workbook
from pypdf import PdfWriter

import company_knowledge as kb
from company_catalog import CompanyDocument, document_store
import company_discovery as discovery
from company_sheet_preview import sheet_info
from company_watermark import WatermarkError, run
from test_company_workspace import setup, upload


def test_password_pdf_is_distinguished_from_damage_and_keeps_original(setup):
    writer=PdfWriter();writer.add_blank_page(width=300,height=400);writer.encrypt('known-test-password')
    output=io.BytesIO();writer.write(output);payload=output.getvalue()
    row=upload(setup,payload=payload,name='protected.pdf').json()
    response=setup.client.get('/company-knowledge/documents/'+row['id']+'/page')
    assert response.status_code==422 and response.headers['x-preview-error']=='pdf_encrypted'
    assert '已加密' in response.json()['detail'] and '打开密码' in response.json()['detail']
    export=setup.client.get('/company-knowledge/documents/'+row['id']+'/download')
    assert export.status_code==422 and '已加密' in export.json()['detail']
    bad=upload(setup,payload=b'%PDF-damaged',name='broken.pdf').json()
    response=setup.client.get('/company-knowledge/documents/'+bad['id']+'/page')
    assert response.status_code==422 and response.headers['x-preview-error']=='pdf_invalid'
    with setup.db() as db:assert document_store().get_bytes(db.get(CompanyDocument,row['id']).object_key)==payload


def test_large_sheet_reads_first_last_and_other_sheet_without_office(setup,monkeypatch):
    book=Workbook();sheet=book.active;sheet.title='大表'
    sheet['A1']='<script>literal</script>';sheet['B1']='=SUM(1,2)';sheet['C1']=datetime(2026,11,10)
    sheet['A10051']='LAST_ROW';other=book.create_sheet('第二表');other['A1']='SECOND_SHEET'
    output=io.BytesIO();book.save(output);source=output.getvalue()
    row=upload(setup,payload=source,name='large.xlsx').json();base='/company-knowledge/documents/'+row['id']
    def no_office(*args):raise AssertionError('A large workbook must never invoke LibreOffice')
    monkeypatch.setattr(discovery,'office_to_pdf',no_office);sheet_info.cache_clear()
    first=setup.client.get(base+'/sheet');assert first.status_code==200
    data=first.json();assert data['mode']=='table' and data['pages']==202
    assert data['values'][0]==['<script>literal</script>','=SUM(1,2)','2026-11-10 00:00:00']
    assert len(data['values'])==50 and data['watermark'] and first.headers['x-watermark-trace']
    last=setup.client.get(base+'/sheet?page=202').json();assert last['values'][0][0]=='LAST_ROW' and last['first_row']==10051
    assert setup.client.get(base+'/sheet?sheet=1').json()['values'][0][0]=='SECOND_SHEET'
    assert setup.client.get(base+'/sheet?page=203').status_code==422
    response=setup.client.get(base+'/page');assert response.status_code==422 and response.headers['x-preview-error']=='spreadsheet_table_available'
    with setup.db() as db:
        doc=db.get(CompanyDocument,row['id']);assert document_store().get_bytes(doc.object_key)==source
        doc.visibility='restricted';db.commit()
    setup.user.username,setup.user.id='bob',2
    assert setup.client.get(base+'/sheet').status_code==404
    sheet_info.cache_clear()


def test_missing_original_can_be_explicitly_restored_without_stale_evidence(setup):
    row=upload(setup,name='history.txt').json();base='/company-knowledge/documents/'+row['id']
    with setup.db() as db:
        doc=db.get(CompanyDocument,row['id']);doc.object_key='';doc.cloud_id='legacy-source';doc.state='ready';db.commit()
    response=setup.client.get(base+'/page');assert response.status_code==404 and response.headers['x-preview-error']=='original_missing'
    def restore(name='history.txt',confirmation=None):return setup.client.post(base+'/original',files={'file':(name,b'RESTORED_SOURCE')},data={'confirmation':confirmation or row['id']})
    assert restore(confirmation='wrong').status_code==422
    assert restore(name='wrong.pdf').status_code==422
    setup.user.username,setup.user.id='bob',2
    assert restore().status_code==403
    setup.user.username,setup.user.id='alice',1
    response=restore();assert response.status_code==202,response.text
    assert response.json()['has_original'] and response.json()['state']=='queued'
    with setup.db() as db:
        doc=db.get(CompanyDocument,row['id']);assert doc.cloud_id is None and doc.stale_cloud_id=='legacy-source'
        assert document_store().get_bytes(doc.object_key)==b'RESTORED_SOURCE'
        assert doc.title==row['title'] and doc.owner==row['owner'] and doc.confidentiality==row['confidentiality']
    assert setup.client.get(base+'/preview').json()['references']==[]
    assert restore().status_code==409
    assert row['id'] in setup.scheduled


def test_conversion_deadline_returns_specific_error():
    with pytest.raises(WatermarkError) as error:
        run([sys.executable,'-c','import time;time.sleep(10)'],timeout=.1)
    assert error.value.code=='conversion_timeout'


def test_restored_legacy_title_without_extension_registers_with_correct_cloud_type(setup,monkeypatch):
    import asyncio,json,httpx
    import company_ingestion as ingestion
    from test_company_workspace import transport
    row=upload(setup,name='legacy.txt').json()
    with setup.db() as db:
        doc=db.get(CompanyDocument,row['id']);doc.title='历史标题没有扩展名';doc.object_key='';doc.state='ready';db.commit()
    response=setup.client.post('/company-knowledge/documents/'+row['id']+'/original',
        files={'file':('actual.txt',b'actual restored text')},data={'confirmation':row['id']})
    assert response.status_code==202
    observed=[]
    def handler(request):
        if request.method=='PUT':return httpx.Response(200)
        body=json.loads(request.content) if request.method=='POST' else {}
        if request.url.path.endswith('applyFileUploadLease'):
            observed.append(body['fileName'])
            return httpx.Response(200,json={'data':{'leaseId':'lease','param':{'url':'https://bucket.oss-cn-beijing.aliyuncs.com/proof'}}})
        if request.url.path.endswith('addFile'):return httpx.Response(200,json={'data':{'fileId':'restored-cloud'}})
        if request.url.path.endswith('job/create'):return httpx.Response(200,json={'data':{'ingestionId':'job'}})
        return httpx.Response(200,json={'data':{'rows':[{'doc_id':'restored-cloud','status':'FINISH'}]}})
    transport(monkeypatch,handler);asyncio.run(ingestion.process_document(row['id']))
    assert observed==['历史标题没有扩展名.txt']
    with setup.db() as db:
        doc=db.get(CompanyDocument,row['id']);assert doc.title=='历史标题没有扩展名' and doc.state=='ready'
