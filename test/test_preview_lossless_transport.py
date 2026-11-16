import io
from PIL import Image, ImageChops
import pytest
import company_watermark as wm
from test_company_workspace import setup

IDENTITY=wm.ExportIdentity('测试账号',1,'2026-11-16 12:00:00','preview-test-trace')

def test_lossless_webp_preview_preserves_stamped_pixels_and_default_download():
    image=Image.new('RGB',(640,480),'white')
    for x in range(70,570):image.putpixel((x,200),(20,40,60))
    raw=io.BytesIO();image.save(raw,'PNG')
    png,mime,name=wm.export_copy(raw.getvalue(),'PNG','source.png',IDENTITY)
    webp,webp_mime,webp_name=wm.export_copy(raw.getvalue(),'PNG','source.png',IDENTITY,preview_image=True)
    assert mime=='image/png' and name.endswith('.png')
    assert webp_mime=='image/webp' and webp_name.endswith('.webp')
    with Image.open(io.BytesIO(png)) as a,Image.open(io.BytesIO(webp)) as b:
        assert a.size==b.size==(640,480)
        assert ImageChops.difference(a.convert('RGBA'),b.convert('RGBA')).getbbox() is None
        assert a.convert('RGB').tobytes()!=image.tobytes()

@pytest.mark.parametrize('accept,mime',[('image/webp','image/webp'),('IMAGE/WEBP;q=0.8','image/webp'),('image/webp;q=0','image/png'),('image/webp;q=0.00, image/png','image/png'),('*/*','image/png')])
def test_page_transport_negotiates_without_changing_acl_audit_or_download(setup,accept,mime):
    from pypdf import PdfWriter
    from company_catalog import CompanyDocument,CompanyAuditEvent,document_store
    writer=PdfWriter();writer.add_blank_page(width=200,height=300);raw=io.BytesIO();writer.write(raw)
    source=raw.getvalue();document_store().put_bytes('preview-transport/source.pdf',source,'application/pdf')
    with setup.db() as db:
        db.add(CompanyDocument(id='preview-transport',index_id='test-index',title='source.pdf',format='PDF',object_key='preview-transport/source.pdf',sha256='stable-preview-digest',owner='alice',owner_user_id=1,state='ready',category='项目原件',visibility='members',confidentiality='internal',is_current=1));db.commit()
    response=setup.client.get('/company-knowledge/documents/preview-transport/page?page=1',headers={'Accept':accept})
    assert response.status_code==200 and response.headers['content-type']==mime
    assert response.headers['vary']=='Accept' and response.headers['cache-control']=='private, no-store'
    assert response.headers['x-document-pages']=='1' and response.headers['x-watermark-trace']
    with Image.open(io.BytesIO(response.content)) as image:assert image.size[0]>0
    with setup.db() as db:
        assert db.get(CompanyAuditEvent,response.headers['x-watermark-trace'])
        row=db.get(CompanyDocument,'preview-transport');row.visibility='restricted';row.owner='bob';row.owner_user_id=2;db.commit()
    assert setup.client.get('/company-knowledge/documents/preview-transport/page?page=1',headers={'Accept':accept}).status_code==404
