"""Compress large read-only research responses without buffering live events."""
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.datastructures import Headers


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
