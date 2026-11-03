"""Short-lived, account-scoped progress only; no file content is cached here."""
import threading
import time

from fastapi import HTTPException

_lock = threading.Lock()
_jobs = {}
_finished = {'ready', 'failed'}


def key(user, document_id, request_id):
    return (getattr(user, 'id', None), user.username, document_id, request_id)


def begin(user, document_id, request_id):
    job = key(user, document_id, request_id)
    now = time.monotonic()
    with _lock:
        for old in list(_jobs):
            if now - _jobs[old]['updated'] > 900:
                _jobs.pop(old, None)
        if job in _jobs:
            raise HTTPException(409, '该下载请求已提交，请等待当前请求完成。')
        if len(_jobs) >= 256:
            finished = sorted((k for k in _jobs if _jobs[k]['stage'] in _finished), key=lambda k: _jobs[k]['updated'])
            for old in finished[:64]:
                _jobs.pop(old, None)
        if len(_jobs) >= 256:
            raise HTTPException(429, '下载请求较多，请稍后重试。')
        _jobs[job] = {'stage': 'preparing', 'page': 0, 'total_pages': 0, 'updated': now}

    def update(stage, page=0, total_pages=0):
        with _lock:
            if job in _jobs:
                _jobs[job].update(stage=stage, page=page, total_pages=total_pages, updated=time.monotonic())
    return update


def status(user, document_id, request_id):
    with _lock:
        job = _jobs.get(key(user, document_id, request_id))
        if not job or time.monotonic() - job['updated'] > 900:
            raise HTTPException(404, '下载进度尚未开始或已过期。')
        return {field: job[field] for field in ('stage', 'page', 'total_pages')}
