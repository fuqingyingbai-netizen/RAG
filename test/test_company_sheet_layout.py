import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Alignment, Font, PatternFill

from company_catalog import CompanyDocument, document_store
from company_sheet_preview import sheet_info
from test_company_workspace import setup, upload


def test_native_layout_preserves_geometry_merges_rich_text_and_access(setup):
    book=Workbook();sheet=book.active;sheet.title='格式原件'
    sheet.column_dimensions['A'].width=19.06640625;sheet.column_dimensions['B'].width=68.265625
    sheet.row_dimensions[1].height=34.5;sheet.row_dimensions[2].height=285.85
    sheet['A1']='标题';sheet['A1'].fill=PatternFill('solid',fgColor='C00000');sheet['A1'].font=Font(name='楷体',sz=12,bold=True,color='FFFFFF')
    sheet['A1'].alignment=Alignment(horizontal='center',vertical='center',wrap_text=True)
    sheet['B2']=CellRichText('普通文字',TextBlock(InlineFont(rFont='楷体',b=True,color='FF0000'),'加粗红字'))
    sheet.merge_cells('A2:A4');sheet['A2']='保留跨行';sheet['B5']='<script>literal</script>'
    sheet['A6']=.125;sheet['A6'].number_format='0.0%';sheet['B6']='=1+2'
    other=book.create_sheet('第二表');other['A1']='第二张原件'
    output=io.BytesIO();book.save(output);source=output.getvalue()
    row=upload(setup,payload=source,name='styled.xlsx').json();base='/company-knowledge/documents/'+row['id']
    sheet_info.cache_clear();response=setup.client.get(base+'/sheet');assert response.status_code==200,response.text
    data=response.json();assert data['mode']=='workbook' and len(data['sheets'])==2
    assert data['column_layout'][0]['width']==19.06640625 and data['row_layout'][1]['height']==285.85
    cells={cell['address']:cell for r in data['row_layout'] for cell in r['cells']}
    assert cells['A1']['style']['backgroundColor']=='#C00000' and cells['A1']['style']['color']=='#FFFFFF'
    assert cells['A2']['rowspan']==3 and 'A3' not in cells and 'A4' not in cells
    assert cells['B2']['runs'][1]['style']['fontWeight']=='700' and cells['B2']['runs'][1]['style']['color']=='#FF0000'
    assert cells['B5']['text']=='<script>literal</script>' and cells['A6']['text']=='12.5%'
    assert cells['B6']['formula']=='=1+2' and cells['B6']['text']=='' and '未保存计算结果' in data['notice']
    assert data['watermark'] and response.headers['x-watermark-trace']
    assert setup.client.get(base+'/sheet?sheet=1').json()['row_layout'][0]['cells'][0]['text']=='第二张原件'
    assert setup.client.get(base+'/sheet?sheet=2').status_code==422
    assert setup.client.get(base+'/sheet?page=2').status_code==422
    with setup.db() as db:
        doc=db.get(CompanyDocument,row['id']);assert document_store().get_bytes(doc.object_key)==source
        doc.visibility='restricted';db.commit()
    setup.user.username,setup.user.id='bob',2
    assert setup.client.get(base+'/sheet').status_code==404
    sheet_info.cache_clear()


def test_merges_crossing_page_and_hidden_rows_keep_anchor_and_spans(setup):
    book=Workbook();s=book.active;s.merge_cells('A49:A53');s['A49']='跨页合并原文'
    s.row_dimensions[51].hidden=True;s.row_dimensions[52].height=30;s['B53']='最后一行'
    output=io.BytesIO();book.save(output)
    row=upload(setup,payload=output.getvalue(),name='cross-page.xlsx').json()
    sheet_info.cache_clear();data=setup.client.get('/company-knowledge/documents/'+row['id']+'/sheet?page=2').json()
    assert [r['number'] for r in data['row_layout']]==[52,53]
    first=data['row_layout'][0]['cells'][0]
    assert first['address']=='A49' and first['rowspan']==2 and first['height']==45
    assert first['text']=='跨页合并原文'
    sheet_info.cache_clear()
