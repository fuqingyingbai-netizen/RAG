"""Transactional file relocation: version families, ACL preview and stable originals."""
import hashlib
import hmac
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import company_knowledge as kb
import company_workspace as ws
from company_audit import mark_modified, record, snapshot
from company_catalog import CompanyDocument, CompanyProject, can_manage, can_read, media_kind, serialize
from company_collections import EXPERIENCE_CATEGORIES
from company_projects import find_folder, project_values
from company_departments import department_label
from models import User

moves_router = APIRouter()
ACTIVE = {'queued', 'uploading', 'parsing', 'indexing', 'deleting'}


class MoveTarget(BaseModel):
    project_id: str = Field(default='', max_length=64)
    folder_id: str = Field(default='', max_length=64)
    confirmation: str = Field(default='', max_length=64)


def acl_label(values):
    if values['confidentiality'] != 'internal':
        return '机密 · 仅管理员可读'
    if values['visibility'] == 'members':
        return '内部 · 所有正常账号可读'
    readers = '、'.join(values['readers'])
    return '内部 · 归属人、管理员' + ('及指定成员（' + readers + '）可读' if readers else '可读')


def prepare(db, doc_id, data, user):
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
    values = (project_values(target) | dict(owner=target.owner, owner_user_id=target.owner_user_id,
               knowledge_project_id=target.id, folder_id=data.folder_id, inherits_project=1, is_root=0)
              if target else dict(project='', knowledge_project_id='', folder_id='', inherits_project=0, is_root=1))
    no_change = all(all(getattr(v, key) == value for key, value in values.items()) for v in versions)
    if not no_change:
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
    payload = dict(target=values, folder=({'id': folder.id, 'updated_at': folder.updated_at.isoformat()} if folder else None),
        projects=[dict(id=p.id, updated_at=p.updated_at.isoformat(), owner=p.owner, **project_values(p)) for p in projects.values()],
        versions=[dict(id=v.id, updated_at=v.updated_at.isoformat(), cloud_id=v.cloud_id, sha256=v.sha256, **snapshot(v)) for v in versions])
    token = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    preview = dict(document_id=doc.id, title=doc.title, version_count=len(versions), confirmation=token,
        source=(source.name if source else '根目录'),
        destination=(target.name + (' / ' + folder.name if folder else ' / 项目根目录') if target else '根目录'),
        before_access=acl_label(before_acl), after_access=acl_label(after_acl),
        before_department=department_label(doc.department),
        after_department=department_label(values.get('department', doc.department)),
        permission_note=('移入后继承目标项目的分类、标签、保密等级与访问权限；文件管理权跟随目标项目归属人。'
                         if target else '移回根目录后保留各版本现有保密等级、访问权限和归属人，不自动扩大可见范围。'),
        access_changes=any(any(getattr(v, k) != after_acl[k] for k in before_acl) for v in versions) if target else False,
        reindex_required=bool(reindex), no_change=no_change)
    return doc, versions, values, preview, reindex, projects


@moves_router.post('/documents/{doc_id}/move-preview')
def move_preview(doc_id: str, data: MoveTarget, user: User = Depends(kb.require_knowledge_user)):
    with ws.SessionLocal() as db:
        return prepare(db, doc_id, data, user)[3]


@moves_router.post('/documents/{doc_id}/move')
async def move_document(doc_id: str, data: MoveTarget, user: User = Depends(kb.require_knowledge_user)):
    with ws.SessionLocal() as db:
        doc, versions, values, preview, reindex, projects = prepare(db, doc_id, data, user)
        if not data.confirmation or not hmac.compare_digest(data.confirmation, preview['confirmation']):
            raise HTTPException(409, '文件或项目权限已变化，请重新查看移动确认内容。')
        if not preview['no_change']:
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
                record(db, user, 'document.move', version, before=before,
                       details={key: preview[key] for key in ('source', 'destination', 'version_count', 'before_access', 'after_access')})
            for project in projects.values():
                mark_modified(project, user)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                raise HTTPException(409, '目标位置已有同名文件，请刷新后重新整理。') from None
        result = serialize(doc, user)
    for version_id in reindex:
        ws.schedule_document(version_id)
    return dict(document=result, moved_version_count=preview['version_count'], no_change=preview['no_change'])
