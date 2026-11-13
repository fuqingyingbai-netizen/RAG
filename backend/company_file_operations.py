"""File identities, shared-original locks and durable operation receipts."""
from contextlib import contextmanager
import hashlib
import json
import re
from pathlib import PurePosixPath
import threading
import weakref

from fastapi import HTTPException
from sqlalchemy import select, text

from company_catalog import CompanyDocument, CompanyAuditEvent, can_manage, can_read

_locks = weakref.WeakValueDictionary()
_guard = threading.Lock()


@contextmanager
def file_lock(db, key):
    """Same lock for creating references and reclaiming the final original."""
    digest = hashlib.sha256(('knowledge-file:' + key).encode()).digest()
    if db.bind.dialect.name == 'postgresql':
        if not db.scalar(text('SELECT pg_try_advisory_xact_lock(:key)'),
                         {'key': int.from_bytes(digest[:8], 'big', signed=True)}):
            raise HTTPException(409, '文件正在被其他操作更新，请稍后重试。')
        yield
    else:
        with _guard:
            lock = _locks.setdefault(digest, threading.Lock())
        if not lock.acquire(blocking=False):
            raise HTTPException(409, '文件正在被其他操作更新，请稍后重试。')
        try:
            yield
        finally:
            lock.release()


def family(doc):
    return select(CompanyDocument).where(CompanyDocument.index_id == doc.index_id,
        CompanyDocument.owner == doc.owner, CompanyDocument.project == doc.project,
        CompanyDocument.knowledge_project_id == doc.knowledge_project_id,
        CompanyDocument.folder_id == doc.folder_id, CompanyDocument.title == doc.title,
        CompanyDocument.note_id == '', CompanyDocument.research_project_id.is_(None))


def latest_document_ids(documents):
    latest, independent = {}, set()
    for doc in documents:
        if not doc.is_current:
            continue
        if doc.note_id or doc.research_project_id or not doc.sha256:
            independent.add(doc.id)
            continue
        key = (doc.index_id, doc.owner, doc.knowledge_project_id, doc.folder_id, doc.project, doc.title)
        if key not in latest or doc.version > latest[key].version:
            latest[key] = doc
    return independent | {doc.id for doc in latest.values()}


def version_title(doc):
    if not doc.sha256 or doc.note_id or doc.research_project_id:
        return doc.title
    path = PurePosixPath(doc.title)
    suffix = path.suffix
    marker = '_V' + str(doc.version)
    stem = doc.title[:-len(suffix)] if suffix else doc.title
    return stem[:255-len(marker)-len(suffix)] + marker + suffix


def upload_family(db, index_id, owner, project_id, folder_id, project, title):
    query = select(CompanyDocument).where(CompanyDocument.index_id == index_id,
        CompanyDocument.owner == owner, CompanyDocument.knowledge_project_id == project_id,
        CompanyDocument.folder_id == folder_id, CompanyDocument.project == project)
    rows = list(db.scalars(query.where(CompanyDocument.title == title)))
    match = re.fullmatch(r'(.+)_V([1-9]\d*)(\.[^.]+)', title)
    if not rows and match:
        base = match[1] + match[3]
        candidates = list(db.scalars(query.where(CompanyDocument.title == base)))
        if any(doc.version == int(match[2]) for doc in candidates):
            return base, candidates
    return title, rows


def copy_title(db, source_title, index_id, owner, project_id, folder_id, project):
    titles = set(db.scalars(select(CompanyDocument.title).where(CompanyDocument.index_id == index_id,
        CompanyDocument.owner == owner, CompanyDocument.knowledge_project_id == project_id,
        CompanyDocument.folder_id == folder_id, CompanyDocument.project == project)))
    if source_title not in titles:
        return source_title
    suffix = PurePosixPath(source_title).suffix
    stem = source_title[:-len(suffix)] if suffix else source_title
    for number in range(1, 10001):
        marker = '（副本' + (str(number) if number > 1 else '') + '）'
        name = stem[:255-len(marker)-len(suffix)] + marker + suffix
        if name not in titles:
            return name
    raise HTTPException(409, '同名副本过多，请先整理或重命名文件。')


def operation_id(user, index_id, action, request_id):
    return hashlib.sha256(f'{index_id}:{user.id}:{action}:{request_id}'.encode()).hexdigest() if request_id else None


def operation_hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def replay(db, event_id, fingerprint, user):
    event = db.get(CompanyAuditEvent, event_id) if event_id else None
    if event is None:
        return None
    if event.actor_id != user.id or event.details.get('operation_fingerprint') != fingerprint:
        raise HTTPException(409, '请求编号已用于其他操作，请重新选择文件后再试。')
    doc = db.get(CompanyDocument, event.target_id)
    if not doc or doc.state == 'deleted' or not can_read(doc, user) or not can_manage(doc, user):
        raise HTTPException(409, '原操作已完成，但文件状态或权限已变化，请刷新目录。')
    return doc, event.details.get('operation_result', {})


def check_snapshot(doc, expected):
    if expected and expected != doc.updated_at.isoformat() + 'Z':
        raise HTTPException(409, '文件已变化，请重新复制或剪切后再粘贴。')
