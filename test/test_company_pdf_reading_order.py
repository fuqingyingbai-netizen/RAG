from copy import deepcopy
from types import SimpleNamespace as NS
import pytest

from company_pdf_reading_order import grid_reading_text,recover_comparison_pages,comparison_page,VERSION


ROWS=[['修订前','修订后'],
      ['注册资本46,267.4004万元。','注册资本46,317.9293万元。'],
      ['董事长为法定代表人。','法定代表人辞任之日起30日内确定新的法定代表人。'],
      [0,False]]


def native_text():
    value='附件公司章程'+''.join(str(c) for r in ROWS for c in r)+'1'
    # A distinct colored number can be last in the PDF content stream even
    # though its visible position is inside this word sequence.
    return value.replace('30日内确定新的法定代表人','日内确定新的法定代表30人')


class Page:
    bbox=(0,0,600,800)
    page_number=1
    def __init__(self):
        self.rows=deepcopy(ROWS)
        self.table=NS(bbox=(50,100,550,700),extract=lambda:self.rows)
        self.chars=[{'text':c,'x0':200,'x1':210,'top':200,'bottom':210}
                    for r in ROWS for cell in r for c in str(cell)]
    def find_tables(self):return [self.table]
    def crop(self,bbox):return NS(extract_text=lambda:'附件公司章程' if bbox[1]==0 else '1')
    def close(self):pass


def test_grid_reading_recovers_positions_without_losing_any_original_glyph_or_value():
    result,error=grid_reading_text(Page(),native_text())
    assert not error
    assert '30日内确定新的法定代表人' in result['text']
    assert '46,317.9293万元' in result['text'] and '| 0 | False |' in result['text']
    assert '修订前 | 修订后' in result['text']


def test_incomplete_cell_extraction_keeps_the_original_stream():
    page=Page();page.rows[1][1]='注册资本元。'
    result,error=grid_reading_text(page,native_text())
    assert result is None and error=='glyph_inventory_mismatch'


def test_side_annotations_cannot_be_silently_moved_away_from_the_table():
    page=Page();page.chars.append({'text':'注','x0':10,'x1':20,'top':300,'bottom':310})
    assert grid_reading_text(page,native_text()+'注')==(None,'text_beside_grid')


def test_comparison_columns_must_be_explicit_not_inferred_from_values():
    page=Page();page.rows[0]=['甲','乙']
    assert grid_reading_text(page,native_text())[1]=='unbound_comparison_columns'


def test_overlapping_table_regions_do_not_guess_a_column_order():
    page=Page();page.find_tables=lambda:[page.table,page.table]
    assert grid_reading_text(page,native_text())[1]=='overlapping_table_regions'


def test_recovery_keeps_a_native_stream_and_distinguishes_geometry_from_ocr(monkeypatch):
    class Document:
        pages=[Page()]
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr('pdfplumber.open',lambda *a,**k:Document())
    original=native_text();pages=[{'page':1,'text':original,'text_origin':'embedded_pdf_text'}]
    result=recover_comparison_pages(b'original-pdf-bytes',pages)
    assert result['recovered_pages']==[1] and result['pending_pages']==[]
    assert pages[0]['native_stream_text']==original
    assert pages[0]['reading_order_glyph_inventory']=='unchanged'
    assert pages[0]['text_origin']=='pdf_vector_grid_reading_order'
    assert pages[0]['reading_order_version']==VERSION


def test_failed_recovery_does_not_modify_native_text(monkeypatch):
    class Document:
        pages=[Page()]
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr('pdfplumber.open',lambda *a,**k:Document())
    pages=[{'page':1,'text':native_text()+'未提取的脚注','text_origin':'embedded_pdf_text'}];before=deepcopy(pages)
    result=recover_comparison_pages(b'original-pdf-bytes',pages)
    assert pages==before and result['pending_pages']==[1] and not result['recovered_pages']


@pytest.mark.parametrize('text',[
    '章程'+('无关段落'*1000)+'修订前 修订后 会计政策。',
    '章程修订前'+('无关段落'*1000)+'修订后。',
    '营业收入 0 0 注册资本 100。',
])
def test_comparison_detection_requires_nearby_headers_and_governance_context(text):
    assert not comparison_page(text)


def ruled_page(number,*,headers=False,caption='',left=50,top=50,bottom=760):
    page=Page();page.page_number=number
    page.rows=deepcopy(ROWS) if headers else [['旧条款注册资本46.00万元。','拟修订注册资本50.00万元。']]
    page.table=NS(bbox=(left,top,550,bottom),extract=lambda:page.rows,
                  cells=[(left,top,300,bottom),(300,top,550,bottom)])
    page.chars=[{'text':c,'x0':200,'x1':210,'top':200,'bottom':210}
                for row in page.rows for cell in row for c in str(cell)]
    page.crop=lambda bbox:NS(extract_text=lambda:caption if bbox[1]==0 else str(number))
    native=caption+''.join(str(cell) for row in page.rows for cell in row)+str(number)
    return page,{'page':number,'text':native,'text_origin':'embedded_pdf_text'}


def recover_pages(monkeypatch,items):
    class Document:
        pages=[p for p,_ in items]
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr('pdfplumber.open',lambda *a,**k:Document())
    records=[r for _,r in items]
    return recover_comparison_pages(b'original-pdf',records),records


def test_adjacent_headerless_pages_keep_explicit_original_column_identity(monkeypatch):
    items=[ruled_page(1,headers=True,caption='公司章程'),ruled_page(2),ruled_page(3)]
    original=[r['text'] for _,r in items]
    result,records=recover_pages(monkeypatch,items)
    assert result['recovered_pages']==[1,2,3] and not result['pending_pages']
    assert [r['native_stream_text'] for r in records]==original
    assert records[2]['comparison_header_binding']=={'physical_page':1,'headers':['修订前','修订后']}
    assert '| 修订前 | 修订后 |' in records[2]['text']
    assert '旧条款注册资本46.00万元。 | 拟修订注册资本50.00万元。' in records[2]['text']


@pytest.mark.parametrize('changed',[
    {'caption':'营业收入报表'}, {'left':80}, {'top':300},
])
def test_new_caption_columns_or_vertical_region_cannot_inherit_old_headers(monkeypatch,changed):
    items=[ruled_page(1,headers=True,caption='公司章程'),ruled_page(2,**changed),ruled_page(3)]
    untouched=deepcopy([r for _,r in items][1:])
    result,records=recover_pages(monkeypatch,items)
    assert result['recovered_pages']==[1]
    assert records[1:]==untouched


def test_page_gap_or_a_table_ending_early_cannot_authorize_a_continuation(monkeypatch):
    for items in ([ruled_page(1,headers=True,caption='公司章程'),ruled_page(3)],
                  [ruled_page(1,headers=True,caption='公司章程',bottom=500),ruled_page(2)]):
        result,records=recover_pages(monkeypatch,items)
        assert result['recovered_pages']==[1] and 'native_stream_text' not in records[1]


def test_failed_glyph_inventory_remains_pending_without_erasing_later_grid_binding(monkeypatch):
    items=[ruled_page(1,headers=True,caption='公司章程'),ruled_page(2),ruled_page(3)]
    items[1][1]['text']+='未提取脚注';original=deepcopy(items[1][1])
    result,records=recover_pages(monkeypatch,items)
    assert result['recovered_pages']==[1,3] and result['pending_pages']==[2]
    assert records[1]==original and result['failures']==[{'page':2,'reason':'glyph_inventory_mismatch'}]


def test_continuation_budget_preserves_unprocessed_originals_and_explicit_pending(monkeypatch):
    monkeypatch.setenv('COMPANY_PDF_COMPARISON_MAX_PAGES','1')
    items=[ruled_page(1,headers=True,caption='公司章程'),ruled_page(2),ruled_page(3)]
    untouched=deepcopy([r for _,r in items][1:])
    result,records=recover_pages(monkeypatch,items)
    assert result['recovered_pages']==[1] and result['pending_pages']==[2,3]
    assert records[1:]==untouched and all(f['reason']=='comparison_page_budget' for f in result['failures'])


def test_exact_repeated_running_header_does_not_hide_a_real_continuation(monkeypatch):
    caption='远帆公司2025年年度股东大会'
    items=[ruled_page(1,headers=True,caption=caption+'\n公司章程议案'),ruled_page(2,caption=caption)]
    result,records=recover_pages(monkeypatch,items)
    assert result['recovered_pages']==[1,2] and records[1]['comparison_header_binding']['physical_page']==1


def test_a_page_can_finish_one_table_and_start_a_new_explicit_comparison(monkeypatch):
    first=ruled_page(1,headers=True,caption='公司章程')
    page,record=ruled_page(2,bottom=250);first_rows=deepcopy(page.rows)
    second_rows=[['修订前','修订后'],['原股东会规则。','拟修订股东会规则。']]
    second=NS(bbox=(50,300,550,760),extract=lambda:second_rows,
              cells=[(50,300,300,760),(300,300,550,760)])
    page.find_tables=lambda:[page.table,second]
    page.chars.extend({'text':c,'x0':200,'x1':210,'top':400,'bottom':410}
                      for row in second_rows for cell in row for c in cell)
    page.crop=lambda bbox:NS(extract_text=lambda:'' if bbox[1]==0 else '公司章程新对照表' if bbox[1]==250 else '2')
    record['text']=''.join(c for row in first_rows for c in row)+'公司章程新对照表'+''.join(c for row in second_rows for c in row)+'2'
    result,records=recover_pages(monkeypatch,[first,(page,record),ruled_page(3)])
    assert result['recovered_pages']==[1,2,3] and not result['pending_pages']
    assert records[1]['comparison_header_binding']['physical_page']==1
    assert records[2]['comparison_header_binding']['physical_page']==2
    assert '公司章程新对照表' in records[1]['text']
