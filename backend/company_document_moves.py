"""Transactional file relocation: version families, ACL preview and stable originals."""
import hashlib
import hmac
import json
import asyncio
import copy
import uuid
from contextlib import ExitStack
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import company_knowledge as kb
import company_workspace as ws
from company_audit import mark_modified, record, snapshot
from company_catalog import CompanyDocument, CompanyProject, can_manage, can_read, media_kind, serialize, document_store
from company_file_operations import check_snapshot, copy_title, file_lock, operation_id, operation_hash, replay, family
from company_collections import EXPERIENCE_CATEGORIES
from company_projects import find_folder, project_values
from company_departments import department_label
from models import User

moves_router = APIRouter()
ACTIVE = {'queued', 'uploading', 'parsing', 'indexing', 'deleting'}


@moves_router.get('/documents/{doc_id}/versions')
def document_versions(doc_id: str, user: User = Depends(kb.require_knowledge_user)):
    with ws.SessionLocal() as db:
        doc = ws.find_doc(db, doc_id, user)
        if not doc.sha256 or doc.note_id or doc.research_project_id:
            raise HTTPException(422, '此资料请在所属功能中查看历史版本。')
        rows = list(db.scalars(family(doc).order_by(CompanyDocument.version.desc())))
        newest = max(row.version for row in rows)
        return {'title': doc.title, 'versions': [serialize(row, user) | {'is_latest': row.version == newest}
            for row in rows if row.state != 'deleted' and can_read(row, user)]}


class MoveTarget(BaseModel):
    project_id: str = Field(default='', max_length=64)
    folder_id: str = Field(default='', max_length=64)
    confirmation: str = Field(default='', max_length=64)
    request_id: str = Field(default='', max_length=64)
    expected_modified_at: str = Field(default='', max_length=64)


def acl_label(values):
    if values['confidentiality'] != 'internal':
        return '机密 · 仅管理员可读'
    if values['visibility'] == 'members':
        return '内部 · 所有正常账号可读'
    readers = '、'.join(values['readers'])
    return '内部 · 归属人、管理员' + ('及指定成员（' + readers + '）可读' if readers else '可读')


def prepare(db, doc_id, data, user, *, copying=False):
    initial = db.get(CompanyDocument, doc_id)
    if not initial or initial.index_id != kb.settings()['index_id'] or initial.state == 'deleted' or not can_read(initial, user):
        raise HTTPException(404, '资料不存在或没有访问权限。')
    source_id = initial.knowledge_project_id
    # Match project deletion/upload lock order. Two opposite moves lock projects
    # in the same order; never acquire a project after locking a document.
    projects = {p.id: p for p in db.scalars(select(CompanyProject).where(
        CompanyProject.id.in_(sorted({source_id, data.project_id} - {''})))
        .order_by(CompanyProject.id).with_for_update())}
    for project_id in {source_id, data.project_id} - {''}:
        p = projects.get(project_id)
        if not p or p.index_id != initial.index_id or not can_read(p, user):
            raise HTTPException(404, '项目不存在或没有访问权限。')
        if not can_manage(p, user):
            raise HTTPException(403, '只有项目创建者或管理员可以移动项目内的资料。')
    target = projects.get(data.project_id)
    source = projects.get(source_id)
    folder = find_folder(db, data.project_id, data.folder_id) if data.project_id else None
    if data.folder_id and not data.project_id:
        raise HTTPException(422, '根目录不能指定子目录。')
    # Serialize against uploads allocating versions under either owner.
    owners = {initial.owner, target.owner if target else initial.owner, user.username}
    list(db.scalars(select(User).where(User.username.in_(sorted(owners))).order_by(User.username).with_for_update()))
    doc = db.scalar(select(CompanyDocument).where(CompanyDocument.id == doc_id)
                    .execution_options(populate_existing=True).with_for_update())
    if doc.knowledge_project_id != source_id:
        raise HTTPException(409, '资料归属已变化，请刷新后重新移动。')
    if doc.note_id or doc.research_project_id:
        raise HTTPException(422, '图文笔记和自动生成的研究成果请在所属项目中管理。')
    if not can_manage(doc, user) or not can_read(doc, user) or doc.state == 'deleted':
        raise HTTPException(403, '只有资料归属人或管理员可以移动文件。')
    check_snapshot(doc, data.expected_modified_at)
    if target and ((target.category in EXPERIENCE_CATEGORIES) != (doc.category in EXPERIENCE_CATEGORIES)):
        raise HTTPException(422, '资料库与经验沉淀分别归档，请选择同一库中的项目。')
    versions = list(db.scalars(select(CompanyDocument).where(
        CompanyDocument.index_id == doc.index_id, CompanyDocument.owner == doc.owner,
        CompanyDocument.knowledge_project_id == source_id, CompanyDocument.folder_id == doc.folder_id,
        CompanyDocument.project == doc.project, CompanyDocument.title == doc.title,
        CompanyDocument.note_id == '', CompanyDocument.state != 'deleted')
        .order_by(CompanyDocument.id).with_for_update()))
    if any(not can_manage(v, user) or not can_read(v, user) for v in versions):
        raise HTTPException(403, '部分历史版本无管理权限，请联系管理员整理。')
    if any(v.state in ACTIVE or (v.lease_until and v.lease_until > datetime.utcnow()) for v in versions):
        raise HTTPException(409, '文件或历史版本仍在处理，请等待完成后移动。')
    if copying and (not doc.object_key or not document_store().exists(doc.object_key)):
        raise HTTPException(409, '原件不存在，请补传原件后再复制。')
    if copying and doc.version != max(v.version for v in versions):
        raise HTTPException(409, '请复制当前最新版本；历史版本可通过下载保留。')
    values = (project_values(target) | dict(owner=target.owner, owner_user_id=target.owner_user_id,
               knowledge_project_id=target.id, folder_id=data.folder_id, inherits_project=1, is_root=0)
              if target else dict(project='', knowledge_project_id='', folder_id='', inherits_project=0, is_root=1))
    if copying:
        values['title'] = copy_title(db, doc.title, doc.index_id, values.get('owner', doc.owner),
                                    data.project_id, data.folder_id, values['project'])
    no_change = not copying and all(all(getattr(v, key) == value for key, value in values.items()) for v in versions)
    if not no_change and not copying:
        conflict = db.scalar(select(CompanyDocument.id).where(
            CompanyDocument.index_id == doc.index_id,
            CompanyDocument.owner == values.get('owner', doc.owner),
            CompanyDocument.knowledge_project_id == data.project_id,
            CompanyDocument.folder_id == data.folder_id,
            CompanyDocument.project == values['project'], CompanyDocument.title == doc.title,
            CompanyDocument.id.not_in([v.id for v in versions]),
            (CompanyDocument.state != 'deleted') | CompanyDocument.version.in_([v.version for v in versions])))
        if conflict:
            raise HTTPException(409, '目标位置已有同名文件或历史版本，请先重命名文件；系统不会覆盖或合并。')
    reindex = [v.id for v in versions if media_kind(v) and v.description.strip() and
               any(key in values and getattr(v, key) != values[key] for key in ('project', 'industry', 'tags'))]
    before_acl = {key: getattr(doc, key) for key in ('confidentiality', 'visibility', 'readers')}
    after_acl = before_acl | {key: value for key, value in values.items() if key in before_acl}
    payload = dict(copying=copying, target=values, folder=({'id': folder.id, 'updated_at': folder.updated_at.isoformat()} if folder else None),
        projects=[dict(id=p.id, updated_at=p.updated_at.isoformat(), owner=p.owner, **project_values(p)) for p in projects.values()],
        versions=[dict(id=v.id, updated_at=v.updated_at.isoformat(), cloud_id=v.cloud_id, sha256=v.sha256, **snapshot(v)) for v in versions])
    token = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    preview = dict(document_id=doc.id, title=doc.title, version_count=len(versions), confirmation=token,
        copy_title=values.get('title', ''), copying=copying,
        source=(source.name if source else '根目录'),
        destination=(target.name + (' / ' + folder.name if folder else ' / 项目根目录') if target else '根目录'),
        before_access=acl_label(before_acl), after_access=acl_label(after_acl),
        before_department=department_label(doc.department),
        after_department=department_label(values.get('department', doc.department)),
        permission_note=('移入后继承目标项目的分类、标签、保密等级与访问权限；文件管理权跟随目标项目归属人。'
                         if target else '移回根目录后保留各版本现有保密等级、访问权限和归属人，不自动扩大可见范围。'),
        access_changes=any(any(getattr(v, k) != after_acl[k] for k in before_acl) or
                           v.owner != values.get('owner', v.owner) for v in versions) if target else False,
        reindex_required=bool(reindex), no_change=no_change)
    return doc, versions, values, preview, reindex, projects


@moves_router.post('/documents/{doc_id}/move-preview')
async def move_preview(doc_id: str, data: MoveTarget, user: User = Depends(kb.require_knowledge_user)):
    return await asyncio.to_thread(preview_transfer, doc_id, data, user, False)


def preview_transfer(doc_id, data, user, copying):
    with ws.SessionLocal() as db:
        action, event_id, fingerprint = transfer_receipt(doc_id, data, user, copying)
        previous = replay(db, event_id, fingerprint, user)
        if previous:
            doc, receipt = previous
            return {'completed': True, 'result': dict(document=serialize(doc, user), **receipt)}
        return prepare(db, doc_id, data, user, copying=copying)[3]


@moves_router.post('/documents/{doc_id}/move')
async def move_document(doc_id: str, data: MoveTarget, user: User = Depends(kb.require_knowledge_user)):
    return await transfer(doc_id, data, user, False)


@moves_router.post('/documents/{doc_id}/copy-preview')
async def copy_preview(doc_id: str, data: MoveTarget, user: User = Depends(kb.require_knowledge_user)):
    return await asyncio.to_thread(preview_transfer, doc_id, data, user, True)


@moves_router.post('/documents/{doc_id}/copy', status_code=201)
async def copy_document(doc_id: str, data: MoveTarget, user: User = Depends(kb.require_knowledge_user)):
    if not data.request_id or not data.expected_modified_at:
        raise HTTPException(422, '复制需要请求编号和源文件快照，请重新选择文件。')
    return await transfer(doc_id, data, user, True)


def transfer_receipt(doc_id, data, user, copying):
    action = 'document.copy' if copying else 'document.move'
    event_id = operation_id(user, kb.settings()['index_id'], action, data.request_id)
    fingerprint = operation_hash({'source': doc_id, 'project': data.project_id, 'folder': data.folder_id,
                                  'snapshot': data.expected_modified_at, 'action': action})
    return action, event_id, fingerprint


def commit_transfer(doc_id, data, user, copying):
    action, event_id, fingerprint = transfer_receipt(doc_id, data, user, copying)
    with ws.SessionLocal() as db:
        with ExitStack() as locks:
            if event_id:
                locks.enter_context(file_lock(db, 'operation:' + event_id))
            previous = replay(db, event_id, fingerprint, user)
            if previous:
                doc, receipt = previous
                return dict(document=serialize(doc, user), **receipt), [doc.id] if copying and doc.state == 'queued' else []
            doc, versions, values, preview, reindex, projects = prepare(db, doc_id, data, user, copying=copying)
            if not data.confirmation or not hmac.compare_digest(data.confirmation, preview['confirmation']):
                raise HTTPException(409, '文件或项目权限已变化，请重新查看操作确认内容。')
            details = {key: preview[key] for key in ('source', 'destination', 'version_count', 'before_access', 'after_access')}
            receipt = dict(copied=True) if copying else dict(moved_version_count=preview['version_count'], no_change=preview['no_change'])
            details.update(operation_fingerprint=fingerprint, operation_result=receipt)
            if copying:
                locks.enter_context(file_lock(db, doc.object_key))
                if not document_store().exists(doc.object_key):
                    raise HTTPException(409, '源文件已不可用，请刷新后重试。')
                origin = dict(source_id=doc.id, source_version=doc.version, source_sha256=doc.sha256,
                    source_uploaded_by=doc.uploaded_by or doc.owner, source_created_at=doc.created_at.isoformat()+'Z',
                    copied_by=user.username, copied_at=datetime.utcnow().isoformat()+'Z')
                fields = {key: copy.deepcopy(getattr(doc, key)) for key in ('format','size','sha256','object_key','description',
                    'parser','review','project','industry','department','category','tags','confidentiality','visibility',
                    'readers','owner','owner_user_id','uploaded_by','uploaded_by_user_id')}
                fields.update(values)
                clone = CompanyDocument(id=uuid.uuid4().hex, index_id=doc.index_id, **fields, version=1,
                    modified_by=user.username, copy_origin=origin, state='archived' if media_kind(doc) and not doc.description.strip() else 'queued',
                    status_message='副本已归档' if media_kind(doc) and not doc.description.strip() else '副本已保存，等待建立索引')
                db.add(clone)
                record(db, user, action, clone, details=details | {'origin': origin}, event_id=event_id)
                reindex = [clone.id] if clone.state == 'queued' else []
                doc = clone
            elif not preview['no_change']:
                for version in versions:
                    before = snapshot(version)
                    for key, value in values.items():
                        setattr(version, key, value)
                    if version.id in reindex:
                        version.stale_cloud_id = version.cloud_id or version.stale_cloud_id
                        version.cloud_id, version.job_id, version.lease_id = None, '', ''
                        version.worker_id, version.lease_until = '', None
                        version.state, version.status_message = 'queued', '归档位置已更新，正在重新索引音视频说明'
                    mark_modified(version, user)
                    record(db, user, action, version, before=before, details=details,
                           event_id=event_id if version.id == doc.id else None)
            elif event_id:
                record(db, user, action, doc, before=snapshot(doc), details=details, event_id=event_id)
            for project in projects.values():
                mark_modified(project, user)
            db.commit()
            return dict(document=serialize(doc, user), **receipt), reindex


async def transfer(doc_id, data, user, copying):
    pending = asyncio.create_task(asyncio.to_thread(commit_transfer, doc_id, data, user, copying))
    try:
        result, reindex = await asyncio.shield(pending)
    except asyncio.CancelledError:
        try:
            result, reindex = await pending
        except Exception:
            pass
        else:
            for version_id in reindex:
                ws.schedule_document(version_id)
        raise
    except IntegrityError:
        raise HTTPException(409, '目标位置正在被更新，请刷新后重新整理。') from None
    for version_id in reindex:
        ws.schedule_document(version_id)
    return result
