import io
import os
import re
import shutil
import wave
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

import company_watermark as wm

IDENTITY = wm.ExportIdentity('中文账号 QA', 17, '2026-11-03 12:34:56', '0123456789abcdef')


def test_pdf_stamps_every_page_preserving_rotation_crop_and_text():
    pdf = PdfWriter()
    pdf.add_blank_page(width=300, height=450)
    page = pdf.add_blank_page(width=500, height=300)
    page.cropbox.lower_left = (40, 20); page.cropbox.upper_right = (460, 280)
    page.rotate(90)
    source = io.BytesIO(); pdf.write(source)
    result, mime, name = wm.export_copy(source.getvalue(), 'PDF', '资料.pdf', IDENTITY)
    reader = PdfReader(io.BytesIO(result))
    assert len(reader.pages) == 2 and all('/XObject' in page['/Resources'] for page in reader.pages)
    assert reader.metadata['/DownloadAccount'] == IDENTITY.username
    assert reader.pages[1].rotation == 0
    assert mime == 'application/pdf' and name.endswith('.pdf')


def test_long_pdf_reuses_watermark_stream_and_reports_real_page_progress(monkeypatch):
    source = PdfWriter()
    for _ in range(178):
        source.add_blank_page(width=595, height=842)
    data = io.BytesIO(); source.write(data)
    calls, progress = [], []
    real_layer = wm.watermark_layer
    def layer(*args):
        calls.append(args)
        return real_layer(*args)
    monkeypatch.setattr(wm, 'watermark_layer', layer)
    result = wm.stamp_pdf(data.getvalue(), IDENTITY, lambda *args: progress.append(args))
    reader = PdfReader(io.BytesIO(result))
    assert len(reader.pages) == 178 and len(calls) == 1
    images = {page['/Resources']['/XObject'][name].indirect_reference.idnum for page in reader.pages for name in page['/Resources']['/XObject']}
    assert len(images) == 1 and len(result) < 1_000_000
    assert progress[0] == ('stamping', 0, 178) and progress[-1] == ('packaging', 178, 178)
    assert [step[1] for step in progress if step[0] == 'stamping'] == list(range(179))


def test_image_watermark_changes_pixels_and_keeps_source_dimensions():
    source = io.BytesIO(); Image.new('RGB', (600,400), 'white').save(source, format='PNG')
    result, mime, name = wm.export_copy(source.getvalue(), 'PNG', '图片.png', IDENTITY)
    image = Image.open(io.BytesIO(result)).convert('RGB')
    assert image.size == (600,400) and image.getpixel((10,390)) != (255,255,255)
    assert result != source.getvalue() and mime == 'image/png'


def test_missing_converter_and_invalid_pdf_fail_closed(monkeypatch):
    monkeypatch.delenv('COMPANY_KNOWLEDGE_OFFICE_BINARY', raising=False)
    monkeypatch.setattr(wm.shutil, 'which', lambda _:None)
    with pytest.raises(wm.WatermarkError, match='Office'):
        wm.export_copy(b'original office', 'DOC', 'a.doc', IDENTITY)
    with pytest.raises(wm.WatermarkError):
        wm.export_copy(b'not PDF', 'PDF', 'a.pdf', IDENTITY)
    with pytest.raises(wm.WatermarkError, match='2 MB'):
        wm.export_copy(b'a' * 2_000_001, 'TXT', 'large.txt', IDENTITY)


def test_native_spreadsheet_preserves_cells_formulas_and_adds_view_and_print_markers():
    from openpyxl import Workbook, load_workbook
    import zipfile
    workbook = Workbook(); workbook.active.append(['Revenue', 12345]);workbook.active['B2']='=B1+1'
    source = io.BytesIO(); workbook.save(source)
    result, mime, name = wm.export_copy(source.getvalue(), 'XLSX', '收入.xlsx', IDENTITY)
    book=load_workbook(io.BytesIO(result))
    assert book.active['A1'].value=='Revenue' and book.active['B1'].value==12345 and book.active['B2'].value=='=B1+1'
    assert IDENTITY.username in book.active.oddFooter.left.text and IDENTITY.trace_id in book.active.oddFooter.right.text
    assert name.endswith('.xlsx') and 'spreadsheetml' in mime
    with zipfile.ZipFile(io.BytesIO(result)) as archive:
        assert any('ckb-watermark-' in name for name in archive.namelist())
    other=wm.ExportIdentity('next-user',18,IDENTITY.timestamp,'second-trace')
    updated,_,_=wm.export_copy(result,'XLSX','again.xlsx',other)
    again=load_workbook(io.BytesIO(updated))
    assert 'next-user' in again.active.oddFooter.left.text and IDENTITY.username not in again.active.oddFooter.left.text
    assert again.active['B2'].value=='=B1+1'


def test_native_text_preserves_extension_encoding_and_original_body_bytes():
    source = b'\xff\xfe' + 'Original text'.encode('utf-16-le')
    result,mime,name=wm.export_copy(source,'TXT','notes.txt',IDENTITY)
    assert result.startswith(b'\xff\xfe') and source[2:] in result
    assert IDENTITY.username in result[2:].decode('utf-16-le')
    assert name.endswith('.txt') and mime=='text/plain; charset=utf-16-le'


def test_native_word_keeps_body_and_existing_header_with_all_header_variants():
    import zipfile
    from lxml import etree as E
    from company_office_watermark import NS
    contents={'[Content_Types].xml':('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/></Types>'),
        '_rels/.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="root" Type="'+NS['r']+'/officeDocument" Target="word/document.xml"/></Relationships>',
        'word/document.xml':'<w:document xmlns:w="'+NS['w']+'" xmlns:r="'+NS['r']+'"><w:body><w:p><w:r><w:t>Keep original paragraph</w:t></w:r></w:p><w:sectPr><w:headerReference w:type="default" r:id="brand"/><w:titlePg/></w:sectPr></w:body></w:document>',
        'word/_rels/document.xml.rels':'<Relationships xmlns="'+NS['rel']+'"><Relationship Id="brand" Type="'+NS['r']+'/header" Target="header1.xml"/></Relationships>',
        'word/header1.xml':'<w:hdr xmlns:w="'+NS['w']+'"><w:p><w:r><w:t>Keep company header</w:t></w:r></w:p></w:hdr>',
        'custom/unchanged.bin':'keep these bytes'}
    source=io.BytesIO()
    with zipfile.ZipFile(source,'w') as archive:
        for name,value in contents.items():archive.writestr(name,value)
    result,mime,name=wm.export_copy(source.getvalue(),'DOCX','report.docx',IDENTITY)
    assert name.endswith('.docx') and 'wordprocessingml' in mime
    with zipfile.ZipFile(io.BytesIO(result)) as archive:
        assert archive.read('custom/unchanged.bin')==b'keep these bytes'
        document=E.fromstring(archive.read('word/document.xml'))
        assert document.xpath('//w:body//w:t/text()',namespaces=NS)==['Keep original paragraph']
        headers=[name for name in archive.namelist() if re.fullmatch(r'word/header.*\.xml',name)]
        assert len(headers)==3
        for header in headers:
            xml=E.fromstring(archive.read(header));assert xml.find('.//{'+NS['wp']+'}anchor') is not None
        assert 'Keep company header' in archive.read('word/header1.xml').decode()
    other=wm.ExportIdentity('next-user',18,IDENTITY.timestamp,'second-trace')
    updated,_,_=wm.export_copy(result,'DOCX','again.docx',other)
    with zipfile.ZipFile(io.BytesIO(updated)) as archive:
        for header in headers:
            xml=E.fromstring(archive.read(header))
            tags=xml.findall('.//{'+NS['wp']+'}docPr')
            assert len(tags)==1 and 'next-user' in tags[0].get('descr')


def test_native_slides_keep_existing_shapes_and_add_overlay_to_each_slide():
    import zipfile
    from lxml import etree as E
    from company_office_watermark import NS
    source=io.BytesIO()
    with zipfile.ZipFile(source,'w') as archive:
        archive.writestr('[Content_Types].xml','<Types xmlns="'+NS['ct']+'"/>')
        archive.writestr('ppt/presentation.xml','<p:presentation xmlns:p="'+NS['p']+'"><p:sldSz cx="9144000" cy="6858000"/></p:presentation>')
        for number in (1,2):
            archive.writestr(f'ppt/slides/slide{number}.xml','<p:sld xmlns:p="'+NS['p']+'" xmlns:a="'+NS['a']+'"><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Keep original slide</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>')
    result,mime,name=wm.export_copy(source.getvalue(),'PPTX','slides.pptx',IDENTITY)
    assert name.endswith('.pptx') and 'presentationml' in mime
    with zipfile.ZipFile(io.BytesIO(result)) as archive:
        for number in (1,2):
            slide=E.fromstring(archive.read(f'ppt/slides/slide{number}.xml'))
            assert slide.xpath('//a:t/text()',namespaces=NS)==['Keep original slide']
            assert slide.find('.//{'+NS['p']+'}pic') is not None


def test_real_audio_video_outputs_contain_marks_and_playable_streams(tmp_path):
    source = io.BytesIO()
    with wave.open(source, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000); audio.writeframes(b'\0\0' * 8000)
    data, mime, name = wm.export_copy(source.getvalue(), 'WAV', '录音.wav', IDENTITY)
    assert mime == 'audio/mpeg' and name.endswith('.mp3') and data != source.getvalue()
    (tmp_path / 'audio.mp3').write_bytes(data)
    binary = wm.ffmpeg_binary()
    wm.run([binary,'-v','error','-i',str(tmp_path/'audio.mp3'),'-f','null','-'])
    wm.run([binary,'-y','-f','lavfi','-i','color=c=white:s=320x240:d=1','-c:v','libx264',str(tmp_path/'input.mp4')])
    data, mime, name = wm.export_copy((tmp_path/'input.mp4').read_bytes(),'MP4','视频.mp4',IDENTITY)
    assert mime == 'video/mp4' and name.endswith('.mp4')
    (tmp_path/'output.mp4').write_bytes(data)
    wm.run([binary,'-y','-i',str(tmp_path/'output.mp4'),'-frames:v','1','-update','1',str(tmp_path/'frame.png')])
    image = Image.open(tmp_path/'frame.png').convert('RGB')
    assert image.size == (320,240) and image.getpixel((10,230)) != (255,255,255)
