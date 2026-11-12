"""Bounded, process-wide admission for the deployed single-worker knowledge app."""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from collections import deque
import os
import threading
import time

from fastapi.responses import JSONResponse
from sqlalchemy.exc import TimeoutError as PoolTimeout

from company_observability import observe_capacity


class CapacityBusy(Exception):
    pass


waiting_reporter = ContextVar('knowledge_waiting_reporter', default=None)


class Capacity:
    def __init__(self, limit, queue=0):
        self.limit, self.queue = limit, queue
        self.active = self.waiting = 0
        self._waiters = deque()
        self.lock = threading.Lock()

    @asynccontextmanager
    async def slot(self, kind, wait=0):
        started = time.monotonic()
        acquired = queued = False
        ticket = object()
        try:
            with self.lock:
                if self.active < self.limit and not self._waiters:
                    self.active += 1
                    acquired = True
                elif wait > 0 and self.waiting < self.queue:
                    self.waiting += 1
                    self._waiters.append(ticket)
                    queued = True
                else:
                    raise CapacityBusy('当前任务较多，请稍后重试。')
            if queued:
                reporter = waiting_reporter.get()
                if reporter:
                    await reporter({'type': 'progress', 'stage': 'queued', 'label': '正在排队',
                                    'detail': '正在等待模型处理，您可以取消本次请求。'})
                while not acquired:
                    await asyncio.sleep(min(.05, max(0, wait - (time.monotonic() - started))))
                    if time.monotonic() - started >= wait:
                        raise CapacityBusy('等待模型处理超时，请稍后重试。')
                    with self.lock:
                        if self.active < self.limit and self._waiters[0] is ticket:
                            self.active += 1
                            self.waiting -= 1
                            self._waiters.popleft()
                            queued, acquired = False, True
                if reporter:
                    await reporter({'type': 'progress', 'stage': 'queued', 'label': '已开始处理',
                                    'detail': '排队结束，正在处理本次请求。', 'finished': True})
            observe_capacity(kind, 'admitted', (time.monotonic() - started) * 1000)
            yield
        except CapacityBusy:
            observe_capacity(kind, 'rejected', (time.monotonic() - started) * 1000)
            raise
        finally:
            with self.lock:
                if acquired:
                    self.active -= 1
                if queued:
                    self.waiting -= 1
                    self._waiters.remove(ticket)


# shortcut: limits are per process; sum them across workers before increasing --workers.
model_slots = Capacity(int(os.getenv('COMPANY_KNOWLEDGE_MODEL_CONCURRENCY', '3')), queue=7)
chat_slots = Capacity(10)
upload_slots = Capacity(3, queue=7)
MODEL_WAIT_SECONDS = float(os.getenv('COMPANY_KNOWLEDGE_MODEL_WAIT_SECONDS', '60'))
if model_slots.limit < 1 or not 0 < MODEL_WAIT_SECONDS <= 60:
    raise ValueError('Invalid knowledge model admission configuration')


class KnowledgeCapacityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] != 'http' or not path.startswith('/company-knowledge/'):
            return await self.app(scope, receive, send)
        started = False
        async def delivered(message):
            nonlocal started
            if message['type'] == 'http.response.start':
                started = True
            await send(message)
        gate, kind = None, ''
        if scope.get('method') == 'POST':
            if path == '/company-knowledge/chat/stream':
                gate, kind = chat_slots, 'chat'
            elif path == '/company-knowledge/uploads' or (path.startswith('/company-knowledge/documents/') and path.endswith('/original')):
                gate, kind = upload_slots, 'upload'
        try:
            if gate:
                async with gate.slot(kind, wait=5 if kind == 'upload' else 0):
                    await self.app(scope, receive, delivered)
            else:
                await self.app(scope, receive, delivered)
        except (CapacityBusy, PoolTimeout):
            if started:
                raise
            response = JSONResponse({'detail': '服务当前繁忙，请稍后重试。'}, status_code=503,
                                    headers={'Retry-After': '2'})
            await response(scope, receive, send)
