"""Read-only worksheet layout. Never recalculate or rewrite the archived workbook."""
import colorsys
import io
import math
import re
from datetime import date, datetime, time

from lxml import etree as E
from openpyxl import load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.styles.colors import COLOR_INDEX
from openpyxl.utils import get_column_letter

from company_watermark import WatermarkError


def theme_colors(book):
    try:
        root = E.fromstring(book.loaded_theme, E.XMLParser(resolve_entities=False, no_network=True))
        scheme = root.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}clrScheme')
        values = {E.QName(n).localname: next(iter(n)).get('lastClr') or next(iter(n)).get('val') for n in scheme}
        return [values[name] for name in ('lt1','dk1','lt2','dk2','accent1','accent2','accent3','accent4','accent5','accent6','hlink','folHlink')]
    except (ValueError, TypeError, AttributeError, KeyError):
        return ['FFFFFF','000000','EEECE1','1F497D','4F81BD','C0504D','9BBB59','8064A2','4BACC6','F79646','0000FF','800080']


def color(value, theme, fallback=None):
    if value is None or value.type == 'auto':
        return fallback
    if value.type == 'rgb':
        rgb = value.rgb[-6:]
    elif value.type == 'theme' and 0 <= value.theme < len(theme):
        rgb = theme[value.theme]
    elif value.type == 'indexed' and 0 <= value.indexed < len(COLOR_INDEX):
        rgb = COLOR_INDEX[value.indexed][-6:]
    else:
        return fallback
    if not re.fullmatch('[0-9A-Fa-f]{6}', rgb or ''):
        return fallback
    if value.tint:
        red, green, blue = [int(rgb[i:i+2], 16)/255 for i in (0,2,4)]
        hue, light, saturation = colorsys.rgb_to_hls(red, green, blue)
        light = light*(1+value.tint) if value.tint < 0 else light*(1-value.tint)+value.tint
        rgb = ''.join(f'{round(v*255):02X}' for v in colorsys.hls_to_rgb(hue, light, saturation))
    return '#'+rgb.upper()


def font_style(font, theme):
    style = {}
    name = getattr(font, 'name', None)
    if not isinstance(name, str):
        name = getattr(font, 'rFont', None)
    if name:
        # CSS strings remain data; names cannot introduce additional properties.
        escaped = name.replace('\\','\\\\').replace('"','\\"').replace('\n',' ')
        style['fontFamily'] = '"'+escaped+'", "Microsoft YaHei", sans-serif'
    if font.sz:
        style['fontSize'] = f'{font.sz:g}pt'
    style['fontWeight'] = '700' if font.b else '400'
    style['fontStyle'] = 'italic' if font.i else 'normal'
    style['color'] = color(font.color, theme, '#000000')
    decoration = ('underline ' if font.u else '')+('line-through' if font.strike else '')
    if decoration:
        style['textDecoration'] = decoration.strip()
    if font.vertAlign in ('superscript','subscript'):
        style['verticalAlign'] = 'super' if font.vertAlign == 'superscript' else 'sub'
    return style


def display_value(value, number_format):
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, (date, datetime, time)):
        # Preserve the workbook's date order and common date/time tokens.
        fmt = (number_format or '').lower()
        if '年' in fmt:
            return value.strftime('%Y年%m月%d日')
        if isinstance(value, time):
            return value.strftime('%H:%M:%S' if 'ss' in fmt else '%H:%M')
        pattern = '%m/%d/%Y' if fmt.startswith('m') else '%d/%m/%Y' if fmt.startswith('d') else '%Y-%m-%d'
        if 'h' in fmt:
            pattern += ' %H:%M'+(':%S' if 'ss' in fmt else '')
        return value.strftime(pattern)
    if isinstance(value, (int, float)) and math.isfinite(value):
        section = (number_format or 'General').split(';')[0]
        if section in ('General', '@'):
            return str(value)
        decimals = re.search(r'\.([0#]+)', section)
        places = len(decimals[1]) if decimals else 0
        numeric = value*100 if '%' in section else value
        text = format(numeric, (',' if ',' in section else '')+'.'+str(places)+'f')
        if '%' in section:
            text += '%'
        currency = re.search(r'[$¥￥€£]', section)
        if currency:
            text = currency[0]+text
        return text
    return str(value)


def worksheet_page(data, info, sheet, page, column, rows=50, columns=40):
    if not 0 <= sheet < len(info['sheets']):
        raise WatermarkError('工作表不存在。', 422, 'sheet_out_of_range')
    meta = info['sheets'][sheet]
    pages = max(1, math.ceil(meta['rows']/rows))
    if not 1 <= page <= pages or not 1 <= column <= max(1, meta['columns']):
        raise WatermarkError('表格行页码或列号超出范围。', 422, 'sheet_out_of_range')
    book = load_workbook(io.BytesIO(data), data_only=False, keep_links=False, rich_text=True)
    cached = None
    try:
        ws = book.worksheets[sheet]
        if any(cell.data_type == 'f' for row in ws for cell in row):
            cached = load_workbook(io.BytesIO(data), data_only=True, keep_links=False)
        values_ws = cached.worksheets[sheet] if cached else None
        theme = theme_colors(book)
        start, end = (page-1)*rows+1, min(meta['rows'], page*rows)
        last_col = min(meta['columns'], column+columns-1)
        column_dims = []
        for number in range(column, last_col+1):
            dim = next((d for d in ws.column_dimensions.values() if (d.min or 0) <= number <= (d.max or 0)), None)
            if dim and dim.hidden:
                continue
            column_dims.append({'number':number,'label':get_column_letter(number),
                                'width':dim.width if dim and dim.width is not None else ws.sheet_format.defaultColWidth or 9.14})
        row_dims = [{'number':number,'height':ws.row_dimensions[number].height or ws.sheet_format.defaultRowHeight or 15}
                    for number in range(start, end+1) if not ws.row_dimensions[number].hidden]
        visible_rows = {item['number'] for item in row_dims}
        visible_cols = {item['number'] for item in column_dims}
        covered, anchors = set(), {}
        for merged in ws.merged_cells.ranges:
            rr = [r for r in range(max(start, merged.min_row), min(end, merged.max_row)+1) if r in visible_rows]
            cc = [c for c in range(max(column, merged.min_col), min(last_col, merged.max_col)+1) if c in visible_cols]
            if not rr or not cc:
                continue
            anchor = (rr[0], cc[0])
            anchors[anchor] = (merged.min_row, merged.min_col, len(rr), len(cc))
            covered.update((r,c) for r in rr for c in cc if (r,c) != anchor)
        rendered, formula_missing = [], False
        for row_index, row in enumerate(row_dims):
            cells = []
            for col in column_dims:
                r, c = row['number'], col['number']
                if (r,c) in covered:
                    continue
                source_r, source_c, rowspan, colspan = anchors.get((r,c), (r,c,1,1))
                cell = ws.cell(source_r, source_c)
                value = cell.value
                formula = value if cell.data_type == 'f' else ''
                if formula:
                    value = values_ws.cell(source_r, source_c).value
                    formula_missing = formula_missing or value is None
                runs = ([{'text':part.text,'style':font_style(part.font,theme)} if isinstance(part,TextBlock)
                         else {'text':str(part),'style':{}} for part in value]
                        if isinstance(value,CellRichText) else [{'text':display_value(value,cell.number_format),'style':{}}])
                style = font_style(cell.font, theme)
                style.update({'textAlign':cell.alignment.horizontal if cell.alignment.horizontal in ('left','center','right','justify') else 'right' if isinstance(value,(int,float)) else 'left',
                              'whiteSpace':'pre-wrap' if cell.alignment.wrap_text else 'pre',
                              'verticalAlign':{'center':'middle','top':'top','bottom':'bottom'}.get(cell.alignment.vertical,'bottom')})
                fill = color(cell.fill.fgColor,theme) if cell.fill.patternType == 'solid' else None
                if fill:
                    style['backgroundColor'] = fill
                for side in ('left','right','top','bottom'):
                    border = getattr(cell.border, side)
                    if border and border.style:
                        line = 'double' if border.style == 'double' else 'dotted' if border.style in ('dotted','hair') else 'dashed' if 'dash' in border.style.lower() else 'solid'
                        width = 3 if border.style in ('thick','double') else 2 if border.style.startswith('medium') else 1
                        style['border'+side.capitalize()] = f'{width}px {line} '+color(border.color,theme,'#000000')
                cells.append({'address':cell.coordinate,'column':c,'rowspan':rowspan,'colspan':colspan,
                              'style':style,'runs':runs,'formula':formula,'text':''.join(part['text'] for part in runs),
                              'height':sum(item['height'] for item in row_dims[row_index:row_index+rowspan])})
            rendered.append({**row,'cells':cells})
        return {**info,'sheet':sheet,'page':page,'pages':pages,'first_row':start,'last_row':end,
                'column':column,'total_columns':meta['columns'],'columns':[col['label'] for col in column_dims],
                'column_layout':column_dims,'row_layout':rendered,'grid_lines':ws.sheet_view.showGridLines is not False,
                'default_font':font_style(book._fonts[0],theme),
                'notice':'按原工作表显示列宽、行高、合并单元格与文字样式。'+('部分公式未保存计算结果，请下载原件核对；预览不会执行公式。' if formula_missing else '')}
    finally:
        book.close()
        if cached:
            cached.close()
