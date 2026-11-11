"""Unmarked, permission-checked media playback, independent of document exports."""
import hashlib
import mimetypes
import os
import re
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from jose import JWTError, jwt

from company_watermark import WatermarkError, ffmpeg_binary, run

RAW_FORMATS = {'PNG', 'JPG', 'JPEG', 'WEBP', 'GIF', 'BMP', 'MP3', 'WAV', 'M4A', 'OGG', 'FLAC', 'MP4', 'WEBM'}
_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix='knowledge-media')
_lock = threading.Lock()
_jobs = {}


def cache_path(doc):
    root = Path(os.getenv('COMPANY_KNOWLEDGE_MEDIA_CACHE', 'data/company_media_cache')).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = hashlib.sha256(('v1:' + doc.object_key + ':' + doc.sha256).encode()).hexdigest()
    return root / (key + ('.mp4' if doc.format in {'MP4', 'WEBM'} else '.mp3'))


def prepare(doc, target, store):
    # Only immutable derivatives live here; originals are never rewritten.
    for old in target.parent.iterdir():
        if old.is_file() and old.suffix in {'.mp4', '.mp3'} and time.time() - old.stat().st_mtime > 86400:
            try:
                old.unlink()
            except OSError:
                pass
    with tempfile.TemporaryDirectory(prefix='prepare-', dir=target.parent) as directory:
        source = Path(directory) / ('source.' + doc.format.lower())
        source.write_bytes(store.get_bytes(doc.object_key))
        output = Path(directory) / target.name
        if doc.format == 'MP3':
            source.replace(output)
        else:
            binary = ffmpeg_binary()
            if doc.format in {'MP4', 'WEBM'}:
                probe = subprocess.run([binary, '-hide_banner', '-i', str(source)], capture_output=True, timeout=30)
                native = re.search(r'Video: h264\b[^\r\n]*\byuv420p\b', probe.stderr.decode(errors='replace'))
                video = ['-c:v', 'copy'] if native else ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p']
                args = ['-map', '0:v:0', '-map', '0:a:0?', *video, '-c:a', 'aac', '-movflags', '+faststart']
            else:
                args = ['-vn', '-c:a', 'libmp3lame', '-b:a', '192k']
            run([binary, '-nostdin', '-v', 'error', '-y', '-i', str(source), *args, '-map_metadata', '-1', str(output)], timeout=360)
        if not output.is_file() or output.stat().st_size > 512 * 1024 * 1024:
            raise WatermarkError('播放版本过大，请下载原文件播放。', 422)
        os.chmod(output, 0o600)
        os.replace(output, target)
    return target


def playback_job(doc, retry=False):
    target = cache_path(doc)
    if target.is_file():
        os.utime(target, None)
        return target, None
    key = str(target)
    with _lock:
        for old, job in list(_jobs.items()):
            if old != key and job.done():
                del _jobs[old]
        job = _jobs.get(key)
        if job and retry and job.done() and job.exception():
            job = None
        if job is None:
            if sum(not job.done() for job in _jobs.values()) >= 8:
                raise HTTPException(429, '播放准备任务较多，请稍后重试。', headers={'Retry-After': '3'})
            from company_catalog import document_store
            job = _jobs[key] = _workers.submit(prepare, doc, target, document_store())
    if job.done():
        try:
            return job.result(), None
        except Exception as exc:
            raise HTTPException(422, '播放版本准备失败，请重试或下载原文件播放。') from exc
    return None, job


def signing_key():
    import auth
    # A playback ticket cannot be used as an application login token.
    return hashlib.sha256((auth.SECRET_KEY + ':knowledge-media-v1').encode()).hexdigest()


def playback_response(doc, user, request, retry=False):
    target, job = playback_job(doc, retry)
    if job is not None:
        return JSONResponse({'state': 'preparing', 'message': '正在准备播放版本，完成后会自动开始加载。'}, status_code=202,
                            headers={'Cache-Control': 'private, no-store', 'Retry-After': '2'})
    path = '/company-knowledge/documents/' + doc.id + '/stream'
    ticket = jwt.encode({'sub': user.username, 'ver': getattr(user, 'token_version', 0), 'doc': doc.id,
                         'sha': doc.sha256, 'exp': int(time.time()) + 3600}, signing_key(), algorithm='HS256')
    response = JSONResponse({'state': 'ready', 'url': path}, headers={'Cache-Control': 'private, no-store'})
    response.set_cookie('ckb_playback', ticket, max_age=3600, httponly=True, secure=request.url.scheme == 'https',
                        samesite='strict', path=path)
    return response


def stream_response(doc_id, request):
    import company_workspace as ws
    import company_knowledge as kb
    from models import User
    from sqlalchemy import select
    try:
        claims = jwt.decode(request.cookies.get('ckb_playback', ''), signing_key(), algorithms=['HS256'])
        if claims.get('doc') != doc_id:
            raise ValueError()
    except (JWTError, ValueError):
        raise HTTPException(401, '播放授权已过期，请重新打开资料。') from None
    with ws.SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == claims.get('sub')))
        if (not user or not user.is_active or user.archived_at or user.must_change_password
                or user.token_version != claims.get('ver')):
            raise HTTPException(401, '播放授权已失效，请重新登录。')
        kb.require_knowledge_user(user)
        doc = ws.find_doc(db, doc_id, user)
        if doc.sha256 != claims.get('sha') or not doc.object_key:
            raise HTTPException(409, '资料版本已变化，请重新打开。')
        path = cache_path(doc)
        if not path.is_file():
            raise HTTPException(410, '播放缓存已过期，请重新打开资料。')
        return file_response(path, request)


def file_response(path, request):
    """Single HTTP byte ranges, including suffix and open-ended seeks."""
    stream = path.open('rb')
    size = os.fstat(stream.fileno()).st_size
    start, end, status = 0, size - 1, 200
    headers = {'Accept-Ranges': 'bytes', 'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'}
    value = request.headers.get('range')
    if value:
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', value.strip())
        try:
            if not match or not any(match.groups()) or not size:
                raise ValueError()
            first, last = match.groups()
            if first:
                start = int(first)
                end = min(int(last), size - 1) if last else size - 1
            else:
                if int(last) <= 0:
                    raise ValueError()
                start = max(0, size - int(last))
            if start > end or start >= size:
                raise ValueError()
        except ValueError:
            stream.close()
            raise HTTPException(416, '请求的播放位置不可用。', headers={**headers, 'Content-Range': f'bytes */{size}'}) from None
        status = 206
        headers['Content-Range'] = f'bytes {start}-{end}/{size}'
    remaining = max(0, end - start + 1)
    headers['Content-Length'] = str(remaining)

    def chunks():
        try:
            stream.seek(start)
            left = remaining
            while left:
                data = stream.read(min(left, 256 * 1024))
                if not data:
                    break
                left -= len(data)
                yield data
        finally:
            stream.close()
    from starlette.background import BackgroundTask
    return StreamingResponse(chunks() if request.method != 'HEAD' else iter(()), status_code=status,
                             media_type=mimetypes.guess_type(str(path))[0] or 'application/octet-stream',
                             headers=headers, background=BackgroundTask(stream.close))
