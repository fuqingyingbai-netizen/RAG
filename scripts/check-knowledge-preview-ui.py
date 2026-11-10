"""Actual failed workbook + real endpoints; isolated local browser regression."""
import io
import json
import httpx
from pypdf import PdfWriter
from playwright.sync_api import expect


def configure(state,args,patch):
    from test_company_workspace import project,upload
    from company_catalog import CompanyDocument
    import company_knowledge as kb
    p=project(state,'异常原件预览验证')
    writer=PdfWriter();writer.add_blank_page(width=300,height=400);writer.encrypt('isolated-preview-password')
    stream=io.BytesIO();writer.write(stream)
    protected=upload(state,payload=stream.getvalue(),name='需要密码.pdf',project_id=p['id']).json()
    missing=upload(state,payload=b'legacy',name='历史原件.txt',project_id=p['id']).json()
    response=upload(state,payload=args.large_sheet.read_bytes(),name='实际大表.xlsx',project_id=p['id'])
    assert response.status_code==202,response.text
    large=response.json()
    with state.db() as db:
        for d in (missing,protected,large):
            row=db.get(CompanyDocument,d['id']);row.state='ready';row.cloud_id='fixture-'+d['id']
        db.get(CompanyDocument,missing['id']).object_key='';db.commit()
    async def cloud(client,cfg,path,body):
        assert path=='/api/v1/indices/rag/index/chunklist'
        return {'nodes':[{'metadata':{'doc_id':body['docId'],'content':'已有解析文字仍可以阅读'}}],'total':1}
    patch.setattr(kb,'cloud_rpc',cloud)
    def check(page,state,experience,args,temp,errors):
        page.goto(page.url.rstrip('/')+'/full')
        page.get_by_role('tab',name='资料库',exact=True).click()
        expect(page.locator('.ckb-project-directory').filter(has_text=p['name'])).to_be_visible()
        def open_doc(doc):
            page.evaluate('id=>window.app.$refs.knowledge.openDocument(window.app.$refs.knowledge.documents.find(d=>d.id===id))',doc['id'])
            reader=page.locator('.ckb-reader-dialog:visible');expect(reader).to_be_visible();return reader
        def close(reader):
            reader.locator('.el-dialog__headerbtn').click();expect(reader).to_have_count(0)
        reader=open_doc(protected)
        expect(reader.get_by_role('heading',name='PDF 已加密，暂不能预览')).to_be_visible()
        expect(reader.locator('.ckb-original-unavailable')).to_contain_text('打开密码')
        expect(reader.get_by_role('button',name='重试预览')).to_have_count(0)
        expect(reader.get_by_role('button',name='下载水印副本',exact=True)).to_be_disabled()
        reader.screenshot(path=str(args.output_dir/'encrypted-pdf.png'),animations='disabled');close(reader)
        reader=open_doc(missing);expect(reader).to_contain_text('原件缺失')
        expect(reader).to_contain_text('已有解析文字')
        path=temp/'restored.txt';path.write_text('RESTORED ORIGINAL / 补传原件成功',encoding='utf-8')
        reader.get_by_label('补传缺失原件').set_input_files(str(path))
        box=page.locator('.el-message-box:visible');expect(box).to_contain_text('重新建立索引')
        box.get_by_role('button',name='取消',exact=True).click()
        expect(box).to_have_count(0)
        assert not state.client.get('/company-knowledge/documents/'+missing['id']+'/original').is_success
        reader.get_by_label('补传缺失原件').set_input_files(str(path))
        box.get_by_role('button',name='确认补传并重新索引',exact=True).click()
        expect(reader.locator('.ckb-fulltext-document')).to_contain_text('补传原件成功',timeout=20000)
        expect(reader.get_by_label('补传缺失原件')).to_have_count(0)
        restored=state.client.get('/company-knowledge/documents').json()['documents']
        restored=next(d for d in restored if d['id']==missing['id']);assert restored['state']=='queued'
        page.screenshot(path=str(args.output_dir/'restored-original.png'));close(reader)
        reader=open_doc(large);table=reader.locator('.ckb-sheet-reader');expect(table).to_be_visible(timeout=20000)
        expect(table.locator('tbody tr')).to_have_count(50)
        expect(table.get_by_role('combobox',name='选择工作表')).to_contain_text('250586 行')
        expect(table).to_contain_text('观复咨询')
        page.screenshot(path=str(args.output_dir/'large-sheet-first.png'))
        control=table.get_by_role('spinbutton',name='表格行页码');control.fill('5012');control.press('Enter')
        expect(table).to_contain_text('第 250551–250586 行',timeout=30000)
        expect(table.locator('tbody tr')).to_have_count(36)
        page.screenshot(path=str(args.output_dir/'large-sheet-last.png'))
        table.get_by_role('combobox',name='选择工作表').select_option('1')
        expect(table).to_contain_text('第 1–50 行');expect(table.locator('tbody tr')).to_have_count(50)
        table.get_by_role('combobox',name='选择工作表').select_option('2')
        expect(table).to_contain_text('第 1–28 行');expect(table.locator('tbody tr')).to_have_count(28)
        page.screenshot(path=str(args.output_dir/'large-sheet-third.png'))
        assert not errors,errors
        result={'status':'passed','checks':['encrypted PDF explicit password notice','encrypted preview does not offer futile retry','missing source keeps parsed text','restore cancellation','restore real source and reindex','actual 250586 row workbook first 50 rows','last 36 rows','second and third worksheets','visible identity watermark'],'console_errors':errors}
        (args.output_dir/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
    return {'response':lambda path:None,'check':check}
