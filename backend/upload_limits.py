"""Bound uploaded content before parsing or changing any existing records."""
import os
from fastapi import HTTPException


def maximum_upload_bytes():
    return max(1, int(os.getenv('MAX_UPLOAD_BYTES', str(50 * 1024 * 1024))))


def validate_filename(filename):
    if (not filename or filename in {'.', '..'} or len(filename.encode('utf-8')) > 240
            or any(c in filename for c in '/\\:"')
            or any(ord(c) < 32 for c in filename)):
        raise HTTPException(400, '文件名包含无效字符，请重命名后上传')
    return filename


async def read_upload(file):
    limit = maximum_upload_bytes()
    if file.size is not None and file.size > limit:
        raise HTTPException(413, '文件超过允许的上传大小')
    content = bytearray()
    while chunk := await file.read(min(1024 * 1024, limit - len(content) + 1)):
        content.extend(chunk)
        if len(content) > limit:
            raise HTTPException(413, '文件超过允许的上传大小')
    if not content:
        raise HTTPException(400, '不能上传空文件')
    return bytes(content)


def copy_upload(file, destination):
    limit = maximum_upload_bytes()
    if file.size is not None and file.size > limit:
        raise HTTPException(413, '文件超过允许的上传大小')
    total = 0
    with destination.open('xb') as output:
        while chunk := file.file.read(min(1024 * 1024, limit - total + 1)):
            total += len(chunk)
            if total > limit:
                raise HTTPException(413, '文件超过允许的上传大小')
            output.write(chunk)
    if not total:
        raise HTTPException(400, '不能上传空文件')
