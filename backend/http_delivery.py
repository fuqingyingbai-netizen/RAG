"""Compress large read-only research responses without buffering live events."""
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.exceptions import HTTPException
import os


class RequestBodyLimit:
    """Bound both declared and streamed bodies before multipart parsing or JSON decoding."""
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        multipart = headers.get('content-type', '').lower().startswith('multipart/')
        setting = 'MAX_REQUEST_BYTES' if multipart else 'MAX_JSON_BYTES'
        default = 52 * 1024 * 1024 if multipart else 2 * 1024 * 1024
        limit = max(1, int(os.getenv(setting, str(default))))
        try:
            length = int(headers.get('content-length', '0'))
            if length < 0:
                raise ValueError()
        except ValueError:
            return await JSONResponse({'detail': '请求长度无效'}, status_code=400)(scope, receive, send)
        if length > limit:
            return await JSONResponse({'detail': '请求内容超过允许大小'}, status_code=413)(scope, receive, send)
        total = 0
        async def bounded_receive():
            nonlocal total
            message = await receive()
            if message['type'] == 'http.request':
                total += len(message.get('body', b''))
                if total > limit:
                    raise HTTPException(413, '请求内容超过允许大小')
            return message
        await self.app(scope, bounded_receive, send)


def _gzip_allowed(scope: Scope) -> bool:
    for entry in Headers(scope=scope).get('accept-encoding', '').split(','):
        coding, *parameters = entry.lower().split(';')
        if coding.strip() != 'gzip':
            continue
        quality = 1.0
        for parameter in parameters:
            name, separator, value = parameter.partition('=')
            if separator and name.strip() == 'q':
                try: quality = float(value.strip())
                except ValueError: return False
        return 0 < quality <= 1
    return False


class ResearchReadCompression:
    def __init__(self, app: ASGIApp):
        self.app = app
        self.compressed = GZipMiddleware(app, minimum_size=1024, compresslevel=3)

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        path = scope.get('path', '')
        if (scope['type'] == 'http' and scope.get('method') == 'GET'
                and path.startswith('/research/') and not path.endswith('/download')
                and _gzip_allowed(scope)):
            # GZipMiddleware negotiates Accept-Encoding and excludes event-stream.
            # Writes and original file downloads bypass it entirely.
            await self.compressed(scope, receive, send)
        else:
            await self.app(scope, receive, send)
