"""Export server-saved answers with provenance; no client-authored answers or code."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import io
import re
from typing import Literal
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

import company_knowledge as kb

router = APIRouter()
CITE = re.compile(r'\[id_([^\]]+)\]')
SEPARATOR = re.compile(r'^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$')
MISSING = {'', '-', '—', '未知', '未披露', '未找到依据', '暂无', '不适用', 'N/A'}
NOTE = '根据本轮回答整理，未经逐份全文核对；缺失项不补猜，数值与口径请核对所附原文。'


class ExportRequest(BaseModel):
    format: Literal['docx', 'xlsx', 'png']
    table_index: int = Field(default=0, ge=0, le=30)
    value_column: int | None = Field(default=None, ge=0, le=30)


def clean(value):
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(value))


def table_cells(line):
    return [clean(v.strip()) for v in re.split(r'(?<!\\)\|', line.strip().strip('|'))]


def blocks(text):
    lines = text.splitlines(); result = []; prose = []; i = 0
    def flush():
        if prose:
            result.append({'type': 'text', 'text': '\n'.join(prose).strip()}); prose.clear()
    while i < len(lines):
        if i+1 < len(lines) and '|' in lines[i] and SEPARATOR.fullmatch(lines[i+1]):
            flush(); headers = table_cells(lines[i]); rows = []; i += 2
            while i < len(lines) and '|' in lines[i] and lines[i].strip():
                row = table_cells(lines[i])
                if len(row) != len(headers):
                    raise HTTPException(422, '回答表格列数不一致，请先重新整理表格。')
                rows.append(row); i += 1
            if len(headers) > 30 or len(rows) > 1000:
                raise HTTPException(422, '表格过大，请按项目或期间拆分后导出。')
            result.append({'type': 'table', 'headers': headers, 'rows': rows})
        else:
            prose.append(lines[i]); i += 1
    flush()
    return result


def number(value):
    value = CITE.sub('', value).replace('**', '').strip()
    if value in MISSING:
        return None
    match = re.fullmatch(r'([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*([^\d\s]{0,8})', value)
    if not match:
        raise ValueError('not an unambiguous number')
    try:
        raw=match[1].replace(',', '')
        if len(raw)>24:raise ValueError('number exceeds chart precision')
        value=Decimal(raw)
        if abs(value)>Decimal('1e18'):raise ValueError('number exceeds chart range')
        return value, match[2]
    except InvalidOperation:
        raise ValueError('invalid number') from None


def selected_table(answer, request):
    tables = [b for b in blocks(answer) if b['type'] == 'table']
    if request.table_index >= len(tables):
        raise HTTPException(422, '回答中没有对应表格，请先要求助手整理为表格。')
    return tables[request.table_index]


def provenance(refs):
    return [{'id': str(r['id']), 'title': clean(r.get('title', '')), 'version': r.get('version', ''),
        'pages': '、'.join(map(str, r.get('pages') or [])), 'text': clean(r.get('text', '')),
        'evidence_id': r.get('evidence_id', ''), 'local_id': r.get('local_id', '')} for r in refs]


def workbook(answer, refs, title, request, identity):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    table = selected_table(answer, request)
    if any(len(value.encode('utf-16-le'))//2 > 32767 for row in [table['headers'],*table['rows']] for value in row):
        raise HTTPException(422, '表格单元格内容过长，请拆分后导出；不会截断原文。')
    wb = Workbook(); sheet = wb.active; sheet.title = '整理结果'
    sheet.append([title]); sheet.append([NOTE]); sheet.append(['生成时间', identity['time'], '下载账号', identity['user']])
    sheet.append(['追踪编号', identity['trace']]); sheet.append([])
    sheet.append(table['headers']+['引用编号', '核对状态'])
    known = {str(r['id']) for r in refs}
    for row in table['rows']:
        cited = set(CITE.findall(' '.join(row)))
        state = '附原文待核对' if cited and cited <= known else '缺少有效行引用，请核对'
        values = []
        for value in row:
            try:
                parsed = number(value)
            except ValueError:
                parsed = None
            # Preserve identifiers, units, and precision; never execute answer text as a formula.
            values.append(float(parsed[0]) if parsed and not parsed[1] and len(str(parsed[0]).replace('.','').lstrip('-+')) <= 15 and not re.match(r'^0\d', value) and not CITE.search(value) else value)
        sheet.append(values+[', '.join(sorted(cited)), state])
    sheet.freeze_panes = 'A7'; sheet.auto_filter.ref = f'A6:{get_column_letter(sheet.max_column)}{sheet.max_row}'
    source = wb.create_sheet('原文依据')
    source.append(['引用编号', '文件', '版本', '原件页码', '原文片段', '证据编号'])
    for r in provenance(refs):
        text = r['text']
        # Split long quotations into visible continuation rows, never discard them.
        for start in range(0, max(1, len(text)), 1000):
            source.append([r['id'], r['title'], r['version'], r['pages'], text[start:start+1000], r['evidence_id']])
    for ws in wb:
        header = 6 if ws == sheet else 1
        for cells in ws:
            for cell in cells:
                if isinstance(cell.value, str):
                    cell.value = clean(cell.value); cell.data_type = 's'
                cell.alignment = Alignment(vertical='top', wrap_text=True)
                cell.font = Font(name='Microsoft YaHei', size=11, color='17212F')
        for cell in ws[header]:
            cell.fill = PatternFill('solid', fgColor='E8EEF5'); cell.font = Font(name='Microsoft YaHei', bold=True, color='17212F')
        for col in range(1, ws.max_column+1):
            ws.column_dimensions[get_column_letter(col)].width = 25 if ws == sheet else (85 if col == 5 else 24)
        ws.sheet_view.showGridLines = False
        ws.oddFooter.center.text = '内部资料  '+identity['user']+'  '+identity['trace']
        ws.print_title_rows = f'{header}:{header}'
    sheet.merge_cells(start_row=1,start_column=1,end_row=1,end_column=sheet.max_column)
    sheet.merge_cells(start_row=2,start_column=1,end_row=2,end_column=sheet.max_column)
    sheet.merge_cells(start_row=4,start_column=2,end_row=4,end_column=sheet.max_column)
    sheet['A1'].font=Font(name='Microsoft YaHei',bold=True,size=16,color='17212F')
    sheet.row_dimensions[1].height=42; sheet.row_dimensions[2].height=36
    source.freeze_panes = 'A2'
    wb.properties.creator = identity['user']; wb.properties.description = NOTE+' Trace '+identity['trace']
    out = io.BytesIO(); wb.save(out); return out.getvalue()


def document(answer, refs, title, request, identity):
    from docx import Document
    from docx.shared import Cm, Pt, RGBColor
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    doc = Document(); section = doc.sections[0]
    section.top_margin = section.bottom_margin = Cm(2)
    section.left_margin = section.right_margin = Cm(2.1)
    for name in ('Normal', 'Title', 'Heading 1', 'Heading 2'):
        style = doc.styles[name]; style.font.name = 'Microsoft YaHei'; style.font.color.rgb = RGBColor(0, 0, 0)
        style.element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
        style.font.underline = False
        for border in list(style.element.iter(qn('w:pBdr'))):border.getparent().remove(border)
    doc.styles['Normal'].font.size = Pt(10.5)
    title_paragraph=doc.add_paragraph('知识库资料整理', 'Title')
    for border in list(title_paragraph._p.iter(qn('w:pBdr'))):border.getparent().remove(border)
    doc.add_paragraph('问题 '+clean(title)); doc.add_paragraph(NOTE)
    doc.add_paragraph('生成时间 '+identity['time']+'  下载账号 '+identity['user'])
    for block in blocks(answer):
        if block['type'] == 'text':
            for line in block['text'].splitlines():
                match = re.match(r'^#{1,3}\s+(.+)', line)
                doc.add_paragraph(clean(match[1] if match else line), 'Heading 2' if match else None)
        else:
            if len(block['headers']) > 8:
                doc.add_paragraph('宽表按逐条记录展开')
                for n, row in enumerate(block['rows'], 1):
                    doc.add_paragraph('记录 '+str(n), 'Heading 2')
                    for key, value in zip(block['headers'], row):
                        doc.add_paragraph(key+'：'+value)
                continue
            table = doc.add_table(rows=1, cols=len(block['headers'])); table.style = 'Table Grid'
            for cell, value in zip(table.rows[0].cells, block['headers']): cell.text = value
            repeat = OxmlElement('w:tblHeader'); table.rows[0]._tr.get_or_add_trPr().append(repeat)
            for row in block['rows']:
                for cell, value in zip(table.add_row().cells, row): cell.text = value
            borders=OxmlElement('w:tblBorders')
            for edge in ('top','left','bottom','right','insideH','insideV'):
                border=OxmlElement('w:'+edge);border.set(qn('w:val'),'single');border.set(qn('w:sz'),'4');border.set(qn('w:color'),'D9D9D9');borders.append(border)
            table._tbl.tblPr.append(borders)
            for cell in table.rows[0].cells:
                fill=OxmlElement('w:shd');fill.set(qn('w:fill'),'E8EEF5');cell._tc.get_or_add_tcPr().append(fill)
                for p in cell.paragraphs:
                    for run in p.runs:run.bold=True
    if refs:
        doc.add_paragraph('原文依据', 'Heading 1')
        for r in provenance(refs):
            doc.add_paragraph('[id_'+r['id']+'] '+r['title']+'  版本 '+str(r['version'])+('  第 '+r['pages']+' 页' if r['pages'] else ''), 'Heading 2')
            doc.add_paragraph(r['text'])
    section.footer.paragraphs[0].text = '内部资料  '+identity['user']+'  追踪编号 '+identity['trace']
    doc.core_properties.author = identity['user']; doc.core_properties.identifier = identity['trace']
    out = io.BytesIO(); doc.save(out); return out.getvalue()


def chart(answer, refs, title, request, identity):
    from PIL import Image, ImageDraw, ImageFont
    from company_watermark import font_path, wrapped_lines
    table = selected_table(answer, request); headers = table['headers']
    columns = [request.value_column] if request.value_column is not None else list(range(1, len(headers)))
    chosen = None
    for col in columns:
        if col >= len(headers) or re.search(r'年份|年度|日期|编号|序号|代码|引用|来源', headers[col]): continue
        try:
            parsed = [number(row[col]) for row in table['rows']]
            values = [(row, n) for row, n in zip(table['rows'], parsed) if n is not None]
            if values and len({n[1] for _, n in values}) == 1:
                chosen = (col, values); break
        except ValueError:
            continue
    if chosen is None:
        raise HTTPException(422, '没有可绘制的同单位数值列；请把单位统一，并将不同口径分列。')
    col, values = chosen
    header_unit = next((unit for unit in ('亿美元','万美元','亿元','万元','美元','元','%','％','万人','人','家','个','天') if unit in headers[col]), '')
    value_unit = values[0][1][1]
    if header_unit and value_unit and header_unit != value_unit:
        raise HTTPException(422, '列标题与数据单位不一致，请统一单位后再生成图表。')
    if len(values) > 30:
        raise HTTPException(422, '图表最多展示30条记录，请先缩小范围；不会截断成不完整图表。')
    known = {str(r['id']):r for r in refs}
    for row, (value, _) in values:
        cited = set(CITE.findall(' '.join(row)))
        if not cited or not cited <= set(known):
            raise HTTPException(422, '每条图表数据都需要有效行引用，请先整理带引用的表格。')
        evidence = ' '.join(known[k].get('text','').replace(',','') for k in cited)
        if not any(Decimal(n) == value for n in re.findall(r'(?<![\d.])[+-]?\d+(?:\.\d+)?', evidence)):
            raise HTTPException(422, '图表存在无法在行引用原文中直接核对的数值；计算结果请先补充计算依据。')
    # Keep all labels, values and source IDs visible; height follows wrapped labels.
    width = 1400; font = ImageFont.truetype(font_path(), 22); small = ImageFont.truetype(font_path(), 17)
    probe = ImageDraw.Draw(Image.new('RGB',(width,10)))
    labels = [wrapped_lines(probe, [CITE.sub('',row[0]).replace('**','')], font, 390) for row,_ in values]
    heights = [max(65, len(label)*28+20) for label in labels]
    if sum(heights) > 6500: raise HTTPException(422, '图表标签过长，请精简名称后生成。')
    height = 230+sum(heights); image = Image.new('RGB',(width,height),'white'); draw = ImageDraw.Draw(image)
    draw.text((35,25), '资料数据图表', font=ImageFont.truetype(font_path(),32),fill='#17212f')
    draw.text((35,78), headers[col][:65], font=font,fill='#17212f')
    draw.text((35,116), f'原表{len(table["rows"])}条，绘制{len(values)}条有数值记录；数值在行引用中出现，对象和口径仍需复核。',font=small,fill='#526174')
    low = min(Decimal(0), min(n[0] for _, n in values)); high = max(Decimal(0), max(n[0] for _, n in values))
    span = high-low or Decimal(1); left=450; chart_width=650; baseline=left+float(-low/span)*chart_width
    y=165
    for (row,(value,unit)), label, h in zip(values, labels, heights):
        for n,line in enumerate(label): draw.text((35,y+n*28),line,font=font,fill='#17212f')
        end = left+float((value-low)/span)*chart_width
        draw.line((baseline,y,baseline,y+35),fill='#bac5d2',width=2)
        if value: draw.rectangle((min(baseline,end),y+5,max(baseline,end),y+32),fill='#356ea5')
        draw.text((1120,y),str(value)+unit,font=font,fill='#17212f')
        draw.text((1120,y+30),'引用 '+','.join(CITE.findall(' '.join(row))),font=small,fill='#526174')
        y+=h
    draw.text((35,height-55),identity['user']+'  '+identity['time']+'  追踪 '+identity['trace'],font=small,fill='#526174')
    out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()


def saved_answer(user, index_id, session_id, message_id):
    from company_memory import factory, owned, KnowledgeChatMessage, valid, accessible
    with factory()() as db:
        thread=owned(db,user,index_id,session_id)
        message=db.scalar(select(KnowledgeChatMessage).where(KnowledgeChatMessage.id==message_id,KnowledgeChatMessage.thread_id==thread.id))
        if message is None or message.role!='assistant': raise HTTPException(404,'回答不存在。')
        if message.status!='completed': raise HTTPException(409,'回答尚未完整生成，请完成后再导出。')
        if not message.content or not message.references: raise HTTPException(422,'这条回答没有资料依据，不能生成资料文件。')
        if not valid(message.dependencies,accessible(db,user,index_id,thread.scope)):
            raise HTTPException(409,'资料版本或权限已变化，请重新提问后导出。')
        from company_catalog import CompanyDocument
        for reference in message.references:
            local_id=reference.get('local_id')
            source=db.get(CompanyDocument,local_id) if local_id else None
            if (not source or local_id not in (message.dependencies or {}) or source.index_id!=index_id
                or source.cloud_id!=reference.get('document_id') or source.version!=reference.get('version')):
                raise HTTPException(409,'历史回答缺少有效来源版本，请重新提问后导出。')
        if len(message.content)>200000: raise HTTPException(422,'回答过长，请按主题拆分导出。')
        return message.content,deepcopy(message.references),thread.title


@router.post('/conversations/{session_id}/messages/{message_id}/export')
async def export_answer(session_id: str, message_id: int, request: ExportRequest, user=Depends(kb.require_knowledge_user)):
    index_id=kb.settings()['index_id']; answer,refs,title=saved_answer(user,index_id,session_id,message_id)
    identity={'user':user.username,'time':datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M UTC+08:00'),'trace':uuid4().hex}
    builders={'xlsx':workbook,'docx':document,'png':chart}
    payload=await asyncio.to_thread(builders[request.format],answer,refs,title,request,identity)
    # Re-read ownership, saved content, version and ACL after the potentially slow build.
    current=saved_answer(user,index_id,session_id,message_id)
    if current!=(answer,refs,title): raise HTTPException(409,'回答已变化，请重新打开后导出。')
    from company_memory import factory
    from company_catalog import CompanyAuditEvent
    with factory()() as db:
        db.add(CompanyAuditEvent(id=identity['trace'],index_id=index_id,target_type='answer',target_id=str(message_id),
            target_name=title,actor_id=user.id,actor_username=user.username,action='answer.export',changes={},
            details={'format':request.format,'session_id':session_id,'sha256':hashlib.sha256(payload).hexdigest(),'trace_id':identity['trace']}))
        db.commit()
    mime={'xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','png':'image/png'}
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',title)[:60] or '知识库回答'
    return Response(payload,media_type=mime[request.format],headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(name+'.'+request.format),
        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Watermark-Trace':identity['trace']})
