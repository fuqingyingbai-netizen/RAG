"""Bounded row previews for large XLSX files; originals and formulas stay unchanged."""
import io
import math
from datetime import date, datetime, time
from functools import lru_cache
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree as E

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from company_catalog import document_store
from company_watermark import WatermarkError

ROWS = 50
COLUMNS = 40
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def workbook(data):
    try:
        return load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
    except Exception:
        raise WatermarkError('表格无法读取，请确认文件未加密或损坏。', 422, 'spreadsheet_unreadable') from None


@lru_cache(maxsize=4)
def sheet_info(key, digest):
    data = document_store().get_bytes(key)
    book = workbook(data)
    try:
        # Streaming writers may omit dimension; calculate it without loading all cells.
        for sheet in book.worksheets:
            if sheet.max_row is None or sheet.max_column is None:
                sheet.calculate_dimension(force=True)
        sheets = [{'name': s.title, 'rows': s.max_row or 0, 'columns': s.max_column or 0,
                   'hidden': s.sheet_state != 'visible'} for s in book.worksheets]
        large = any(s['rows'] > 10000 or s['columns'] > 256 or s['rows'] * s['columns'] > 200000 for s in sheets)
        with ZipFile(io.BytesIO(data)) as package:
            native = (sum(part.file_size for part in package.infolist()) <= 64*1024*1024 and
                      not any(name.startswith(('xl/media/', 'xl/charts/', 'xl/drawings/')) for name in package.namelist()))
        return {'mode': 'table' if large else 'workbook' if native else 'pdf', 'sheets': sheets}
    finally:
        book.close()


def sheet_page(key, digest, sheet, page, column):
    info = sheet_info(key, digest)
    if info['mode'] == 'workbook':
        from company_sheet_layout import worksheet_page
        return worksheet_page(document_store().get_bytes(key), info, sheet, page, column, ROWS, COLUMNS)
    if info['mode'] == 'pdf':
        return info
    if not 0 <= sheet < len(info['sheets']):
        raise WatermarkError('工作表不存在。', 422, 'sheet_out_of_range')
    meta = info['sheets'][sheet]
    pages = max(1, math.ceil(meta['rows'] / ROWS))
    if page > pages or column > max(1, meta['columns']):
        raise WatermarkError('表格行页码或列号超出范围。', 422, 'sheet_out_of_range')
    start = (page - 1) * ROWS + 1
    end = min(meta['rows'], start + ROWS - 1)
    end_column = min(meta['columns'], column + COLUMNS - 1)
    data = document_store().get_bytes(key)
    book = workbook(data)
    try:
        # openpyxl constructs every preceding cell when min_row is large. Stream
        # past those XML rows in C, retaining only this window, then let openpyxl
        # decode its types/styles/formulas from a temporary in-memory package.
        target = book.worksheets[sheet]._worksheet_path.lstrip('/')
        book.close()
        selected = []
        output = io.BytesIO()
        with ZipFile(io.BytesIO(data)) as source:
            with source.open(target) as stream:
                for _, row in E.iterparse(stream, events=('end',), tag='{'+NS+'}row',
                                          resolve_entities=False, no_network=True):
                    number = int(row.get('r', '0'))
                    if number > end:
                        break
                    if number >= start:
                        selected.append(E.tostring(row))
                    row.clear()
                    while row.getprevious() is not None:
                        del row.getparent()[0]
            with ZipFile(output, 'w', ZIP_DEFLATED) as preview:
                for part in source.infolist():
                    if part.filename.startswith(('xl/media/', 'xl/drawings/')):
                        continue
                    if part.filename.startswith('xl/worksheets/') and part.filename.endswith('.xml'):
                        rows = b''.join(selected) if part.filename == target else b''
                        body = ('<worksheet xmlns="'+NS+'"><dimension ref="A1:'+get_column_letter(max(1, meta['columns']))+str(max(1, meta['rows']))+'"/><sheetData>').encode()+rows+b'</sheetData></worksheet>'
                        preview.writestr(part.filename, body)
                    else:
                        preview.writestr(part, source.read(part.filename))
        book = workbook(output.getvalue())
        def cell_text(cell):
            value = cell.value
            if isinstance(value, (date, datetime, time)):
                return value.isoformat(sep=' ') if isinstance(value, datetime) else value.isoformat()
            return '' if value is None else str(value)
        values = [[cell_text(cell) for cell in row] for row in book.worksheets[sheet].iter_rows(
            min_row=start, max_row=max(start, end), min_col=column, max_col=max(column, end_column))]
        while len(values) < max(0, end - start + 1):
            values.append([''] * max(0, end_column - column + 1))
        return {**info, 'sheet': sheet, 'page': page, 'pages': pages, 'first_row': start,
                'last_row': end, 'column': column, 'total_columns': meta['columns'],
                'columns': [get_column_letter(i) for i in range(column, end_column + 1)], 'values': values,
                'notice': '按行展示已归档表格，公式显示原式，不重新计算；图片、图表及打印版式请核对原件。'}
    finally:
        book.close()
