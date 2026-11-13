"""Bounded, metadata-only knowledge traces; never record content, SQL or credentials."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import threading
import time
import uuid

from starlette.datastructures import MutableHeaders

_current = ContextVar('knowledge_trace', default=None)
_lock = threading.Lock()
_pruned = {}
_warned = set()
LIMITS = {'detail': (7, 16 * 1024 * 1024), 'summary': (30, 4 * 1024 * 1024)}


def now():
    return datetime.now(timezone.utc)


def log_root():
    return Path(os.getenv('COMPANY_KNOWLEDGE_LOG_DIR') or
                str(Path(os.getenv('COMPANY_KNOWLEDGE_LOCAL_STORE', 'data/company_knowledge')).parent / 'knowledge_logs'))


def write(kind, values):
    """One process/day file; logging failures and daily caps cannot fail a request."""
    try:
        instant = now()
        record = {'at': instant.isoformat(), **values}
        payload = (json.dumps(record, ensure_ascii=True, separators=(',', ':')) + '\n').encode()
        root = log_root()
        days, maximum = LIMITS[kind]
        with _lock:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            if time.monotonic() - _pruned.get(str(root), -60) >= 60:
                for entry in root.iterdir():
                    match = re.fullmatch(r'kb-(detail|summary)-(\d{4}-\d{2}-\d{2})-\d+\.jsonl', entry.name)
                    if match:
                        try:
                            age = (instant.date() - datetime.fromisoformat(match[2]).date()).days
                        except ValueError:
                            continue
                        if age >= LIMITS[match[1]][0]:
                            entry.unlink(missing_ok=True)
                _pruned[str(root)] = time.monotonic()
            path = root / f'kb-{kind}-{instant.date().isoformat()}-{os.getpid()}.jsonl'
            if (path.stat().st_size if path.exists() else 0) + len(payload) > maximum:
                if str(path) not in _warned:
                    logging.getLogger(__name__).warning('knowledge_trace_daily_capacity_reached kind=%s', kind)
                    _warned.add(str(path))
                return False
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            try:
                remaining = memoryview(payload)
                while remaining:
                    written = os.write(fd, remaining)
                    if written <= 0:
                        raise OSError('incomplete trace write')
                    remaining = remaining[written:]
            finally:
                os.close(fd)
        return True
    except Exception:
        logging.getLogger(__name__).warning('knowledge_trace_write_failed')
        return False


class Trace:
    def __init__(self):
        self.id = uuid.uuid4().hex
        self.started = time.perf_counter()
        self.active = True
        self.lock = threading.Lock()
        self.stats = {'sql_calls': 0, 'sql_errors': 0, 'sql_execution_ms': 0,
                      'db_checkouts': 0, 'db_connection_hold_ms': 0, 'db_max_connection_hold_ms': 0,
                      'admission_wait_ms': 0, 'admission_rejections': 0,
                      'commits_confirmed': 0, 'rollbacks_confirmed': 0,
                      'upstream_calls': 0, 'upstream_errors': 0, 'model_retry_attempts': 0,
                      'upstream_statuses': {}, 'upstream_error_types': {},
                      'retrieval_attempted': False,
                      'sse_done_generated': False, 'sse_error_generated': False, 'detail_records_dropped': 0}

    def event(self, event, **values):
        if self.active and not write('detail', {'request_id': self.id, 'event': event, **values}):
            with self.lock:
                self.stats['detail_records_dropped'] += 1


@contextmanager
def phase(operation, **values):
    trace = _current.get()
    started, error = time.perf_counter(), ''
    try:
        yield values
    except BaseException as exc:
        error = type(exc).__name__
        raise
    finally:
        if trace and trace.active:
            status = values.get('http_status', 0)
            with trace.lock:
                trace.stats['upstream_calls'] += 1
                trace.stats['upstream_errors'] += int(bool(error) or status >= 400)
                trace.stats['model_retry_attempts'] += int(operation in {'model_stream', 'model_complete'} and values.get('attempt', 1) > 1)
                if status:
                    counts = trace.stats['upstream_statuses']
                    counts[str(status)] = counts.get(str(status), 0) + 1
                if error:
                    counts = trace.stats['upstream_error_types']
                    counts[error] = counts.get(error, 0) + 1
            trace.event('upstream', operation=operation, scope_ms=round((time.perf_counter()-started)*1000, 3),
                        error_type=error, **values)


def observe_intent(intent, source, elapsed, failure=''):
    trace = _current.get()
    if trace and trace.active:
        values = {'intent': intent, 'intent_source': source, 'intent_ms': round(elapsed * 1000, 3),
                  'intent_error_type': failure}
        with trace.lock:
            trace.stats.update(values)
        trace.event('intent', **values)


def observe_retrieval():
    trace = _current.get()
    if trace and trace.active:
        with trace.lock:
            trace.stats['retrieval_attempted'] = True
        trace.event('retrieval', attempted=True)


def observe_sse(event):
    trace = _current.get()
    if not trace or not trace.active:
        return
    kind = event.get('type')
    if kind == 'answer_delta' and event.get('text'):
        with trace.lock:
            first = 'first_answer_delta_ms' not in trace.stats
            if first:
                trace.stats['first_answer_delta_ms'] = round((time.perf_counter()-trace.started)*1000, 3)
        if first:
            trace.event('first_answer_delta')
    if kind in ('done', 'error'):
        with trace.lock:
            trace.stats['sse_' + kind + '_generated'] = True
        trace.event('sse', kind=kind)
    elif kind == 'progress':
        stage = event.get('stage', '')
        if stage in {'connecting', 'queued', 'context', 'retrieving', 'organizing', 'answering', 'citations', 'memory', 'saving'}:
            trace.event('stage', stage=stage)


def observe_capacity(kind, outcome, wait_ms):
    trace = _current.get()
    if trace and trace.active:
        with trace.lock:
            trace.stats['admission_wait_ms'] += round(wait_ms, 3)
            trace.stats['admission_rejections'] += int(outcome == 'rejected')
        trace.event('admission', kind=kind, outcome=outcome, wait_ms=round(wait_ms, 3))


@contextmanager
def span(operation):
    started = time.perf_counter()
    try:
        yield
    finally:
        trace = _current.get()
        if trace and trace.active:
            trace.event('application', operation=operation, scope_ms=round((time.perf_counter()-started)*1000, 3))


def model_content(response):
    observation = response.extensions.get('knowledge_observation')
    if observation is not None and 'first_content_ms' not in observation:
        observation['first_content_ms'] = round((time.perf_counter()-response.extensions['knowledge_started'])*1000, 3)


def observe_checkpoint(state):
    trace = _current.get()
    if trace and trace.active and state in {'queued', 'uploading', 'parsing', 'indexing', 'ready', 'failed', 'archived'}:
        trace.stats['persisted_state'] = state
        trace.event('checkpoint', state=state)


@contextmanager
def ingestion_trace(doc_id):
    """A background attempt has its own lifetime, even after HTTP has completed."""
    parent = _current.get()
    trace = Trace()
    token = _current.set(trace)
    error = ''
    try:
        yield
    except BaseException as exc:
        error = type(exc).__name__
        raise
    finally:
        trace.active = False
        write('summary', {'request_id': trace.id, 'parent_request_id': parent.id if parent else '',
            'task': 'ingestion', 'document_fingerprint': hashlib.sha256(doc_id.encode()).hexdigest()[:16],
            'task_scope_ms': round((time.perf_counter()-trace.started)*1000, 3),
            'error_type': error, **trace.stats})
        _current.reset(token)


class KnowledgeHTTPMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] != 'http' or not (path == '/company-knowledge' or path.startswith('/company-knowledge/')):
            return await self.app(scope, receive, send)
        trace = Trace()
        token = _current.set(trace)
        status, complete, streaming = 500, False, False
        error = ''
        async def traced_send(message):
            nonlocal status, complete, streaming
            if message['type'] == 'http.response.start':
                status = message['status']
                headers = MutableHeaders(scope=message)
                headers['X-Request-ID'] = trace.id
                streaming = 'text/event-stream' in headers.get('content-type', '')
            await send(message)
            if message['type'] == 'http.response.body' and not message.get('more_body', False):
                complete = True
        try:
            await self.app(scope, receive, traced_send)
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            trace.active = False
            route = getattr(scope.get('route'), 'path', '/company-knowledge/*')
            with trace.lock:
                stats = dict(trace.stats)
            outcome = 'http_error' if status >= 400 else 'success'
            if error or not complete:
                outcome = 'interrupted'
            elif streaming:
                outcome = 'business_error' if stats['sse_error_generated'] else (
                    'success' if stats['sse_done_generated'] else 'incomplete')
            write('summary', {'request_id': trace.id, 'route': route, 'method': scope.get('method'),
                'http_status': status, 'outcome': outcome, 'response_complete': complete,
                'http_scope_ms': round((time.perf_counter()-trace.started)*1000, 3),
                'error_type': error, **stats})
            _current.reset(token)


def instrument_engine(engine):
    """Cursor execution and confirmed Session events, not pool waits or commit spans."""
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    if event.contains(engine, 'before_cursor_execute', before_sql):
        return
    event.listen(engine, 'before_cursor_execute', before_sql)
    event.listen(engine, 'after_cursor_execute', after_sql)
    event.listen(engine, 'handle_error', failed_sql)
    event.listen(engine, 'checkout', checkout)
    event.listen(engine, 'checkin', checkin)
    if not event.contains(Session, 'after_commit', committed):
        event.listen(Session, 'after_commit', committed)
        event.listen(Session, 'after_rollback', rolled_back)


def checkout(connection, record, proxy):
    trace = _current.get()
    record.info['knowledge_hold'] = (trace, time.perf_counter())
    if trace and trace.active:
        with trace.lock:
            trace.stats['db_checkouts'] += 1


def checkin(connection, record):
    trace, started = record.info.pop('knowledge_hold', (None, 0))
    if trace and trace.active:
        duration = round((time.perf_counter()-started)*1000, 3)
        with trace.lock:
            trace.stats['db_connection_hold_ms'] += duration
            trace.stats['db_max_connection_hold_ms'] = max(trace.stats['db_max_connection_hold_ms'], duration)


def before_sql(connection, cursor, statement, parameters, context, many):
    trace = _current.get()
    if trace and trace.active:
        context._knowledge_observation = (trace, time.perf_counter(), hashlib.sha256(statement.encode()).hexdigest()[:16])


def finish_sql(context, failed=False):
    observation = getattr(context, '_knowledge_observation', None)
    if not observation:
        return
    context._knowledge_observation = None
    trace, started, fingerprint = observation
    if trace.active:
        duration = round((time.perf_counter()-started)*1000, 3)
        with trace.lock:
            trace.stats['sql_calls'] += 1
            trace.stats['sql_errors'] += int(failed)
            trace.stats['sql_execution_ms'] += duration
        trace.event('sql', fingerprint=fingerprint, execution_ms=duration, failed=failed)


def after_sql(connection, cursor, statement, parameters, context, many):
    finish_sql(context)


def failed_sql(error):
    finish_sql(error.execution_context, True)


def committed(session):
    if not session.in_nested_transaction():
        transaction_event('commits_confirmed')


def rolled_back(session):
    if not session.in_nested_transaction():
        transaction_event('rollbacks_confirmed')


def transaction_event(key):
    trace = _current.get()
    if trace and trace.active:
        with trace.lock:
            trace.stats[key] += 1
        trace.event('transaction', kind=key)
