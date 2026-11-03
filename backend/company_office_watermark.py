"""Watermark Office packages without changing their document format or cell data."""
import hashlib
import io
import posixpath
import re
import zipfile

from lxml import etree as E

from company_watermark import WatermarkError, convert_office, watermark_layer

NS = {
    'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'wp':'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
    'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
    'pic':'http://schemas.openxmlformats.org/drawingml/2006/picture',
    'p':'http://schemas.openxmlformats.org/presentationml/2006/main',
    's':'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'rel':'http://schemas.openxmlformats.org/package/2006/relationships',
    'ct':'http://schemas.openxmlformats.org/package/2006/content-types',
}


def q(name):
    prefix, local = name.split(':')
    return '{' + NS[prefix] + '}' + local


def child(parent, name, attributes=None, text=None):
    node = E.SubElement(parent, q(name), attributes or {})
    node.text = text
    return node


class Package:
    def __init__(self, data, identity):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 10000 or sum(info.file_size for info in infos) > 256 * 1024 * 1024:
                raise WatermarkError('Office 包内容过大，无法生成水印副本。', 422)
            if len({info.filename for info in infos}) != len(infos):
                raise WatermarkError('Office 包存在重复部件，无法安全生成水印副本。', 422)
            self.parts = {info.filename: archive.read(info) for info in infos}
        self.identity = identity
        self.token = hashlib.sha256(identity.trace_id.encode()).hexdigest()[:24]
        self.types = self.xml('[Content_Types].xml')
        self.counter = 0

    def xml(self, name):
        return E.fromstring(self.parts[name], parser=E.XMLParser(resolve_entities=False, no_network=True))

    def save_xml(self, name, node):
        self.parts[name] = E.tostring(node, encoding='UTF-8', xml_declaration=True, standalone=True)

    def type(self, name, mime):
        if not any(node.get('PartName') == '/' + name for node in self.types):
            child(self.types, 'ct:Override', {'PartName':'/' + name, 'ContentType':mime})

    def relate(self, part, kind, target):
        name = posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels')
        root = self.xml(name) if name in self.parts else E.Element(q('rel:Relationships'), nsmap={None:NS['rel']})
        used = {node.get('Id') for node in root}
        self.counter += 1
        rid = 'rIdCKB' + self.token + str(self.counter)
        while rid in used:
            self.counter += 1; rid = 'rIdCKB' + self.token + str(self.counter)
        child(root, 'rel:Relationship', {'Id':rid, 'Type':NS['r'] + '/' + kind,
            'Target':posixpath.relpath(target, posixpath.dirname(part))})
        self.save_xml(name, root)
        return rid

    def target(self, part, rid):
        name = posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels')
        for relation in self.xml(name):
            if relation.get('Id') == rid and relation.get('TargetMode') != 'External':
                path = posixpath.normpath(posixpath.join(posixpath.dirname(part), relation.get('Target',''))).lstrip('/')
                if path.startswith('../') or path not in self.parts:
                    break
                return path
        raise WatermarkError('Office 部件关系异常，无法安全生成水印副本。', 422)

    def image(self, folder, size=(1000,1000), footer=False):
        name = folder + '/media/ckb-watermark-' + self.token + '.png'
        if name not in self.parts:
            output = io.BytesIO(); watermark_layer(size, self.identity, footer=footer).save(output, format='PNG')
            self.parts[name] = output.getvalue()
            self.type(name, 'image/png')
        return name

    def finish(self):
        self.save_xml('[Content_Types].xml', self.types)
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in self.parts.items():
                archive.writestr(name, payload)
        return output.getvalue()


def picture(parent, rid, width, height, identity, identifier, word=False):
    if word:
        drawing = child(parent, 'w:drawing')
        anchor = child(drawing, 'wp:anchor', {'distT':'0','distB':'0','distL':'0','distR':'0',
            'simplePos':'0','relativeHeight':'251658240','behindDoc':'0','locked':'0','layoutInCell':'0','allowOverlap':'1'})
        child(anchor, 'wp:simplePos', {'x':'0','y':'0'})
        for tag in ('wp:positionH','wp:positionV'):
            position = child(anchor, tag, {'relativeFrom':'page'}); child(position, 'wp:align', text='center')
        child(anchor, 'wp:extent', {'cx':str(width),'cy':str(height)})
        child(anchor, 'wp:wrapNone')
        child(anchor, 'wp:docPr', {'id':str(identifier),'name':'CKB watermark ' + identity.trace_id,'descr':' | '.join(identity.lines)})
        frame = child(anchor, 'wp:cNvGraphicFramePr'); child(frame, 'a:graphicFrameLocks', {'noChangeAspect':'1'})
        graphic = child(anchor, 'a:graphic'); data = child(graphic, 'a:graphicData', {'uri':NS['pic']})
        pic = child(data, 'pic:pic')
        nonvisual = child(pic, 'pic:nvPicPr')
        child(nonvisual, 'pic:cNvPr', {'id':'0','name':'Personal watermark'}); child(nonvisual, 'pic:cNvPicPr')
        fill = child(pic, 'pic:blipFill')
        shape = child(pic, 'pic:spPr')
    else:
        pic = child(parent, 'p:pic')
        nonvisual = child(pic, 'p:nvPicPr')
        child(nonvisual, 'p:cNvPr', {'id':str(identifier),'name':'CKB watermark ' + identity.trace_id,'descr':' | '.join(identity.lines)})
        child(nonvisual, 'p:cNvPicPr'); child(nonvisual, 'p:nvPr')
        fill = child(pic, 'p:blipFill'); shape = child(pic, 'p:spPr')
    child(fill, 'a:blip', {q('r:embed'):rid})
    stretch = child(fill, 'a:stretch'); child(stretch, 'a:fillRect')
    transform = child(shape, 'a:xfrm'); child(transform, 'a:off', {'x':'0','y':'0'})
    child(transform, 'a:ext', {'cx':str(width),'cy':str(height)})
    geometry = child(shape, 'a:prstGeom', {'prst':'rect'}); child(geometry, 'a:avLst')


def mark_word(package, progress):
    document = package.xml('word/document.xml')
    sections = list(document.iter(q('w:sectPr')))
    if not sections:
        raise WatermarkError('Word 文档结构不支持安全水印。', 422)
    active, stamped = {}, set()
    used_ids = {int(node.get('id')) for name in package.parts
        if re.fullmatch(r'word/(?:document|header[^/]*|footer[^/]*)\.xml',name)
        for node in package.xml(name).iter(q('wp:docPr')) if node.get('id','').isdigit()}
    next_id = 1000000000
    image = package.image('word')
    for number, section in enumerate(sections, 1):
        refs = {ref.get(q('w:type')):ref for ref in section.findall(q('w:headerReference'))}
        for kind in ('default','first','even'):
            if kind in refs:
                active[kind] = package.target('word/document.xml', refs[kind].get(q('r:id')))
            elif kind not in active:
                name = 'word/headerCKB' + package.token + kind + '.xml'
                header = E.Element(q('w:hdr'), nsmap={prefix:NS[prefix] for prefix in ('w','r','wp','a','pic')})
                child(header, 'w:p'); package.save_xml(name, header)
                package.type(name, 'application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml')
                rid = package.relate('word/document.xml', 'header', name)
                section.insert(0, E.Element(q('w:headerReference'), {q('w:type'):kind,q('r:id'):rid}))
                active[kind] = name
            name = active[kind]
            if name not in stamped:
                header = package.xml(name)
                for drawing in list(header.iter(q('w:drawing'))):
                    tag = drawing.find('.//' + q('wp:docPr'))
                    if tag is not None and tag.get('name','').startswith('CKB watermark '):
                        drawing.getparent().remove(drawing)
                paragraph = next(header.iter(q('w:p')), None)
                if paragraph is None: paragraph = child(header, 'w:p')
                run = child(paragraph, 'w:r')
                rid = package.relate(name, 'image', image)
                while next_id in used_ids: next_id += 1
                picture(run, rid, 5486400, 5486400, package.identity, next_id, word=True)
                used_ids.add(next_id); next_id += 1
                package.save_xml(name, header); stamped.add(name)
        if progress: progress('stamping', number, len(sections))
    package.save_xml('word/document.xml', document)


def mark_slides(package, progress):
    presentation = package.xml('ppt/presentation.xml')
    size = presentation.find(q('p:sldSz'))
    width, height = (int(size.get('cx')), int(size.get('cy'))) if size is not None else (9144000,6858000)
    image = package.image('ppt', size=(1280, max(16, min(1800, int(1280 * height / width)))), footer=True)
    slides = [name for name in package.parts if re.fullmatch(r'ppt/slides/slide\d+\.xml', name)]
    if not slides: raise WatermarkError('PPT 没有可加水印的页面。', 422)
    for number, name in enumerate(slides, 1):
        slide = package.xml(name); tree = slide.find('.//' + q('p:spTree'))
        if tree is None: raise WatermarkError('PPT 页面结构异常。', 422)
        for old in list(tree.findall(q('p:pic'))):
            tag = old.find('.//' + q('p:cNvPr'))
            if tag is not None and tag.get('name','').startswith('CKB watermark '): tree.remove(old)
        ids = [int(node.get('id')) for node in tree.iter(q('p:cNvPr')) if node.get('id','').isdigit()]
        picture(tree, package.relate(name,'image',image), width, height, package.identity, max(ids,default=0)+1)
        package.save_xml(name, slide)
        if progress: progress('stamping', number, len(slides))


def ordered_insert(sheet, node, later):
    index = next((i for i, item in enumerate(sheet) if E.QName(item).localname in later), len(sheet))
    sheet.insert(index, node)


def footer_sections(value):
    parts, active, index = {'L':'','C':'','R':''}, 'C', 0
    while index < len(value):
        pair = value[index:index+2]
        if pair == '&&':
            parts[active] += pair; index += 2
        elif pair == '&"':
            end = value.find('"',index+2)
            if end < 0: raise WatermarkError('Excel 页脚字体格式异常。',422)
            parts[active] += value[index:end+1]; index = end+1
        elif len(pair)==2 and pair[0]=='&' and pair[1] in parts:
            active = pair[1]; index += 2
        else:
            parts[active] += value[index]; index += 1
    return parts


def mark_sheets(package, progress):
    sheets = [name for name in package.parts if re.fullmatch(r'xl/worksheets/sheet\d+\.xml', name)]
    if not sheets: raise WatermarkError('Excel 没有可加水印的工作表。', 422)
    default_image = package.image('xl', size=(1200,1000))
    identity = package.identity
    safe = lambda text: text.replace('&','&&').replace('\r',' ').replace('\n',' ')
    stamp = {'L':'观复下载水印 · '+safe(identity.username),'C':identity.timestamp+' UTC','R':'ID '+identity.trace_id}
    for number, name in enumerate(sheets, 1):
        sheet = package.xml(name); image = default_image
        background = sheet.find(q('s:picture'))
        if background is not None and not posixpath.basename(package.target(name,background.get(q('r:id')))).startswith('ckb-watermark-'):
            from PIL import Image
            existing = package.target(name, background.get(q('r:id')))
            with Image.open(io.BytesIO(package.parts[existing])) as source:
                marked = Image.alpha_composite(source.convert('RGBA'),watermark_layer(source.size,identity,footer=False))
                output=io.BytesIO();marked.save(output,format='PNG')
            image = 'xl/media/ckb-background-' + package.token + str(number) + '.png'
            package.parts[image]=output.getvalue();package.type(image,'image/png')
        else:
            background = E.Element(q('s:picture'))
            ordered_insert(sheet,background,{'oleObjects','controls','webPublishItems','tableParts','extLst'})
        background.set(q('r:id'),package.relate(name,'image',image))
        footer = sheet.find(q('s:headerFooter'))
        if footer is None:
            footer = E.Element(q('s:headerFooter'))
            ordered_insert(sheet,footer,{'rowBreaks','colBreaks','customProperties','cellWatches','ignoredErrors','smartTags','drawing','legacyDrawing','legacyDrawingHF','picture','oleObjects','controls','webPublishItems','tableParts','extLst'})
        for field in ('oddFooter','evenFooter','firstFooter'):
            entry = footer.find(q('s:' + field))
            if entry is None:
                entry = E.Element(q('s:' + field))
                order = ['oddHeader','oddFooter','evenHeader','evenFooter','firstHeader','firstFooter']
                ordered_insert(footer,entry,set(order[order.index(field)+1:]))
            original = footer_sections(entry.text or '')
            marker = '&K435C79&7 '
            if '观复下载水印 · ' in original['L'].split('\n')[-1] and 'ID ' in original['R'].split('\n')[-1]:
                original = {zone:value.rsplit('\n',1)[0] if '\n' in value else '' for zone,value in original.items()}
            value = ''.join('&'+zone+original[zone]+ ('\n' if original[zone] else '') + '&K435C79&7 '+stamp[zone] for zone in ('L','C','R'))
            if len(value) > 255:
                raise WatermarkError('Excel 原页脚过长，无法保留原内容并添加身份标记，请联系管理员。', 422)
            entry.text = value
        package.save_xml(name,sheet)
        if progress: progress('stamping',number,len(sheets))


def mark_office(data, fmt, identity, directory, progress=None):
    if fmt in ('DOC','XLS','PPT'):
        modern = {'DOC':'docx','XLS':'xlsx','PPT':'pptx'}[fmt]
        if progress: progress('converting',0,0)
        first=directory/'modern';first.mkdir()
        converted = convert_office(data,fmt,modern,first)
        marked,_,_ = mark_office(converted,modern.upper(),identity,directory,progress)
        second=directory/'legacy';second.mkdir()
        if progress: progress('converting',0,0)
        result=convert_office(marked,modern.upper(),fmt.lower(),second)
        return result,{'DOC':'application/msword','XLS':'application/vnd.ms-excel','PPT':'application/vnd.ms-powerpoint'}[fmt],fmt.lower()
    package = Package(data,identity)
    {'DOCX':mark_word,'XLSX':mark_sheets,'PPTX':mark_slides}[fmt](package,progress)
    return package.finish(),{'DOCX':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'XLSX':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'PPTX':'application/vnd.openxmlformats-officedocument.presentationml.presentation'}[fmt],fmt.lower()


def mark_text(data, fmt, identity):
    if len(data) > 2_000_000:
        raise WatermarkError('文字资料过大，请拆分后下载（最多 2 MB 文本）。',422)
    bom, encoding, body = b'', 'utf-8', data
    for prefix, codec in ((b'\xff\xfe','utf-16-le'),(b'\xfe\xff','utf-16-be'),(b'\xef\xbb\xbf','utf-8')):
        if data.startswith(prefix): bom,encoding,body=prefix,codec,data[len(prefix):];break
    try: body.decode(encoding)
    except UnicodeError:
        encoding='gb18030'
        try: body.decode(encoding)
        except UnicodeError: raise WatermarkError('文字编码无法识别，无法安全添加身份标记。',422) from None
    linebreak='\r\n' if '\r\n' in body.decode(encoding) else '\n'
    marker=linebreak.join(('> ' if fmt=='MD' else '') + line for line in identity.lines)
    prefix=(marker+linebreak*2).encode(encoding,errors='xmlcharrefreplace')
    suffix=(linebreak*2+marker+linebreak).encode(encoding,errors='xmlcharrefreplace')
    return bom+prefix+body+suffix, encoding
