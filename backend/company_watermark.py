"""Personalised export copies. Conversion errors never return the original bytes."""
import io
import os
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

_slots = threading.BoundedSemaphore(2)
OFFICE_FORMATS = {'DOC', 'DOCX', 'XLS', 'XLSX', 'PPT', 'PPTX'}
IMAGE_FORMATS = {'JPG', 'JPEG', 'PNG'}
AUDIO_FORMATS = {'MP3', 'WAV', 'M4A', 'OGG', 'FLAC'}


class WatermarkError(Exception):
    def __init__(self, message, status=503):
        self.status = status
        super().__init__(message)


@dataclass(frozen=True)
class ExportIdentity:
    username: str
    user_id: int | None
    timestamp: str
    trace_id: str

    @property
    def lines(self):
        return ['观复咨询 · 内部资料', '下载账号：' + self.username,
                self.timestamp + ' UTC', '追踪编号：' + self.trace_id]


def font_path():
    candidates = [os.getenv('COMPANY_KNOWLEDGE_WATERMARK_FONT', ''), 'C:/Windows/Fonts/simhei.ttf',
        'C:/Windows/Fonts/msyh.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc', '/System/Library/Fonts/PingFang.ttc']
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise WatermarkError('水印中文字体未配置，请联系管理员；不会提供无水印原件。')


def wrapped_lines(draw, lines, font, width):
    result = []
    for line in lines:
        part = ''
        for char in line:
            if part and draw.textlength(part + char, font=font) > width:
                result.append(part)
                part = ''
            part += char
        result.append(part)
    return result


def watermark_layer(size, identity, footer=True):
    width, height = size
    if width < 16 or height < 16 or width * height > 40_000_000:
        raise WatermarkError('文件页面或图片尺寸不支持安全水印导出。', 422)
    output = Image.new('RGBA', size)
    font = ImageFont.truetype(font_path(), max(10, min(27, width // 40)))
    draw = ImageDraw.Draw(output)
    lines = wrapped_lines(draw, identity.lines, font, width * .73)
    line_height = font.size + 5
    tile = Image.new('RGBA', (width, max(height, len(lines) * line_height + 20)))
    tile_draw = ImageDraw.Draw(tile)
    top = (tile.height - line_height * len(lines)) // 2
    for i, line in enumerate(lines):
        tile_draw.text(((width - tile_draw.textlength(line, font=font)) / 2, top + i * line_height),
                       line, font=font, fill=(66, 99, 133, 68))
    tile = tile.rotate(24, resample=Image.Resampling.BICUBIC)
    output.alpha_composite(tile, (0, (height - tile.height) // 2))
    if height > 700:
        output.alpha_composite(tile, (0, -height // 3))
        output.alpha_composite(tile, (0, height // 3))
    if not footer:
        return output
    footer_font = ImageFont.truetype(font_path(), max(9, min(14, width // 65)))
    footer = wrapped_lines(draw, [identity.lines[1], identity.timestamp + ' UTC | ID ' + identity.trace_id], footer_font, width - 20)
    footer_height = (footer_font.size + 4) * len(footer) + 10
    draw.rectangle((0, height - footer_height, width, height), fill=(240, 246, 252, 205))
    for i, line in enumerate(footer):
        draw.text((10, height - footer_height + 5 + i * (footer_font.size + 4)), line,
                  font=footer_font, fill=(43, 65, 92, 235))
    return output


def stamp_pdf(data, identity, progress=None):
    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted and not reader.decrypt(''):
        raise WatermarkError('加密 PDF 无法加水印，请先上传可处理的版本。', 422)
    if not 0 < len(reader.pages) <= 1000:
        raise WatermarkError('PDF 页数超出水印导出范围（1–1000 页）。', 422)
    writer = PdfWriter()
    overlays = {}
    total = len(reader.pages)
    if progress:
        progress('stamping', 0, total)
    for number, page in enumerate(reader.pages, 1):
        page.transfer_rotation_to_content()
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        if not 0 < width <= 14400 or not 0 < height <= 14400:
            raise WatermarkError('PDF 页面尺寸不支持水印导出。', 422)
        # Stamp the visible crop box as well as the complete page, including offset crops.
        box = page.cropbox
        crop_width, crop_height = float(box.width), float(box.height)
        size = (crop_width, crop_height)
        if size not in overlays:
            scale = min(2, 1600 / max(crop_width, crop_height))
            layer = watermark_layer((max(16, int(crop_width * scale)), max(16, int(crop_height * scale))), identity)
            overlay = io.BytesIO()
            pdf = canvas.Canvas(overlay, pagesize=size)
            pdf.drawImage(ImageReader(layer), 0, 0, crop_width, crop_height, mask='auto')
            pdf.save()
            # Keep the same PDF object graph for this request's page size. This also
            # lets PdfWriter share image streams rather than embedding them per page.
            overlays[size] = PdfReader(io.BytesIO(overlay.getvalue()))
        page.merge_transformed_page(overlays[size].pages[0],
            Transformation().translate(float(box.left), float(box.bottom)), over=True, expand=False)
        # Export copies do not carry an unmarked file inside PDF attachment annotations.
        if '/Annots' in page:
            from pypdf.generic import ArrayObject, NameObject
            page[NameObject('/Annots')] = ArrayObject([a for a in page['/Annots'] if a.get_object().get('/Subtype') != '/FileAttachment'])
        writer.add_page(page)
        if progress:
            progress('stamping', number, total)
    writer.add_metadata({'/Producer': 'Company Knowledge Watermarked Export', '/WatermarkTrace': identity.trace_id,
                         '/DownloadAccount': identity.username, '/DownloadTimeUTC': identity.timestamp})
    output = io.BytesIO()
    if progress:
        progress('packaging', total, total)
    writer.write(output)
    return output.getvalue()


def run(args, *, timeout=180, cwd=None, env=None):
    try:
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
            cwd=cwd, env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired):
        raise WatermarkError('带水印副本生成失败或超时，请联系管理员；不会提供无水印原件。') from None
    if result.returncode:
        raise WatermarkError('带水印副本生成失败，请联系管理员；不会提供无水印原件。')


def office_to_pdf(data, fmt, directory):
    return convert_office(data, fmt, 'pdf', directory)


def convert_office(data, fmt, target_format, directory):
    binary = os.getenv('COMPANY_KNOWLEDGE_OFFICE_BINARY') or shutil.which('soffice') or shutil.which('libreoffice')
    if not binary:
        raise WatermarkError('Office 转换服务未配置，请联系管理员；不会提供无水印原件。')
    source = directory / ('source.' + fmt.lower())
    source.write_bytes(data)
    profile = directory / 'profile'
    profile.mkdir()
    user_dir = profile / 'user'; user_dir.mkdir()
    (user_dir / 'registrymodifications.xcu').write_text('''<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry"><item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item><item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="UpdateDocMode" oor:op="fuse"><value>0</value></prop></item></oor:items>''', encoding='utf-8')
    run([binary, '-env:UserInstallation=' + profile.as_uri(), '--headless', '--nologo', '--nodefault',
         '--norestore', '--convert-to', target_format, '--outdir', str(directory), str(source)])
    output = directory / ('source.' + target_format)
    if not output.is_file():
        raise WatermarkError('Office 文件无法处理，请确认文件未加密或损坏。', 422)
    return output.read_bytes()


def text_to_pdf(data):
    if len(data) > 2_000_000:
        raise WatermarkError('文字资料过大，请拆分后生成带水印 PDF（最多 2 MB 文本）。', 422)
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    text = None
    for encoding in ('utf-8-sig', 'utf-16', 'gb18030'):
        try:
            text = data.decode(encoding)
            break
        except UnicodeError:
            pass
    if text is None:
        raise WatermarkError('文字编码无法识别，无法生成带水印 PDF。', 422)
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=(595, 842))
    y = 792
    for raw in text.splitlines():
        # Keep text literal; markdown and file content are never evaluated as markup.
        line = ''
        for char in raw.expandtabs(4):
            if pdfmetrics.stringWidth(line + char, 'STSong-Light', 10) > 495:
                if y < 55: pdf.showPage(); y = 792
                pdf.setFont('STSong-Light', 10); pdf.drawString(50, y, line); y -= 16
                line = ''
            line += char if ord(char) >= 32 else ' '
        if y < 55: pdf.showPage(); y = 792
        pdf.setFont('STSong-Light', 10); pdf.drawString(50, y, line); y -= 16
    pdf.showPage(); pdf.save()
    return output.getvalue()


def ffmpeg_binary():
    binary = os.getenv('COMPANY_KNOWLEDGE_FFMPEG_BINARY') or shutil.which('ffmpeg')
    if binary:
        return binary
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise WatermarkError('音视频水印服务未配置，请联系管理员。') from None


def speech_notice(identity, directory):
    text = ('Internal company material. Downloaded by account number ' + str(identity.user_id or 'unknown') +
        '. Account ' + re.sub(r'[^a-zA-Z0-9 ._-]', ' ', identity.username) + '. UTC time ' + identity.timestamp +
        '. Trace ' + ' '.join(identity.trace_id) + '. For internal use only.')
    output = directory / 'notice.wav'
    source = directory / 'notice.txt'; source.write_text(text, encoding='utf-8')
    if os.name == 'nt':
        command = ('Add-Type -AssemblyName System.Speech; $voice = New-Object System.Speech.Synthesis.SpeechSynthesizer; '
            'try { $voice.SetOutputToWaveFile($env:CKB_SPEECH_OUTPUT); '
            '$voice.Speak([IO.File]::ReadAllText($env:CKB_SPEECH_INPUT)); } finally { $voice.Dispose() }')
        run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command], timeout=60,
            env={**os.environ, 'CKB_SPEECH_OUTPUT': str(output), 'CKB_SPEECH_INPUT': str(source)})
    else:
        binary = os.getenv('COMPANY_KNOWLEDGE_SPEECH_BINARY') or shutil.which('espeak-ng') or shutil.which('espeak')
        if not binary:
            raise WatermarkError('录音身份提示服务未配置（需要 espeak-ng），不会提供无标记录音。')
        run([binary, '-v', 'en', '-s', '175', '-f', str(source), '-w', str(output)], timeout=60)
    if not output.is_file() or output.stat().st_size < 44:
        raise WatermarkError('录音身份提示生成失败。')
    return output


def marked_media(data, fmt, identity, directory):
    binary = ffmpeg_binary()
    source = directory / ('source.' + fmt.lower()); source.write_bytes(data)
    metadata = ['-map_metadata', '-1', '-metadata', 'comment=' + ' | '.join(identity.lines)]
    if fmt in AUDIO_FORMATS:
        notice = speech_notice(identity, directory)
        output = directory / 'marked.mp3'
        convert = 'aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo'
        filters = '[1:a]' + convert + ',asplit=2[intro][outro];[0:a]' + convert + '[body];[intro][body][outro]concat=n=3:v=0:a=1[out]'
        run([binary, '-nostdin', '-y', '-i', str(source), '-i', str(notice), '-filter_complex', filters,
            '-map', '[out]', '-c:a', 'libmp3lame', '-b:a', '192k', *metadata, str(output)], timeout=360)
        mime, extension = 'audio/mpeg', 'mp3'
    else:
        frame = directory / 'frame.png'
        run([binary, '-nostdin', '-y', '-i', str(source), '-frames:v', '1', '-update', '1', str(frame)], timeout=60)
        with Image.open(frame) as image:
            layer = watermark_layer(image.size, identity)
        mark = directory / 'mark.png'; layer.save(mark)
        output = directory / 'marked.mp4'
        run([binary, '-nostdin', '-y', '-i', str(source), '-loop', '1', '-i', str(mark),
            '-filter_complex', '[0:v][1:v]overlay=0:0:shortest=1,pad=ceil(iw/2)*2:ceil(ih/2)*2[v]',
            '-map', '[v]', '-map', '0:a?', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
            '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', *metadata, str(output)], timeout=360)
        mime, extension = 'video/mp4', 'mp4'
    if output.stat().st_size > 512 * 1024 * 1024:
        raise WatermarkError('带标记副本过大，请联系管理员分段导出。', 422)
    return output.read_bytes(), mime, extension


def export_copy(data, fmt, title, identity, progress=None):
    if not _slots.acquire(blocking=False):
        raise WatermarkError('水印导出正在处理中，请稍后重试。', 429)
    try:
        with tempfile.TemporaryDirectory(prefix='ckb-export-') as temporary:
            directory = Path(temporary)
            if fmt in IMAGE_FORMATS:
                if progress: progress('stamping', 0, 1)
                with Image.open(io.BytesIO(data)) as original:
                    from PIL import ImageOps
                    image = ImageOps.exif_transpose(original).convert('RGBA')
                    image = Image.alpha_composite(image, watermark_layer(image.size, identity))
                    output = io.BytesIO(); image.save(output, format='PNG')
                result, mime, extension = output.getvalue(), 'image/png', 'png'
            elif fmt in AUDIO_FORMATS or fmt in ('MP4', 'WEBM'):
                if progress: progress('media', 0, 0)
                result, mime, extension = marked_media(data, fmt, identity, directory)
            elif fmt in OFFICE_FORMATS:
                from company_office_watermark import mark_office
                result, mime, extension = mark_office(data, fmt, identity, directory, progress)
            elif fmt in ('TXT', 'MD'):
                from company_office_watermark import mark_text
                if progress: progress('stamping', 0, 1)
                result, encoding = mark_text(data, fmt, identity)
                mime, extension = ('text/markdown' if fmt == 'MD' else 'text/plain') + '; charset=' + encoding, fmt.lower()
            else:
                if fmt != 'PDF':
                    raise WatermarkError('该格式暂不支持带水印下载。', 422)
                result, mime, extension = stamp_pdf(data, identity, progress), 'application/pdf', 'pdf'
            return result, mime, Path(title).stem + '_水印副本.' + extension
    except WatermarkError:
        raise
    except Exception:
        raise WatermarkError('无法生成带水印副本，请确认文件未损坏；不会提供无水印原件。', 422) from None
    finally:
        _slots.release()
