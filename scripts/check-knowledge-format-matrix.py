"""Real conversion/codec acceptance in an isolated PostgreSQL restore only.

Called by deployment preflight with a TestClient and a temporary object store.
Artifacts contain synthetic text/media and account-marked preview derivatives.
"""
import io
import json
import math
from pathlib import Path
import struct
import subprocess
import time
import uuid
import wave


def run_matrix(client, headers, factory, artifact_dir):
    from docx import Document
    from openpyxl import Workbook
    from PIL import Image
    from reportlab.pdfgen import canvas
    import company_workspace as ws
    from company_catalog import CompanyDocument, document_store
    from company_watermark import ffmpeg_binary
    import shutil
    office_executable = shutil.which('libreoffice') or shutil.which('soffice')
    assert office_executable
    assert str(factory.kw['bind'].url.database).startswith('supermew_members_verify_')
    artifact_dir = Path(artifact_dir)
    assert artifact_dir.is_relative_to('/opt/supermew/verification')
    artifact_dir.mkdir(exist_ok=True)
    sources = artifact_dir / 'synthetic-sources'; sources.mkdir(exist_ok=True)
    fixtures = {}

    def command(args):
        process = subprocess.run(args, capture_output=True, timeout=90)
        assert process.returncode == 0, 'Fixture conversion failed: ' + process.stderr.decode(errors='replace')[-300:]

    def office(source, extension, directory):
        directory.mkdir(exist_ok=True)
        profile = directory / ('profile-' + uuid.uuid4().hex)
        command([office_executable, '-env:UserInstallation=' + profile.as_uri(), '--headless', '--convert-to',
                 extension, '--outdir', str(directory), str(source)])
        output = directory / (source.stem + '.' + extension)
        assert output.is_file(), 'No converted ' + extension + ' fixture'
        return output

    doc = Document(); doc.add_paragraph('FIRST_MARKER: full original document')
    doc.add_page_break(); doc.add_paragraph('LAST_MARKER: end of original')
    doc.save(sources / 'word.docx')
    fixtures['DOCX'] = sources / 'word.docx'
    fixtures['DOC'] = office(fixtures['DOCX'], 'doc', sources / 'legacy-word')
    book = Workbook(); book.active['A1'] = 'FIRST_MARKER'; book.active['A2'] = 'LAST_MARKER'
    book.save(sources / 'sheet.xlsx'); fixtures['XLSX'] = sources / 'sheet.xlsx'
    fixtures['XLS'] = office(fixtures['XLSX'], 'xls', sources / 'legacy-sheet')
    flat = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" office:version="1.2" office:mimetype="application/vnd.oasis.opendocument.presentation">
<office:automatic-styles><style:page-layout style:name="PM1"><style:page-layout-properties fo:page-width="28cm" fo:page-height="21cm"/></style:page-layout></office:automatic-styles>
<office:master-styles><style:master-page style:name="Default" style:page-layout-name="PM1"/></office:master-styles>
<office:body><office:presentation>PAGES</office:presentation></office:body></office:document>'''
    pages = ''.join('<draw:page draw:name="page' + str(index) + '" draw:master-page-name="Default"><draw:frame svg:x="2cm" svg:y="2cm" svg:width="22cm" svg:height="6cm"><draw:text-box><text:p>' + marker + '</text:p></draw:text-box></draw:frame></draw:page>'
                    for index, marker in enumerate(('FIRST_MARKER', 'LAST_MARKER')))
    (sources / 'slides.fodp').write_text(flat.replace('PAGES', pages))
    fixtures['PPTX'] = office(sources / 'slides.fodp', 'pptx', sources / 'slides-modern')
    fixtures['PPT'] = office(fixtures['PPTX'], 'ppt', sources / 'slides-legacy')
    pdf = canvas.Canvas(str(sources / 'file.pdf'))
    for marker in ('FIRST_MARKER', 'MIDDLE_MARKER', 'LAST_MARKER'):
        pdf.drawString(60, 720, marker); pdf.showPage()
    pdf.save(); fixtures['PDF'] = sources / 'file.pdf'
    for extension in ('txt', 'md'):
        path = sources / ('file.' + extension)
        path.write_text('FIRST_MARKER\n正文测试\nLAST_MARKER', encoding='utf-8')
        fixtures[extension.upper()] = path
    for extension, color in [('png','#bbddff'),('jpg','#aaddec'),('jpeg','#deddee')]:
        path = sources / ('image.' + extension)
        image = Image.new('RGB', (360, 240), color)
        from PIL import ImageDraw
        ImageDraw.Draw(image).text((30, 80), 'IMAGE_MARKER', fill='#123456')
        image.save(path); fixtures[extension.upper()] = path
    with wave.open(str(sources / 'tone.wav'), 'wb') as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000)
        output.writeframes(b''.join(struct.pack('<h', int(5000 * math.sin(2 * math.pi * 440 * i / 16000))) for i in range(16000)))
    fixtures['WAV'] = sources / 'tone.wav'
    for extension, codec in [('mp3', 'libmp3lame'), ('m4a', 'aac'), ('ogg', 'libvorbis'), ('flac', 'flac')]:
        path = sources / ('tone.' + extension)
        command([ffmpeg_binary(), '-nostdin', '-v', 'error', '-y', '-i', str(fixtures['WAV']), '-c:a', codec, str(path)])
        fixtures[extension.upper()] = path
    for extension, codec in [('mp4', 'libx264'), ('webm', 'libvpx-vp9')]:
        path = sources / ('clip.' + extension)
        command([ffmpeg_binary(), '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                 'color=c=blue:s=320x180:r=10:d=1', '-c:v', codec, '-pix_fmt', 'yuv420p', str(path)])
        fixtures[extension.upper()] = path
    assert set(fixtures) == {fmt.upper() for fmt in ws.FORMATS}, 'Every accepted format needs a real fixture'
    project = client.post('/company-knowledge/projects', headers=headers, json={'name': 'FORMAT MATRIX ' + uuid.uuid4().hex}).json()
    results = []
    for fmt, path in sorted(fixtures.items()):
        started = time.monotonic()
        source = path.read_bytes()
        uploaded = client.post('/company-knowledge/uploads', headers=headers,
            files={'file': (path.name, source)}, data={'project_id': project['id'], 'description': 'Synthetic format verification'})
        assert uploaded.status_code == 202, (fmt, 'upload', uploaded.status_code, uploaded.text[:200])
        doc_id = uploaded.json()['id']
        base = '/company-knowledge/documents/' + doc_id
        original = client.get(base + '/original', headers=headers)
        assert original.status_code == 200, (fmt, 'original', original.status_code, original.text[:200])
        assert original.headers.get('x-watermark-trace') and original.content
        original_name = fmt.lower() + '-marked.bin'
        (artifact_dir / original_name).write_bytes(original.content)
        row = {'format': fmt, 'id': doc_id, 'original': original_name,
               'mime': original.headers['content-type'], 'trace': original.headers['x-watermark-trace'],
               'pages': [], 'original_status': 200}
        if fmt in {'PDF', 'PNG', 'JPG', 'JPEG', 'MP4', 'WEBM'}:
            thumbnail = client.get(base + '/thumbnail', headers=headers)
            assert thumbnail.status_code == 200, (fmt, 'thumbnail', thumbnail.status_code)
            Image.open(io.BytesIO(thumbnail.content)).verify()
            row['thumbnail'] = fmt.lower() + '-thumbnail.png'
            (artifact_dir / row['thumbnail']).write_bytes(thumbnail.content)
        if fmt in {'PDF', 'DOC', 'DOCX', 'XLS', 'XLSX', 'PPT', 'PPTX'}:
            first = client.get(base + '/page?page=1', headers=headers)
            assert first.status_code == 200, (fmt, 'first-page', first.status_code, first.text[:200])
            count = int(first.headers['x-document-pages']); assert count >= 1
            for page in range(1, count + 1):
                response = first if page == 1 else client.get(base + '/page?page=' + str(page), headers=headers)
                assert response.status_code == 200, (fmt, page, response.status_code)
                image = Image.open(io.BytesIO(response.content)); assert image.width > 100 and image.height > 100
                name = fmt.lower() + '-page-' + str(page) + '.png'
                (artifact_dir / name).write_bytes(response.content); row['pages'].append(name)
            from company_discovery import reading_pdf
            with factory() as db:
                doc_row = db.get(CompanyDocument, doc_id)
                import pypdfium2 as pdfium
                with ws.pdf_render_lock:
                    pdf = pdfium.PdfDocument(reading_pdf(doc_row)); parts = []
                    for number in range(len(pdf)):
                        page = pdf[number]; text = page.get_textpage(); parts.append(text.get_text_range())
                        text.close(); page.close()
                    pdf.close()
            full = ''.join(parts)
            assert 'FIRST_MARKER' in full and 'LAST_MARKER' in full, (fmt, 'missing source beginning or ending')
            row['first_and_last_content'] = True
        elif fmt in {'PNG', 'JPG', 'JPEG'}:
            image = Image.open(io.BytesIO(original.content)); assert image.size == (360, 240)
        elif fmt in {'TXT', 'MD'}:
            assert b'FIRST_MARKER' in original.content and b'LAST_MARKER' in original.content
        else:
            probe = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json',
                str(artifact_dir / original_name)], capture_output=True, timeout=30)
            assert probe.returncode == 0
            metadata = json.loads(probe.stdout)
            expected = 'video' if fmt in {'MP4', 'WEBM'} else 'audio'
            assert any(stream['codec_type'] == expected for stream in metadata['streams'])
            assert float(metadata['format']['duration']) >= 1
            row['stream_verified'] = expected
        with factory() as db:
            stored = db.get(CompanyDocument, doc_id)
            assert document_store().get_bytes(stored.object_key) == source, (fmt, 'source changed')
        row['seconds'] = round(time.monotonic() - started, 2); results.append(row)
        print('Verified format ' + fmt, flush=True)
    (artifact_dir / 'matrix.json').write_text(json.dumps(results, indent=2))
    return results
