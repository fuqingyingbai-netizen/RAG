"""Company-only PDF collection: retain physical pages beyond the introduction."""
import os
import re
from io import BytesIO

from pypdf import PdfReader
from company_ocr import native_text_issue, enrich_pdf_pages
from company_charts import extract_survey_charts

TABLES_VERSION='company-native-tables-v2-accounting-and-operating'


def _limit(name,default,minimum,maximum):
    try:value=int(os.getenv(name,str(default)))
    except (TypeError,ValueError):value=default
    return max(minimum,min(maximum,value))


def extract_company_pdf(payload):
    reader=PdfReader(BytesIO(payload))
    if reader.is_encrypted:reader.decrypt('')
    max_pages=_limit('COMPANY_PDF_MAX_PAGES',1000,1,3000)
    max_chars=_limit('COMPANY_PDF_MAX_CHARS',2000000,10000,6000000)
    pages=[];blocks=[];used=0;needs_ocr=[]
    for index,page in enumerate(reader.pages):
        if index>=max_pages:break
        text=(page.extract_text() or '').replace('\x00','').strip()
        if used+len(text)>max_chars:continue
        issue=native_text_issue(text)
        record={'page':index+1,'text':text,'text_origin':'embedded_pdf_text'}
        if issue:record['native_text_issue']=issue
        # Two-column metric tables need both labels and cell alignment. Keep
        # layout for relevant pages without pretending text extraction is OCR.
        if re.search(r'满意度|投诉|员工流失率|market share|satisfaction',text,re.I):
            try:record['layout_text']=(page.extract_text(extraction_mode='layout') or '').replace('\x00','')
            except Exception:pass
        pages.append(record)
        used+=len(text)
    ocr=enrich_pdf_pages(payload,pages)
    needs_ocr=ocr['pending_pages']
    # OCR can add characters to an originally empty scan. Apply the body
    # budget after recognition too; never silently return 'complete' while
    # dropping these pages. The OCR receipt still records what was attempted.
    retained=[];used=0;budget_omitted=[]
    for record in pages:
        if used+len(record['text'])>max_chars:
            budget_omitted.append(record['page']);continue
        retained.append(record);used+=len(record['text'])
    pages=retained
    table_status=extract_business_tables(payload,pages)
    accounting_status=extract_accounting_tables(payload,pages)
    management_status=extract_management_tables(payload,pages)
    judicial_status=extract_judicial_tables(payload,pages)
    chart_status=extract_survey_charts(payload,pages)
    from company_pdf_reading_order import recover_comparison_pages
    comparison_status=recover_comparison_pages(payload,pages)
    # Rebuild only after verified geometry recovery. The native stream remains
    # alongside every recovered page; the PDF bytes and all glyphs are retained.
    for record in pages:
        if record['text']:blocks.append(f"--- PDF page {record['page']} ---\n{record['text']}")
    return {'content':'\n\n'.join(blocks),'pages':len(reader.pages),'document_pages':pages,
            'document_extraction':{'method':'embedded_pdf_text_with_selective_ocr' if ocr['accepted_pages'] else 'embedded_pdf_text','extracted_pages':len(pages),
                                   'omitted_pages':len(reader.pages)-len(pages),'needs_ocr_pages':needs_ocr,
                                   'ocr_content_budget_omitted_pages':budget_omitted,
                                   'complete':len(pages)==len(reader.pages) and not needs_ocr,'ocr':ocr,
                                   'table_version':TABLES_VERSION,'business_tables':table_status,
                                   'accounting_tables':accounting_status,'management_tables':management_status,
                                   'judicial_tables':judicial_status,'survey_charts':chart_status,
                                   'comparison_tables':comparison_status}}


def extract_business_tables(payload,pages):
    """Recover vector grid cells; never read project goals as actual progress.

    Only relevant pages and bounded continuations are processed. Missing
    libraries, unrecognised grids and page limits remain explicit diagnostics.
    """
    selected=set();by_page={p['page']:p for p in pages}
    for record in pages:
        text=re.sub(r'\s+','',record['text'])
        if re.search(r'营业收入构成|主营业务分(?:行业|产品|地区|销售模式)情况|整车产品产销情况|产能利用率|本月数|本月数量',text) or ('本月' in text and '本年累计' in text):
            selected.add(record['page']);selected.add(record['page']+1)
        if '项目进展' in text and '项目目的' in text:
            for n in range(record['page'],record['page']+9):
                if n not in by_page:break
                selected.add(n)
                if n>record['page'] and re.search(r'公司研发人员情况|公司研发投入情况',compact_page(by_page[n])):break
    selected=sorted(n for n in selected if n in by_page)
    return _extract_grids(payload,pages,selected,'COMPANY_PDF_TABLE_MAX_PAGES')


def extract_accounting_tables(payload,pages):
    selected=set()
    for page in pages[:55]:
        text=compact_page(page)
        if re.search(r'主要会计数据|主要財務數據|主要财务数据',text) and '营业收入' in text:
            selected.update((page['page'],page['page']+1))
    return _extract_grids(payload,pages,selected,'COMPANY_PDF_ACCOUNTING_MAX_PAGES')


def extract_management_tables(payload,pages):
    selected=set();by_page={p['page']:p for p in pages}
    for p in pages:
        text=compact_page(p)
        if ('任期起始日期' in text and '任职状态' in text) or all(s in text for s in ('姓名','担任的职务','类型','日期','原因')):
            selected.update((p['page'],p['page']+1))
        if re.search(r'在其他单位任职情况|在股东单位任职情况',text):
            for n in range(p['page'],p['page']+6):
                if n not in by_page:break
                selected.add(n)
                if n>p['page'] and re.search(r'报酬情况|薪酬情况|从公司获得的税前报酬',compact_page(by_page[n])):break
    return _extract_grids(payload,pages,selected,'COMPANY_PDF_MANAGEMENT_MAX_PAGES')


def extract_judicial_tables(payload,pages):
    selected=set()
    for p in pages:
        text=compact_page(p)
        if all(s in text for s in ('涉案金额','预计负债','进展')):
            selected.update((p['page'],p['page']+1))
    return _extract_grids(payload,pages,selected,'COMPANY_PDF_JUDICIAL_MAX_PAGES')


def _extract_grids(payload,pages,selected,limit_name):
    by_page={p['page']:p for p in pages}
    selected=sorted(n for n in selected if n in by_page)
    maximum=_limit(limit_name,24,1,100)
    pending=selected[maximum:];selected=selected[:maximum]
    if not selected:return {'method':'not_needed','processed_pages':[],'pending_pages':[]}
    try:
        import pdfplumber
    except ImportError:
        return {'method':'library_unavailable','processed_pages':[],'pending_pages':selected+pending}
    processed=[];empty=[]
    try:
        with pdfplumber.open(BytesIO(payload),pages=selected) as doc:
            for page in doc.pages:
                tables=page.extract_tables()
                if not tables:empty.append(page.page_number)
                by_page[page.page_number]['tables']=[[
                    [(cell or '').replace('\x00','') for cell in row] for row in table] for table in tables]
                by_page[page.page_number]['table_method']='pdf_vector_grid'
                processed.append(page.page_number)
                page.close()
    except Exception as exc:
        return {'method':'grid_extraction_incomplete','processed_pages':processed,
                'pending_pages':sorted(set(selected+pending)-set(processed)),'error_type':type(exc).__name__}
    return {'method':'pdf_vector_grid','processed_pages':processed,'pending_pages':pending,'empty_grid_pages':empty}


def compact_page(page):
    return re.sub(r'\s+','',page['text'])
