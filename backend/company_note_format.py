"""Bounded structured notes and local, portable DOCX/Markdown rendering."""
import io
import json
import re
from urllib.parse import urlsplit

from fastapi import HTTPException

EMPTY = {'type': 'doc', 'content': [{'type': 'paragraph'}]}
BLOCKS = {'paragraph', 'heading', 'bulletList', 'orderedList', 'blockquote', 'codeBlock', 'horizontalRule', 'table', 'image'}
CHILDREN = {
    'doc': BLOCKS,
    'paragraph': {'text', 'hardBreak'}, 'heading': {'text', 'hardBreak'}, 'codeBlock': {'text'},
    'bulletList': {'listItem'}, 'orderedList': {'listItem'},
    # Match Tiptap's `paragraph block*` and `block+` containers. Inserting a
    # table while a list is active produces a table inside a list item.
    'listItem': BLOCKS,
    'blockquote': BLOCKS,
    'table': {'tableRow'}, 'tableRow': {'tableCell', 'tableHeader'},
    'tableCell': BLOCKS,
    'tableHeader': BLOCKS,
    'text': set(), 'hardBreak': set(), 'horizontalRule': set(), 'image': set(),
}


def invalid(message='笔记格式不完整，请重试或恢复最近保存的草稿。'):
    raise HTTPException(422, message)


def checked_content(value, asset_ids):
    if not isinstance(value, dict) or value.get('type') != 'doc':
        invalid()
    if len(json.dumps(value, ensure_ascii=False).encode()) > 2_000_000:
        invalid('笔记内容超过 2 MB，请拆分为多篇；图片单独保存，不计入正文大小。')
    count = 0
    def walk(node, depth=0):
        nonlocal count
        count += 1
        if count > 12000 or depth > 18 or not isinstance(node, dict) or node.get('type') not in CHILDREN:
            invalid('笔记内容过长或嵌套过深，请分段整理。')
        kind = node['type']; result = {'type': kind}
        if kind == 'text':
            text = node.get('text')
            if not isinstance(text, str) or not text or any(ord(char) < 32 and char not in '\n\t' for char in text):
                invalid()
            result['text'] = text
            marks = []
            for mark in node.get('marks', []):
                if not isinstance(mark, dict) or mark.get('type') not in ('bold','italic','strike','underline','code','link'):
                    invalid()
                clean = {'type': mark['type']}
                if mark['type'] == 'link':
                    href = (mark.get('attrs') or {}).get('href', '')
                    if not isinstance(href, str) or len(href) > 2048 or re.search(r'[\x00-\x20]', href) or urlsplit(href).scheme.lower() not in ('https','http','mailto'):
                        invalid('链接只支持 http、https 或邮件地址。')
                    clean['attrs'] = {'href': href}
                marks.append(clean)
            if marks: result['marks'] = marks
        attrs = node.get('attrs') or {}
        if not isinstance(attrs, dict): invalid()
        if kind == 'heading':
            level = attrs.get('level', 1)
            if level not in (1,2,3): invalid()
            result['attrs'] = {'level': level}
        if kind == 'orderedList':
            start = attrs.get('start', 1)
            if not isinstance(start, int) or not 1 <= start <= 10000: invalid()
            result['attrs'] = {'start': start}
        if kind == 'image':
            asset = attrs.get('assetId')
            if asset not in asset_ids: invalid('图片尚未保存，或不属于这篇笔记。请重试上传后再保存。')
            width = attrs.get('width', 80)
            if not isinstance(width, (int,float)) or not 20 <= width <= 100: invalid('图片宽度应为正文宽度的 20% 至 100%。')
            result['attrs'] = {'assetId': asset, 'width': round(width), 'caption': '', 'alt': '', 'ocrText': ''}
            for key, limit in (('caption',1000),('alt',500),('ocrText',20000)):
                text = attrs.get(key) or ''
                if not isinstance(text,str) or len(text)>limit or any(ord(char)<32 and char not in '\n\t' for char in text): invalid('图片说明或识别文字过长，或含有无效控制字符。')
                result['attrs'][key] = text
        if kind in ('tableCell','tableHeader'):
            spans = {key: attrs.get(key,1) for key in ('colspan','rowspan')}
            if any(not isinstance(n,int) or n<1 or n>12 for n in spans.values()): invalid('表格合并范围过大。')
            result['attrs'] = spans
        content = node.get('content', [])
        if not isinstance(content,list) or any(not isinstance(child,dict) or child.get('type') not in CHILDREN[kind] for child in content): invalid()
        if kind in ('bulletList','orderedList','listItem','blockquote','table','tableRow','tableCell','tableHeader') and not content: invalid()
        if kind=='listItem' and content[0]['type']!='paragraph':invalid('列表项需以正文段落开头，请保留内容并重新整理列表。')
        if kind=='table' and len(content)>100: invalid('单个表格最多 100 行，请拆分表格。')
        if content: result['content']=[walk(child,depth+1) for child in content]
        if kind=='tableRow' and sum(cell.get('attrs',{}).get('colspan',1) for cell in result['content'])>12: invalid('单个表格最多 12 列。')
        if kind=='table': table_grid(result)
        return result
    return walk(value)


def image_ids(content):
    result = []
    def walk(node):
        if node['type']=='image' and node['attrs']['assetId'] not in result: result.append(node['attrs']['assetId'])
        for child in node.get('content',[]): walk(child)
    walk(content)
    return result


def plain_text(content):
    def walk(node):
        if node['type']=='text': return node['text']
        if node['type']=='image': return '\n'.join(node['attrs'].get(key,'') for key in ('caption','ocrText'))
        if node['type']=='hardBreak': return '\n'
        separator='' if node['type'] in ('paragraph','heading') else '\n'
        return separator.join(walk(child) for child in node.get('content',[]))
    return walk(content)


def table_grid(node):
    rows = node.get('content',[]); occupied={}; cells=[]; width=0
    for row_index,row in enumerate(rows):
        column=0
        for cell in row['content']:
            while (row_index,column) in occupied: column+=1
            attrs=cell.get('attrs',{}); height=attrs.get('rowspan',1); span=attrs.get('colspan',1)
            if column+span>12 or row_index+height>len(rows): invalid('表格合并范围与行列不一致，请调整表格。')
            for r in range(row_index,row_index+height):
                for c in range(column,column+span):
                    if (r,c) in occupied: invalid('表格单元格发生重叠，请调整表格。')
                    occupied[r,c]=True
            cells.append((row_index,column,height,span,cell));column+=span;width=max(width,column)
    return max(1,width),cells


def markdown(title, content):
    def escape(text): return re.sub(r'([\\`*_{}\[\]<>#|])',r'\\\1',text)
    def walk(node,depth=0):
        kind=node['type'];children=node.get('content',[])
        if kind=='text':
            text=escape(node['text'])
            for mark in node.get('marks',[]):
                op=mark['type']
                if op=='link': text='['+text+']('+mark['attrs']['href'].replace('(','%28').replace(')','%29')+')'
                elif op in ('bold','italic','strike','code'): token={'bold':'**','italic':'*','strike':'~~','code':'`'}[op];text=token+text+token
                elif op=='underline':text='<u>'+text+'</u>'
            return text
        if kind=='hardBreak':return '  \n'
        if kind=='horizontalRule':return '\n---\n'
        if kind=='image':
            a=node['attrs'];result=f'![{escape(a.get("alt") or a.get("caption") or "图片") }](images/{a["assetId"]}.png)'
            if a.get('caption'):result+='\n\n'+escape(a['caption'])
            if a.get('ocrText'):result+='\n\n图片文字（机器识别 / 人工校正，请核对）：\n\n'+escape(a['ocrText'])
            return result+'\n\n'
        if kind=='table':
            width,cells=table_grid(node);grid=[['']*width for _ in children]
            for row,col,_,_,cell in cells:
                text=' '.join(walk(c,depth) for c in cell.get('content',[])).strip().replace('\n','<br>')
                # Nested tables become readable cell text in portable GFM. Their
                # separators must not accidentally create extra outer columns.
                grid[row][col]=re.sub(r'(?<!\\)\|',r'\|',text)
            return '\n'.join(['| '+' | '.join(grid[0])+' |','| '+' | '.join(['---']*width)+' |',*['| '+' | '.join(row)+' |' for row in grid[1:]]])+'\n\n'
        if kind in ('bulletList','orderedList'):
            rows=[]
            for index,child in enumerate(children):
                prefix='- ' if kind=='bulletList' else str(node.get('attrs',{}).get('start',1)+index)+'. '
                body=walk(child,depth+1).strip().splitlines() or ['']
                rows.append('  '*depth+prefix+body[0]+'\n'+'\n'.join('  '*(depth+1)+line for line in body[1:]))
            return '\n'.join(rows)+'\n\n'
        text=''.join(walk(child,depth) for child in children)
        if kind=='heading':return '#'*node['attrs']['level']+' '+text+'\n\n'
        if kind=='blockquote':return '\n'.join('> '+line for line in text.strip().splitlines())+'\n\n'
        if kind=='codeBlock':return '```\n'+text.replace('```','` ` `')+'\n```\n\n'
        return text+ ('\n\n' if kind=='paragraph' else '')
    return '# '+escape(title)+'\n\n'+walk(content).strip()+'\n'


def word_document(title, content, images, revision=1):
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    doc=Document();section=doc.sections[0]
    doc.core_properties.title=title
    doc.core_properties.revision=revision
    section.page_width=Inches(8.27);section.page_height=Inches(11.69)
    section.top_margin=section.bottom_margin=Inches(.72);section.left_margin=section.right_margin=Inches(.78)
    normal=doc.styles['Normal'];normal.font.name='Microsoft YaHei';normal.font.size=Pt(10.5)
    normal.element.rPr.rFonts.set(qn('w:eastAsia'),'Microsoft YaHei')
    normal.paragraph_format.line_spacing=1.35;normal.paragraph_format.space_after=Pt(7)
    for name in ('Title','Heading 1','Heading 2','Heading 3'):
        style=doc.styles[name];style.font.name='Microsoft YaHei';style.font.color.rgb=RGBColor.from_string('214C67')
        style.element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'Microsoft YaHei')
    doc.add_heading(title,0)
    def inline(paragraph, children):
        for node in children:
            if node['type']=='hardBreak':paragraph.add_run().add_break();continue
            run=paragraph.add_run(node.get('text',''));marks={mark['type']:mark for mark in node.get('marks',[])}
            run.bold='bold' in marks;run.italic='italic' in marks;run.underline='underline' in marks;run.font.strike='strike' in marks
            if 'code' in marks:run.font.name='Consolas'
            if 'link' in marks:
                link=OxmlElement('w:hyperlink');link.set(qn('r:id'),paragraph.part.relate_to(marks['link']['attrs']['href'],RT.HYPERLINK,is_external=True));link.append(run._r);paragraph._p.append(link)
    def blocks(parent,nodes,depth=0,list_style=None,available_width=6.7):
        for node in nodes:
            kind=node['type'];children=node.get('content',[])
            if kind in ('paragraph','heading','codeBlock'):
                style=('Heading '+str(node['attrs']['level'])) if kind=='heading' else list_style or 'Normal'
                paragraph=parent.add_paragraph(style=style);inline(paragraph,children)
                if depth:paragraph.paragraph_format.left_indent=Inches(.22*depth)
                if kind=='codeBlock':
                    for run in paragraph.runs:run.font.name='Consolas';run.font.size=Pt(9)
            elif kind in ('bulletList','orderedList'):
                for item in children:blocks(parent,item['content'],depth+1,'List Bullet' if kind=='bulletList' else 'List Number',available_width-.22)
            elif kind=='blockquote':blocks(parent,children,depth+1,available_width=available_width-.22)
            elif kind=='horizontalRule':parent.add_paragraph('────────────────────────────────')
            elif kind=='image':
                a=node['attrs'];paragraph=parent.add_paragraph();paragraph.alignment=1
                from PIL import Image
                with Image.open(io.BytesIO(images[a['assetId']])) as picture:
                    width=min(max(.3,available_width)*a['width']/100,9*picture.width/picture.height)
                paragraph.add_run().add_picture(io.BytesIO(images[a['assetId']]),width=Inches(width))
                if a.get('caption'):
                    caption=parent.add_paragraph(a['caption']);caption.alignment=1
                    for run in caption.runs:run.font.size=Pt(9);run.font.color.rgb=RGBColor.from_string('526A80')
                if a.get('ocrText'):parent.add_paragraph('图片文字（机器识别 / 人工校正，请核对）：\n'+a['ocrText'])
            elif kind=='table':
                width,cells=table_grid(node);table=parent.add_table(rows=len(children),cols=width);table.style='Table Grid'
                for row,col,height,span,cell in cells:
                    target=table.cell(row,col)
                    if height>1 or span>1:target=target.merge(table.cell(row+height-1,col+span-1))
                    target.text='';blocks(target,cell['content'],available_width=available_width*span/width-.18)
                    if len(target.paragraphs)>1 and not target.paragraphs[0].text:target.paragraphs[0]._element.getparent().remove(target.paragraphs[0]._element)
                    if cell['type']=='tableHeader':
                        shading=OxmlElement('w:shd');shading.set(qn('w:fill'),'E7F2F7');target._tc.get_or_add_tcPr().append(shading)
                        for paragraph in target.paragraphs:
                            for run in paragraph.runs:run.bold=True
                if table.rows:
                    repeat=OxmlElement('w:tblHeader');table.rows[0]._tr.get_or_add_trPr().append(repeat)
    blocks(doc,content.get('content',[]))
    output=io.BytesIO();doc.save(output);return output.getvalue()
