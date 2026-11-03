import io
import os
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


@pytest.mark.skipif(not os.environ.get('COMPANY_KNOWLEDGE_OFFICE_BINARY') and not shutil.which('soffice'), reason='requires configured LibreOffice')
def test_real_spreadsheet_conversion_preserves_cells():
    from openpyxl import Workbook
    workbook = Workbook(); workbook.active.append(['Revenue', 12345])
    source = io.BytesIO(); workbook.save(source)
    result, mime, name = wm.export_copy(source.getvalue(), 'XLSX', '收入.xlsx', IDENTITY)
    reader = PdfReader(io.BytesIO(result))
    assert 'Revenue' in reader.pages[0].extract_text() and '12345' in reader.pages[0].extract_text()
    assert reader.metadata['/WatermarkTrace'] == IDENTITY.trace_id


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
